"""
os_tf_patcher.py — OpenStack Terraform auto-fixer

Architecture khác AWS patcher vì OpenStack networking dùng
separate resource blocks cho mỗi rule (không phải inline block).

Fix strategies:
  A) Attribute patch  — sửa/thêm attribute trong resource block
  B) Restrict rule    — đổi remote_ip_prefix từ 0.0.0.0/0 → restricted CIDR
  C) Insert block     — thêm nested block (dns_nameservers, external_gateway_info)
  D) Remove rule      — comment-out rule quá permissive (nếu không thể restrict)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ─────────────────────────────────────────────────────────────────────────────
# FixRule
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FixRule:
    check_id   : str
    title      : str
    severity   : str
    fixer      : Callable[[str, dict], tuple[str, bool]]
    description: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Generic TF helpers (shared với AWS patcher)
# ─────────────────────────────────────────────────────────────────────────────

def _find_resource_block(content: str, resource_type: str,
                          resource_name: str) -> tuple[int, int] | None:
    """Return (block_start, block_end) byte offsets of the resource body (inside braces)."""
    pattern = rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{'
    m = re.search(pattern, content)
    if not m:
        return None
    start = m.end()
    depth, pos = 1, start
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    return start, pos  # pos is right after closing }


def _set_attr(content: str, resource_type: str, resource_name: str,
              attr: str, value: str) -> tuple[str, bool]:
    """Set or insert a top-level attribute inside a resource block."""
    bounds = _find_resource_block(content, resource_type, resource_name)
    if not bounds:
        return content, False
    body_start, body_end = bounds
    body = content[body_start:body_end - 1]

    attr_re = rf'^(\s*{re.escape(attr)}\s*=\s*).*'
    if re.search(attr_re, body, re.MULTILINE):
        new_body = re.sub(attr_re, rf'\g<1>{value}', body, count=1, flags=re.MULTILINE)
    else:
        new_body = body.rstrip() + f"\n  {attr} = {value}\n"

    if new_body == body:
        return content, False
    return content[:body_start] + new_body + "}" + content[body_end:], True


def _set_nested_attr(content: str, resource_type: str, resource_name: str,
                     nested_block: str, attr: str, value: str,
                     create_if_missing: bool = True) -> tuple[str, bool]:
    """Set attribute inside a nested block, creating the block if needed."""
    bounds = _find_resource_block(content, resource_type, resource_name)
    if not bounds:
        return content, False
    body_start, body_end = bounds
    body = content[body_start:body_end - 1]

    nb_match = re.search(rf'{re.escape(nested_block)}\s*\{{', body)
    if nb_match:
        nb_start = nb_match.end()
        depth, p = 1, nb_start
        while p < len(body) and depth > 0:
            if body[p] == '{':
                depth += 1
            elif body[p] == '}':
                depth -= 1
            p += 1
        nb_body = body[nb_start:p - 1]
        attr_re = rf'^(\s*{re.escape(attr)}\s*=\s*).*'
        if re.search(attr_re, nb_body, re.MULTILINE):
            new_nb = re.sub(attr_re, rf'\g<1>{value}', nb_body, count=1, flags=re.MULTILINE)
        else:
            new_nb = nb_body.rstrip() + f"\n    {attr} = {value}\n  "
        new_body = body[:nb_match.end()] + new_nb + "}" + body[p:]
    elif create_if_missing:
        block_str = f"\n  {nested_block} {{\n    {attr} = {value}\n  }}\n"
        new_body = body.rstrip() + block_str
    else:
        return content, False

    if new_body == body:
        return content, False
    return content[:body_start] + new_body + "}" + content[body_end:], True


def _parse_resource(finding: dict) -> tuple[str, str]:
    """'openstack_networking_secgroup_rule_v2.ssh_open' → (type, name)."""
    parts = finding.get("resource", "").split(".")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    r = finding.get("resource", "")
    return r, r


# ─────────────────────────────────────────────────────────────────────────────
# OpenStack-specific fixers
# ─────────────────────────────────────────────────────────────────────────────

# Restricted CIDRs thay thế cho 0.0.0.0/0
_RESTRICTED_SSH_CIDR  = '"10.0.0.0/8"'    # chỉ cho phép internal
_RESTRICTED_RDP_CIDR  = '"10.0.0.0/8"'
_MANAGEMENT_CIDR      = '"10.0.0.0/8"'

# Default DNS nameservers cho OpenStack (có thể override qua env)
_DEFAULT_DNS = '["8.8.8.8", "8.8.4.4"]'


def fix_ssh_open_world(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_1 — restrict SSH ingress từ 0.0.0.0/0 → management CIDR."""
    rtype, rname = _parse_resource(finding)
    return _set_attr(content, rtype, rname,
                     "remote_ip_prefix", _RESTRICTED_SSH_CIDR)


def fix_rdp_open_world(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_2 — restrict RDP ingress từ 0.0.0.0/0 → management CIDR."""
    rtype, rname = _parse_resource(finding)
    return _set_attr(content, rtype, rname,
                     "remote_ip_prefix", _RESTRICTED_RDP_CIDR)


def fix_allow_all_ingress(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_4 — rule cho phép tất cả ingress: restrict CIDR."""
    rtype, rname = _parse_resource(finding)
    # Kiểm tra xem đây có phải rule không có protocol (allow all)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]

    # Nếu không có protocol field → đây là allow-all rule, restrict CIDR
    if not re.search(r'^\s*protocol\s*=', body, re.MULTILINE):
        return _set_attr(content, rtype, rname,
                         "remote_ip_prefix", _MANAGEMENT_CIDR)

    # Nếu có protocol nhưng CIDR là 0.0.0.0/0 → restrict
    if re.search(r'remote_ip_prefix\s*=\s*"0\.0\.0\.0/0"', body):
        return _set_attr(content, rtype, rname,
                         "remote_ip_prefix", _MANAGEMENT_CIDR)

    return content, False


def fix_allow_all_egress(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_5 — rule cho phép tất cả egress: restrict CIDR."""
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]

    if re.search(r'remote_ip_prefix\s*=\s*"0\.0\.0\.0/0"', body):
        return _set_attr(content, rtype, rname,
                         "remote_ip_prefix", _MANAGEMENT_CIDR)
    return content, False


def fix_subnet_no_dns(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_8 — thêm dns_nameservers vào subnet nếu thiếu."""
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]

    # Nếu đã có dns_nameservers → skip
    if re.search(r'^\s*dns_nameservers\s*=', body, re.MULTILINE):
        return content, False

    # Insert dns_nameservers list
    new_body = body.rstrip() + f"\n  dns_nameservers = {_DEFAULT_DNS}\n"
    new_content = content[:bounds[0]] + new_body + "}" + content[bounds[1]:]
    return new_content, True


def fix_router_no_gateway(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_7 — thêm external_network_id placeholder vào router."""
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]

    if re.search(r'^\s*external_network_id\s*=', body, re.MULTILINE):
        return content, False

    # Insert comment + placeholder — ops team phải điền UUID thật
    placeholder = (
        "\n  # TODO: set external_network_id to your provider network UUID"
        "\n  # Run: openstack network list --external"
        '\n  external_network_id = var.external_network_id\n'
    )
    new_body = body.rstrip() + placeholder
    new_content = content[:bounds[0]] + new_body + "}" + content[bounds[1]:]
    return new_content, True


def fix_metadata_service(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_OPENSTACK_6 — disable metadata service on compute instance."""
    rtype, rname = _parse_resource(finding)
    return _set_nested_attr(content, rtype, rname,
                            "metadata", "disable", "true",
                            create_if_missing=True)


# ─────────────────────────────────────────────────────────────────────────────
# FIX_REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

FIX_REGISTRY: dict[str, FixRule] = {
    "CKV_OPENSTACK_1": FixRule(
        "CKV_OPENSTACK_1",
        "SSH (22) open to 0.0.0.0/0 — restrict to management CIDR",
        "HIGH",
        fix_ssh_open_world,
        f"Changes remote_ip_prefix to {_RESTRICTED_SSH_CIDR}",
    ),
    "CKV_OPENSTACK_2": FixRule(
        "CKV_OPENSTACK_2",
        "RDP (3389) open to 0.0.0.0/0 — restrict to management CIDR",
        "HIGH",
        fix_rdp_open_world,
        f"Changes remote_ip_prefix to {_RESTRICTED_RDP_CIDR}",
    ),
    "CKV_OPENSTACK_4": FixRule(
        "CKV_OPENSTACK_4",
        "Security group allows all ingress — restrict CIDR",
        "MEDIUM",
        fix_allow_all_ingress,
        f"Changes remote_ip_prefix to {_MANAGEMENT_CIDR}",
    ),
    "CKV_OPENSTACK_5": FixRule(
        "CKV_OPENSTACK_5",
        "Security group allows all egress — restrict CIDR",
        "MEDIUM",
        fix_allow_all_egress,
        f"Changes remote_ip_prefix to {_MANAGEMENT_CIDR}",
    ),
    "CKV_OPENSTACK_6": FixRule(
        "CKV_OPENSTACK_6",
        "Instance metadata service not disabled",
        "LOW",
        fix_metadata_service,
    ),
    "CKV_OPENSTACK_7": FixRule(
        "CKV_OPENSTACK_7",
        "Router has no external gateway — add external_network_id placeholder",
        "MEDIUM",
        fix_router_no_gateway,
        "Inserts external_network_id = var.external_network_id with TODO comment",
    ),
    "CKV_OPENSTACK_8": FixRule(
        "CKV_OPENSTACK_8",
        "Subnet has no DNS nameservers — add default DNS",
        "LOW",
        fix_subnet_no_dns,
        f"Adds dns_nameservers = {_DEFAULT_DNS}",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# SingleFilePatcher
# ─────────────────────────────────────────────────────────────────────────────

class SingleFilePatcher:
    def __init__(self, tf_path: Path):
        self.tf_path  = tf_path
        self.original = tf_path.read_text(encoding="utf-8")
        self.content  = self.original
        self.dirty    = False

    def apply(self, findings: list[dict]) -> list[dict]:
        results = []
        for finding in findings:
            rule_id = finding.get("rule_id", "")
            rule    = FIX_REGISTRY.get(rule_id)

            if not rule:
                results.append({**finding, "status": "skipped",
                                 "reason": f"No fixer rule for {rule_id}"})
                continue

            try:
                new_content, changed = rule.fixer(self.content, finding)
                if changed:
                    self.content = new_content
                    self.dirty   = True
                    results.append({**finding, "status": "fixed", "rule": rule.title})
                else:
                    results.append({**finding, "status": "skipped",
                                    "reason": "Pattern not found or already compliant"})
            except Exception as exc:
                results.append({**finding, "status": "failed", "reason": str(exc)})
        return results

    def write(self, out_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.content, encoding="utf-8")

    def diff_lines(self) -> list[str]:
        import difflib
        return list(difflib.unified_diff(
            self.original.splitlines(keepends=True),
            self.content.splitlines(keepends=True),
            fromfile=f"{self.tf_path} (original)",
            tofile  =f"{self.tf_path} (patched)",
        ))


# ─────────────────────────────────────────────────────────────────────────────
# MultiFilePatcher
# ─────────────────────────────────────────────────────────────────────────────

class MultiFilePatcher:
    def __init__(self, tf_files: list[Path], out_dir: Path, dry_run: bool = False):
        self.tf_files = tf_files
        self.out_dir  = out_dir
        self.dry_run  = dry_run
        self._patchers: dict[Path, SingleFilePatcher] = {
            f.resolve(): SingleFilePatcher(f) for f in tf_files
        }

    def apply(self, findings: list[dict]) -> list[dict]:
        all_results, unmatched = [], []
        for finding in findings:
            target = self._resolve_file(finding.get("file_path", ""))
            if target is None:
                unmatched.append(finding)
                all_results.append({
                    **finding, "status": "skipped",
                    "reason": f"No matching .tf file for '{finding.get('file_path','')}'"
                })
                continue
            all_results.extend(self._patchers[target].apply([finding]))

        if unmatched:
            print(f"  ⚠️  {len(unmatched)} finding(s) could not be matched to a .tf file")
        return all_results

    def write_all(self) -> dict[Path, Path]:
        written = {}
        if self.dry_run:
            return written
        resolved = list(self._patchers.keys())
        if len(resolved) == 1:
            common = resolved[0].parent
        else:
            prefix = self._common_prefix_len(resolved)
            try:
                common = Path(*resolved[0].parts[:prefix]) if prefix else resolved[0].parent
            except Exception:
                common = resolved[0].parent

        for abs_path, patcher in self._patchers.items():
            if not patcher.dirty:
                continue
            try:
                rel = abs_path.relative_to(common)
            except ValueError:
                rel = Path(abs_path.name)
            out_path = self.out_dir / rel
            patcher.write(out_path)
            written[abs_path] = out_path
        return written

    def _resolve_file(self, reported_path: str) -> Path | None:
        if not reported_path:
            return None
        rp = Path(reported_path)
        try:
            c = rp.resolve()
            if c in self._patchers:
                return c
        except Exception:
            pass
        matches = [p for p in self._patchers if p.name == rp.name]
        if len(matches) == 1:
            return matches[0]
        best, best_len = None, 0
        for p in self._patchers:
            l = self._common_suffix_len(p.parts, rp.parts)
            if l > best_len:
                best, best_len = p, l
        return best

    @staticmethod
    def _common_suffix_len(a, b) -> int:
        n = 0
        for x, y in zip(reversed(a), reversed(b)):
            if x == y:
                n += 1
            else:
                break
        return n

    @staticmethod
    def _common_prefix_len(paths: list[Path]) -> int:
        if not paths:
            return 0
        parts = [p.parts for p in paths]
        prefix = 0
        for i in range(min(len(p) for p in parts)):
            if len({p[i] for p in parts}) == 1:
                prefix += 1
            else:
                break
        return prefix

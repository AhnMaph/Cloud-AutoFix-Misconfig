"""
os_tf_patcher.py — OpenStack Terraform auto-fixer

Correct CKV_OPENSTACK_* mapping (từ Checkov source code):
  CKV_OPENSTACK_1 — Hardcoded credentials trong provider block (password/token/secret)
  CKV_OPENSTACK_2 — SSH port 22 open 0.0.0.0/0  (openstack_networking_secgroup_rule_v2)
  CKV_OPENSTACK_3 — RDP port 3389 open 0.0.0.0/0 (openstack_networking_secgroup_rule_v2)
  CKV_OPENSTACK_4 — admin_pass set trong openstack_compute_instance_v2
  CKV_OPENSTACK_5 — (nếu tồn tại) — kiểm tra thêm
  CKV_OPENSTACK_6 — (nếu tồn tại) — kiểm tra thêm

Resource types liên quan:
  - openstack_networking_secgroup_rule_v2 (SSH/RDP rules)
  - openstack_networking_secgroup_v2      (security group)
  - openstack_compute_instance_v2         (compute instance)
  - openstack_networking_subnet_v2        (subnet)
  - openstack_networking_router_v2        (router)
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
# Generic TF helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_resource_block(content: str, resource_type: str,
                          resource_name: str) -> tuple[int, int] | None:
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
    return start, pos


def _find_provider_block(content: str, provider_name: str = "openstack") -> tuple[int, int] | None:
    pattern = rf'provider\s+"{re.escape(provider_name)}"\s*\{{'
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
    return start, pos


def _set_attr(content: str, resource_type: str, resource_name: str,
              attr: str, value: str) -> tuple[str, bool]:
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


def _remove_attr(content: str, resource_type: str, resource_name: str,
                 attr: str) -> tuple[str, bool]:
    """Remove an attribute line from a resource block."""
    bounds = _find_resource_block(content, resource_type, resource_name)
    if not bounds:
        return content, False
    body_start, body_end = bounds
    body = content[body_start:body_end - 1]

    new_body = re.sub(rf'^\s*{re.escape(attr)}\s*=.*\n?', '', body, flags=re.MULTILINE)
    if new_body == body:
        return content, False
    return content[:body_start] + new_body + "}" + content[body_end:], True


def _replace_provider_sensitive_attr(content: str, attr: str,
                                      var_name: str) -> tuple[str, bool]:
    """Replace hardcoded value in provider block with a variable reference."""
    bounds = _find_provider_block(content, "openstack")
    if not bounds:
        return content, False
    body_start, body_end = bounds
    body = content[body_start:body_end - 1]

    # Match attr = "some_literal_value" (not already a var/env reference)
    attr_re = rf'(\s*{re.escape(attr)}\s*=\s*)"(?!\${{var\.|env\.)[^"]*"'
    if not re.search(attr_re, body):
        return content, False

    new_body = re.sub(
        attr_re,
        rf'\1var.{var_name}',
        body,
        count=1,
    )
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
# Fixer implementations
# ─────────────────────────────────────────────────────────────────────────────

_RESTRICTED_MGMT_CIDR = '"10.0.0.0/8"'
_DEFAULT_DNS           = '["8.8.8.8", "8.8.4.4"]'


def fix_hardcoded_credentials(content: str, finding: dict) -> tuple[str, bool]:
    """
    CKV_OPENSTACK_1 — Hardcoded credentials in provider block.
    Replaces literal string values for password/token/application_credential_secret
    with var.* references and appends variable declarations if not present.

    Resource in finding is typically 'openstack.default' (provider alias).
    """
    changed_any = False

    # Sensitive fields to replace in provider block
    sensitive_fields = {
        "password"                     : "openstack_password",
        "token"                        : "openstack_token",
        "application_credential_secret": "openstack_app_credential_secret",
    }

    for field, var_name in sensitive_fields.items():
        new_content, changed = _replace_provider_sensitive_attr(content, field, var_name)
        if changed:
            content = new_content
            changed_any = True

    if changed_any:
        # Append variable declarations at end of file if not already present
        for field, var_name in sensitive_fields.items():
            if f'variable "{var_name}"' not in content:
                content += (
                    f'\nvariable "{var_name}" {{\n'
                    f'  description = "OpenStack {field} — set via TF_VAR_{var_name} env var"\n'
                    f'  type        = string\n'
                    f'  sensitive   = true\n'
                    f'}}\n'
                )

    return content, changed_any


def fix_ssh_open_world(content: str, finding: dict) -> tuple[str, bool]:
    """
    CKV_OPENSTACK_2 — SSH ingress open to 0.0.0.0/0.
    Restricts remote_ip_prefix to management CIDR.
    """
    rtype, rname = _parse_resource(finding)
    return _set_attr(content, rtype, rname,
                     "remote_ip_prefix", _RESTRICTED_MGMT_CIDR)


def fix_rdp_open_world(content: str, finding: dict) -> tuple[str, bool]:
    """
    CKV_OPENSTACK_3 — RDP ingress open to 0.0.0.0/0.
    Restricts remote_ip_prefix to management CIDR.
    """
    rtype, rname = _parse_resource(finding)
    return _set_attr(content, rtype, rname,
                     "remote_ip_prefix", _RESTRICTED_MGMT_CIDR)


def fix_admin_pass(content: str, finding: dict) -> tuple[str, bool]:
    """
    CKV_OPENSTACK_4 — admin_pass set on compute instance.
    Removes admin_pass attribute (should use keypair + cloud-init instead).
    Adds a comment explaining the fix.
    """
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False

    body_start, body_end = bounds
    body = content[body_start:body_end - 1]

    # Remove admin_pass line and replace with a comment
    new_body = re.sub(
        r'(\s*)admin_pass\s*=\s*"[^"]*"',
        r'\1# admin_pass removed — use key_pair + user_data for instance access',
        body,
    )
    if new_body == body:
        return content, False
    return content[:body_start] + new_body + "}" + content[body_end:], True


def fix_subnet_no_dns(content: str, finding: dict) -> tuple[str, bool]:
    """Subnet missing dns_nameservers."""
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]
    if re.search(r'^\s*dns_nameservers\s*=', body, re.MULTILINE):
        return content, False
    new_body = body.rstrip() + f"\n  dns_nameservers = {_DEFAULT_DNS}\n"
    return content[:bounds[0]] + new_body + "}" + content[bounds[1]:], True


def fix_router_no_gateway(content: str, finding: dict) -> tuple[str, bool]:
    """Router missing external_network_id."""
    rtype, rname = _parse_resource(finding)
    bounds = _find_resource_block(content, rtype, rname)
    if not bounds:
        return content, False
    body = content[bounds[0]:bounds[1] - 1]
    if re.search(r'^\s*external_network_id\s*=', body, re.MULTILINE):
        return content, False
    placeholder = (
        "\n  # TODO: set external_network_id to your provider network UUID"
        "\n  # Run: openstack network list --external"
        "\n  external_network_id = var.external_network_id\n"
    )
    new_body = body.rstrip() + placeholder
    return content[:bounds[0]] + new_body + "}" + content[bounds[1]:], True


# ─────────────────────────────────────────────────────────────────────────────
# FIX_REGISTRY — corrected mapping
# ─────────────────────────────────────────────────────────────────────────────

FIX_REGISTRY: dict[str, FixRule] = {
    "CKV_OPENSTACK_1": FixRule(
        "CKV_OPENSTACK_1",
        "Hardcoded credentials in OpenStack provider block",
        "LOW",
        fix_hardcoded_credentials,
        "Replaces literal password/token values with var.* references, "
        "appends sensitive variable declarations",
    ),
    "CKV_OPENSTACK_2": FixRule(
        "CKV_OPENSTACK_2",
        "SSH (22) ingress open to 0.0.0.0/0 — restrict to management CIDR",
        "LOW",
        fix_ssh_open_world,
        f"Changes remote_ip_prefix → {_RESTRICTED_MGMT_CIDR}",
    ),
    "CKV_OPENSTACK_3": FixRule(
        "CKV_OPENSTACK_3",
        "RDP (3389) ingress open to 0.0.0.0/0 — restrict to management CIDR",
        "HIGH",
        fix_rdp_open_world,
        f"Changes remote_ip_prefix → {_RESTRICTED_MGMT_CIDR}",
    ),
    "CKV_OPENSTACK_4": FixRule(
        "CKV_OPENSTACK_4",
        "Compute instance has admin_pass set — remove and use keypair",
        "LOW",
        fix_admin_pass,
        "Removes admin_pass attribute, adds comment to use key_pair instead",
    ),
    # Extra network-level rules (không có CKV_OPENSTACK_* official ID,
    # nhưng Checkov custom / community checks có thể dùng)
    "CKV_OPENSTACK_DNS": FixRule(
        "CKV_OPENSTACK_DNS",
        "Subnet missing dns_nameservers",
        "LOW",
        fix_subnet_no_dns,
    ),
    "CKV_OPENSTACK_ROUTER_GW": FixRule(
        "CKV_OPENSTACK_ROUTER_GW",
        "Router missing external_network_id",
        "MEDIUM",
        fix_router_no_gateway,
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
            if x == y: n += 1
            else: break
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

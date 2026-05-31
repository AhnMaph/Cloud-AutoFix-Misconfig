"""
TerraformPatcher — applies fix rules to main.tf content.

Architecture:
  - FIX_REGISTRY: maps check_id → FixRule
  - FixRule: knows HOW to detect and patch a specific block
  - TerraformPatcher: orchestrates reading, applying, writing
"""

from __future__ import annotations

import re
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ─────────────────────────────────────────────────────────────────────────────
# FixRule dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FixRule:
    check_id   : str
    title      : str
    severity   : str
    fixer      : Callable[[str, dict], tuple[str, bool]]
    description: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Individual fixer functions
# Each receives (tf_content: str, finding: dict) → (patched_content: str, changed: bool)
# ─────────────────────────────────────────────────────────────────────────────

def _set_attribute_in_block(content: str, resource_type: str, resource_name: str,
                             attr: str, value: str) -> tuple[str, bool]:
    """
    Generic helper: find a resource block and set/insert an attribute.
    Returns (new_content, was_changed).
    """
    pattern = rf'(resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{)'
    match   = re.search(pattern, content)
    if not match:
        return content, False

    block_start = match.end()
    # Find matching closing brace (brace counting)
    depth = 1
    pos   = block_start
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    block_end    = pos  # after the closing }
    block_body   = content[block_start:block_end - 1]

    # Check if attribute already exists
    attr_pattern = rf'^\s*{re.escape(attr)}\s*='
    if re.search(attr_pattern, block_body, re.MULTILINE):
        # Replace existing value
        new_body = re.sub(
            rf'(\s*{re.escape(attr)}\s*=\s*).*',
            rf'\g<1>{value}',
            block_body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        # Insert before closing brace
        indent   = "  "
        new_body = block_body.rstrip() + f"\n{indent}{attr} = {value}\n"

    if new_body == block_body:
        return content, False

    new_content = content[:block_start] + new_body + "}" + content[block_end:]
    return new_content, True


def _set_nested_attribute(content: str, resource_type: str, resource_name: str,
                           nested_block: str, attr: str, value: str,
                           create_block: bool = True) -> tuple[str, bool]:
    """Set attribute inside a nested block, optionally creating the block."""
    # First find the resource
    res_pattern = rf'(resource\s+"{re.escape(resource_type)}"\s+"{re.escape(resource_name)}"\s*\{{)'
    res_match   = re.search(res_pattern, content)
    if not res_match:
        return content, False

    res_start = res_match.end()
    # Find resource block end
    depth, pos = 1, res_start
    while pos < len(content) and depth > 0:
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
        pos += 1
    res_end  = pos
    res_body = content[res_start:res_end - 1]

    # Check if nested block exists
    nested_pattern = rf'({re.escape(nested_block)}\s*\{{)'
    nested_match   = re.search(nested_pattern, res_body)

    if nested_match:
        # Find nested block body
        nb_start = nested_match.end()
        depth2, p2 = 1, nb_start
        while p2 < len(res_body) and depth2 > 0:
            if res_body[p2] == '{':
                depth2 += 1
            elif res_body[p2] == '}':
                depth2 -= 1
            p2 += 1
        nb_end  = p2
        nb_body = res_body[nb_start:nb_end - 1]

        attr_pattern = rf'^\s*{re.escape(attr)}\s*='
        if re.search(attr_pattern, nb_body, re.MULTILINE):
            new_nb_body = re.sub(
                rf'(\s*{re.escape(attr)}\s*=\s*).*',
                rf'\g<1>{value}',
                nb_body,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            new_nb_body = nb_body.rstrip() + f"\n    {attr} = {value}\n  "

        if new_nb_body == nb_body:
            return content, False

        new_res_body = (
            res_body[:nested_match.end()]
            + new_nb_body
            + "}"
            + res_body[nb_end:]
        )
    elif create_block:
        # Inject the entire nested block
        block_str    = f"\n  {nested_block} {{\n    {attr} = {value}\n  }}\n"
        new_res_body = res_body.rstrip() + block_str
    else:
        return content, False

    new_content = content[:res_start] + new_res_body + "}" + content[res_end:]
    return new_content, True


# ── Concrete fixer implementations ────────────────────────────────────────────

def fix_ebs_encrypted(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_8 / aws-ec2-enable-at-rest-encryption: EBS root volume not encrypted."""
    rtype, rname = _parse_resource(finding)
    return _set_nested_attribute(content, rtype, rname,
                                  "root_block_device", "encrypted", "true")


def fix_ebs_volume_encrypted(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_3: aws_ebs_volume not encrypted."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname, "encrypted", "true")


def fix_s3_versioning(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_21 / S3 versioning disabled."""
    rtype, rname = _parse_resource(finding)
    return _set_nested_attribute(content, rtype, rname,
                                  "versioning", "enabled", "true")


def fix_s3_access_logging(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_18 / S3 access logging disabled."""
    rtype, rname = _parse_resource(finding)
    return _set_nested_attribute(content, rtype, rname,
                                  "logging", "target_bucket", '"s3-access-logs"',
                                  create_block=True)


def fix_cloudtrail_log_validation(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_36 / cloudtrail log file validation disabled."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname,
                                    "enable_log_file_validation", "true")


def fix_cloudtrail_cloudwatch(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_35 / cloudtrail not sending to CloudWatch."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname,
                                    "cloud_watch_logs_group_arn",
                                    '"arn:aws:logs:us-east-1:000000000000:log-group:CloudTrail"')


def fix_rds_backup_retention(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_133 / RDS backup retention too short."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname,
                                    "backup_retention_period", "7")


def fix_rds_minor_upgrade(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_129 / RDS auto minor version upgrade disabled."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname,
                                    "auto_minor_version_upgrade", "true")


def fix_ec2_imdsv2(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_79 / EC2 IMDSv2 not required."""
    rtype, rname = _parse_resource(finding)
    # Need nested metadata_options block with http_tokens = required
    c, changed = _set_nested_attribute(content, rtype, rname,
                                        "metadata_options", "http_tokens", '"required"')
    if changed:
        # Also ensure http_endpoint is enabled
        c, _ = _set_nested_attribute(c, rtype, rname,
                                      "metadata_options", "http_endpoint", '"enabled"')
    return c, changed


def fix_ec2_detailed_monitoring(content: str, finding: dict) -> tuple[str, bool]:
    """CKV_AWS_126 / EC2 detailed monitoring disabled."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname, "monitoring", "true")


def fix_s3_public_acl(content: str, finding: dict) -> tuple[str, bool]:
    """aws-s3-no-public-acl / S3 public ACL."""
    rtype, rname = _parse_resource(finding)
    return _set_attribute_in_block(content, rtype, rname, "acl", '"private"')


def fix_generic_tag_missing(content: str, finding: dict) -> tuple[str, bool]:
    """Add a default 'ManagedBy' tag block if no tags exist."""
    rtype, rname = _parse_resource(finding)
    return _set_nested_attribute(content, rtype, rname,
                                  "tags", "ManagedBy", '"terraform"',
                                  create_block=False)


def _parse_resource(finding: dict) -> tuple[str, str]:
    """Extract resource_type and resource_name from finding['resource']."""
    resource = finding.get("resource", "")
    # Formats: "aws_instance.my_ec2" or "module.x.aws_instance.my_ec2"
    parts = resource.split(".")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return resource, resource


# ─────────────────────────────────────────────────────────────────────────────
# FIX_REGISTRY — maps check_id → FixRule
# ─────────────────────────────────────────────────────────────────────────────

FIX_REGISTRY: dict[str, FixRule] = {
    # ── EC2 ──────────────────────────────────────────────────────────────────
    "CKV_AWS_8": FixRule(
        "CKV_AWS_8", "EBS root volume not encrypted", "HIGH",
        fix_ebs_encrypted,
        "Sets encrypted=true inside root_block_device block",
    ),
    "CKV_AWS_3": FixRule(
        "CKV_AWS_3", "EBS volume not encrypted", "HIGH",
        fix_ebs_volume_encrypted,
    ),
    "CKV_AWS_79": FixRule(
        "CKV_AWS_79", "EC2 IMDSv2 not enforced", "MEDIUM",
        fix_ec2_imdsv2,
        "Adds metadata_options { http_tokens = required }",
    ),
    "CKV_AWS_126": FixRule(
        "CKV_AWS_126", "EC2 detailed monitoring disabled", "LOW",
        fix_ec2_detailed_monitoring,
    ),
    # aws-ec2-enable-at-rest-encryption (tfsec rule ID)
    "aws-ec2-enable-at-rest-encryption": FixRule(
        "aws-ec2-enable-at-rest-encryption", "EBS not encrypted (tfsec)", "HIGH",
        fix_ebs_encrypted,
    ),
    "aws-ec2-no-public-ip": FixRule(
        "aws-ec2-no-public-ip", "EC2 public IP association", "LOW",
        lambda c, f: _set_attribute_in_block(
            c, *_parse_resource(f)[:2], "associate_public_ip_address", "false"),
    ),
    "AVD-AWS-0131": FixRule(   # Trivy rule for IMDSv2
        "AVD-AWS-0131", "EC2 IMDSv2 not required (Trivy)", "HIGH",
        fix_ec2_imdsv2,
    ),

    # ── S3 ───────────────────────────────────────────────────────────────────
    "CKV_AWS_18": FixRule(
        "CKV_AWS_18", "S3 access logging disabled", "LOW",
        fix_s3_access_logging,
    ),
    "CKV_AWS_21": FixRule(
        "CKV_AWS_21", "S3 versioning disabled", "LOW",
        fix_s3_versioning,
    ),
    "aws-s3-enable-versioning": FixRule(
        "aws-s3-enable-versioning", "S3 versioning disabled (tfsec)", "LOW",
        fix_s3_versioning,
    ),
    "aws-s3-enable-logging": FixRule(
        "aws-s3-enable-logging", "S3 logging disabled (tfsec)", "LOW",
        fix_s3_access_logging,
    ),
    "aws-s3-no-public-acl": FixRule(
        "aws-s3-no-public-acl", "S3 public ACL (tfsec)", "HIGH",
        fix_s3_public_acl,
    ),

    # ── CloudTrail ────────────────────────────────────────────────────────────
    "CKV_AWS_36": FixRule(
        "CKV_AWS_36", "CloudTrail log file validation disabled", "LOW",
        fix_cloudtrail_log_validation,
    ),
    "CKV_AWS_35": FixRule(
        "CKV_AWS_35", "CloudTrail not integrated with CloudWatch", "LOW",
        fix_cloudtrail_cloudwatch,
    ),
    "aws-cloudtrail-enable-log-validation": FixRule(
        "aws-cloudtrail-enable-log-validation",
        "CloudTrail log validation (tfsec)", "LOW",
        fix_cloudtrail_log_validation,
    ),

    # ── RDS ──────────────────────────────────────────────────────────────────
    "CKV_AWS_129": FixRule(
        "CKV_AWS_129", "RDS auto minor version upgrade disabled", "LOW",
        fix_rds_minor_upgrade,
    ),
    "CKV_AWS_133": FixRule(
        "CKV_AWS_133", "RDS backup retention < 7 days", "LOW",
        fix_rds_backup_retention,
    ),
    "aws-rds-enable-minor-version-upgrade": FixRule(
        "aws-rds-enable-minor-version-upgrade", "RDS minor upgrade (tfsec)", "LOW",
        fix_rds_minor_upgrade,
    ),
    "aws-rds-specify-backup-retention": FixRule(
        "aws-rds-specify-backup-retention", "RDS backup retention (tfsec)", "LOW",
        fix_rds_backup_retention,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# SingleFilePatcher — patches one .tf file in memory
# ─────────────────────────────────────────────────────────────────────────────

class SingleFilePatcher:
    def __init__(self, tf_path: Path):
        self.tf_path  = tf_path
        self.original = tf_path.read_text(encoding="utf-8")
        self.content  = self.original
        self.dirty    = False           # True once any fix is applied

    def apply(self, findings: list[dict]) -> list[dict]:
        """Apply all findings that target this file. Returns per-finding results."""
        results = []
        for finding in findings:
            check_id = finding.get("rule_id") or finding.get("check_id", "")
            rule     = FIX_REGISTRY.get(check_id)

            if not rule:
                results.append({**finding,
                                 "status": "skipped",
                                 "reason": f"No fixer rule for {check_id}"})
                continue

            try:
                new_content, changed = rule.fixer(self.content, finding)
                if changed:
                    self.content = new_content
                    self.dirty   = True
                    results.append({**finding,
                                    "status": "fixed",
                                    "rule"  : rule.title})
                else:
                    results.append({**finding,
                                    "status": "skipped",
                                    "reason": "Pattern not found or already compliant"})
            except Exception as exc:
                results.append({**finding,
                                 "status": "failed",
                                 "reason": str(exc)})

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
# MultiFilePatcher — orchestrates patching across many .tf files
# ─────────────────────────────────────────────────────────────────────────────

class MultiFilePatcher:
    """
    Groups findings by the .tf file they reference, routes each group to
    a SingleFilePatcher, and mirrors the patched output tree under out_dir.

    Finding-to-file matching strategy (in priority order):
      1. Exact absolute/relative path match
      2. Basename match  (tools often report just 'main.tf', not full path)
      3. Suffix match    (longest common suffix wins)
    """

    def __init__(self, tf_files: list[Path], out_dir: Path, dry_run: bool = False):
        self.tf_files = tf_files
        self.out_dir  = out_dir
        self.dry_run  = dry_run
        # Keyed by resolved absolute path
        self._patchers: dict[Path, SingleFilePatcher] = {
            f.resolve(): SingleFilePatcher(f) for f in tf_files
        }

    # ── public API ────────────────────────────────────────────────────────────

    def apply(self, findings: list[dict]) -> list[dict]:
        """Route findings to the right SingleFilePatcher and collect results."""
        all_results = []
        unmatched   = []

        for finding in findings:
            target = self._resolve_file(finding.get("file_path") or finding.get("file") or "")
            if target is None:
                unmatched.append(finding)
                all_results.append({
                    **finding,
                    "status": "skipped",
                    "reason": f"No matching .tf file for '{finding.get('file','')}'"
                })
                continue

            # Delegate — SingleFilePatcher.apply() takes a list
            results = self._patchers[target].apply([finding])
            all_results.extend(results)

        if unmatched:
            print(f"  ⚠️  {len(unmatched)} finding(s) could not be matched to a .tf file")

        return all_results

    def write_all(self) -> dict[Path, Path]:
        """
        Write every dirty (changed) file to out_dir, preserving relative structure.
        Returns {original_path: output_path} for files that were written.
        """
        written = {}
        if self.dry_run:
            return written

        # Find common ancestor to reconstruct relative paths
        resolved = list(self._patchers.keys())
        try:
            common = Path(*resolved[0].parts[:self._common_prefix_len(resolved)])
        except Exception:
            common = resolved[0].parent

        for abs_path, patcher in self._patchers.items():
            if not patcher.dirty:
                continue
            try:
                rel       = abs_path.relative_to(common)
            except ValueError:
                rel       = Path(abs_path.name)
            out_path  = self.out_dir / rel
            if out_path.is_dir() or out_path == self.out_dir:
                # Đảm bảo tạo thư mục cha trước nếu cần
                out_path.mkdir(parents=True, exist_ok=True)
                # Ép đường dẫn đích phải đi kèm tên file cụ thể (Ví dụ: fix_output/main.tf)
                out_path = out_path / abs_path.name
            patcher.write(out_path)
            written[abs_path] = out_path

        return written

    # ── private helpers ───────────────────────────────────────────────────────

    def _resolve_file(self, reported_path: str) -> Path | None:
        """Map a path string from a scanner finding to a known tf_file."""
        if not reported_path:
            return None

        rp = Path(reported_path)

        # 1. Exact match (resolved)
        try:
            candidate = rp.resolve()
            if candidate in self._patchers:
                return candidate
        except Exception:
            pass

        # 2. Basename match — safe when all filenames are unique
        basename = rp.name
        matches  = [p for p in self._patchers if p.name == basename]
        if len(matches) == 1:
            return matches[0]

        # 3. Longest-suffix match
        best, best_len = None, 0
        rp_parts = rp.parts
        for p in self._patchers:
            common_len = self._common_suffix_len(p.parts, rp_parts)
            if common_len > best_len:
                best, best_len = p, common_len
        return best  # None if nothing matched

    @staticmethod
    def _common_suffix_len(a: tuple, b: tuple) -> int:
        length = 0
        for x, y in zip(reversed(a), reversed(b)):
            if x == y:
                length += 1
            else:
                break
        return length

    @staticmethod
    def _common_prefix_len(paths: list[Path]) -> int:
        if not paths:
            return 0
        parts_list = [p.parts for p in paths]
        min_len    = min(len(p) for p in parts_list)
        prefix_len = 0
        for i in range(min_len):
            if len({p[i] for p in parts_list}) == 1:
                prefix_len += 1
            else:
                break
        return prefix_len

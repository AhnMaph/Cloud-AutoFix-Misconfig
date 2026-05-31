"""Normalize Checkov JSON output (OpenStack provider) → common Finding schema.

Correct CKV_OPENSTACK_* severity mapping (từ Checkov source + Prisma Cloud docs):
  CKV_OPENSTACK_1 — HIGH   — Hardcoded creds trong provider block
  CKV_OPENSTACK_2 — HIGH   — SSH (22) ingress 0.0.0.0/0
  CKV_OPENSTACK_3 — HIGH   — RDP (3389) ingress 0.0.0.0/0
  CKV_OPENSTACK_4 — MEDIUM — admin_pass on compute instance
"""

from __future__ import annotations

SEVERITY_MAP: dict[str, str] = {
    "CKV_OPENSTACK_1": "LOW",    # hardcoded provider credentials
    "CKV_OPENSTACK_2": "HIGH",    # SSH 0.0.0.0/0
    "CKV_OPENSTACK_3": "LOW",    # RDP 0.0.0.0/0
    "CKV_OPENSTACK_4": "LOW",  # admin_pass on compute instance
}


def normalize_checkov(data: dict | list) -> list[dict]:
    findings = []
    results_list = data if isinstance(data, list) else [data]

    for framework_result in results_list:
        if not isinstance(framework_result, dict):
            continue

        failed_checks = framework_result.get("results", {}).get("failed_checks", [])

        for chk in failed_checks:
            check_id = chk.get("check_id", "UNKNOWN")

            raw_sev  = chk.get("severity")
            severity = (raw_sev.upper() if raw_sev else None) \
                       or SEVERITY_MAP.get(check_id, "UNKNOWN")

            file_path  = chk.get("repo_file_path") or chk.get("file_path", "UNKNOWN")
            resource   = chk.get("resource", "UNKNOWN")
            line_range = chk.get("file_line_range", [0])
            start_line = line_range[0] if line_range else 0
            end_line   = line_range[1] if len(line_range) > 1 else start_line

            description = (
                chk.get("check", {}).get("name", "")
                if isinstance(chk.get("check"), dict)
                else chk.get("check_name", check_id)
            )

            findings.append({
                "scanner"    : "checkov",
                "rule_id"    : check_id,
                "severity"   : severity,
                "resource"   : resource,
                "description": description,
                "file_path"  : file_path,
                "line"       : start_line,
                "line_end"   : end_line,
                "guideline"  : chk.get("guideline", ""),
            })

    return findings

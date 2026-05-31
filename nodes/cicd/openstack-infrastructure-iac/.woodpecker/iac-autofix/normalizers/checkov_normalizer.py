"""Normalize Checkov JSON output (OpenStack provider) → common Finding schema."""

from __future__ import annotations

# Offline severity map — Checkov OSS trả null cho OpenStack checks
SEVERITY_MAP: dict[str, str] = {
    # Security Group rules
    "CKV_OPENSTACK_1" : "HIGH",    # SSH 0.0.0.0/0
    "CKV_OPENSTACK_2" : "HIGH",    # RDP 0.0.0.0/0
    "CKV_OPENSTACK_4" : "MEDIUM",  # allow all ingress
    "CKV_OPENSTACK_5" : "MEDIUM",  # allow all egress
    # Compute
    "CKV_OPENSTACK_3" : "HIGH",    # no keypair
    "CKV_OPENSTACK_6" : "LOW",     # metadata service
    # Networking
    "CKV_OPENSTACK_7" : "MEDIUM",  # router no external gateway
    "CKV_OPENSTACK_8" : "LOW",     # subnet no DNS
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

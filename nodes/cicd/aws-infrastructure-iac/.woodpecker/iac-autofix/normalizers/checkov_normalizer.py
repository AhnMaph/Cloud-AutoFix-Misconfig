"""Normalize Checkov JSON output → common Finding schema."""

from __future__ import annotations

# Offline severity fallback — Checkov OSS trả về null cho severity
SEVERITY_MAP = {
    # EC2
    "CKV_AWS_8"  : "HIGH",    "CKV_AWS_28" : "MEDIUM",  "CKV_AWS_79" : "MEDIUM",
    "CKV_AWS_126": "LOW",     "CKV_AWS_135": "LOW",
    # S3
    "CKV_AWS_18" : "LOW",     "CKV_AWS_19" : "HIGH",    "CKV_AWS_20" : "HIGH",
    "CKV_AWS_52" : "MEDIUM",  "CKV_AWS_53" : "HIGH",    "CKV_AWS_54" : "HIGH",
    "CKV_AWS_55" : "LOW",     "CKV_AWS_56" : "LOW",
    # RDS
    "CKV_AWS_16" : "HIGH",    "CKV_AWS_17" : "HIGH",    "CKV_AWS_23" : "LOW",
    "CKV_AWS_129": "LOW",     "CKV_AWS_133": "LOW",
    # IAM
    "CKV_AWS_1"  : "HIGH",    "CKV_AWS_40" : "HIGH",    "CKV_AWS_274": "LOW",
    # Security Group
    "CKV_AWS_24" : "HIGH",    "CKV_AWS_25" : "HIGH",    "CKV_AWS_260": "LOW",
    # EBS
    "CKV_AWS_3"  : "HIGH",
    # CloudTrail
    "CKV_AWS_35" : "LOW",     "CKV_AWS_36" : "LOW",     "CKV_AWS_67" : "LOW",
}


def normalize_checkov(data: dict | list) -> list[dict]:
    findings = []

    # Checkov JSON: list of framework results hoặc single dict
    results_list = data if isinstance(data, list) else [data]

    for framework_result in results_list:
        if not isinstance(framework_result, dict):
            continue

        failed_checks = framework_result.get("results", {}).get("failed_checks", [])

        for chk in failed_checks:
            check_id = chk.get("check_id", "UNKNOWN")

            # Checkov OSS trả null → fallback sang SEVERITY_MAP
            raw_sev  = chk.get("severity")
            severity = (raw_sev.upper() if raw_sev else None) \
                       or SEVERITY_MAP.get(check_id, "UNKNOWN")

            file_path  = chk.get("repo_file_path") or chk.get("file_path", "UNKNOWN")
            resource   = chk.get("resource", "UNKNOWN")
            line_range = chk.get("file_line_range", [0])
            start_line = line_range[0] if line_range else 0
            end_line   = line_range[1] if len(line_range) > 1 else start_line

            # check_name: Checkov có thể để ở chk["check"]["name"] hoặc chk["check_name"]
            description = (
                chk.get("check", {}).get("name", "")
                if isinstance(chk.get("check"), dict)
                else chk.get("check_name", check_id)
            )

            findings.append({
                # ── primary fields (schema chung) ───────────────
                "scanner"    : "checkov",
                "rule_id"    : check_id,
                "severity"   : severity,
                "resource"   : resource,
                "description": description,
                "file_path"  : file_path,
                "line"       : start_line,
                # ── extended fields ──────────────────────────────
                "line_end"   : end_line,
                "guideline"  : chk.get("guideline", ""),
            })

    return findings

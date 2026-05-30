"""Normalize Trivy JSON output → common Finding schema."""

from __future__ import annotations

SEV_MAP = {
    "CRITICAL": "CRITICAL",
    "HIGH"    : "HIGH",
    "MEDIUM"  : "MEDIUM",
    "LOW"     : "LOW",
    "UNKNOWN" : "UNKNOWN",
}


def normalize_trivy(data: dict | list) -> list[dict]:
    findings = []

    # Trivy config scan: {"Results": [...]}
    results = data.get("Results", []) if isinstance(data, dict) else data

    for result in results:
        if not isinstance(result, dict):
            continue

        file_path  = result.get("Target", "UNKNOWN")
        misconfigs = result.get("Misconfigurations", [])

        for item in misconfigs:
            # Chỉ lấy FAIL — bỏ PASS / EXCEPTION
            if item.get("Status", "FAIL") != "FAIL":
                continue

            raw_sev  = item.get("Severity", "UNKNOWN").upper()
            severity = SEV_MAP.get(raw_sev, "UNKNOWN")

            cause      = item.get("CauseMetadata", {})
            start_line = cause.get("StartLine", 0)
            end_line   = cause.get("EndLine", start_line)

            findings.append({
                # ── primary fields (schema chung) ───────────────
                "scanner"    : "trivy",
                "rule_id"    : item.get("ID", "UNKNOWN"),
                "severity"   : severity,
                "resource"   : cause.get("Resource", "UNKNOWN"),
                "description": item.get("Title", item.get("Description", "")),
                "file_path"  : file_path,
                "line"       : start_line,
                # ── extended fields ──────────────────────────────
                "line_end"   : end_line,
                "guideline"  : item.get("PrimaryURL", ""),
            })

    return findings

"""Normalize tfsec JSON output → common Finding schema."""

from __future__ import annotations

SEV_MAP = {
    "CRITICAL": "CRITICAL",
    "HIGH"    : "HIGH",
    "MEDIUM"  : "MEDIUM",
    "LOW"     : "LOW",
    "INFO"    : "LOW",    # tfsec INFO → treat as LOW
}


def normalize_tfsec(data: dict | list) -> list[dict]:
    findings = []

    # tfsec output: {"results": [...]} hoặc list trực tiếp
    results = data if isinstance(data, list) else data.get("results", [])

    for item in results:
        if not isinstance(item, dict):
            continue

        # Bỏ qua các rule đã pass (tfsec đôi khi include passed results)
        if item.get("status", 0) == 0 and item.get("passed", False):
            continue

        raw_sev  = item.get("severity", "UNKNOWN").upper()
        severity = SEV_MAP.get(raw_sev, "UNKNOWN")

        location   = item.get("location", {})
        file_path  = location.get("filename", location.get("file", "UNKNOWN"))
        start_line = location.get("start_line", 0)
        end_line   = location.get("end_line", start_line)

        links    = item.get("links", [])
        guideline = links[0] if links else ""

        findings.append({
            # ── primary fields (schema chung) ───────────────
            "scanner"    : "tfsec",
            "rule_id"    : item.get("rule_id", item.get("long_id", "UNKNOWN")),
            "severity"   : severity,
            "resource"   : item.get("resource", "UNKNOWN"),
            "description": item.get("description",
                           item.get("rule_description", "")),
            "file_path"  : file_path,
            "line"       : start_line,
            # ── extended fields ──────────────────────────────
            "line_end"   : end_line,
            "guideline"  : guideline,
        })

    return findings

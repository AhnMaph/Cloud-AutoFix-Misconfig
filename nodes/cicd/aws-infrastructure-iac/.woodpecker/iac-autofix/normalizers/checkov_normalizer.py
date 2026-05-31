"""Normalize Checkov JSON output → common Finding schema."""

from __future__ import annotations

import json
from pathlib import Path

# Checkov OSS trả null cho severity → tra cứu static map theo check_id
_MAPPINGS_PATH = Path(__file__).resolve().parent.parent.parent / "checkov_severity_mappings.json"
VALID_SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"})


def _load_severity_mappings() -> dict[str, str]:
    with open(_MAPPINGS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mappings", {})


SEVERITY_MAP: dict[str, str] = _load_severity_mappings()


def resolve_severity(raw_sev: str | None, check_id: str) -> str:
    """Return Checkov severity when valid; otherwise map by check_id or UNKNOWN."""
    if raw_sev and isinstance(raw_sev, str):
        normalized = raw_sev.strip().upper()
        if normalized in VALID_SEVERITIES:
            return normalized
    return SEVERITY_MAP.get(check_id, "UNKNOWN")


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
            severity = resolve_severity(chk.get("severity"), check_id)

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

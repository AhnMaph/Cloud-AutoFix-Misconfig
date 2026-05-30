# opa/aws/iac.rego
#
# Policy: Deny pipeline nếu có bất kỳ finding nào severity != LOW
# (tức là MEDIUM, HIGH, CRITICAL đều block)
#
# Input schema (normalized-results.json):
# [
#   {
#     "scanner"    : "tfsec" | "checkov" | "trivy",
#     "rule_id"    : "CKV_AWS_8",
#     "severity"   : "HIGH",
#     "resource"   : "aws_instance.vulnerable_ec2",
#     "description": "...",
#     "file_path"  : "main.tf",
#     "line"       : 5,
#     "line_end"   : 12,
#     "guideline"  : "https://..."
#   },
#   ...
# ]
#
# Gọi từ pipeline:
#   curl -X POST http://opa:8181/v1/data/aws/iac \
#        -H "Content-Type: application/json" \
#        -d '{"input": <array>}'
#
# OPA trả về:
#   { "result": { "allow": false, "deny": [...], "summary": {...} } }

package aws.iac

import future.keywords.in
import future.keywords.if
import future.keywords.contains
import future.keywords.every

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Severity thứ tự — dùng để sort trong output
SEVERITY_RANK := {
    "CRITICAL": 4,
    "HIGH"    : 3,
    "MEDIUM"  : 2,
    "LOW"     : 1,
    "UNKNOWN" : 0,
}

# Severity được phép pass (không block pipeline)
ALLOWED_SEVERITIES := {"LOW"}

# Severity sẽ block pipeline
BLOCKED_SEVERITIES := {"CRITICAL", "HIGH", "MEDIUM", "UNKNOWN"}

# ─────────────────────────────────────────────────────────────────────────────
# Helper rules
# ─────────────────────────────────────────────────────────────────────────────

# Normalize severity về uppercase, default UNKNOWN nếu thiếu
severity_of(finding) := upper(finding.severity) if finding.severity
severity_of(_)       := "UNKNOWN"

# True nếu finding cần block
is_blocked(finding) if {
    sev := severity_of(finding)
    sev in BLOCKED_SEVERITIES
}

# ─────────────────────────────────────────────────────────────────────────────
# Core: tập hợp các finding bị deny
# ─────────────────────────────────────────────────────────────────────────────

deny contains finding if {
    some finding in input
    is_blocked(finding)
}

# ─────────────────────────────────────────────────────────────────────────────
# allow / violations — entry points chính cho pipeline check
# ─────────────────────────────────────────────────────────────────────────────

# Pipeline được phép chạy chỉ khi không có finding nào bị block
allow if {
    count(deny) == 0
}

# Mặc định deny nếu có blocking findings
default allow := false

# ─────────────────────────────────────────────────────────────────────────────
# violations — chi tiết từng finding bị block (dùng cho report)
# ─────────────────────────────────────────────────────────────────────────────

violations contains msg if {
    some finding in deny
    sev  := severity_of(finding)
    rank := object.get(SEVERITY_RANK, sev, 0)
    msg  := {
        "rule_id"    : finding.rule_id,
        "severity"   : sev,
        "severity_rank": rank,
        "scanner"    : finding.scanner,
        "resource"   : finding.resource,
        "file_path"  : finding.file_path,
        "line"       : finding.line,
        "description": finding.description,
        "guideline"  : object.get(finding, "guideline", ""),
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# Per-severity counts — dùng cho ELK metrics
# ─────────────────────────────────────────────────────────────────────────────

count_by_severity[sev] := n if {
    sev in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}
    n   := count([f | some f in input; severity_of(f) == sev])
}

count_by_scanner[scanner] := n if {
    some scanner
    scanner in {f.scanner | some f in input}
    n := count([f | some f in input; f.scanner == scanner])
}

# ─────────────────────────────────────────────────────────────────────────────
# summary — tổng hợp trả về cùng response (tiện cho CI log)
# ─────────────────────────────────────────────────────────────────────────────

summary := {
    "allow"           : allow,
    "total_findings"  : count(input),
    "blocked_findings": count(deny),
    "by_severity"     : count_by_severity,
    "by_scanner"      : count_by_scanner,
    "policy_version"  : "1.0.0",
}

# ─────────────────────────────────────────────────────────────────────────────
# critical_only — subset chỉ CRITICAL (dùng cho alert riêng)
# ─────────────────────────────────────────────────────────────────────────────

critical_findings contains finding if {
    some finding in input
    severity_of(finding) == "CRITICAL"
}

has_critical if count(critical_findings) > 0

package openstack.iac

import future.keywords.in
import future.keywords.if
import future.keywords.contains

# ─────────────────────────────────────────────────────────────────────────────
# Helper rules & Functions
# ─────────────────────────────────────────────────────────────────────────────

# SỬA LỖI TẠI ĐÂY: Dùng cấu trúc else chuẩn của Rego
severity_of(finding) := upper(finding.severity) if {
    finding.severity
} else := "UNKNOWN"

# Hàm kiểm tra block
is_blocked(finding) := true if {
    sev := severity_of(finding)
    sev != "LOW"
}

# ─────────────────────────────────────────────────────────────────────────────
# QUY TẮC QUYẾT ĐỊNH
# ─────────────────────────────────────────────────────────────────────────────

default deny := false

# TRƯỜNG HỢP 1: Chặn nếu có lỗi nguy hiểm nằm trong danh sách KHÔNG THỂ TỰ VÁ (no_fix)
deny if {
    some finding in input.no_fix
    is_blocked(finding)
}

# TRƯỜNG HỢP 2: Chặn nếu có lỗi nguy hiểm nằm trong danh sách fix_results nhưng bị "skipped" hoặc "failed"
deny if {
    some finding in input.fix_results
    is_blocked(finding)
    finding.status in {"skipped", "failed"}
}

main := {
    "deny": deny
}
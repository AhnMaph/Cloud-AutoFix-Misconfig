package aws.iac

import future.keywords.in
import future.keywords.if

# ─────────────────────────────────────────────────────────────────────────────
# Helper rules
# ─────────────────────────────────────────────────────────────────────────────

# Định nghĩa hàm dùng else để đảm bảo duy nhất 1 đầu ra (Sửa lỗi dòng 12)
severity_of(finding) := upper(finding.severity) if {
    finding.severity
} else := "UNKNOWN"

# Định nghĩa danh sách các Severity bắt buộc phải BLOCK nếu xuất hiện trong hệ thống
blocked_severities := {"HIGH", "CRITICAL"}

# Lỗi bị block nếu mức độ nghiêm trọng nằm trong danh sách cấm
is_blocked(finding) if {
    sev := severity_of(finding)
    sev in blocked_severities
}

# ─────────────────────────────────────────────────────────────────────────────
# QUY TẮC QUYẾT ĐỊNH (Gộp mảng xử lý schema từ pipeline)
# ─────────────────────────────────────────────────────────────────────────────

# Mặc định pipeline sẽ được CHO PHÉP (không bị deny)
default deny := false

# TRƯỜNG HỢP 1: Chặn nếu có lỗi nguy hiểm (MED/HIGH/CRIT) nằm trong danh sách KHÔNG THỂ TỰ VÁ (no_fix)
deny if {
    some finding in input.no_fix
    is_blocked(finding)
}

# TRƯỜNG HỢP 2: Chặn nếu có lỗi nguy hiểm nằm trong danh sách fix_results nhưng auto-patch bị "skipped" hoặc "failed"
deny if {
    some finding in input.fix_results
    is_blocked(finding)
    finding.status in {"skipped", "failed"}
}

# ─────────────────────────────────────────────────────────────────────────────
# ĐỊNH HÌNH FORMAT ĐẦU RA
# ─────────────────────────────────────────────────────────────────────────────

main := {
    "deny": deny
}
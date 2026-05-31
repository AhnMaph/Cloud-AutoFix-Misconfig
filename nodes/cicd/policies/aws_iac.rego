package aws.iac

import future.keywords.in
import future.keywords.if

# ─────────────────────────────────────────────────────────────────────────────
# Helper rules
# ─────────────────────────────────────────────────────────────────────────────

# Trích xuất và chuẩn hóa mức độ lỗi
severity_of(finding) := upper(finding.severity) if finding.severity
severity_of(_)       := "UNKNOWN"

# BẤT KỲ lỗi nào có mức độ KHÔNG PHẢI LÀ "LOW" thì đều bị block!
is_blocked(finding) if {
    sev := severity_of(finding)
    sev != "LOW"
}

# ─────────────────────────────────────────────────────────────────────────────
# QUY TẮC QUYẾT ĐỊNH (Gộp mảng xử lý schema mới)
# ─────────────────────────────────────────────────────────────────────────────

# Mặc định pipeline sẽ được CHO PHÉP (không bị deny)
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
# ─────────────────────────────────────────────────────────────────────────────
# ĐỊNH HÌNH FORMAT ĐẦU RA: Trả về trực tiếp trường "deny" thay vì "result"
# ─────────────────────────────────────────────────────────────────────────────

main := {
    "deny": deny
}
# ============================================================
# policies/aws_iac.rego
# ============================================================

package aws.iac

default deny = false

# Từ chối (Deny) pipeline nếu có bất kỳ lỗi nào mang mức độ HIGH hoặc CRITICAL
deny {
    some i
    vuln := input[i]
    vuln.severity == "HIGH"
}

deny {
    some i
    vuln := input[i]
    vuln.severity == "CRITICAL"
}
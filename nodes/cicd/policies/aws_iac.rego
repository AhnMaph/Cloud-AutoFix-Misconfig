# ============================================================
# policies/aws_iac.rego
# ============================================================

package aws.iac

import future.keywords.if
import future.keywords.in

# ❌ Quy định mặc định ban đầu là mảng rỗng (Tránh lỗi tự sinh Object {})
deny := msg_list if {
    some_rules := [msg | 
        # Thử kiểm tra tfsec critical
        input.metrics.tfsec_critical > 0
        msg := sprintf("OPA BLOCK: tfsec detected %v CRITICAL vulnerabilities!", [input.metrics.tfsec_critical])
    ]
    
    some_rules_high := [msg |
        input.metrics.tfsec_high > 0
        msg := sprintf("OPA BLOCK: tfsec detected %v HIGH vulnerabilities!", [input.metrics.tfsec_high])
    ]

    some_rules_trivy_crit := [msg |
        input.metrics.trivy_critical > 0
        msg := sprintf("OPA BLOCK: Trivy detected %v CRITICAL misconfigurations!", [input.metrics.trivy_critical])
    ]

    some_rules_trivy_high := [msg |
        input.metrics.trivy_high > 0
        msg := sprintf("OPA BLOCK: Trivy detected %v HIGH misconfigurations!", [input.metrics.trivy_high])
    ]

    some_rules_checkov := [msg |
        input.metrics.checkov_total_failed > 0
        msg := sprintf("OPA BLOCK: Checkov detected %v failed security checks!", [input.metrics.checkov_total_failed])
    ]

    # Gộp tất cả các mảng lỗi lại làm một
    msg_list := array.concat(some_rules, array.concat(some_rules_high, array.concat(some_rules_trivy_crit, array.concat(some_rules_trivy_high, some_rules_checkov))))
}
# opa/openstack/iac.rego
#
# Policy: Deny nếu có finding severity != LOW cho OpenStack IaC
# Tương tự AWS policy nhưng có thêm OpenStack-specific rules

package openstack.iac

import future.keywords.in
import future.keywords.if
import future.keywords.contains

SEVERITY_RANK := {
    "CRITICAL": 4,
    "HIGH"    : 3,
    "MEDIUM"  : 2,
    "LOW"     : 1,
    "UNKNOWN" : 0,
}

BLOCKED_SEVERITIES := {"CRITICAL", "HIGH", "MEDIUM", "UNKNOWN"}

# ── Network-specific HIGH risk rules — always block bất kể severity ──────────
# Những rule này quá nguy hiểm, override cả LOW nếu misconfig
CRITICAL_NETWORK_RULES := {
    "CKV_OPENSTACK_1",   # SSH open world
    "CKV_OPENSTACK_2",   # RDP open world
}

severity_of(f) := upper(f.severity) if f.severity
severity_of(_) := "UNKNOWN"

# Blocked nếu severity cao hoặc là critical network rule
is_blocked(f) if {
    severity_of(f) in BLOCKED_SEVERITIES
}

is_blocked(f) if {
    f.rule_id in CRITICAL_NETWORK_RULES
}

deny contains f if {
    some f in input
    is_blocked(f)
}

default allow := false

allow if { count(deny) == 0 }

violations contains msg if {
    some f in deny
    sev  := severity_of(f)
    msg  := {
        "rule_id"      : f.rule_id,
        "severity"     : sev,
        "severity_rank": object.get(SEVERITY_RANK, sev, 0),
        "scanner"      : f.scanner,
        "resource"     : f.resource,
        "file_path"    : f.file_path,
        "line"         : f.line,
        "description"  : f.description,
        "guideline"    : object.get(f, "guideline", ""),
    }
}

# ── Network-specific aggregations ────────────────────────────────────────────

# Security group rules với 0.0.0.0/0
open_world_rules contains f if {
    some f in input
    f.rule_id in CRITICAL_NETWORK_RULES
}

# Tất cả security group findings
secgroup_findings contains f if {
    some f in input
    regex.match(`CKV_OPENSTACK_[124578]`, f.rule_id)
}

count_by_severity[sev] := n if {
    sev in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"}
    n   := count([f | some f in input; severity_of(f) == sev])
}

summary := {
    "allow"              : allow,
    "total_findings"     : count(input),
    "blocked_findings"   : count(deny),
    "open_world_rules"   : count(open_world_rules),
    "secgroup_findings"  : count(secgroup_findings),
    "by_severity"        : count_by_severity,
    "policy_version"     : "1.0.0",
    "cloud_provider"     : "openstack",
}

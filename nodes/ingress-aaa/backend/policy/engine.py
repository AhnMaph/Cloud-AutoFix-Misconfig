import yaml
from pathlib import Path

POLICY_FILE = Path(__file__).parent / "routing_policy.yaml"

def load_policy():
    with open(POLICY_FILE) as f:
        return yaml.safe_load(f)

def resolve_provider(resource_type: str) -> str:
    """
    Trả về 'aws' hoặc 'openstack' dựa trên resource_type.
    """
    policy = load_policy()
    
    for rule in policy["rules"]:
        if rule["resource_type"] == resource_type:
            return rule["provider"]
        if rule["resource_type"] == "*":
            return rule["provider"]  # fallback
    
    return "aws"  # default
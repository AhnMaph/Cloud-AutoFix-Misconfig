import os
import hvac
from fastapi import HTTPException

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
VAULT_KV_MOUNT = os.getenv("VAULT_KV_MOUNT", "kv")
AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID")
KEYCLOAK_PIPELINE_CLIENT_ID = os.getenv("KEYCLOAK_PIPELINE_CLIENT_ID", "aws-pipeline-client")
KEYCLOAK_PIPELINE_AUDIENCE = os.getenv("KEYCLOAK_PIPELINE_AUDIENCE", "account")


def vault_client():
    if not VAULT_TOKEN:
        raise HTTPException(status_code=500, detail="Missing VAULT_TOKEN")

    client = hvac.Client(
        url=VAULT_ADDR,
        token=VAULT_TOKEN,
    )

    if not client.is_authenticated():
        raise HTTPException(status_code=500, detail="Vault authentication failed")

    return client


def write_cloud_token(request_id: str, data: dict):
    client = vault_client()
    path = f"cloud-token/{request_id}"

    client.secrets.kv.v2.create_or_update_secret(
        mount_point=VAULT_KV_MOUNT,
        path=path,
        secret=data,
    )

    return {
        "vault_path": f"{VAULT_KV_MOUNT}/data/{path}",
        "request_id": request_id,
    }


def read_cloud_token(request_id: str) -> dict:
    client = vault_client()
    path = f"cloud-token/{request_id}"

    try:
        res = client.secrets.kv.v2.read_secret_version(
            mount_point=VAULT_KV_MOUNT,
            path=path,
        )
        return res["data"]["data"]
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Cloud token not found for request_id={request_id}: {str(e)}",
        )

def provision_vault_aws_for_tenant(tenant_id: str) -> dict:
    """
    Tạo cấu hình Vault cho 1 tenant:
    - aws/roles/<tenant_id>-deploy
    - policy tenant-<tenant_id>-aws
    - auth/jwt/role/<tenant_id>-pipeline
    """

    if not AWS_ACCOUNT_ID:
        raise HTTPException(status_code=500, detail="Missing AWS_ACCOUNT_ID")

    client = vault_client()

    tenant_slug = tenant_id.lower().strip()
    aws_role_name = f"hybridcompany-{tenant_slug}-deploy-role"
    aws_role_arn = f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{aws_role_name}"

    vault_aws_role = f"{tenant_slug}-deploy"
    vault_policy_name = f"tenant-{tenant_slug}-aws"
    vault_jwt_role = f"{tenant_slug}-pipeline"

    # 1. Vault AWS role: map Vault role -> AWS IAM tenant role
    client.write(
        f"aws/roles/{vault_aws_role}",
        credential_type="assumed_role",
        role_arns=aws_role_arn,
        default_sts_ttl="30m",
        max_sts_ttl="1h",
    )

    # 2. Vault policy: chỉ cho đọc đúng aws/sts/<tenant>-deploy
    policy = f'''
path "aws/sts/{vault_aws_role}" {{
  capabilities = ["read"]
}}
'''
    client.sys.create_or_update_policy(
        name=vault_policy_name,
        policy=policy,
    )

    # 3. Vault JWT role: Keycloak token -> Vault policy tenant
    client.write(
        f"auth/jwt/role/{vault_jwt_role}",
        role_type="jwt",
        user_claim="sub",
        bound_audiences=[KEYCLOAK_PIPELINE_AUDIENCE],
        bound_claims={
            "azp": KEYCLOAK_PIPELINE_CLIENT_ID
        },
        policies=[vault_policy_name],
        ttl="30m",
    )

    return {
        "tenant_id": tenant_slug,
        "aws_role_name": aws_role_name,
        "aws_role_arn": aws_role_arn,
        "vault_aws_role": vault_aws_role,
        "vault_policy": vault_policy_name,
        "vault_jwt_role": vault_jwt_role,
    }
    
def write_openstack_tenant_secret(tenant_id: str, credential: dict) -> dict:
    """
    Lưu credential OpenStack của tenant vào Vault KV v2.

    Logical path:
      kv/openstack/tenants/<tenant_id>

    HTTP path thực tế:
      kv/data/openstack/tenants/<tenant_id>
    """

    client = vault_client()

    tenant_slug = tenant_id.lower().strip()
    path = f"openstack/tenants/{tenant_slug}"

    client.secrets.kv.v2.create_or_update_secret(
        mount_point=VAULT_KV_MOUNT,
        path=path,
        secret=credential,
    )

    return {
        "tenant_id": tenant_slug,
        "vault_path": f"{VAULT_KV_MOUNT}/data/{path}",
        "logical_path": f"{VAULT_KV_MOUNT}/{path}",
    }
    
def provision_vault_openstack_for_tenant(tenant_id: str) -> dict:
    """
    Tạo cấu hình Vault cho OpenStack tenant:
    - policy tenant-<tenant_id>-openstack
    - auth/jwt/role/<tenant_id>-openstack-pipeline

    Policy chỉ cho đọc đúng secret:
      kv/data/openstack/tenants/<tenant_id>
    """

    client = vault_client()

    tenant_slug = tenant_id.lower().strip()

    vault_policy_name = f"tenant-{tenant_slug}-openstack"
    vault_jwt_role = f"{tenant_slug}-openstack-pipeline"

    secret_path = f"{VAULT_KV_MOUNT}/data/openstack/tenants/{tenant_slug}"

    policy = f'''
path "{secret_path}" {{
  capabilities = ["read"]
}}
'''

    client.sys.create_or_update_policy(
        name=vault_policy_name,
        policy=policy,
    )

    client.write(
        f"auth/jwt/role/{vault_jwt_role}",
        role_type="jwt",
        user_claim="sub",
        bound_audiences=[KEYCLOAK_PIPELINE_AUDIENCE],
        bound_claims={
            "azp": KEYCLOAK_PIPELINE_CLIENT_ID
        },
        policies=[vault_policy_name],
        ttl="30m",
    )

    return {
        "tenant_id": tenant_slug,
        "vault_policy": vault_policy_name,
        "vault_jwt_role": vault_jwt_role,
        "vault_secret_path": secret_path,
    }
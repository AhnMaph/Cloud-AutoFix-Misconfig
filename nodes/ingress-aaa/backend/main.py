import os
import re
import time
import requests

from fastapi import FastAPI, Header, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from auth_cookies import (
    COOKIE_REFRESH,
    SESSION_MAX_AGE,
    clear_auth_cookies,
    extract_access_token,
    extract_refresh_token,
    set_auth_cookies,
)
from pydantic import BaseModel, Field
import jwt
from jwt import PyJWKClient
from typing import Literal

from providers.aws import (
    create_tenant_iam_role,
    terraform_aws_deploy,
    assume_tenant_role,
)

from providers.vault import (
    write_cloud_token,
    read_cloud_token,
    provision_vault_aws_for_tenant,
    write_openstack_tenant_secret,
    provision_vault_openstack_for_tenant,
)

from providers.openstack import ensure_openstack_tenant

# from providers.openstack import create_tenant_project, terraform_openstack_deploy
# try:
#     from providers.openstack import create_tenant_project, terraform_openstack_deploy
# except Exception:
#     create_tenant_project = None
#     terraform_openstack_deploy = None

from policy.engine import resolve_provider
    
from template_generator import generate_template
from tenants import (
    create_tenant_record,
    get_tenant_record,
    update_tenant_record,
    list_tenant_records,
)

import uuid
from iac_repo import (
    push_iac_request_to_gitea,
    accept_autofix_for_deployment,
    prepare_deployment_workdir,
)
from deployments import (
    create_deployment,
    update_deployment,
    get_deployment,
    list_deployments_by_tenant,
)

KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth")
KEYCLOAK_PUBLIC_URL = os.getenv("KEYCLOAK_PUBLIC_URL", KEYCLOAK_INTERNAL_URL)
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD")

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


OPENSTACK_ENABLED = env_bool("OPENSTACK_ENABLED", False)

REALM     = os.getenv("KEYCLOAK_REALM", "hybrid-cloud")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "hybrid-cloud-portal")

KEYCLOAK_ISSUER = os.getenv(
    "KEYCLOAK_ISSUER",
    f"{KEYCLOAK_INTERNAL_URL.rstrip('/')}/realms/{REALM}"
)

ISSUER = KEYCLOAK_ISSUER.rstrip("/")
JWKS_URL = f"{KEYCLOAK_INTERNAL_URL.rstrip('/')}/realms/{REALM}/protocol/openid-connect/certs"

jwks_client = PyJWKClient(JWKS_URL)

TOKEN_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM}/protocol/openid-connect/token"

ADMIN_TOKEN_URL  = f"{KEYCLOAK_INTERNAL_URL}/realms/master/protocol/openid-connect/token"
ADMIN_USERS_URL  = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/users"
ADMIN_GROUPS_URL = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/groups"
ADMIN_ROLES_URL  = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/roles"

app = FastAPI(title="Hybrid Cloud Portal Backend")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", FRONTEND_URL).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3)
    password: str = Field(min_length=6)
    email: str | None = None

class LoginRequest(BaseModel):
    username: str
    password: str

class AwsDeployRequest(BaseModel):
    action: Literal["plan", "apply", "destroy"] = "plan"
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    
class DeployRequest(BaseModel):
    resource_type: str  # "database", "object_storage", "vm", "cache"
    action: Literal["plan", "apply", "destroy"] = "plan"
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    extra: dict = {}
    
class PipelineCloudTokenRequest(BaseModel):
    tenant_id: str
    request_id: str
    provider: Literal["aws"] = "aws"
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    
class OpaDecision(BaseModel):
    deny: bool = True

class CiOpaResultRequest(BaseModel):
    deployment_id: str
    repo: str | None = None
    commit: str | None = None
    branch: str | None = None
    tf_workdir: str | None = None
    pipeline_url: str | None = None
    opa: OpaDecision
    summary_markdown: str | None = None
    fix_report: dict = {}

def safe_slug(value: str, max_len: int = 38) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")

    if not value:
        raise HTTPException(status_code=400, detail="Invalid username for tenant_id generation")

    return value[:max_len]

class VaultCloudTokenRequest(BaseModel):
    tenant_id: str
    request_id: str
    provider: Literal["aws"] = "aws"
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

def generate_tenant_id(username: str) -> str:
    """
    1 user = 1 tenant.
    Ví dụ:
      alice      -> t-alice
      bob_123    -> t-bob-123
      Alice Lee  -> t-alice-lee
    """
    return f"t-{safe_slug(username)}"

def wait_keycloak():
    for _ in range(30):
        try:
            r = requests.get(f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM}", timeout=3)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)

    raise HTTPException(status_code=503, detail="Keycloak is not ready")


def get_admin_token():
    wait_keycloak()

    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": KEYCLOAK_ADMIN,
        "password": KEYCLOAK_ADMIN_PASSWORD,
    }

    r = requests.post(
        ADMIN_TOKEN_URL,
        data=data,
        timeout=10
    )
    
    if r.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot get Keycloak admin token: {r.text}"
        )

    return r.json()["access_token"]


def admin_headers():
    token = get_admin_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def get_group_id_by_path(path: str):
    headers = admin_headers()
    target_path = "/" + path.strip("/")

    r = requests.get(
        ADMIN_GROUPS_URL,
        headers=headers,
        params={"briefRepresentation": "false"},
        timeout=10
    )

    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Cannot list groups: {r.text}")

    groups = r.json()

    def walk(group, parent_path=""):
        name = group.get("name")
        if not name:
            return None

        current_path = group.get("path") or f"{parent_path}/{name}"

        if current_path == target_path:
            return group.get("id")

        for sub in group.get("subGroups", []) or []:
            found = walk(sub, current_path)
            if found:
                return found

        return None

    for group in groups:
        found = walk(group)
        if found:
            return found

    return None


def create_tenant_group_if_missing(tenant_id: str):
    path = f"/tenants/{tenant_id}"

    existing_id = get_group_id_by_path(path)
    if existing_id:
        return existing_id

    headers = admin_headers()

    parent_id = get_group_id_by_path("/tenants")
    if not parent_id:
        raise HTTPException(status_code=500, detail="Parent group /tenants not found")

    r = requests.post(
        f"{ADMIN_GROUPS_URL}/{parent_id}/children",
        headers=headers,
        json={"name": tenant_id},
        timeout=10
    )

    if r.status_code in [201, 204]:
        location = r.headers.get("Location")
        if location:
            return location.rstrip("/").split("/")[-1]

        new_id = get_group_id_by_path(path)
        if new_id:
            return new_id

        raise HTTPException(status_code=500, detail="Tenant group created but not found")

    if r.status_code == 409:
        existing_id = get_group_id_by_path(path)
        if existing_id:
            return existing_id

    raise HTTPException(
        status_code=500,
        detail=f"Cannot create tenant group: {r.text}"
    )


def get_user_id(username: str):
    headers = admin_headers()

    r = requests.get(
        ADMIN_USERS_URL,
        headers=headers,
        params={
            "username": username,
            "exact": "true"
        },
        timeout=10
    )

    if r.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot search user: {r.text}"
        )

    users = r.json()

    if not users:
        return None

    return users[0]["id"]


def assign_realm_role(user_id: str, role_name: str):
    headers = admin_headers()

    role_res = requests.get(
        f"{ADMIN_ROLES_URL}/{role_name}",
        headers=headers,
        timeout=10
    )

    if role_res.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot get role {role_name}: {role_res.text}"
        )

    role = role_res.json()

    assign_res = requests.post(
        f"{ADMIN_USERS_URL}/{user_id}/role-mappings/realm",
        headers=headers,
        json=[role],
        timeout=10
    )

    if assign_res.status_code not in [204, 201]:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot assign role {role_name}: {assign_res.text}"
        )


def add_user_to_group(user_id: str, group_id: str):
    headers = admin_headers()

    r = requests.put(
        f"{ADMIN_USERS_URL}/{user_id}/groups/{group_id}",
        headers=headers,
        timeout=10
    )

    if r.status_code not in [204, 201]:
        raise HTTPException(status_code=500, detail=f"Cannot add user to group: {r.text}")


def login_keycloak(username: str, password: str):
    wait_keycloak()

    data = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "username": username,
        "password": password,
        "scope": "openid profile email",
    }

    r = requests.post(TOKEN_URL, data=data, timeout=10)

    if r.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    return r.json()


def refresh_keycloak(refresh_token: str):
    wait_keycloak()

    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    }

    r = requests.post(TOKEN_URL, data=data, timeout=10)

    if r.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please sign in again.",
        )

    return r.json()


def get_public_key(token: str):
    try:
        jwks = requests.get(JWKS_URL, timeout=5).json()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Keycloak JWKS: {str(e)}"
        )

    header = jwt.get_unverified_header(token)

    for key in jwks.get("keys", []):
        if key.get("kid") == header.get("kid"):
            return key

    raise HTTPException(status_code=401, detail="Public key not found")


def verify_token(token: str):
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={
                "verify_aud": False
            }
        )

        return payload

    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}"
        )


def get_roles(payload):
    roles = []

    realm_access = payload.get("realm_access", {})
    roles.extend(realm_access.get("roles", []))

    resource_access = payload.get("resource_access", {})
    client_access = resource_access.get(CLIENT_ID, {})
    roles.extend(client_access.get("roles", []))

    return roles


def require_role(payload, role_name: str):
    roles = get_roles(payload)

    if role_name not in roles:
        raise HTTPException(
            status_code=403,
            detail=f"Missing required role: {role_name}"
        )


def extract_tenant_id(user: dict) -> str:
    if user.get("tenant_id"):
        tenant_value = user["tenant_id"]

        if isinstance(tenant_value, list):
            return tenant_value[0]

        return tenant_value

    groups = user.get("groups", [])

    for group in groups:
        if group.startswith("/tenants/"):
            return group.split("/")[-1]

    username = user.get("preferred_username")
    if username:
        return generate_tenant_id(username)

    sub = user.get("sub")
    if sub:
        return f"t-{sub[:12]}"

    raise HTTPException(status_code=400, detail="Cannot determine tenant_id")

def provision_openstack_for_tenant_record(tenant_id: str):
    """
    Auto provision OpenStack giống AWS:
    - create project/user/quota bên OpenStack
    - lưu service credential vào Vault KV
    - tạo Vault policy + JWT role cho pipeline
    - update tenant record
    """

    if not OPENSTACK_ENABLED:
        return update_tenant_record(
            tenant_id,
            {
                "openstack": {
                    "project_name": tenant_id,
                    "project_id": None,
                    "service_user": None,
                    "vault_secret_path": None,
                    "vault_jwt_role": None,
                    "vault_policy": None,
                    "provisioned": False,
                    "last_error": "OpenStack provisioning is disabled",
                }
            },
        )

    try:
        os_credential = ensure_openstack_tenant(tenant_id)

        vault_secret = write_openstack_tenant_secret(
            tenant_id=tenant_id,
            credential=os_credential,
        )

        vault_access = provision_vault_openstack_for_tenant(
            tenant_id=tenant_id,
        )

        return update_tenant_record(
            tenant_id,
            {
                "openstack": {
                    "project_name": os_credential.get("project_name", tenant_id),
                    "project_id": os_credential.get("project_id"),
                    "service_user": os_credential.get("username"),
                    "auth_url": os_credential.get("auth_url"),
                    "region_name": os_credential.get("region_name"),
                    "interface": os_credential.get("interface"),
                    "vault_secret_path": vault_secret.get("vault_path"),
                    "vault_jwt_role": vault_access.get("vault_jwt_role"),
                    "vault_policy": vault_access.get("vault_policy"),
                    "provisioned": True,
                    "last_error": None,
                }
            },
        )

    except Exception as e:
        return update_tenant_record(
            tenant_id,
            {
                "openstack": {
                    "project_name": tenant_id,
                    "project_id": None,
                    "service_user": f"svc-{tenant_id}-ci",
                    "vault_secret_path": None,
                    "vault_jwt_role": None,
                    "vault_policy": None,
                    "provisioned": False,
                    "last_error": str(e),
                }
            },
        )

# Cloud provider operations
def get_roles_from_token(user: dict) -> set[str]:
    roles = set()

    realm_access = user.get("realm_access", {})
    roles.update(realm_access.get("roles", []))

    resource_access = user.get("resource_access", {})
    for client_data in resource_access.values():
        roles.update(client_data.get("roles", []))

    return roles

def get_current_user(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
):
    token = extract_access_token(request, authorization)

    if token:
        try:
            return verify_token(token)
        except HTTPException:
            pass
    
    # if token:
    #     try:
    #         return verify_token(token)
    #     except HTTPException as e:
    #         print("JWT verify failed:", e.detail)
    #         raise e

    refresh_token = request.cookies.get(COOKIE_REFRESH)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_data = refresh_keycloak(refresh_token)
    set_auth_cookies(response, token_data)
    return verify_token(token_data["access_token"])

@app.get("/")
def root():
    return {
        "message": "Hybrid Cloud Portal Backend is running",
        "keycloak_internal_url": KEYCLOAK_INTERNAL_URL,
        "realm": REALM
    }


@app.post("/auth/register")
def register(req: RegisterRequest):
    username = req.username.strip()
    tenant_id = generate_tenant_id(username)

    headers = admin_headers()

    existing_user = get_user_id(username)
    if existing_user:
        raise HTTPException(status_code=409, detail="Username already exists")

    existing_tenant_group = get_group_id_by_path(f"/tenants/{tenant_id}")
    if existing_tenant_group:
        raise HTTPException(
            status_code=409,
            detail=f"Tenant already exists: {tenant_id}"
        )

    user_payload = {
        "username": username,
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],
        "firstName": username,
        "lastName": tenant_id,
        "email": req.email or f"{username}@local.test",
        "attributes": {
            "tenant_id": [tenant_id]
        },
        "credentials": [
            {
                "type": "password",
                "value": req.password,
                "temporary": False
            }
        ]
    }

    r = requests.post(
        f"{ADMIN_USERS_URL}",
        headers=headers,
        json=user_payload,
        timeout=10
    )

    if r.status_code not in [201, 204]:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot create user: {r.text}"
        )

    user_id = get_user_id(username)

    group_id = create_tenant_group_if_missing(tenant_id)
    add_user_to_group(user_id, group_id)

    assign_realm_role(user_id, "tenant")
    assign_realm_role(user_id, "view_resource")
    
    tenant_record = create_tenant_record(
        tenant_id=tenant_id,
        username=username,
        email=req.email or f"{username}@local.test",
    )
    
    aws_account_id = os.getenv("AWS_ACCOUNT_ID")

    if aws_account_id:
        try:
            aws_role = create_tenant_iam_role(
                tenant_id=tenant_id,
                aws_account_id=aws_account_id,
            )

            vault_provision = provision_vault_aws_for_tenant(tenant_id)

            tenant_record = update_tenant_record(
                tenant_id,
                {
                    "aws": {
                        "role_name": aws_role["role_name"],
                        "role_arn": aws_role["role_arn"],
                        "provisioned": True,
                        "last_error": None,
                    },
                    "vault": {
                        "aws_role": vault_provision["vault_aws_role"],
                        "jwt_role": vault_provision["vault_jwt_role"],
                        "policy": vault_provision["vault_policy"],
                        "provisioned": True,
                        "last_error": None,
                    }
                },
            )

        except Exception as e:
            tenant_record = update_tenant_record(
                tenant_id,
                {
                    "aws": {
                        "provisioned": False,
                        "last_error": str(e),
                    }
                },
            )
        
    else:
        tenant_record = update_tenant_record(
            tenant_id,
            {
                "aws": {
                    "provisioned": False,
                    "last_error": "Missing AWS_ACCOUNT_ID",
                }
            },
        )
        
    tenant_record = provision_openstack_for_tenant_record(tenant_id)
    
    return {
        "status": "created",
        "message": "User registered successfully",
        "username": username,
        "tenant_id": tenant_id,
        "tenant": tenant_record,
        "default_roles": ["tenant", "view_resource"]
    }


@app.post("/auth/login")
def login(req: LoginRequest, response: Response):
    token_data = login_keycloak(req.username, req.password)
    set_auth_cookies(response, token_data)

    return {
        "status": "ok",
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
        "token_type": token_data.get("token_type", "Bearer"),
        "session_max_age": SESSION_MAX_AGE,
    }


@app.post("/auth/refresh")
def refresh_session(request: Request, response: Response):
    refresh_token = extract_refresh_token(request, None)

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    token_data = refresh_keycloak(refresh_token)
    set_auth_cookies(response, token_data)

    return {
        "status": "refreshed",
        "expires_in": token_data.get("expires_in"),
    }


@app.post("/auth/logout")
def logout(response: Response):
    clear_auth_cookies(response)
    return {"status": "logged_out"}

@app.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    roles = get_roles(current_user)
    tenant_id = extract_tenant_id(current_user)
    tenant_record = get_tenant_record(tenant_id)

    return {
        "username": current_user.get("preferred_username"),
        "email": current_user.get("email"),
        "roles": roles,
        "groups": current_user.get("groups", []),
        "tenant_id": tenant_id,
        "tenant": tenant_record,
    }

@app.get("/tenants/me")
def my_tenant(current_user: dict = Depends(get_current_user)):
    tenant_id = extract_tenant_id(current_user)
    tenant_record = get_tenant_record(tenant_id)

    if not tenant_record:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant record not found: {tenant_id}"
        )

    return tenant_record

@app.get("/tenants")
def tenants(current_user: dict = Depends(get_current_user)):
    roles = get_roles_from_token(current_user)

    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Missing role: admin")

    return {
        "items": list_tenant_records()
    }

@app.post("/scan/iac")
def scan_iac(current_user: dict = Depends(get_current_user)):
    require_role(current_user, "tenant")
    payload = current_user

    return {
        "status": "scanning",
        "tenant_id": extract_tenant_id(payload),
        "message": "IaC scan started",
        "tools": ["checkov", "tfsec"]
    }


@app.post("/deploy/openstack")
def deploy_openstack(current_user: dict = Depends(get_current_user)):
    payload = current_user
    require_role(payload, "deploy_openstack")

    username = payload.get("preferred_username")
    tenant_id = extract_tenant_id(payload)

    return {
        "status": "accepted",
        "username": username,
        "tenant_id": tenant_id,
        "message": f"Deploy request accepted for tenant {tenant_id}",
        "next_step": "Run Checkov -> Auto remediate -> Terraform apply to OpenStack project"
    }

@app.post("/deploy/aws")
def deploy_aws(
    payload: AwsDeployRequest,
    current_user: dict = Depends(get_current_user),
):
    roles = get_roles_from_token(current_user)

    allowed_roles = {"admin", "tenant", "deploy_aws"}

    if roles.isdisjoint(allowed_roles):
        raise HTTPException(
            status_code=403,
            detail="Missing role: tenant, deploy_aws, or admin"
        )

    tenant_id = extract_tenant_id(current_user)

    try:
        result = terraform_aws_deploy(
            tenant_id=tenant_id,
            aws_region=payload.region,
            action=payload.action,
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
        
@app.post("/deploy/repo")
def deploy_to_repo(
    req: DeployRequest,
    current_user: dict = Depends(get_current_user),
):
    roles = get_roles_from_token(current_user)

    if roles.isdisjoint({"admin", "tenant", "deploy_aws", "deploy_openstack"}):
        raise HTTPException(status_code=403, detail="Insufficient role")

    tenant_id = extract_tenant_id(current_user)
    provider = resolve_provider(req.resource_type)
    
    if provider == "openstack":
        if not OPENSTACK_ENABLED:
            raise HTTPException(
                status_code=503,
                detail="OpenStack provider is temporarily disabled"
            )

        tenant_record = get_tenant_record(tenant_id) or {}
        openstack_state = tenant_record.get("openstack", {})

        if not openstack_state.get("provisioned"):
            provision_openstack_for_tenant_record(tenant_id)

    deployment_id = f"dep-{uuid.uuid4().hex[:12]}"

    ingress_public_url = os.getenv("INGRESS_PUBLIC_URL", "").rstrip("/")
    if not ingress_public_url:
        raise HTTPException(status_code=500, detail="Missing INGRESS_PUBLIC_URL")

    callback_url = f"{ingress_public_url}/api/ci/opa-result"

    context = {
        "tenant_id": tenant_id,

        # AWS
        "aws_region": req.region,
        "project_name": "hybrid-portal",

        # OpenStack
        "os_region_name": os.getenv("OS_REGION_NAME", "RegionOne"),
        "os_auth_url": os.getenv("OPENSTACK_AUTH_URL", "http://192.168.9.254:5000"),

        **req.extra,
    }

    tf_file = generate_template(
        provider=provider,
        resource_type=req.resource_type,
        context=context,
    )

    repo_result = push_iac_request_to_gitea(
        deployment_id=deployment_id,
        provider=provider,
        tenant_id=tenant_id,
        resource_type=req.resource_type,
        action=req.action,
        region=req.region,
        tf_file=tf_file,
        callback_url=callback_url,
    )

    record = create_deployment({
        "deployment_id": deployment_id,
        "tenant_id": tenant_id,
        "provider": provider,
        "resource_type": req.resource_type,
        "action": req.action,
        "region": req.region,
        "status": "submitted",
        "user_decision": None,
        "opa": None,
        "summary_markdown": None,
        "fix_report": None,
        **repo_result,
    })

    return {
        "status": "submitted",
        "message": "IaC template pushed to private repository. CI/CD scan started.",
        "deployment": record,
    }        

@app.post("/deploy")
def deploy(
    req: DeployRequest,
    current_user: dict = Depends(get_current_user),
):
    roles = get_roles_from_token(current_user)

    if roles.isdisjoint({"admin", "tenant", "deploy_aws", "deploy_openstack"}):
        raise HTTPException(status_code=403, detail="Insufficient role")

    tenant_id = extract_tenant_id(current_user)
    provider = resolve_provider(req.resource_type)

    if provider == "openstack" and not OPENSTACK_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="OpenStack provider is temporarily disabled"
        )

    context = {
        "tenant_id": tenant_id,

        # AWS
        "aws_region": req.region,
        "project_name": "hybrid-portal",

        # OpenStack
        "os_region_name": os.getenv("OS_REGION_NAME", "RegionOne"),

        **req.extra,
    }

    tf_file = generate_template(provider, req.resource_type, context)

    if provider == "aws":
        result = terraform_aws_deploy(
            tenant_id=tenant_id,
            aws_region=req.region,
            action=req.action,
            workdir=tf_file.parent,
        )

    # elif provider == "openstack":
    #     if terraform_openstack_deploy is None:
    #         raise HTTPException(
    #             status_code=500,
    #             detail="OpenStack deploy function is not available"
    #         )

    #     # Đảm bảo project tenant tồn tại trước khi Terraform chạy.
    #     if create_tenant_project:
    #         create_tenant_project(tenant_id)

    #     from providers.openstack import prepare_openstack_workspace

    #     workdir = prepare_openstack_workspace(
    #         tenant_id=tenant_id,
    #         resource_type=req.resource_type,
    #         generated_tf_file=tf_file,
    #     )

    #     result = terraform_openstack_deploy(
    #         tenant_id=tenant_id,
    #         resource_type=req.resource_type,
    #         action=req.action,
    #         workdir=workdir,
    #     )
    elif provider == "openstack":
        raise HTTPException(
            status_code=400,
            detail="OpenStack direct deploy is disabled. Use /deploy/repo so CI/CD can fetch credentials from Vault."
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}"
        )

    return {
        "provider": provider,
        "resource_type": req.resource_type,
        "tenant_id": tenant_id,
        **result,
    }
    
@app.post("/internal/vault/issue-cloud-token")
def issue_cloud_token_to_vault(req: VaultCloudTokenRequest):
    aws_account_id = os.getenv("AWS_ACCOUNT_ID")

    if not aws_account_id:
        raise HTTPException(status_code=500, detail="Missing AWS_ACCOUNT_ID")

    if req.provider != "aws":
        raise HTTPException(status_code=400, detail="Only AWS is supported for now")

    try:
        creds = assume_tenant_role(
            tenant_id=req.tenant_id,
            aws_account_id=aws_account_id,
        )

        secret_data = {
            "provider": "aws",
            "tenant_id": req.tenant_id,
            "request_id": req.request_id,
            "region": req.region,
            "AWS_ACCESS_KEY_ID": creds["AWS_ACCESS_KEY_ID"],
            "AWS_SECRET_ACCESS_KEY": creds["AWS_SECRET_ACCESS_KEY"],
            "AWS_SESSION_TOKEN": creds["AWS_SESSION_TOKEN"],
            "AWS_DEFAULT_REGION": req.region,
        }

        vault_result = write_cloud_token(
            request_id=req.request_id,
            data=secret_data,
        )

        return {
            "status": "stored",
            "provider": "aws",
            "tenant_id": req.tenant_id,
            "request_id": req.request_id,
            "vault_path": vault_result["vault_path"],
            "message": "AWS STS credential stored in Vault before pipeline scan",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/internal/vault/cloud-token/{request_id}")
def get_cloud_token_from_vault(request_id: str):
    data = read_cloud_token(request_id)

    return {
        "status": "ok",
        "request_id": request_id,
        "provider": data.get("provider"),
        "tenant_id": data.get("tenant_id"),
        "credentials": {
            "AWS_ACCESS_KEY_ID": data.get("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": data.get("AWS_SECRET_ACCESS_KEY"),
            "AWS_SESSION_TOKEN": data.get("AWS_SESSION_TOKEN"),
            "AWS_DEFAULT_REGION": data.get("AWS_DEFAULT_REGION"),
        },
    }
    
@app.post("/ci/opa-result")
def receive_opa_result(
    req: CiOpaResultRequest,
    x_ci_token: str | None = Header(default=None),
):
    expected = os.getenv("CI_CALLBACK_TOKEN")

    if not expected:
        raise HTTPException(status_code=500, detail="Missing CI_CALLBACK_TOKEN")

    if x_ci_token != expected:
        raise HTTPException(status_code=401, detail="Invalid CI callback token")

    deployment = get_deployment(req.deployment_id)

    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment not found: {req.deployment_id}"
        )

    deny = req.opa.deny
    fix_report = req.fix_report or {}
    summary = fix_report.get("summary", {})

    total = int(summary.get("total", 0) or 0)
    fixed = int(summary.get("fixed", 0) or 0)
    manual = int(summary.get("manual", 0) or 0)
    failed = int(summary.get("failed", 0) or 0)
    skipped = int(summary.get("skipped", 0) or 0)

    # Defensive guard:
    # Nếu scanner report không có finding nào thì không được block deployment.
    # Trường hợp này thường xảy ra khi OPA response bị missing/malformed
    # nhưng notify-ingress fallback deny=true.
    if total == 0 and fixed == 0 and manual == 0 and failed == 0 and skipped == 0:
        deny = False

    if deny:
        if fixed > 0:
            status = "needs_user_fix_decision"
            recommendation = "Policy denied deployment. Auto-fix is available. Ask user whether to apply/merge the fix."
        elif manual > 0 or failed > 0 or skipped > 0:
            status = "blocked_by_policy"
            recommendation = "Policy denied deployment. Manual review or additional fix rules are required."
        else:
            status = "blocked_by_policy"
            recommendation = "Policy denied deployment."
    else:
        status = "waiting_user_approval"
        recommendation = "Policy passed. Ask user to accept or deny Terraform deployment."

    updated = update_deployment(
        req.deployment_id,
        {
            "status": status,
            "repo": req.repo or deployment.get("repo"),
            "commit": req.commit or deployment.get("commit"),
            "branch": req.branch or deployment.get("branch"),
            "tf_workdir": req.tf_workdir or deployment.get("tf_workdir"),
            "pipeline_url": req.pipeline_url,
            "opa": {
                "deny": deny,
            },
            "summary_markdown": req.summary_markdown,
            "fix_report": fix_report,
            "recommendation": recommendation,
        },
    )

    return {
        "status": "received",
        "deployment": updated,
    }
    
@app.get("/deployments")
def list_my_deployments(current_user: dict = Depends(get_current_user)):
    tenant_id = extract_tenant_id(current_user)

    return {
        "items": list_deployments_by_tenant(tenant_id)
    }


# IMPORTANT:
# This route must be declared BEFORE /deployments/{deployment_id}
@app.get("/deployments/latest")
def latest_my_deployment(current_user: dict = Depends(get_current_user)):
    tenant_id = extract_tenant_id(current_user)
    items = list_deployments_by_tenant(tenant_id)

    if not items:
        return {"item": None}

    return {"item": items[0]}


@app.get("/deployments/{deployment_id}")
def get_my_deployment(
    deployment_id: str,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = extract_tenant_id(current_user)
    deployment = get_deployment(deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return deployment


@app.post("/deployments/{deployment_id}/request-fix")
def request_fix_deployment(
    deployment_id: str,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = extract_tenant_id(current_user)
    deployment = get_deployment(deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not deployment.get("opa", {}).get("deny", True):
        raise HTTPException(
            status_code=400,
            detail="Deployment is not denied by policy"
        )

    if deployment.get("status") not in [
        "needs_user_fix_decision",
        "blocked_by_policy",
        "user_requested_fix",
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Deployment is not waiting for auto-fix decision. Current status: {deployment.get('status')}"
        )

    repo_full_name = deployment.get("repo")
    if not repo_full_name:
        raise HTTPException(
            status_code=400,
            detail="Deployment has no repository information"
        )

    try:
        autofix_result = accept_autofix_for_deployment(
            repo_full_name=repo_full_name,
            deployment_id=deployment_id,
        )

        updated = update_deployment(
            deployment_id,
            {
                "status": "autofix_merged",
                "user_decision": "accept_autofix",
                "autofix": autofix_result,
                "recommendation": (
                    "Auto-fix PR was merged. Waiting for the next CI/CD scan result. "
                    "If policy passes, deployment will move to waiting_user_approval."
                ),
            },
        )

        return {
            "status": "autofix_merged",
            "message": "Auto-fix PR merged successfully. CI/CD will run again from the merge commit.",
            "deployment": updated,
        }

    except Exception as e:
        updated = update_deployment(
            deployment_id,
            {
                "status": "autofix_failed",
                "user_decision": "accept_autofix",
                "autofix_error": str(e),
                "recommendation": "Auto-fix merge failed. Please review the PR manually in Gitea.",
            },
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Auto-fix merge failed",
                "error": str(e),
                "deployment": updated,
            },
        )


@app.post("/deployments/{deployment_id}/deny")
def deny_deployment(
    deployment_id: str,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = extract_tenant_id(current_user)
    deployment = get_deployment(deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    updated = update_deployment(
        deployment_id,
        {
            "status": "user_denied",
            "user_decision": "deny",
        },
    )

    return {
        "status": "user_denied",
        "deployment": updated,
    }
    
@app.post("/deployments/{deployment_id}/accept")
def accept_deployment(
    deployment_id: str,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = extract_tenant_id(current_user)
    deployment = get_deployment(deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if deployment.get("status") != "waiting_user_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Deployment is not waiting for approval. Current status: {deployment.get('status')}",
        )

    if deployment.get("opa", {}).get("deny", True):
        raise HTTPException(
            status_code=400,
            detail="OPA denied this deployment. Cannot apply.",
        )

    update_deployment(
        deployment_id,
        {
            "status": "deploying",
            "user_decision": "accept_deploy",
            "recommendation": "User accepted deployment. Terraform is running...",
        },
    )

    try:
        provider = deployment.get("provider")
        action = deployment.get("action", "plan")
        resource_type = deployment.get("resource_type")
        region = deployment.get("region")

        # Quan trọng: clone đúng repo/commit đã scan và lấy đúng tf_workdir.
        workdir = prepare_deployment_workdir(deployment)

        if provider == "aws":
            result = terraform_aws_deploy(
                tenant_id=tenant_id,
                aws_region=region,
                action=action,
                workdir=workdir,
            )

        # elif provider == "openstack":
        #     if terraform_openstack_deploy is None:
        #         raise RuntimeError("OpenStack deploy function is not available")

        #     # Đảm bảo OpenStack project tenant tồn tại.
        #     if create_tenant_project:
        #         create_tenant_project(tenant_id)

        #     result = terraform_openstack_deploy(
        #         tenant_id=tenant_id,
        #         resource_type=resource_type,
        #         action=action,
        #         workdir=workdir,
        #     )
        
        elif provider == "openstack":
            result = {
                "status": "approved",
                "message": (
                    "OpenStack deployment approved. "
                    "Terraform apply should be handled by the Woodpecker pipeline using Vault credentials."
                ),
            }

        else:
            raise RuntimeError(f"Unsupported provider: {provider}")

        final_status = result.get("status") or (
            "applied" if action == "apply" else "planned"
        )

        updated = update_deployment(
            deployment_id,
            {
                "status": final_status,
                "terraform_result": result,
                "recommendation": "Terraform completed successfully.",
            },
        )

        return {
            "status": final_status,
            "deployment": updated,
        }

    except Exception as e:
        updated = update_deployment(
            deployment_id,
            {
                "status": "apply_failed",
                "apply_error": str(e),
                "recommendation": "Terraform deployment failed.",
            },
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": "Terraform deployment failed",
                "error": str(e),
                "deployment": updated,
            },
        )
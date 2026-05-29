import os
import re
import time
import requests

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import jwt
from jwt import PyJWKClient
from typing import Literal

from providers.aws import terraform_aws_deploy, create_tenant_iam_role
try:
    from providers.openstack import create_tenant_project
except Exception:
    create_tenant_project = None

from policy.engine import resolve_provider
    
from template_generator import generate_template
from tenants import (
    create_tenant_record,
    get_tenant_record,
    update_tenant_record,
    list_tenant_records,
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

ISSUER = f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM}"
JWKS_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM}/protocol/openid-connect/certs"

jwks_client = PyJWKClient(JWKS_URL)

TOKEN_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{REALM}/protocol/openid-connect/token"

ADMIN_TOKEN_URL  = f"{KEYCLOAK_INTERNAL_URL}/realms/master/protocol/openid-connect/token"
ADMIN_USERS_URL  = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/users"
ADMIN_GROUPS_URL = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/groups"
ADMIN_ROLES_URL  = f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{REALM}/roles"

app = FastAPI(title="Hybrid Cloud Portal Backend")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

def safe_slug(value: str, max_len: int = 38) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")

    if not value:
        raise HTTPException(status_code=400, detail="Invalid username for tenant_id generation")

    return value[:max_len]


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
        "scope": "openid profile email"
    }

    r = requests.post(TOKEN_URL, data=data, timeout=10)

    if r.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
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

# Cloud provider operations
def get_roles_from_token(user: dict) -> set[str]:
    roles = set()

    realm_access = user.get("realm_access", {})
    roles.update(realm_access.get("roles", []))

    resource_access = user.get("resource_access", {})
    for client_data in resource_access.values():
        roles.update(client_data.get("roles", []))

    return roles

def get_current_user(authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )

    authorization = authorization.strip()

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail=f"Invalid Authorization header format: {authorization[:20]}"
        )

    token = authorization.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Empty bearer token"
        )

    return verify_token(token)

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

            tenant_record = update_tenant_record(
                tenant_id,
                {
                    "aws": {
                        "role_name": aws_role["role_name"],
                        "role_arn": aws_role["role_arn"],
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
        
    if OPENSTACK_ENABLED and create_tenant_project:
        try:
            os_project = create_tenant_project(tenant_id)

            tenant_record = update_tenant_record(
                tenant_id,
                {
                    "openstack": {
                        "project_name": os_project["project_name"],
                        "project_id": os_project["project_id"],
                        "provisioned": True,
                        "last_error": None,
                    }
                },
            )

        except Exception as e:
            tenant_record = update_tenant_record(
                tenant_id,
                {
                    "openstack": {
                        "project_name": tenant_id,
                        "project_id": None,
                        "provisioned": False,
                        "last_error": str(e),
                    }
                },
            )
    else:
        tenant_record = update_tenant_record(
            tenant_id,
            {
                "openstack": {
                    "project_name": tenant_id,
                    "project_id": None,
                    "provisioned": False,
                    "last_error": "OpenStack provisioning is disabled",
                }
            },
        )
    
    return {
        "status": "created",
        "message": "User registered successfully",
        "username": username,
        "tenant_id": tenant_id,
        "tenant": tenant_record,
        "default_roles": ["tenant", "view_resource"]
    }


@app.post("/auth/login")
def login(req: LoginRequest):
    token_data = login_keycloak(req.username, req.password)

    return {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
        "token_type": token_data.get("token_type", "Bearer")
    }

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
def scan_iac(authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_role(payload, "tenant")

    return {
        "status": "scanning",
        "tenant_id": extract_tenant_id(payload),
        "message": "IaC scan started",
        "tools": ["checkov", "tfsec"]
    }


@app.post("/deploy/openstack")
def deploy_openstack(authorization: str = Header(None)):
    payload = verify_token(authorization)
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
        
@app.post("/deploy")
def deploy(
    req: DeployRequest,
    current_user: dict = Depends(get_current_user),
):
    roles = get_roles_from_token(current_user)
    if roles.isdisjoint({"admin", "tenant", "deploy_aws", "deploy_openstack"}):
        raise HTTPException(status_code=403, detail="Insufficient role")

    tenant_id = extract_tenant_id(current_user)

    # Policy engine quyết định provider
    provider = resolve_provider(req.resource_type)
    
    if provider == "openstack" and not OPENSTACK_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="OpenStack provider is temporarily disabled"
        )

    # Generate .tf file từ Jinja2 template
    context = {
        "tenant_id": tenant_id,
        "aws_region": req.region,
        "project_name": "hybrid-portal",
        **req.extra,
    }
    tf_file = generate_template(provider, req.resource_type, context)

    # Gọi terraform theo provider
    if provider == "aws":
        result = terraform_aws_deploy(
            tenant_id=tenant_id,
            aws_region=req.region,
            action=req.action,
            workdir=tf_file.parent,
        )
    else:
        raise HTTPException(status_code=501, detail="OpenStack provider not yet implemented")

    return {
        "provider": provider,
        "resource_type": req.resource_type,
        "tenant_id": tenant_id,
        **result,
    }
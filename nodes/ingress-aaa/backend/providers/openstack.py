import os
import requests
import json
import shutil
import subprocess
from pathlib import Path
from typing import Literal



def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def keystone_url() -> str:
    url = _required_env("OS_AUTH_URL").rstrip("/")
    if not url.endswith("/v3"):
        url = f"{url}/v3"
    return url


def os_env_ready() -> bool:
    required = [
        "OS_AUTH_URL",
        "OS_USERNAME",
        "OS_PASSWORD",
        "OS_USER_DOMAIN_NAME",
        "OS_PROJECT_NAME",
        "OS_PROJECT_DOMAIN_NAME",
    ]
    return all(os.getenv(x) for x in required)


def get_admin_token() -> str:
    """
    Lấy token admin/project-scoped để gọi Keystone Admin API.
    """
    url = keystone_url()

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": _required_env("OS_USERNAME"),
                        "password": _required_env("OS_PASSWORD"),
                        "domain": {
                            "name": os.getenv("OS_USER_DOMAIN_NAME", "Default")
                        },
                    }
                },
            },
            "scope": {
                "project": {
                    "name": os.getenv("OS_PROJECT_NAME", "admin"),
                    "domain": {
                        "name": os.getenv("OS_PROJECT_DOMAIN_NAME", "Default")
                    },
                }
            },
        }
    }

    r = requests.post(
        f"{url}/auth/tokens",
        json=payload,
        timeout=15,
    )

    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Cannot get OpenStack admin token: {r.status_code} {r.text}")

    token = r.headers.get("X-Subject-Token")
    if not token:
        raise RuntimeError("OpenStack response missing X-Subject-Token")

    return token


def _headers(token: str) -> dict:
    return {
        "X-Auth-Token": token,
        "Content-Type": "application/json",
    }


def get_domain_id(token: str, domain_name: str = "Default") -> str:
    url = keystone_url()

    r = requests.get(
        f"{url}/domains",
        headers=_headers(token),
        params={"name": domain_name},
        timeout=15,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Cannot list domains: {r.status_code} {r.text}")

    domains = r.json().get("domains", [])
    if not domains:
        raise RuntimeError(f"Domain not found: {domain_name}")

    return domains[0]["id"]


def get_project_by_name(token: str, project_name: str, domain_id: str) -> dict | None:
    url = keystone_url()

    r = requests.get(
        f"{url}/projects",
        headers=_headers(token),
        params={
            "name": project_name,
            "domain_id": domain_id,
        },
        timeout=15,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Cannot list projects: {r.status_code} {r.text}")

    projects = r.json().get("projects", [])

    for project in projects:
        if project.get("name") == project_name:
            return project

    return None


def create_project(token: str, project_name: str, domain_id: str) -> dict:
    url = keystone_url()

    existing = get_project_by_name(token, project_name, domain_id)
    if existing:
        return existing

    payload = {
        "project": {
            "name": project_name,
            "domain_id": domain_id,
            "enabled": True,
            "description": f"Tenant project managed by hybrid-cloud-portal: {project_name}",
        }
    }

    r = requests.post(
        f"{url}/projects",
        headers=_headers(token),
        json=payload,
        timeout=15,
    )

    if r.status_code not in [201, 202]:
        raise RuntimeError(f"Cannot create project: {r.status_code} {r.text}")

    return r.json()["project"]


def get_user_by_name(token: str, username: str, domain_id: str) -> dict | None:
    url = keystone_url()

    r = requests.get(
        f"{url}/users",
        headers=_headers(token),
        params={
            "name": username,
            "domain_id": domain_id,
        },
        timeout=15,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Cannot list users: {r.status_code} {r.text}")

    users = r.json().get("users", [])

    for user in users:
        if user.get("name") == username:
            return user

    return None


def get_role_by_name(token: str, role_name: str) -> dict | None:
    url = keystone_url()

    r = requests.get(
        f"{url}/roles",
        headers=_headers(token),
        params={"name": role_name},
        timeout=15,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Cannot list roles: {r.status_code} {r.text}")

    roles = r.json().get("roles", [])

    for role in roles:
        if role.get("name") == role_name:
            return role

    return None


def assign_role_to_user_on_project(
    token: str,
    project_id: str,
    user_id: str,
    role_id: str,
):
    """
    Gán role cho admin/service user trên project tenant.
    Nếu role đã tồn tại, Keystone thường trả 204.
    """
    url = keystone_url()

    r = requests.put(
        f"{url}/projects/{project_id}/users/{user_id}/roles/{role_id}",
        headers=_headers(token),
        timeout=15,
    )

    if r.status_code not in [204, 201]:
        raise RuntimeError(f"Cannot assign role on project: {r.status_code} {r.text}")


def create_tenant_project(tenant_id: str) -> dict:
    """
    Tạo OpenStack Project riêng cho tenant.
    Project name = tenant_id, ví dụ t-alice3.
    """
    if not os_env_ready():
        raise RuntimeError("OpenStack environment variables are not fully configured")

    admin_token = get_admin_token()
    domain_name = os.getenv("OS_PROJECT_DOMAIN_NAME", "Default")
    domain_id = get_domain_id(admin_token, domain_name)

    project = create_project(
        token=admin_token,
        project_name=tenant_id,
        domain_id=domain_id,
    )

    # Gán role cho admin/service user trên project tenant để sau này có thể lấy token scoped.
    admin_user = get_user_by_name(
        token=admin_token,
        username=os.getenv("OS_USERNAME", "admin"),
        domain_id=domain_id,
    )

    if not admin_user:
        raise RuntimeError(f"OpenStack admin user not found: {os.getenv('OS_USERNAME')}")

    role = (
        get_role_by_name(admin_token, "member")
        or get_role_by_name(admin_token, "_member_")
        or get_role_by_name(admin_token, "admin")
    )

    if not role:
        raise RuntimeError("No suitable OpenStack role found: member/_member_/admin")

    assign_role_to_user_on_project(
        token=admin_token,
        project_id=project["id"],
        user_id=admin_user["id"],
        role_id=role["id"],
    )

    return {
        "project_name": project["name"],
        "project_id": project["id"],
    }


def get_tenant_project_scoped_token(tenant_id: str) -> str:
    """
    Lấy token scoped vào project tenant.
    Task deploy OpenStack sau này sẽ dùng hàm này.
    """
    url = keystone_url()

    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": _required_env("OS_USERNAME"),
                        "password": _required_env("OS_PASSWORD"),
                        "domain": {
                            "name": os.getenv("OS_USER_DOMAIN_NAME", "Default")
                        },
                    }
                },
            },
            "scope": {
                "project": {
                    "name": tenant_id,
                    "domain": {
                        "name": os.getenv("OS_PROJECT_DOMAIN_NAME", "Default")
                    },
                }
            },
        }
    }

    r = requests.post(
        f"{url}/auth/tokens",
        json=payload,
        timeout=15,
    )

    if r.status_code not in [200, 201]:
        raise RuntimeError(
            f"Cannot get OpenStack token for project {tenant_id}: {r.status_code} {r.text}"
        )

    token = r.headers.get("X-Subject-Token")
    if not token:
        raise RuntimeError("OpenStack response missing X-Subject-Token")

    return token

TF_STATE_ROOT = Path(
    os.getenv(
        "TERRAFORM_STATE_ROOT",
        "/app/tfstate"
    )
)


def run_cmd(
    cmd: list[str],
    cwd: Path,
    timeout: int = 300,
    env_overrides: dict | None = None,
) -> str:
    env = os.environ.copy()

    if env_overrides:
        env.update(env_overrides)

    process = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )

    if process.returncode != 0:
        raise RuntimeError(process.stdout)

    return process.stdout


def tail(text: str, lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-lines:])


def openstack_terraform_env(tenant_id: str) -> dict:
    """
    Terraform OpenStack provider đọc credential từ OS_* env.
    Ở đây dùng admin user nhưng scope vào project tenant.
    """
    auth_url = os.getenv("OS_AUTH_URL", "").rstrip("/")
    if auth_url and not auth_url.endswith("/v3"):
        auth_url = f"{auth_url}/v3"

    return {
        "OS_AUTH_URL": auth_url,
        "OS_USERNAME": _required_env("OS_USERNAME"),
        "OS_PASSWORD": _required_env("OS_PASSWORD"),
        "OS_PROJECT_NAME": tenant_id,
        "OS_TENANT_NAME": tenant_id,
        "OS_USER_DOMAIN_NAME": os.getenv("OS_USER_DOMAIN_NAME", "Default"),
        "OS_PROJECT_DOMAIN_NAME": os.getenv("OS_PROJECT_DOMAIN_NAME", "Default"),
        "OS_REGION_NAME": os.getenv("OS_REGION_NAME", "RegionOne"),
        "OS_INTERFACE": os.getenv("OS_INTERFACE", "internal"),
        "OS_IDENTITY_API_VERSION": os.getenv("OS_IDENTITY_API_VERSION", "3"),
    }


def prepare_openstack_workspace(
    tenant_id: str,
    resource_type: str,
    generated_tf_file: Path,
) -> Path:
    workdir = TF_STATE_ROOT / "openstack" / tenant_id / resource_type
    workdir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(generated_tf_file, workdir / "main.tf")

    return workdir


def terraform_openstack_deploy(
    tenant_id: str,
    resource_type: str,
    action: Literal["plan", "apply", "destroy"] = "plan",
    workdir: Path | None = None,
) -> dict:
    if workdir is None:
        raise RuntimeError("Missing OpenStack Terraform workdir")

    os_env = openstack_terraform_env(tenant_id)

    init_output = run_cmd(
        ["terraform", "init", "-input=false"],
        cwd=workdir,
        timeout=300,
        env_overrides=os_env,
    )

    validate_output = run_cmd(
        ["terraform", "validate"],
        cwd=workdir,
        timeout=120,
        env_overrides=os_env,
    )

    if action == "plan":
        deploy_output = run_cmd(
            ["terraform", "plan", "-input=false"],
            cwd=workdir,
            timeout=300,
            env_overrides=os_env,
        )

        return {
            "status": "planned",
            "provider": "openstack",
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "terraform_init": tail(init_output),
            "terraform_validate": tail(validate_output),
            "terraform_output": tail(deploy_output, 120),
        }

    if action == "apply":
        deploy_output = run_cmd(
            ["terraform", "apply", "-input=false", "-auto-approve"],
            cwd=workdir,
            timeout=600,
            env_overrides=os_env,
        )

        output_json_raw = run_cmd(
            ["terraform", "output", "-json"],
            cwd=workdir,
            timeout=120,
            env_overrides=os_env,
        )

        try:
            output_json = json.loads(output_json_raw)
        except json.JSONDecodeError:
            output_json = {}

        return {
            "status": "applied",
            "provider": "openstack",
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "outputs": output_json,
            "terraform_output": tail(deploy_output, 120),
        }

    if action == "destroy":
        deploy_output = run_cmd(
            ["terraform", "destroy", "-input=false", "-auto-approve"],
            cwd=workdir,
            timeout=600,
            env_overrides=os_env,
        )

        return {
            "status": "destroyed",
            "provider": "openstack",
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "terraform_output": tail(deploy_output, 120),
        }

    raise ValueError(f"Unsupported action: {action}")
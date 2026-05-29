import os
import requests


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
import os
import secrets
import string
import subprocess
from typing import Dict


def _env_admin() -> Dict[str, str]:
    env = os.environ.copy()

    env.update({
        "OS_AUTH_TYPE": "password",
        "OS_AUTH_URL": os.getenv("OPENSTACK_AUTH_URL", "http://192.168.9.254:5000"),
        "OS_USERNAME": os.getenv("OPENSTACK_ADMIN_USERNAME", "admin"),
        "OS_PASSWORD": os.getenv("OPENSTACK_ADMIN_PASSWORD", ""),
        "OS_PROJECT_NAME": os.getenv("OPENSTACK_ADMIN_PROJECT", "admin"),
        "OS_USER_DOMAIN_NAME": os.getenv("OPENSTACK_USER_DOMAIN_NAME", "Default"),
        "OS_PROJECT_DOMAIN_NAME": os.getenv("OPENSTACK_PROJECT_DOMAIN_NAME", "Default"),
        "OS_REGION_NAME": os.getenv("OPENSTACK_REGION_NAME", "RegionOne"),
        "OS_INTERFACE": os.getenv("OPENSTACK_INTERFACE", "internal"),
        "OS_IDENTITY_API_VERSION": os.getenv("OPENSTACK_IDENTITY_API_VERSION", "3"),
    })

    return env


def _run_openstack(args: list[str]) -> str:
    cmd = ["openstack"] + args
    result = subprocess.run(
        cmd,
        env=_env_admin(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"OpenStack command failed: {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    return result.stdout.strip()


def _random_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def openstack_project_exists(project_name: str) -> bool:
    result = subprocess.run(
        ["openstack", "project", "show", project_name, "-f", "value", "-c", "id"],
        env=_env_admin(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def openstack_user_exists(username: str) -> bool:
    result = subprocess.run(
        ["openstack", "user", "show", username, "-f", "value", "-c", "id"],
        env=_env_admin(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def ensure_openstack_tenant(tenant_id: str) -> dict:
    """
    Creates:
      - Keystone project: <tenant_id>
      - Service user: svc-<tenant_id>-ci
      - Role member in that project
      - Quota
    Returns credential that should be stored in Vault.
    """

    project_name = tenant_id
    username = f"svc-{tenant_id}-ci"
    password = _random_password()

    if not openstack_project_exists(project_name):
        _run_openstack([
            "project", "create", project_name,
            "--domain", os.getenv("OPENSTACK_PROJECT_DOMAIN_NAME", "Default"),
            "--description", f"Tenant project for {tenant_id}",
        ])

    if not openstack_user_exists(username):
        _run_openstack([
            "user", "create", username,
            "--domain", os.getenv("OPENSTACK_USER_DOMAIN_NAME", "Default"),
            "--password", password,
        ])
    else:
        # reset password so Vault has current credential
        _run_openstack([
            "user", "set", username,
            "--password", password,
        ])

    _run_openstack([
        "role", "add",
        "--project", project_name,
        "--user", username,
        "member",
    ])

    # quota best-effort; nếu cloud bạn không support flag nào thì có thể tách try/except
    try:
        _run_openstack([
            "quota", "set", project_name,
            "--instances", "5",
            "--cores", "8",
            "--ram", "16384",
            "--volumes", "5",
            "--gigabytes", "100",
            "--floating-ips", "2",
            "--networks", "3",
            "--subnets", "5",
            "--routers", "2",
        ])
    except Exception as e:
        print(f"[WARN] OpenStack quota set failed for {tenant_id}: {e}")

    return {
        "auth_url": os.getenv("OPENSTACK_AUTH_URL", "http://192.168.9.254:5000"),
        "username": username,
        "password": password,
        "project_name": project_name,
        "user_domain_name": os.getenv("OPENSTACK_USER_DOMAIN_NAME", "Default"),
        "project_domain_name": os.getenv("OPENSTACK_PROJECT_DOMAIN_NAME", "Default"),
        "region_name": os.getenv("OPENSTACK_REGION_NAME", "RegionOne"),
        "interface": os.getenv("OPENSTACK_INTERFACE", "internal"),
        "identity_api_version": os.getenv("OPENSTACK_IDENTITY_API_VERSION", "3"),
    }
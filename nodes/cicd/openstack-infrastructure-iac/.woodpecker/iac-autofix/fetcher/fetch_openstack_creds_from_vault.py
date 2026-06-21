import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing env: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP POST FORM error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP POST JSON error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"X-Vault-Token": token},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP GET JSON error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode(), file=sys.stderr)
        sys.exit(1)


def shell_quote(value) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


KEYCLOAK_TOKEN_URL = required_env("KEYCLOAK_TOKEN_URL")
KEYCLOAK_CLIENT_ID = required_env("KEYCLOAK_CLIENT_ID")
KEYCLOAK_CLIENT_SECRET = required_env("KEYCLOAK_CLIENT_SECRET")

VAULT_ADDR = required_env("VAULT_ADDR").rstrip("/")
VAULT_JWT_ROLE = required_env("VAULT_JWT_ROLE")
VAULT_OPENSTACK_PATH = required_env("VAULT_OPENSTACK_PATH").lstrip("/")

# 1. Get Keycloak client token
kc_resp = post_form(
    KEYCLOAK_TOKEN_URL,
    {
        "grant_type": "client_credentials",
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    },
)

jwt = kc_resp.get("access_token")
if not jwt:
    print(f"Keycloak response missing access_token: {kc_resp}", file=sys.stderr)
    sys.exit(1)

# 2. Login Vault using JWT
vault_login = post_json(
    f"{VAULT_ADDR}/v1/auth/jwt/login",
    {
        "role": VAULT_JWT_ROLE,
        "jwt": jwt,
    },
)

vault_token = vault_login.get("auth", {}).get("client_token")
if not vault_token:
    print(f"Vault login failed: {vault_login}", file=sys.stderr)
    sys.exit(1)

# 3. Read OpenStack tenant credential from Vault KV v2
secret = get_json(
    f"{VAULT_ADDR}/v1/{VAULT_OPENSTACK_PATH}",
    vault_token,
)

data = secret.get("data", {}).get("data", {})
if not data:
    print(f"Vault OpenStack secret is empty or invalid: {secret}", file=sys.stderr)
    sys.exit(1)

required_keys = [
    "auth_url",
    "username",
    "password",
    "project_name",
]

for key in required_keys:
    if not data.get(key):
        print(f"Vault OpenStack secret missing key: {key}", file=sys.stderr)
        sys.exit(1)

env_map = {
    "OS_AUTH_TYPE": "password",
    "OS_AUTH_URL": data["auth_url"],
    "OS_USERNAME": data["username"],
    "OS_PASSWORD": data["password"],
    "OS_PROJECT_NAME": data["project_name"],
    "OS_USER_DOMAIN_NAME": data.get("user_domain_name", "Default"),
    "OS_PROJECT_DOMAIN_NAME": data.get("project_domain_name", "Default"),
    "OS_REGION_NAME": data.get("region_name", "RegionOne"),
    "OS_INTERFACE": data.get("interface", "internal"),
    "OS_IDENTITY_API_VERSION": str(data.get("identity_api_version", "3")),
}

for key, value in env_map.items():
    print(f"export {key}={shell_quote(value)}")
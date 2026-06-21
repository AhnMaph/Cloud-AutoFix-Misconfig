#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required env: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def http_post_form(url: str, data: dict, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        print(f"HTTP POST form error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"HTTP POST form failed: {url}: {e}", file=sys.stderr)
        sys.exit(1)


def http_post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        print(f"HTTP POST JSON error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"HTTP POST JSON failed: {url}: {e}", file=sys.stderr)
        sys.exit(1)


def http_get_json(url: str, headers: dict | None = None, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers=headers or {},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        print(f"HTTP GET error: {e.code} {url}", file=sys.stderr)
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"HTTP GET failed: {url}: {e}", file=sys.stderr)
        sys.exit(1)


def shell_quote(value: str) -> str:
    return value.replace('"', '\\"')


def main():
    keycloak_token_url = required_env("KEYCLOAK_TOKEN_URL")
    keycloak_client_id = os.getenv("KEYCLOAK_CLIENT_ID", "aws-pipeline-client")
    keycloak_client_secret = required_env("KEYCLOAK_CLIENT_SECRET")

    vault_addr = required_env("VAULT_ADDR").rstrip("/")
    vault_jwt_role = required_env("VAULT_JWT_ROLE")
    vault_aws_role = required_env("VAULT_AWS_ROLE")

    aws_default_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    # 1. Get Keycloak access token
    kc_data = http_post_form(
        keycloak_token_url,
        {
            "grant_type": "client_credentials",
            "client_id": keycloak_client_id,
            "client_secret": keycloak_client_secret,
        },
    )

    keycloak_token = kc_data.get("access_token")
    if not keycloak_token:
        print("Keycloak response missing access_token", file=sys.stderr)
        print(json.dumps(kc_data, indent=2), file=sys.stderr)
        sys.exit(1)

    # 2. Login Vault using Keycloak JWT
    vault_login = http_post_json(
        f"{vault_addr}/v1/auth/jwt/login",
        {
            "role": vault_jwt_role,
            "jwt": keycloak_token,
        },
    )

    vault_token = vault_login.get("auth", {}).get("client_token")
    if not vault_token:
        print("Vault login response missing client_token", file=sys.stderr)
        print(json.dumps(vault_login, indent=2), file=sys.stderr)
        sys.exit(1)

    # 3. Read AWS STS credentials from Vault AWS secrets engine
    aws_creds = http_get_json(
        f"{vault_addr}/v1/aws/sts/{vault_aws_role}",
        headers={
            "X-Vault-Token": vault_token,
        },
    )

    data = aws_creds.get("data", {})

    access_key = data.get("access_key")
    secret_key = data.get("secret_key")
    security_token = data.get("security_token")

    if not access_key or not secret_key or not security_token:
        print("Vault AWS STS response missing credential fields", file=sys.stderr)
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)

    # 4. Print shell exports. Pipeline redirect output to .env.cloud.
    print(f'export AWS_ACCESS_KEY_ID="{shell_quote(access_key)}"')
    print(f'export AWS_SECRET_ACCESS_KEY="{shell_quote(secret_key)}"')
    print(f'export AWS_SESSION_TOKEN="{shell_quote(security_token)}"')
    print(f'export AWS_DEFAULT_REGION="{shell_quote(aws_default_region)}"')
    print(f'export AWS_REGION="{shell_quote(aws_default_region)}"')
    print(f'export VAULT_AWS_ROLE="{shell_quote(vault_aws_role)}"')


if __name__ == "__main__":
    main()
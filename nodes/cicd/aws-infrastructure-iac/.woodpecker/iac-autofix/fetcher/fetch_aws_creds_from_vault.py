#!/usr/bin/env python3
import os
import sys
import requests


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required env: {name}", file=sys.stderr)
        sys.exit(1)
    return value


KEYCLOAK_TOKEN_URL = required_env("KEYCLOAK_TOKEN_URL")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "aws-pipeline-client")
KEYCLOAK_CLIENT_SECRET = required_env("KEYCLOAK_CLIENT_SECRET")

VAULT_ADDR = required_env("VAULT_ADDR").rstrip("/")
VAULT_JWT_ROLE = required_env("VAULT_JWT_ROLE")
VAULT_AWS_ROLE = required_env("VAULT_AWS_ROLE")

AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


# 1. Get Keycloak access token
kc_res = requests.post(
    KEYCLOAK_TOKEN_URL,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "client_credentials",
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    },
    timeout=20,
)

if kc_res.status_code != 200:
    print(f"Keycloak token error: {kc_res.status_code}", file=sys.stderr)
    print(kc_res.text, file=sys.stderr)
    sys.exit(1)

keycloak_token = kc_res.json().get("access_token")
if not keycloak_token:
    print("Keycloak response missing access_token", file=sys.stderr)
    print(kc_res.text, file=sys.stderr)
    sys.exit(1)


# 2. Login Vault using Keycloak JWT
vault_login_res = requests.post(
    f"{VAULT_ADDR}/v1/auth/jwt/login",
    json={
        "role": VAULT_JWT_ROLE,
        "jwt": keycloak_token,
    },
    timeout=20,
)

if vault_login_res.status_code != 200:
    print(f"Vault JWT login error: {vault_login_res.status_code}", file=sys.stderr)
    print(vault_login_res.text, file=sys.stderr)
    sys.exit(1)

vault_token = vault_login_res.json().get("auth", {}).get("client_token")
if not vault_token:
    print("Vault login response missing client_token", file=sys.stderr)
    print(vault_login_res.text, file=sys.stderr)
    sys.exit(1)


# 3. Read AWS STS credentials from Vault AWS secrets engine
aws_creds_res = requests.get(
    f"{VAULT_ADDR}/v1/aws/sts/{VAULT_AWS_ROLE}",
    headers={"X-Vault-Token": vault_token},
    timeout=20,
)

if aws_creds_res.status_code != 200:
    print(f"Vault AWS STS error: {aws_creds_res.status_code}", file=sys.stderr)
    print(aws_creds_res.text, file=sys.stderr)
    sys.exit(1)

data = aws_creds_res.json().get("data", {})

access_key = data.get("access_key")
secret_key = data.get("secret_key")
security_token = data.get("security_token")

if not access_key or not secret_key or not security_token:
    print("Vault AWS STS response missing credential fields", file=sys.stderr)
    print(data, file=sys.stderr)
    sys.exit(1)


# 4. Print shell exports to .env.cloud
print(f'export AWS_ACCESS_KEY_ID="{access_key}"')
print(f'export AWS_SECRET_ACCESS_KEY="{secret_key}"')
print(f'export AWS_SESSION_TOKEN="{security_token}"')
print(f'export AWS_DEFAULT_REGION="{AWS_DEFAULT_REGION}"')
print(f'export AWS_REGION="{AWS_DEFAULT_REGION}"')
print(f'export VAULT_AWS_ROLE="{VAULT_AWS_ROLE}"')
#!/usr/bin/env bash
set -euo pipefail

: "${VAULT_ADDR:?Missing VAULT_ADDR}"
: "${VAULT_TOKEN:?Missing VAULT_TOKEN}"
: "${AWS_REGION:=us-east-1}"
: "${VAULT_BROKER_AWS_ACCESS_KEY_ID:?Missing VAULT_BROKER_AWS_ACCESS_KEY_ID}"
: "${VAULT_BROKER_AWS_SECRET_ACCESS_KEY:?Missing VAULT_BROKER_AWS_SECRET_ACCESS_KEY}"
: "${KEYCLOAK_ISSUER:?Missing KEYCLOAK_ISSUER}"

echo "[1/4] Enable AWS secrets engine if needed"
vault secrets enable -path=aws aws 2>/dev/null || true

echo "[2/4] Configure AWS root credential for Vault AWS engine"
vault write aws/config/root \
  access_key="$VAULT_BROKER_AWS_ACCESS_KEY_ID" \
  secret_key="$VAULT_BROKER_AWS_SECRET_ACCESS_KEY" \
  region="$AWS_REGION"

echo "[3/4] Enable JWT auth if needed"
vault auth enable jwt 2>/dev/null || true

echo "[4/4] Configure Vault JWT auth with Keycloak issuer"
vault write auth/jwt/config \
  oidc_discovery_url="$KEYCLOAK_ISSUER" \
  bound_issuer="$KEYCLOAK_ISSUER"

echo "✅ Vault global AWS/JWT bootstrap completed"
#!/usr/bin/env bash
set -euo pipefail

# Instala objetos SQL en una base PostgreSQL existente usando credenciales
# obtenidas desde AWS Secrets Manager.
#
# Uso:
#   AWS_PROFILE=prod AWS_REGION=us-east-1 \
#   ./scripts/install-prod-db-objects.sh \
#     --secret-id "rag-agents/prod/postgres" \
#     --db-host "postgres-aurora-prod.cluster-ch7yo6tzxi4l.us-east-1.rds.amazonaws.com" \
#     --db-name "postgres" \
#     --tenant-schema "alert_prod"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DDL_FILE="${ROOT_DIR}/ddl.sql"

SECRET_ID=""
DB_HOST=""
DB_NAME="postgres"
DB_PORT="5432"
TENANT_SCHEMA=""

usage() {
  echo "Usage:"
  echo "  $0 --secret-id <secret_id> --db-host <host> --tenant-schema <schema> [--db-name <name>] [--db-port <port>]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secret-id)
      SECRET_ID="$2"
      shift 2
      ;;
    --db-host)
      DB_HOST="$2"
      shift 2
      ;;
    --db-name)
      DB_NAME="$2"
      shift 2
      ;;
    --db-port)
      DB_PORT="$2"
      shift 2
      ;;
    --tenant-schema)
      TENANT_SCHEMA="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${SECRET_ID}" || -z "${DB_HOST}" || -z "${TENANT_SCHEMA}" ]]; then
  echo "ERROR: missing required arguments."
  usage
  exit 1
fi

if [[ ! -f "${DDL_FILE}" ]]; then
  echo "ERROR: ddl.sql not found at ${DDL_FILE}"
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI is required."
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: psql is required."
  exit 1
fi

echo "[INFO] Reading credentials from Secrets Manager: ${SECRET_ID}"
SECRET_JSON="$(aws secretsmanager get-secret-value --secret-id "${SECRET_ID}" --query SecretString --output text)"

readarray -t SECRET_FIELDS < <(
  python3 - <<'PY' "${SECRET_JSON}"
import json
import sys

payload = json.loads(sys.argv[1])
username = payload.get("username") or payload.get("user") or ""
password = payload.get("password") or payload.get("pass") or ""
print(username)
print(password)
PY
)

DB_USER="${SECRET_FIELDS[0]:-}"
DB_PASSWORD="${SECRET_FIELDS[1]:-}"

if [[ -z "${DB_USER}" || -z "${DB_PASSWORD}" ]]; then
  echo "ERROR: secret must contain username/user and password/pass keys."
  exit 1
fi

if [[ ! "${TENANT_SCHEMA}" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "ERROR: tenant schema contains invalid characters: ${TENANT_SCHEMA}"
  exit 1
fi

echo "[INFO] Applying DDL to ${DB_HOST}:${DB_PORT}/${DB_NAME} schema=${TENANT_SCHEMA}"
TMP_SQL="$(mktemp)"
trap 'rm -f "${TMP_SQL}"' EXIT

sed "s/{{TENANT_SCHEMA}}/${TENANT_SCHEMA}/g" "${DDL_FILE}" > "${TMP_SQL}"

PGPASSWORD="${DB_PASSWORD}" psql \
  "host=${DB_HOST} port=${DB_PORT} dbname=${DB_NAME} user=${DB_USER} sslmode=require" \
  --set=ON_ERROR_STOP=1 \
  --file "${TMP_SQL}"

echo "[OK] Objects created successfully for schema ${TENANT_SCHEMA}"

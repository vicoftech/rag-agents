#!/bin/bash

set -euo pipefail

# Parámetros esperados
LAMBDA_NAME=$1           # ej: landing_lambda
WORKSPACE=${2:-dev}
ENVIRONMENT=$3

# Validación
if [[ -z "$LAMBDA_NAME" ]]; then
  echo "Uso: $0 <lambda_name> [environment]"
  exit 1
fi

# Rutas y nombres
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
DIST_DIR="${PROJECT_ROOT}/dist"
ZIP_NAME="${LAMBDA_NAME}-${ENVIRONMENT}.zip"

# Limpiar anteriores builds
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "📦 Instalando dependencias en $DIST_DIR ..."
pip install --upgrade pip
pip install -r requirements.txt -t "$DIST_DIR"

# Copiar fuentes Python (index.py, utils.py, etc.)
cp ./*.py "$DIST_DIR/" 2>/dev/null || true
mkdir -p "$DIST_DIR/lib/"
cp ./lib/*.py "$DIST_DIR/lib/" 2>/dev/null || true

# Crear el ZIP
cd "$DIST_DIR"
zip -r "$ZIP_NAME" . > /dev/null
cd "$PROJECT_ROOT"

echo "✅ ZIP generado en: dist/$ZIP_NAME"

# Deploy con Terraform
echo "🚀 Ejecutando Terraform..."
pushd "$PROJECT_ROOT/../../infra" > /dev/null

terraform workspace select "$WORKSPACE"
terraform apply -var-file="environments/${WORKSPACE}.tfvars" -auto-approve

popd > /dev/null

# Limpieza (opcional)
#rm -rf "$DIST_DIR"
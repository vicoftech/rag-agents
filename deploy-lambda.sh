#!/bin/bash
# deploy-lambda.sh
# Deploya una Lambda individual con sus dependencias, usando S3 para paquetes grandes

set -e

LAMBDA_NAME="${1:-rag_lmbd_embeddings}"
ENV="${2:-dev}"
PROFILE="${3:-asap_main}"
REGION="${4:-us-east-1}"

# Obtener el Account ID para construir el nombre del bucket
ACCOUNT_ID=$(aws sts get-caller-identity --profile "${PROFILE}" --query Account --output text)
S3_BUCKET="rag-documents-${ENV}-${ACCOUNT_ID}"
S3_KEY="lambda-deployments/${LAMBDA_NAME}-$(date +%Y%m%d%H%M%S).zip"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAMBDA_DIR="${SCRIPT_DIR}/apps/${LAMBDA_NAME}"
BUILD_DIR="/tmp/${LAMBDA_NAME}-build"
ZIP_FILE="/tmp/${LAMBDA_NAME}.zip"

echo "============================================================"
echo "🚀 Deploying Lambda: ${LAMBDA_NAME}-${ENV}"
echo "============================================================"
echo "Region:  ${REGION}"
echo "Profile: ${PROFILE}"
echo "Bucket:  ${S3_BUCKET}"
echo ""

# Verificar que el directorio existe
if [ ! -d "${LAMBDA_DIR}" ]; then
    echo "❌ Error: Directorio ${LAMBDA_DIR} no existe"
    exit 1
fi

# Limpiar builds anteriores
rm -rf "${BUILD_DIR}"
rm -f "${ZIP_FILE}"
mkdir -p "${BUILD_DIR}"

echo "📁 Copiando código fuente..."
# Copiar código fuente al directorio de build
cp -r "${LAMBDA_DIR}"/* "${BUILD_DIR}/" 2>/dev/null || true

# Remover archivos innecesarios del build
rm -rf "${BUILD_DIR}/.git" \
       "${BUILD_DIR}/.gitignore" \
       "${BUILD_DIR}/.DS_Store" \
       "${BUILD_DIR}/__pycache__" \
       "${BUILD_DIR}/venv" \
       "${BUILD_DIR}/test_*.py" \
       "${BUILD_DIR}/build_lambda.sh" \
       "${BUILD_DIR}/*.md"

find "${BUILD_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${BUILD_DIR}" -name "*.pyc" -delete 2>/dev/null || true

# Instalar dependencias si existe requirements.txt
if [ -f "${LAMBDA_DIR}/requirements.txt" ]; then
    echo "📦 Instalando dependencias desde requirements.txt..."
    
    pip install \
        --quiet \
        --target "${BUILD_DIR}" \
        --platform manylinux2014_x86_64 \
        --implementation cp \
        --python-version 3.12 \
        --only-binary=:all: \
        --upgrade \
        -r "${LAMBDA_DIR}/requirements.txt" 2>/dev/null || \
    pip install \
        --quiet \
        --target "${BUILD_DIR}" \
        --upgrade \
        -r "${LAMBDA_DIR}/requirements.txt"
    
    echo "✅ Dependencias instaladas"
    
    # Limpiar archivos innecesarios de las dependencias
    find "${BUILD_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "${BUILD_DIR}" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
    find "${BUILD_DIR}" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
    find "${BUILD_DIR}" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
    find "${BUILD_DIR}" -name "*.pyc" -delete 2>/dev/null || true
    find "${BUILD_DIR}" -name "*.pyo" -delete 2>/dev/null || true
else
    echo "⚠️  No se encontró requirements.txt, empaquetando solo código fuente"
fi

echo "🗜️  Creando paquete ZIP..."
cd "${BUILD_DIR}"
zip -r -q "${ZIP_FILE}" .
cd - > /dev/null

# Mostrar tamaño del zip
ZIP_SIZE=$(du -h "${ZIP_FILE}" | cut -f1)
echo "📊 Tamaño del paquete: ${ZIP_SIZE}"

# Si el zip es mayor a 50MB, usar S3
ZIP_SIZE_BYTES=$(stat -f%z "${ZIP_FILE}" 2>/dev/null || stat -c%s "${ZIP_FILE}" 2>/dev/null)
MAX_DIRECT_SIZE=50000000  # 50MB

if [ "${ZIP_SIZE_BYTES}" -gt "${MAX_DIRECT_SIZE}" ]; then
    echo "📤 Paquete grande (${ZIP_SIZE}), subiendo a S3..."
    
    aws s3 cp "${ZIP_FILE}" "s3://${S3_BUCKET}/${S3_KEY}" \
        --profile "${PROFILE}" \
        --region "${REGION}"
    
    echo "🔄 Actualizando función Lambda desde S3..."
    aws lambda update-function-code \
        --function-name "${LAMBDA_NAME}-${ENV}" \
        --s3-bucket "${S3_BUCKET}" \
        --s3-key "${S3_KEY}" \
        --profile "${PROFILE}" \
        --region "${REGION}"
    
    echo "🧹 Limpiando archivo en S3..."
    aws s3 rm "s3://${S3_BUCKET}/${S3_KEY}" \
        --profile "${PROFILE}" \
        --region "${REGION}"
else
    echo "🔄 Actualizando función Lambda directamente..."
    aws lambda update-function-code \
        --function-name "${LAMBDA_NAME}-${ENV}" \
        --zip-file "fileb://${ZIP_FILE}" \
        --profile "${PROFILE}" \
        --region "${REGION}"
fi

# Limpiar archivos temporales
echo "🧹 Limpiando archivos temporales..."
rm -rf "${BUILD_DIR}"
rm -f "${ZIP_FILE}"

echo ""
echo "============================================================"
echo "✅ Deploy completado: ${LAMBDA_NAME}-${ENV}"
echo "============================================================"

# Mostrar info de la función
aws lambda get-function \
    --function-name "${LAMBDA_NAME}-${ENV}" \
    --profile "${PROFILE}" \
    --region "${REGION}" \
    --query 'Configuration.{LastModified:LastModified,CodeSize:CodeSize,MemorySize:MemorySize,Timeout:Timeout}' \
    --output table

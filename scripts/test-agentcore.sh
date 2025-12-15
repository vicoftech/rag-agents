#!/bin/bash
# ==============================================================================
# Test Bedrock AgentCore
# ==============================================================================

set -e

AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

# Cargar configuración si existe
CONFIG_FILE="/tmp/agentcore-${ENVIRONMENT}.conf"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
    echo -e "${GREEN}[OK]${NC} Configuración cargada de $CONFIG_FILE"
fi

# Si no hay RUNTIME_ID, buscarlo
if [ -z "$RUNTIME_ID" ]; then
    AGENT_NAME="${AGENT_NAME:-RagAgent_${ENVIRONMENT}}"
    echo -e "${BLUE}[INFO]${NC} Buscando Agent Runtime: $AGENT_NAME"
    
    RUNTIME_ID=$(aws_cmd bedrock-agentcore-control list-agent-runtimes \
        --query "agentRuntimeSummaries[?name=='${AGENT_NAME}'].agentRuntimeId" \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$RUNTIME_ID" ] || [ "$RUNTIME_ID" = "None" ]; then
        echo "Error: No se encontró el Agent Runtime"
        exit 1
    fi
fi

echo -e "${GREEN}[OK]${NC} Runtime ID: $RUNTIME_ID"

# Obtener endpoint si no está definido
if [ -z "$ENDPOINT_ID" ]; then
    ENDPOINT_ID=$(aws_cmd bedrock-agentcore-control list-agent-runtime-endpoints \
        --agent-runtime-id "$RUNTIME_ID" \
        --query "agentRuntimeEndpointSummaries[0].agentRuntimeEndpointId" \
        --output text 2>/dev/null || echo "")
fi

echo -e "${GREEN}[OK]${NC} Endpoint ID: $ENDPOINT_ID"

# Parámetros de prueba
TENANT_ID="${1:-asap}"
AGENT_CONFIG_ID="${2:-d8c38f93-f4cd-4a85-9c31-297d14ce7009}"
QUERY="${3:-¿Cuáles son los lineamientos de arquitectura?}"

echo ""
echo "============================================"
echo "Invocando AgentCore:"
echo "  Runtime ID: $RUNTIME_ID"
echo "  Endpoint ID: $ENDPOINT_ID"
echo "  Tenant ID: $TENANT_ID"
echo "  Query: $QUERY"
echo "============================================"
echo ""

# Invocar el agente
aws_cmd bedrock-agentcore invoke-agent \
    --agent-runtime-id "$RUNTIME_ID" \
    --endpoint-id "$ENDPOINT_ID" \
    --input "{\"prompt\": \"$QUERY\", \"tenant_id\": \"$TENANT_ID\", \"agent_id\": \"$AGENT_CONFIG_ID\"}" \
    --output json 2>&1 || {
        echo ""
        echo "Si el comando anterior falló, intenta con:"
        echo ""
        echo "aws bedrock-agentcore invoke --help"
        echo ""
        echo "O verifica el estado del runtime:"
        echo "aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id $RUNTIME_ID --profile $AWS_PROFILE --region $AWS_REGION"
    }

echo ""

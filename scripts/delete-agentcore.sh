#!/bin/bash
# ==============================================================================
# Delete Bedrock AgentCore Resources
# ==============================================================================

set -e

AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AGENT_NAME="${AGENT_NAME:-RagAgent_${ENVIRONMENT}}"

RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

echo -e "${YELLOW}[WARNING]${NC} Este script eliminará todos los recursos de AgentCore para: $AGENT_NAME"
echo ""
read -p "¿Estás seguro? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Operación cancelada"
    exit 0
fi

# Buscar Runtime
echo -e "${BLUE}[INFO]${NC} Buscando Agent Runtime..."
RUNTIME_ID=$(aws_cmd bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimeSummaries[?name=='${AGENT_NAME}'].agentRuntimeId" \
    --output text 2>/dev/null || echo "")

if [ -n "$RUNTIME_ID" ] && [ "$RUNTIME_ID" != "None" ]; then
    echo -e "${BLUE}[INFO]${NC} Runtime encontrado: $RUNTIME_ID"
    
    # Eliminar endpoints primero
    echo -e "${BLUE}[INFO]${NC} Eliminando endpoints..."
    ENDPOINTS=$(aws_cmd bedrock-agentcore-control list-agent-runtime-endpoints \
        --agent-runtime-id "$RUNTIME_ID" \
        --query "agentRuntimeEndpointSummaries[].agentRuntimeEndpointId" \
        --output text 2>/dev/null || echo "")
    
    for endpoint_id in $ENDPOINTS; do
        if [ -n "$endpoint_id" ] && [ "$endpoint_id" != "None" ]; then
            echo "  Eliminando endpoint: $endpoint_id"
            aws_cmd bedrock-agentcore-control delete-agent-runtime-endpoint \
                --agent-runtime-id "$RUNTIME_ID" \
                --agent-runtime-endpoint-id "$endpoint_id" 2>/dev/null || true
        fi
    done
    
    sleep 10
    
    # Eliminar runtime
    echo -e "${BLUE}[INFO]${NC} Eliminando Agent Runtime..."
    aws_cmd bedrock-agentcore-control delete-agent-runtime \
        --agent-runtime-id "$RUNTIME_ID" 2>/dev/null || true
    
    echo -e "${GREEN}[OK]${NC} Agent Runtime eliminado"
else
    echo -e "${BLUE}[INFO]${NC} No se encontró Agent Runtime"
fi

# Eliminar Memory
MEMORY_NAME="${AGENT_NAME/RagAgent/RagAgentMemory}"
echo -e "${BLUE}[INFO]${NC} Buscando Memory: $MEMORY_NAME"

MEMORY_ID=$(aws_cmd bedrock-agentcore-control list-memories \
    --query "memories[?name=='${MEMORY_NAME}'].memoryId" \
    --output text 2>/dev/null || echo "")

if [ -n "$MEMORY_ID" ] && [ "$MEMORY_ID" != "None" ]; then
    echo -e "${BLUE}[INFO]${NC} Eliminando Memory: $MEMORY_ID"
    aws_cmd bedrock-agentcore-control delete-memory \
        --memory-id "$MEMORY_ID" 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC} Memory eliminada"
else
    echo -e "${BLUE}[INFO]${NC} No se encontró Memory"
fi

# Eliminar IAM Role
ROLE_NAME="${AGENT_NAME}_role"
echo -e "${BLUE}[INFO]${NC} Eliminando IAM Role: $ROLE_NAME"

aws_cmd iam delete-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "${AGENT_NAME}_policy" 2>/dev/null || true

aws_cmd iam delete-role --role-name "$ROLE_NAME" 2>/dev/null || true

echo -e "${GREEN}[OK]${NC} IAM Role eliminado"

# Limpiar archivo de configuración
rm -f "/tmp/agentcore-${ENVIRONMENT}.conf"

echo ""
echo -e "${GREEN}[DONE]${NC} Todos los recursos de AgentCore han sido eliminados"

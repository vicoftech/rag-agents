#!/bin/bash
# ==============================================================================
# Delete Bedrock Agent
# ==============================================================================

set -e

AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AGENT_NAME="rag-agent-${ENVIRONMENT}"

RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

echo -e "${YELLOW}[WARNING]${NC} Este script eliminará el agente: $AGENT_NAME"
echo ""

# Buscar agente
AGENT_ID=$(aws_cmd bedrock-agent list-agents \
    --query "agentSummaries[?agentName=='${AGENT_NAME}'].agentId" \
    --output text 2>/dev/null || echo "")

if [ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "None" ]; then
    echo -e "${BLUE}[INFO]${NC} No se encontró el agente $AGENT_NAME"
    exit 0
fi

echo "Agent ID: $AGENT_ID"
echo ""
read -p "¿Estás seguro de que deseas eliminar este agente? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Operación cancelada"
    exit 0
fi

# Eliminar aliases primero
echo -e "${BLUE}[INFO]${NC} Eliminando aliases..."
ALIASES=$(aws_cmd bedrock-agent list-agent-aliases \
    --agent-id "$AGENT_ID" \
    --query "agentAliasSummaries[].agentAliasId" \
    --output text 2>/dev/null || echo "")

for alias_id in $ALIASES; do
    if [ -n "$alias_id" ] && [ "$alias_id" != "None" ]; then
        echo "  Eliminando alias: $alias_id"
        aws_cmd bedrock-agent delete-agent-alias \
            --agent-id "$AGENT_ID" \
            --agent-alias-id "$alias_id" 2>/dev/null || true
    fi
done

# Esperar un poco
sleep 5

# Eliminar action groups
echo -e "${BLUE}[INFO]${NC} Eliminando action groups..."
ACTION_GROUPS=$(aws_cmd bedrock-agent list-agent-action-groups \
    --agent-id "$AGENT_ID" \
    --agent-version "DRAFT" \
    --query "actionGroupSummaries[].actionGroupId" \
    --output text 2>/dev/null || echo "")

for ag_id in $ACTION_GROUPS; do
    if [ -n "$ag_id" ] && [ "$ag_id" != "None" ]; then
        echo "  Eliminando action group: $ag_id"
        aws_cmd bedrock-agent delete-agent-action-group \
            --agent-id "$AGENT_ID" \
            --agent-version "DRAFT" \
            --action-group-id "$ag_id" \
            --skip-resource-in-use-check 2>/dev/null || true
    fi
done

sleep 5

# Eliminar el agente
echo -e "${BLUE}[INFO]${NC} Eliminando agente..."
aws_cmd bedrock-agent delete-agent \
    --agent-id "$AGENT_ID" \
    --skip-resource-in-use-check

# Eliminar IAM role
AGENT_ROLE_NAME="${AGENT_NAME}-role"
echo -e "${BLUE}[INFO]${NC} Eliminando IAM role: $AGENT_ROLE_NAME"

# Eliminar políticas inline
aws_cmd iam delete-role-policy \
    --role-name "$AGENT_ROLE_NAME" \
    --policy-name "${AGENT_NAME}-policy" 2>/dev/null || true

# Eliminar role
aws_cmd iam delete-role --role-name "$AGENT_ROLE_NAME" 2>/dev/null || true

echo ""
echo -e "${BLUE}[INFO]${NC} Agente $AGENT_NAME eliminado correctamente"

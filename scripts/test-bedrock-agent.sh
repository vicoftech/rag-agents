#!/bin/bash
# ==============================================================================
# Test Bedrock Agent via REST
# ==============================================================================

set -e

# Configuración
AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AGENT_NAME="rag-agent-${ENVIRONMENT}"

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

# Obtener Agent ID y Alias ID
echo -e "${BLUE}[INFO]${NC} Buscando agente: $AGENT_NAME"

AGENT_ID=$(aws_cmd bedrock-agent list-agents \
    --query "agentSummaries[?agentName=='${AGENT_NAME}'].agentId" \
    --output text)

if [ -z "$AGENT_ID" ] || [ "$AGENT_ID" = "None" ]; then
    echo "Error: No se encontró el agente $AGENT_NAME"
    exit 1
fi

ALIAS_ID=$(aws_cmd bedrock-agent list-agent-aliases \
    --agent-id "$AGENT_ID" \
    --query "agentAliasSummaries[?agentAliasName=='live'].agentAliasId" \
    --output text)

echo -e "${GREEN}[SUCCESS]${NC} Agent ID: $AGENT_ID"
echo -e "${GREEN}[SUCCESS]${NC} Alias ID: $ALIAS_ID"

# Parámetros de prueba
TENANT_ID="${1:-asap}"
AGENT_CONFIG_ID="${2:-d8c38f93-f4cd-4a85-9c31-297d14ce7009}"
QUERY="${3:-¿Cuáles son los lineamientos de arquitectura?}"
SESSION_ID="test-session-$(date +%s)"

echo ""
echo "============================================"
echo "Invocando agente con:"
echo "  Tenant ID: $TENANT_ID"
echo "  Agent Config ID: $AGENT_CONFIG_ID"
echo "  Query: $QUERY"
echo "  Session ID: $SESSION_ID"
echo "============================================"
echo ""

# Crear archivo temporal para la respuesta
OUTPUT_FILE="/tmp/bedrock-agent-response-$$.txt"

# Invocar el agente
aws_cmd bedrock-agent-runtime invoke-agent \
    --agent-id "$AGENT_ID" \
    --agent-alias-id "$ALIAS_ID" \
    --session-id "$SESSION_ID" \
    --input-text "$QUERY" \
    --session-state "{
        \"sessionAttributes\": {
            \"tenant_id\": \"$TENANT_ID\",
            \"agent_id\": \"$AGENT_CONFIG_ID\"
        }
    }" \
    "$OUTPUT_FILE"

echo ""
echo "============================================"
echo "Respuesta del Agente:"
echo "============================================"
cat "$OUTPUT_FILE"
echo ""

rm -f "$OUTPUT_FILE"

echo ""
echo "============================================"
echo "Para hacer otra pregunta en la misma sesión:"
echo "============================================"
echo "SESSION_ID=$SESSION_ID $0 $TENANT_ID $AGENT_CONFIG_ID \"tu nueva pregunta\""

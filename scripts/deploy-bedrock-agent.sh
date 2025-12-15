#!/bin/bash
# ==============================================================================
# Deploy Bedrock Agent with Memory and REST API
# ==============================================================================
# Este script crea un Bedrock Agent completo con:
# - Memory (retención de contexto entre sesiones)
# - Action Group para invocar la Lambda de RAG
# - Alias para acceso via REST API
# ==============================================================================

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==============================================================================
# CONFIGURACIÓN - Modificar según tu entorno
# ==============================================================================
AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Nombres de recursos
AGENT_NAME="rag-agent-${ENVIRONMENT}"
AGENT_DESCRIPTION="RAG Agent con búsqueda semántica en base de conocimiento empresarial"

# Modelo de Bedrock a usar
AGENT_MODEL_ID="${AGENT_MODEL_ID:-anthropic.claude-3-5-sonnet-20241022-v2:0}"

# Lambda que el agente invocará
LAMBDA_QUERY_NAME="${LAMBDA_QUERY_NAME:-rag_lmbd_query-${ENVIRONMENT}}"

# Configuración de memoria
MEMORY_DAYS="${MEMORY_DAYS:-30}"  # Días de retención de memoria

# ==============================================================================
# Funciones auxiliares
# ==============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

wait_for_agent_status() {
    local agent_id=$1
    local target_status=$2
    local max_attempts=${3:-30}
    local attempt=0
    
    log_info "Esperando que el agente alcance estado: $target_status..."
    
    while [ $attempt -lt $max_attempts ]; do
        status=$(aws_cmd bedrock-agent get-agent --agent-id "$agent_id" \
            --query 'agent.agentStatus' --output text 2>/dev/null || echo "UNKNOWN")
        
        if [ "$status" = "$target_status" ]; then
            log_success "Agente en estado: $status"
            return 0
        elif [ "$status" = "FAILED" ]; then
            log_error "El agente falló"
            return 1
        fi
        
        log_info "Estado actual: $status (intento $((attempt+1))/$max_attempts)"
        sleep 5
        ((attempt++))
    done
    
    log_error "Timeout esperando estado $target_status"
    return 1
}

# ==============================================================================
# Obtener información de cuenta
# ==============================================================================

log_info "Obteniendo información de cuenta AWS..."
AWS_ACCOUNT_ID=$(aws_cmd sts get-caller-identity --query 'Account' --output text)
log_success "Cuenta AWS: $AWS_ACCOUNT_ID"

# ==============================================================================
# Crear IAM Role para el Agente (si no existe)
# ==============================================================================

AGENT_ROLE_NAME="${AGENT_NAME}-role"
AGENT_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${AGENT_ROLE_NAME}"

log_info "Verificando/creando IAM Role: $AGENT_ROLE_NAME"

# Trust policy para Bedrock Agent
TRUST_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock.amazonaws.com"
            },
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": "${AWS_ACCOUNT_ID}"
                },
                "ArnLike": {
                    "aws:SourceArn": "arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:agent/*"
                }
            }
        }
    ]
}
EOF
)

# Crear role si no existe
if ! aws_cmd iam get-role --role-name "$AGENT_ROLE_NAME" &>/dev/null; then
    log_info "Creando IAM Role..."
    aws_cmd iam create-role \
        --role-name "$AGENT_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Role for Bedrock Agent ${AGENT_NAME}"
    
    sleep 5  # Esperar propagación
else
    log_info "IAM Role ya existe, actualizando trust policy..."
    aws_cmd iam update-assume-role-policy \
        --role-name "$AGENT_ROLE_NAME" \
        --policy-document "$TRUST_POLICY"
fi

# Política para invocar Bedrock y Lambda
AGENT_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "BedrockInvokeModel",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": [
                "arn:aws:bedrock:${AWS_REGION}::foundation-model/*"
            ]
        },
        {
            "Sid": "LambdaInvoke",
            "Effect": "Allow",
            "Action": [
                "lambda:InvokeFunction"
            ],
            "Resource": [
                "arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${LAMBDA_QUERY_NAME}*"
            ]
        }
    ]
}
EOF
)

# Aplicar política inline
log_info "Aplicando política al role..."
aws_cmd iam put-role-policy \
    --role-name "$AGENT_ROLE_NAME" \
    --policy-name "${AGENT_NAME}-policy" \
    --policy-document "$AGENT_POLICY"

sleep 10  # Esperar propagación de IAM

# ==============================================================================
# Crear el Agente de Bedrock
# ==============================================================================

log_info "Verificando si el agente ya existe..."
EXISTING_AGENT_ID=$(aws_cmd bedrock-agent list-agents \
    --query "agentSummaries[?agentName=='${AGENT_NAME}'].agentId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_AGENT_ID" ] && [ "$EXISTING_AGENT_ID" != "None" ]; then
    log_warning "Agente ya existe con ID: $EXISTING_AGENT_ID"
    AGENT_ID="$EXISTING_AGENT_ID"
else
    log_info "Creando nuevo Bedrock Agent: $AGENT_NAME"
    
    # Instrucciones del agente
    AGENT_INSTRUCTION=$(cat <<'EOF'
Eres un asistente inteligente especializado en buscar y sintetizar información de bases de conocimiento empresariales.

## Instrucciones:

1. **Siempre usa la acción knowledge_base_search** para buscar información antes de responder preguntas sobre documentos o conocimiento específico.

2. **Parámetros requeridos para knowledge_base_search**: 
   - query: La pregunta o términos de búsqueda
   - tenant_id: El identificador del tenant/organización
   - agent_id: El identificador del agente

3. **Formato de respuesta**:
   - Sintetiza la información encontrada de manera clara y estructurada
   - Si no encuentras información, indica que no hay datos disponibles
   - Cita las fuentes cuando sea posible

4. **Memoria**:
   - Recuerda el contexto de conversaciones anteriores
   - Usa la información previa para dar respuestas más relevantes

5. **Comportamiento**:
   - Responde siempre en español
   - Sé conciso pero completo
   - Si no tienes información suficiente, pregunta para clarificar
EOF
)

    # Crear el agente con memoria habilitada
    AGENT_RESPONSE=$(aws_cmd bedrock-agent create-agent \
        --agent-name "$AGENT_NAME" \
        --agent-resource-role-arn "$AGENT_ROLE_ARN" \
        --foundation-model "$AGENT_MODEL_ID" \
        --description "$AGENT_DESCRIPTION" \
        --instruction "$AGENT_INSTRUCTION" \
        --idle-session-ttl-in-seconds 1800 \
        --memory-configuration "enabledMemoryTypes=SESSION_SUMMARY,storageDays=${MEMORY_DAYS}" \
        --output json)
    
    AGENT_ID=$(echo "$AGENT_RESPONSE" | jq -r '.agent.agentId')
    log_success "Agente creado con ID: $AGENT_ID"
fi

# Esperar a que el agente esté listo
wait_for_agent_status "$AGENT_ID" "NOT_PREPARED" 20 || wait_for_agent_status "$AGENT_ID" "PREPARED" 20

# ==============================================================================
# Crear Action Group (para invocar Lambda)
# ==============================================================================

log_info "Configurando Action Group para Lambda..."

# Obtener ARN de la Lambda
LAMBDA_ARN=$(aws_cmd lambda get-function \
    --function-name "$LAMBDA_QUERY_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text 2>/dev/null || echo "")

if [ -z "$LAMBDA_ARN" ] || [ "$LAMBDA_ARN" = "None" ]; then
    log_error "No se encontró la Lambda: $LAMBDA_QUERY_NAME"
    log_warning "Asegúrate de que la Lambda esté desplegada antes de ejecutar este script"
    exit 1
fi

log_info "Lambda ARN: $LAMBDA_ARN"

# OpenAPI Schema para el Action Group
ACTION_GROUP_SCHEMA=$(cat <<'EOF'
{
    "openapi": "3.0.0",
    "info": {
        "title": "RAG Knowledge Base Search API",
        "version": "1.0.0",
        "description": "API para buscar en la base de conocimiento empresarial"
    },
    "paths": {
        "/search": {
            "post": {
                "operationId": "knowledge_base_search",
                "summary": "Busca información en la base de conocimiento",
                "description": "Realiza una búsqueda semántica en la base de conocimiento del tenant especificado y retorna información relevante procesada por un modelo LLM.",
                "requestBody": {
                    "required": true,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["query", "tenant_id", "agent_id"],
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "La pregunta o términos de búsqueda para encontrar información relevante"
                                    },
                                    "tenant_id": {
                                        "type": "string",
                                        "description": "Identificador único del tenant/organización"
                                    },
                                    "agent_id": {
                                        "type": "string",
                                        "description": "Identificador único del agente configurado para este tenant"
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Respuesta exitosa con la información encontrada",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "response": {
                                            "type": "string",
                                            "description": "Respuesta procesada con la información encontrada"
                                        },
                                        "sources": {
                                            "type": "array",
                                            "items": {
                                                "type": "string"
                                            },
                                            "description": "Lista de fuentes de donde se obtuvo la información"
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
EOF
)

# Guardar schema en archivo temporal
SCHEMA_FILE="/tmp/agent-schema-${AGENT_ID}.json"
echo "$ACTION_GROUP_SCHEMA" > "$SCHEMA_FILE"

# Verificar si ya existe un Action Group
EXISTING_AG=$(aws_cmd bedrock-agent list-agent-action-groups \
    --agent-id "$AGENT_ID" \
    --agent-version "DRAFT" \
    --query "actionGroupSummaries[?actionGroupName=='RAGSearchActionGroup'].actionGroupId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_AG" ] && [ "$EXISTING_AG" != "None" ]; then
    log_info "Action Group ya existe, actualizando..."
    aws_cmd bedrock-agent update-agent-action-group \
        --agent-id "$AGENT_ID" \
        --agent-version "DRAFT" \
        --action-group-id "$EXISTING_AG" \
        --action-group-name "RAGSearchActionGroup" \
        --action-group-executor "lambda={lambdaArn=${LAMBDA_ARN}}" \
        --api-schema "payload=$(cat $SCHEMA_FILE)" \
        --action-group-state "ENABLED"
else
    log_info "Creando Action Group..."
    
    # Dar permisos a Bedrock para invocar la Lambda
    log_info "Agregando permisos de invocación a Lambda..."
    aws_cmd lambda add-permission \
        --function-name "$LAMBDA_QUERY_NAME" \
        --statement-id "AllowBedrockAgent-${AGENT_ID}" \
        --action "lambda:InvokeFunction" \
        --principal "bedrock.amazonaws.com" \
        --source-arn "arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:agent/${AGENT_ID}" \
        2>/dev/null || log_warning "Permiso ya existe o error al agregar"

    aws_cmd bedrock-agent create-agent-action-group \
        --agent-id "$AGENT_ID" \
        --agent-version "DRAFT" \
        --action-group-name "RAGSearchActionGroup" \
        --action-group-executor "lambda={lambdaArn=${LAMBDA_ARN}}" \
        --api-schema "payload=$(cat $SCHEMA_FILE)" \
        --action-group-state "ENABLED"
fi

rm -f "$SCHEMA_FILE"
log_success "Action Group configurado"

# ==============================================================================
# Preparar el Agente
# ==============================================================================

log_info "Preparando el agente..."
aws_cmd bedrock-agent prepare-agent --agent-id "$AGENT_ID"

wait_for_agent_status "$AGENT_ID" "PREPARED" 60

# ==============================================================================
# Crear Alias (necesario para invocar via REST)
# ==============================================================================

ALIAS_NAME="live"
log_info "Verificando/creando alias: $ALIAS_NAME"

EXISTING_ALIAS=$(aws_cmd bedrock-agent list-agent-aliases \
    --agent-id "$AGENT_ID" \
    --query "agentAliasSummaries[?agentAliasName=='${ALIAS_NAME}'].agentAliasId" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_ALIAS" ] && [ "$EXISTING_ALIAS" != "None" ]; then
    log_info "Alias ya existe, actualizando..."
    ALIAS_ID="$EXISTING_ALIAS"
    aws_cmd bedrock-agent update-agent-alias \
        --agent-id "$AGENT_ID" \
        --agent-alias-id "$ALIAS_ID" \
        --agent-alias-name "$ALIAS_NAME" \
        --description "Alias de producción para acceso REST"
else
    log_info "Creando nuevo alias..."
    ALIAS_RESPONSE=$(aws_cmd bedrock-agent create-agent-alias \
        --agent-id "$AGENT_ID" \
        --agent-alias-name "$ALIAS_NAME" \
        --description "Alias de producción para acceso REST" \
        --output json)
    
    ALIAS_ID=$(echo "$ALIAS_RESPONSE" | jq -r '.agentAlias.agentAliasId')
fi

log_success "Alias ID: $ALIAS_ID"

# ==============================================================================
# Resumen y comandos de prueba
# ==============================================================================

echo ""
echo "=============================================================================="
echo -e "${GREEN}¡Bedrock Agent desplegado exitosamente!${NC}"
echo "=============================================================================="
echo ""
echo "Información del Agente:"
echo "  - Agent ID:    $AGENT_ID"
echo "  - Agent Name:  $AGENT_NAME"
echo "  - Alias ID:    $ALIAS_ID"
echo "  - Alias Name:  $ALIAS_NAME"
echo "  - Model:       $AGENT_MODEL_ID"
echo "  - Memory:      ${MEMORY_DAYS} días de retención"
echo ""
echo "=============================================================================="
echo "Invocar el agente via REST (AWS CLI):"
echo "=============================================================================="
echo ""
cat <<EOF
# Invocar el agente
aws bedrock-agent-runtime invoke-agent \\
    --agent-id "${AGENT_ID}" \\
    --agent-alias-id "${ALIAS_ID}" \\
    --session-id "session-\$(date +%s)" \\
    --input-text "¿Cuáles son los lineamientos de arquitectura?" \\
    --profile ${AWS_PROFILE} \\
    --region ${AWS_REGION} \\
    output.txt

# Ver respuesta
cat output.txt
EOF

echo ""
echo "=============================================================================="
echo "Invocar con Python (boto3):"
echo "=============================================================================="
echo ""
cat <<EOF
import boto3
import json

client = boto3.client('bedrock-agent-runtime', region_name='${AWS_REGION}')

response = client.invoke_agent(
    agentId='${AGENT_ID}',
    agentAliasId='${ALIAS_ID}',
    sessionId='my-session-123',
    inputText='¿Cuáles son los lineamientos de arquitectura?',
    sessionState={
        'sessionAttributes': {
            'tenant_id': 'tu_tenant',
            'agent_id': 'tu_agent_id'
        }
    }
)

# Procesar respuesta streaming
for event in response['completion']:
    if 'chunk' in event:
        print(event['chunk']['bytes'].decode('utf-8'), end='')
EOF

echo ""
echo "=============================================================================="
echo "URLs útiles:"
echo "=============================================================================="
echo ""
echo "  Console: https://${AWS_REGION}.console.aws.amazon.com/bedrock/home?region=${AWS_REGION}#/agents/${AGENT_ID}"
echo ""

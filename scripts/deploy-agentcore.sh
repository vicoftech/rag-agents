#!/bin/bash
# ==============================================================================
# Deploy Agent Runtime to Amazon Bedrock AgentCore
# ==============================================================================
# Despliega el agente Strands (imagen ECR) en AgentCore
# El agente ya tiene las tools configuradas internamente
# ==============================================================================

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
AWS_PROFILE="${AWS_PROFILE:-asap_main}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Nombre del agente (solo letras, números, guión bajo - debe empezar con letra)
AGENT_NAME="${AGENT_NAME:-RagAgent_${ENVIRONMENT}}"

# ECR Image
ECR_REPO="${ECR_REPO:-rag-agent}"
ECR_TAG="${ECR_TAG:-latest}"

# Lambda que el agente invoca (para variables de entorno)
LAMBDA_QUERY_NAME="${LAMBDA_QUERY_NAME:-rag_lmbd_query-${ENVIRONMENT}}"

# ==============================================================================
# Funciones auxiliares
# ==============================================================================

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

aws_cmd() {
    aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
}

wait_for_status() {
    local resource=$1
    local cmd=$2
    local target=$3
    local max=${4:-60}
    local i=0
    
    log_info "Esperando $resource → $target..."
    while [ $i -lt $max ]; do
        status=$(eval "$cmd" 2>/dev/null || echo "UNKNOWN")
        if [ "$status" = "$target" ]; then
            log_success "$resource: $status"
            return 0
        elif [[ "$status" == *"FAILED"* ]]; then
            log_error "$resource falló: $status"
            return 1
        fi
        echo -n "."
        sleep 5
        ((i++))
    done
    echo ""
    log_warning "Timeout (estado actual: $status)"
    return 1
}

# ==============================================================================
# Obtener información de cuenta
# ==============================================================================

log_info "Obteniendo información de cuenta AWS..."
AWS_ACCOUNT_ID=$(aws_cmd sts get-caller-identity --query 'Account' --output text)
log_success "Cuenta: $AWS_ACCOUNT_ID | Región: $AWS_REGION"

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${ECR_TAG}"
log_info "ECR URI: $ECR_URI"

# Verificar imagen ECR
log_info "Verificando imagen ECR..."
if ! aws_cmd ecr describe-images --repository-name "$ECR_REPO" &>/dev/null; then
    log_error "Repositorio ECR no encontrado: $ECR_REPO"
    exit 1
fi
log_success "Imagen ECR verificada"

# ==============================================================================
# Crear IAM Role para Agent Runtime
# ==============================================================================

ROLE_NAME="${AGENT_NAME}_role"
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}"

log_info "Configurando IAM Role: $ROLE_NAME"

TRUST_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "bedrock-agentcore.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF
)

if ! aws_cmd iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    log_info "Creando IAM Role..."
    aws_cmd iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Role for AgentCore Runtime ${AGENT_NAME}"
    sleep 5
else
    log_info "Role existe, actualizando trust policy..."
    aws_cmd iam update-assume-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-document "$TRUST_POLICY" 2>/dev/null || true
fi

# Política para el agente
AGENT_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "BedrockInvoke",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": ["arn:aws:bedrock:${AWS_REGION}::foundation-model/*"]
        },
        {
            "Sid": "LambdaInvoke",
            "Effect": "Allow",
            "Action": ["lambda:InvokeFunction"],
            "Resource": ["arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:*"]
        },
        {
            "Sid": "ECRPull",
            "Effect": "Allow",
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability"
            ],
            "Resource": ["arn:aws:ecr:${AWS_REGION}:${AWS_ACCOUNT_ID}:repository/${ECR_REPO}"]
        },
        {
            "Sid": "ECRAuth",
            "Effect": "Allow",
            "Action": ["ecr:GetAuthorizationToken"],
            "Resource": ["*"]
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": ["arn:aws:logs:${AWS_REGION}:${AWS_ACCOUNT_ID}:*"]
        }
    ]
}
EOF
)

aws_cmd iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "${AGENT_NAME}_policy" \
    --policy-document "$AGENT_POLICY"

log_info "Esperando propagación IAM..."
sleep 15

# ==============================================================================
# Crear Agent Runtime
# ==============================================================================

log_info "Verificando Agent Runtime existente..."

RUNTIME_ID=$(aws_cmd bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimes[?name=='${AGENT_NAME}'].agentRuntimeId" \
    --output text 2>/dev/null || echo "")

if [ -n "$RUNTIME_ID" ] && [ "$RUNTIME_ID" != "None" ]; then
    log_info "Agent Runtime existe: $RUNTIME_ID"
else
    log_info "Creando Agent Runtime: $AGENT_NAME"
    
    # Configuración del runtime
    RUNTIME_CONFIG=$(cat <<EOF
{
    "agentRuntimeName": "${AGENT_NAME}",
    "description": "RAG Agent con Strands - búsqueda semántica empresarial",
    "roleArn": "${ROLE_ARN}",
    "agentRuntimeArtifact": {
        "containerConfiguration": {
            "containerUri": "${ECR_URI}"
        }
    },
    "networkConfiguration": {
        "networkMode": "PUBLIC"
    },
    "protocolConfiguration": {
        "serverProtocol": "HTTP"
    },
    "environmentVariables": {
        "LAMBDA_QUERY": "${LAMBDA_QUERY_NAME}",
        "AGENT_NAME": "${AGENT_NAME}",
        "ENVIRONMENT": "${ENVIRONMENT}"
    },
    "lifecycleConfiguration": {
        "idleRuntimeSessionTimeout": 3600,
        "maxLifetime": 28800
    }
}
EOF
)
    
    RUNTIME_RESPONSE=$(aws_cmd bedrock-agentcore-control create-agent-runtime \
        --cli-input-json "$RUNTIME_CONFIG" \
        --output json 2>&1)
    
    if echo "$RUNTIME_RESPONSE" | grep -q "agentRuntimeId"; then
        RUNTIME_ID=$(echo "$RUNTIME_RESPONSE" | grep -o '"agentRuntimeId"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
        RUNTIME_ARN=$(echo "$RUNTIME_RESPONSE" | grep -o '"agentRuntimeArn"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
        log_success "Agent Runtime creado: $RUNTIME_ID"
    else
        log_error "Error creando Agent Runtime:"
        echo "$RUNTIME_RESPONSE"
        exit 1
    fi
    
    # Esperar a que esté listo
    wait_for_status "Agent Runtime" \
        "aws_cmd bedrock-agentcore-control get-agent-runtime --agent-runtime-id $RUNTIME_ID --query 'status' --output text" \
        "READY" 120
fi

# Obtener ARN del runtime
RUNTIME_ARN=$(aws_cmd bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "$RUNTIME_ID" \
    --query 'agentRuntimeArn' \
    --output text 2>/dev/null || echo "")

log_success "Agent Runtime ARN: $RUNTIME_ARN"

# ==============================================================================
# Crear Agent Runtime Endpoint (opcional, para REST externo)
# ==============================================================================

ENDPOINT_NAME="${AGENT_NAME}_endpoint"
log_info "Verificando Endpoint: $ENDPOINT_NAME"

ENDPOINT_ID=$(aws_cmd bedrock-agentcore-control list-agent-runtime-endpoints \
    --agent-runtime-id "$RUNTIME_ID" \
    --query "agentRuntimeEndpoints[?name=='${ENDPOINT_NAME}'].id" \
    --output text 2>/dev/null || echo "")

if [ -n "$ENDPOINT_ID" ] && [ "$ENDPOINT_ID" != "None" ]; then
    log_info "Endpoint existe: $ENDPOINT_ID"
else
    log_info "Creando Endpoint..."
    
    ENDPOINT_RESPONSE=$(aws_cmd bedrock-agentcore-control create-agent-runtime-endpoint \
        --agent-runtime-id "$RUNTIME_ID" \
        --name "$ENDPOINT_NAME" \
        --description "Endpoint REST para ${AGENT_NAME}" \
        --output json 2>&1)
    
    if echo "$ENDPOINT_RESPONSE" | grep -q "agentRuntimeEndpointId"; then
        ENDPOINT_ID=$(echo "$ENDPOINT_RESPONSE" | grep -o '"agentRuntimeEndpointId"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
        log_success "Endpoint creado: $ENDPOINT_ID"
        
        wait_for_status "Endpoint" \
            "aws_cmd bedrock-agentcore-control get-agent-runtime-endpoint --agent-runtime-id $RUNTIME_ID --agent-runtime-endpoint-id $ENDPOINT_ID --query 'status' --output text" \
            "READY" 120
    else
        log_warning "No se pudo crear endpoint (puede continuar sin él)"
        echo "$ENDPOINT_RESPONSE"
    fi
fi

# ==============================================================================
# Crear Gateway (para REST/curl)
# ==============================================================================

GATEWAY_NAME="${AGENT_NAME}_gateway"
log_info "Verificando Gateway: $GATEWAY_NAME"

GATEWAY_ID=$(aws_cmd bedrock-agentcore-control list-gateways \
    --query "gateways[?name=='${GATEWAY_NAME}'].gatewayId" \
    --output text 2>/dev/null || echo "")

if [ -n "$GATEWAY_ID" ] && [ "$GATEWAY_ID" != "None" ]; then
    log_info "Gateway existe: $GATEWAY_ID"
else
    log_info "Creando Gateway para REST..."
    
    GATEWAY_RESPONSE=$(aws_cmd bedrock-agentcore-control create-gateway \
        --name "$GATEWAY_NAME" \
        --description "REST Gateway para ${AGENT_NAME}" \
        --role-arn "$ROLE_ARN" \
        --protocol-type "MCP" \
        --authorizer-type "AWS_IAM" \
        --exception-level "DEBUG" \
        --output json 2>&1)
    
    if echo "$GATEWAY_RESPONSE" | grep -q "gatewayId"; then
        GATEWAY_ID=$(echo "$GATEWAY_RESPONSE" | grep -o '"gatewayId"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4)
        log_success "Gateway creado: $GATEWAY_ID"
        
        wait_for_status "Gateway" \
            "aws_cmd bedrock-agentcore-control get-gateway --gateway-identifier $GATEWAY_ID --query 'status' --output text" \
            "READY" 60
    else
        log_warning "No se pudo crear Gateway:"
        echo "$GATEWAY_RESPONSE"
    fi
fi

# Obtener URL del Gateway
if [ -n "$GATEWAY_ID" ] && [ "$GATEWAY_ID" != "None" ]; then
    GATEWAY_URL=$(aws_cmd bedrock-agentcore-control get-gateway \
        --gateway-identifier "$GATEWAY_ID" \
        --query 'gatewayUrl' \
        --output text 2>/dev/null || echo "")
    
    log_success "Gateway URL: $GATEWAY_URL"
fi

# ==============================================================================
# Resumen
# ==============================================================================

echo ""
echo "=============================================================================="
echo -e "${GREEN}¡Agent Runtime desplegado exitosamente!${NC}"
echo "=============================================================================="
echo ""
INVOKE_URL="https://bedrock-agentcore.${AWS_REGION}.amazonaws.com/runtimes/${RUNTIME_ARN}/invocations"

echo "Recursos creados:"
echo "  Agent Name:     $AGENT_NAME"
echo "  Runtime ID:     $RUNTIME_ID"
echo "  Runtime ARN:    $RUNTIME_ARN"
echo "  Invoke URL:     $INVOKE_URL"
echo "  Endpoint ID:    ${ENDPOINT_ID:-N/A}"
echo "  Gateway ID:     ${GATEWAY_ID:-N/A}"
echo "  ECR Image:      $ECR_URI"
echo "  IAM Role:       $ROLE_NAME"
echo ""
echo "=============================================================================="
echo "Invocar el agente:"
echo "=============================================================================="
echo ""
cat <<EOF
# Invocar via AWS CLI
aws bedrock-agentcore invoke-agent-runtime \\
    --agent-runtime-arn "${RUNTIME_ARN}" \\
    --content-type "application/json" \\
    --payload '{
        "prompt": "¿Cuáles son los lineamientos de arquitectura?",
        "tenant_id": "asap",
        "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
    }' \\
    --profile ${AWS_PROFILE} \\
    --region ${AWS_REGION} \\
    /tmp/agent-response.json

cat /tmp/agent-response.json
EOF

echo ""
echo "=============================================================================="
echo "Invocar con Python:"
echo "=============================================================================="
echo ""
cat <<EOF
import boto3
import json

client = boto3.client('bedrock-agentcore', region_name='${AWS_REGION}')

response = client.invoke_agent_runtime(
    agentRuntimeArn='${RUNTIME_ARN}',
    contentType='application/json',
    payload=json.dumps({
        'prompt': '¿Cuáles son los lineamientos de arquitectura?',
        'tenant_id': 'asap',
        'agent_id': 'd8c38f93-f4cd-4a85-9c31-297d14ce7009'
    })
)

# Leer respuesta streaming
for event in response['body']:
    print(event, end='')
EOF

# Construir URL de invocación
INVOKE_URL="https://bedrock-agentcore.${AWS_REGION}.amazonaws.com/runtimes/${RUNTIME_ARN}/invocations"

echo ""
echo "=============================================================================="
echo "Invocar con CURL:"
echo "=============================================================================="
echo ""
echo "URL de Invocación: $INVOKE_URL"
echo ""
cat <<EOF
# OPCIÓN 1: Usando awscurl (firma automática SigV4)
pip install awscurl

awscurl --service bedrock-agentcore \\
    --region ${AWS_REGION} \\
    --profile ${AWS_PROFILE} \\
    -X POST "${INVOKE_URL}" \\
    -H "Content-Type: application/json" \\
    -d '{
        "prompt": "¿Cuáles son los lineamientos de arquitectura?",
        "tenant_id": "asap",
        "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
    }'

# OPCIÓN 2: Usando curl normal (necesita token de sesión)
# Primero obtener credenciales temporales
export AWS_ACCESS_KEY=\$(aws configure get aws_access_key_id --profile ${AWS_PROFILE})
export AWS_SECRET_KEY=\$(aws configure get aws_secret_access_key --profile ${AWS_PROFILE})

# Usar el siguiente script Python para firmar la request:
python3 << 'PYTHON'
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import json

session = boto3.Session(profile_name='${AWS_PROFILE}', region_name='${AWS_REGION}')
credentials = session.get_credentials()

url = "${INVOKE_URL}"
payload = json.dumps({
    "prompt": "¿Cuáles son los lineamientos de arquitectura?",
    "tenant_id": "asap",
    "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
})

request = AWSRequest(method='POST', url=url, data=payload, headers={'Content-Type': 'application/json'})
SigV4Auth(credentials, 'bedrock-agentcore', '${AWS_REGION}').add_auth(request)

response = requests.post(url, headers=dict(request.headers), data=payload)
print(response.text)
PYTHON
EOF

echo ""
echo "=============================================================================="
echo "Ver logs:"
echo "=============================================================================="
echo ""
echo "aws logs tail /aws/bedrock-agentcore/${AGENT_NAME} --follow --profile ${AWS_PROFILE} --region ${AWS_REGION}"
echo ""
echo "=============================================================================="
echo "Consola AWS:"
echo "=============================================================================="
echo ""
echo "https://${AWS_REGION}.console.aws.amazon.com/bedrock/home?region=${AWS_REGION}#/agentcore/runtimes/${RUNTIME_ID}"
echo ""

# Guardar config
cat > "/tmp/agentcore-${ENVIRONMENT}.conf" <<EOF
RUNTIME_ID=${RUNTIME_ID}
RUNTIME_ARN=${RUNTIME_ARN}
INVOKE_URL=${INVOKE_URL}
ENDPOINT_ID=${ENDPOINT_ID}
GATEWAY_ID=${GATEWAY_ID}
AGENT_NAME=${AGENT_NAME}
ECR_URI=${ECR_URI}
EOF
log_info "Config guardada en /tmp/agentcore-${ENVIRONMENT}.conf"

#!/bin/bash
# Script de despliegue para Amazon Bedrock AgentCore

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Despliegue de RAG Agent en Bedrock AgentCore ===${NC}"

# Verificar que agentcore CLI esté instalado
if ! command -v agentcore &> /dev/null; then
    echo -e "${YELLOW}Instalando agentcore CLI...${NC}"
    pip install bedrock-agentcore
fi

# Verificar credenciales AWS
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo -e "${YELLOW}Advertencia: Variables AWS no configuradas. Usando perfil por defecto.${NC}"
fi

# Configurar región
AWS_REGION=${AWS_REGION:-us-east-1}
echo -e "${GREEN}Región AWS: ${AWS_REGION}${NC}"

# Paso 1: Configurar el agente
echo -e "\n${GREEN}[1/3] Configurando agente...${NC}"
agentcore configure \
    -e agentcore_handler.py \
    --protocol MCP \
    --region $AWS_REGION

# Paso 2: Construir y publicar imagen Docker
echo -e "\n${GREEN}[2/3] Construyendo imagen Docker...${NC}"
agentcore build

# Paso 3: Lanzar el agente
echo -e "\n${GREEN}[3/3] Desplegando agente...${NC}"
agentcore launch

echo -e "\n${GREEN}=== Despliegue completado ===${NC}"
echo -e "${YELLOW}Para probar el agente, ejecuta: python test_agent.py${NC}"



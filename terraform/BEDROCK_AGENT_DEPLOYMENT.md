# Despliegue del Agente RAG en Bedrock Agent Core con API Gateway y JWT

Este documento describe cómo desplegar el agente RAG en AWS Bedrock Agent Core y exponerlo mediante una API Gateway asegurada con autenticación JWT usando Cognito.

## Arquitectura

```
API Gateway (JWT Auth) → Lambda Handler → Bedrock Agent Core → RAG Tools
                                                              ↓
                                                         Lambda Query
                                                         Lambda Embeddings
```

## Componentes

1. **Bedrock Agent Core**: Agente desplegado en AWS Bedrock que utiliza el framework Strands
2. **Lambda Handler**: Función Lambda que procesa las peticiones del agente
3. **API Gateway**: API HTTP con autenticación JWT mediante Cognito
4. **Cognito User Pool**: Servicio de autenticación para generar tokens JWT

## Configuración

### Variables Requeridas

Las siguientes variables deben configurarse en tu archivo `.tfvars`:

```hcl
# Configuración básica
environment = "dev"
region      = "us-east-1"
aws_profile = "your-profile"

# Red
vpc_id  = "vpc-xxxxx"
subnets = ["subnet-xxxxx", "subnet-yyyyy"]

# Base de datos
master_username = "postgres"
master_password = "your-secure-password"

# Agente
agent_name    = "rag-agent"
agent_model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# API Gateway
create_cognito_user_pool = true
cors_allowed_origins     = ["https://yourdomain.com"]
```

### Variables Opcionales

```hcl
# Si ya tienes un Cognito User Pool existente
create_cognito_user_pool     = false
cognito_user_pool_id         = "us-east-1_xxxxx"
cognito_user_pool_client_id  = "xxxxx"
cognito_user_pool_arn        = "arn:aws:cognito-idp:us-east-1:xxxxx:userpool/us-east-1_xxxxx"

# Variables de entorno adicionales para el agente
agent_environment_variables = {
  CUSTOM_VAR = "value"
}
```

## Despliegue

1. **Inicializar Terraform**:
```bash
cd terraform
terraform init
```

2. **Planificar el despliegue**:
```bash
terraform plan -var-file=environments/dev.tfvars
```

3. **Aplicar los cambios**:
```bash
terraform apply -var-file=environments/dev.tfvars
```

## Uso de la API

### 1. Obtener Token JWT

Si creaste un nuevo Cognito User Pool, primero necesitas crear un usuario:

```bash
# Crear usuario
aws cognito-idp admin-create-user \
  --user-pool-id <COGNITO_USER_POOL_ID> \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com \
  --message-action SUPPRESS

# Establecer contraseña temporal
aws cognito-idp admin-set-user-password \
  --user-pool-id <COGNITO_USER_POOL_ID> \
  --username user@example.com \
  --password "TempPassword123!" \
  --permanent
```

Obtener token JWT:

```bash
TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <COGNITO_USER_POOL_CLIENT_ID> \
  --auth-parameters USERNAME=user@example.com,PASSWORD=TempPassword123! \
  --query 'AuthenticationResult.IdToken' \
  --output text)
```

### 2. Invocar la API

```bash
curl -X POST https://<API_GATEWAY_ENDPOINT>/<ENVIRONMENT>/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "¿Cuáles son los lineamientos de arquitectura?",
    "tenant_id": "your_tenant",
    "agent_id": "your_agent_id"
  }'
```

### 3. Respuesta Esperada

```json
{
  "statusCode": 200,
  "result": "Respuesta del agente basada en la base de conocimiento...",
  "tenant_id": "your_tenant",
  "agent_id": "your_agent_id"
}
```

## Outputs de Terraform

Después del despliegue, Terraform proporcionará los siguientes outputs:

- `api_gateway_endpoint`: URL completa del endpoint de la API
- `api_gateway_id`: ID de la API Gateway
- `cognito_user_pool_id`: ID del User Pool de Cognito
- `cognito_user_pool_client_id`: ID del cliente de Cognito
- `bedrock_agent_id`: ID del agente de Bedrock
- `bedrock_agent_arn`: ARN del agente de Bedrock

Para ver todos los outputs:

```bash
terraform output
```

## Seguridad

### JWT Authentication

La API está protegida con autenticación JWT mediante AWS Cognito. Cada petición debe incluir un token JWT válido en el header `Authorization`:

```
Authorization: Bearer <JWT_TOKEN>
```

### CORS

La configuración de CORS se puede ajustar mediante la variable `cors_allowed_origins`. Por defecto, permite todos los orígenes (`*`), pero en producción deberías restringirlo a tus dominios específicos.

### IAM Permissions

El agente Lambda tiene los siguientes permisos:
- Invocar modelos de Bedrock
- Invocar la Lambda de query RAG
- Acceso a CloudWatch Logs
- Acceso a VPC (si está configurado)

## Troubleshooting

### Error: "Unauthorized"
- Verifica que el token JWT sea válido y no haya expirado
- Asegúrate de incluir el header `Authorization: Bearer <token>`

### Error: "Lambda timeout"
- Aumenta el timeout de la Lambda en la configuración
- Verifica que las Lambdas de RAG estén funcionando correctamente

### Error: "Bedrock model not found"
- Verifica que el modelo esté disponible en tu región
- Asegúrate de que el agente tenga permisos para invocar el modelo

## Monitoreo

### CloudWatch Logs

Los logs están disponibles en:
- Lambda Handler: `/aws/lambda/rag-agent-<environment>`
- API Gateway: `/aws/apigateway/rag-agent-api-<environment>`

### Métricas

Las métricas de API Gateway están disponibles en CloudWatch:
- Número de peticiones
- Latencia
- Errores 4xx/5xx
- Throttling

## Costos

Los principales costos asociados son:
- **API Gateway**: $3.50 por millón de peticiones
- **Lambda**: Basado en invocaciones y duración
- **Bedrock**: Basado en tokens procesados
- **Cognito**: Gratis hasta 50,000 MAU (Monthly Active Users)

## Referencias

- [AWS Bedrock Agent Core Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [API Gateway JWT Authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)
- [AWS Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)






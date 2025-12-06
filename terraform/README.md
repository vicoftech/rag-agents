# RAG Agents - Terraform Infrastructure

Infraestructura como código para desplegar las Lambdas RAG y recursos asociados en AWS.

## 📁 Estructura

```
terraform/
├── main.tf                    # Configuración principal
├── variables.tf               # Definición de variables
├── outputs.tf                 # Outputs del deployment
├── environments/
│   ├── asap_main.tfvars       # Config para ambiente dev
│   └── prod.tfvars.example    # Ejemplo para producción
├── modules/
│   ├── aurora_postgres/       # Módulo Aurora PostgreSQL
│   ├── lambda/                # Módulo Lambda genérico
│   └── s3_documents/          # Módulo S3 para documentos
└── scripts/
    ├── deploy.sh              # Script de deploy
    └── build-lambdas.sh       # Script de build
```

## 🚀 Quick Start

### Prerrequisitos

1. **AWS CLI** configurado con credenciales
2. **Terraform** >= 1.3.0
3. **Python** >= 3.12 (para build de lambdas)

### Deployment

```bash
# 1. Ir al directorio de terraform
cd terraform

# 2. Inicializar Terraform
terraform init

# 3. Crear/seleccionar workspace
terraform workspace new dev  # o: terraform workspace select dev

# 4. Ver plan de cambios
terraform plan -var-file=environments/asap_main.tfvars

# 5. Aplicar cambios
terraform apply -var-file=environments/asap_main.tfvars
```

### Usando el script de deploy

```bash
# Ver plan
./scripts/deploy.sh plan -e dev

# Aplicar cambios
./scripts/deploy.sh apply -e dev

# Aplicar con auto-approve
./scripts/deploy.sh apply -e dev -y

# Destruir recursos
./scripts/deploy.sh destroy -e dev
```

## 📦 Recursos Creados

### Lambdas

| Lambda | Descripción | Trigger |
|--------|-------------|---------|
| `rag_lmbd_embeddings` | Procesa PDFs, genera embeddings y guarda en PostgreSQL | S3 (*.pdf) |
| `rag_lmbd_query` | Búsqueda semántica + respuesta LLM | Invocación directa |

### Otros Recursos

- **S3 Bucket**: Para almacenar documentos PDF
- **Aurora PostgreSQL**: Base de datos con pgvector
- **IAM Roles**: Permisos para cada Lambda
- **Security Groups**: Acceso a RDS desde Lambdas
- **CloudWatch Log Groups**: Logs de las Lambdas

## ⚙️ Variables de Configuración

### Generales

| Variable | Descripción | Default |
|----------|-------------|---------|
| `region` | Región de AWS | `us-east-1` |
| `aws_profile` | Perfil de AWS CLI | - |
| `environment` | Ambiente (dev/staging/prod) | - |

### Red

| Variable | Descripción |
|----------|-------------|
| `vpc_id` | ID de la VPC |
| `subnets` | Lista de subnets (privadas recomendadas) |

### Aurora PostgreSQL

| Variable | Descripción | Default |
|----------|-------------|---------|
| `master_username` | Usuario admin | - |
| `master_password` | Password admin | - |
| `engine_version` | Versión de PostgreSQL | `14.11` |
| `aurora_min_capacity` | ACUs mínimos | `0.5` |
| `aurora_max_capacity` | ACUs máximos | `4` |

### Modelos Bedrock

| Variable | Descripción | Default |
|----------|-------------|---------|
| `embeddings_model` | Modelo para embeddings | `cohere.embed-v4:0` |
| `main_llm_model` | Modelo LLM principal | `claude-3-5-sonnet` |
| `fallback_llm_model` | Modelo LLM fallback | `claude-3-haiku` |

## 🔐 Seguridad

### Recomendaciones para Producción

1. **Secrets Manager**: Usar para credenciales de BD
   ```hcl
   # En lugar de:
   master_password = "plain_text_password"
   
   # Usar:
   master_password = data.aws_secretsmanager_secret_version.db.secret_string
   ```

2. **Subnets Privadas**: Las Lambdas deben estar en subnets privadas con NAT Gateway

3. **Security Groups**: Restringir CIDR blocks en lugar de `0.0.0.0/0`

4. **S3 Bucket Policy**: Restringir acceso al bucket de documentos

5. **VPC Endpoints**: Considerar endpoints para S3, Bedrock para reducir costos

## 📊 Arquitectura

```
                                    ┌─────────────────────┐
                                    │    S3 Bucket        │
                                    │  (rag-documents-*)  │
                                    └─────────┬───────────┘
                                              │ S3 Event
                                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              VPC                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        Private Subnets                           │   │
│  │                                                                  │   │
│  │  ┌──────────────────────┐      ┌──────────────────────┐        │   │
│  │  │  Lambda              │      │  Lambda              │        │   │
│  │  │  rag_lmbd_embeddings │      │  rag_lmbd_query      │        │   │
│  │  │                      │      │                      │        │   │
│  │  │  • PDF Processing    │      │  • Semantic Search   │        │   │
│  │  │  • Embeddings Gen    │      │  • LLM Response      │        │   │
│  │  │  • Store in DB       │      │  • Query Embeddings  │        │   │
│  │  └──────────┬───────────┘      └──────────┬───────────┘        │   │
│  │             │                             │                     │   │
│  │             └──────────────┬──────────────┘                     │   │
│  │                            │                                    │   │
│  │                            ▼                                    │   │
│  │             ┌──────────────────────────┐                       │   │
│  │             │    Aurora PostgreSQL     │                       │   │
│  │             │    (with pgvector)       │                       │   │
│  │             └──────────────────────────┘                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                    │                           │
                    ▼                           ▼
          ┌─────────────────┐         ┌─────────────────┐
          │ Amazon Bedrock  │         │ Amazon Textract │
          │ (Embeddings/LLM)│         │ (PDF OCR)       │
          └─────────────────┘         └─────────────────┘
```

## 🧪 Testing

### Subir un documento

```bash
# Estructura: s3://bucket/tenant_id/agent_id/filename.pdf
aws s3 cp documento.pdf s3://rag-documents-dev-123456789012/tenant_asap/agent_123/documento.pdf
```

### Invocar Lambda de Query

```bash
aws lambda invoke \
  --function-name rag_lmbd_query-dev \
  --payload '{"query": "¿Qué es arquitectura hexagonal?", "tenant_id": "tenant_asap", "agent_id": "agent_123"}' \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
```

### Ver logs

```bash
# Logs de embeddings
aws logs tail /aws/lambda/rag_lmbd_embeddings-dev --follow

# Logs de query
aws logs tail /aws/lambda/rag_lmbd_query-dev --follow
```

## 🔄 CI/CD

### GitHub Actions (ejemplo)

```yaml
name: Deploy Infrastructure

on:
  push:
    branches: [main]
    paths:
      - 'terraform/**'
      - 'apps/rag_lmbd_*/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.6.0
      
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      
      - name: Terraform Init
        run: terraform init
        working-directory: terraform
      
      - name: Terraform Plan
        run: terraform plan -var-file=environments/prod.tfvars
        working-directory: terraform
      
      - name: Terraform Apply
        if: github.ref == 'refs/heads/main'
        run: terraform apply -var-file=environments/prod.tfvars -auto-approve
        working-directory: terraform
```

## 🛠️ Troubleshooting

### Lambda no puede conectar a RDS

1. Verificar que la Lambda está en la misma VPC que Aurora
2. Verificar que el Security Group permite tráfico en puerto 5432
3. Verificar que las subnets tienen acceso a internet (NAT Gateway)

### Lambda timeout procesando PDF

1. Aumentar `timeout` en la configuración (máx 900s)
2. Aumentar `memory_size` para PDFs grandes
3. Verificar tamaño del PDF y considerar chunking

### Error de permisos Bedrock

1. Verificar que el modelo está habilitado en la cuenta
2. Verificar la política IAM incluye el modelo correcto
3. Verificar la región del modelo

## 📝 Notas

- Los workspaces de Terraform permiten manejar múltiples ambientes
- El state de Terraform se guarda localmente por defecto
- Para producción, configurar backend S3 para el state

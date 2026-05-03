# RAG Agents - Terraform Infrastructure

Infraestructura como código para desplegar las Lambdas RAG y recursos asociados en AWS.

## 📁 Estructura

```
terraform/
├── main.tf                    # Configuración principal
├── variables.tf               # Definición de variables
├── outputs.tf                 # Outputs del deployment
├── bootstrap/                 # Crea bucket S3 + DynamoDB para estado remoto (una vez por cuenta)
├── environments/
│   ├── asap_main.tfvars       # Config histórica (otra cuenta / referencia)
│   ├── asap_dev_615.tfvars    # Instalación limpia cuenta 615216531593 + perfil asap_dev
│   └── prod.tfvars.example    # Ejemplo para producción
├── modules/
│   ├── aurora_postgres/       # Módulo Aurora PostgreSQL
│   ├── lambda/                # Módulo Lambda genérico
│   └── s3_documents/          # Módulo S3 para documentos
└── scripts/
    ├── deploy.sh              # Script de deploy
    └── build-lambdas.sh       # Script de build
```

## Estado remoto Terraform (S3 + DynamoDB)

El `backend "s3"` en `main.tf` usa:

- **Bucket:** `rag-agents-terraform-state-615216531593`
- **Tabla locks:** `rag-agents-terraform-locks`
- **Perfil backend:** `asap_dev` (ajustar en `main.tf` si cambiás de perfil)

**Primera vez en la cuenta:** crear bucket y tabla con estado **local**:

```bash
cd terraform/bootstrap
terraform init
terraform apply -auto-approve
```

Luego en `terraform/`:

```bash
terraform init -reconfigure
terraform apply -var-file=environments/asap_dev_615.tfvars
```

Para instalación limpia, no migrar un `terraform.tfstate` viejo de otra cuenta; el estado vive solo en S3.

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
| `rag_lmbd_embeddings-async` | Procesa PDFs (consume SQS), genera embeddings y guarda en PostgreSQL | SQS (ingesta desde S3 vía encolador) |
| `rag_lmbd_query` | Búsqueda semántica + respuesta LLM | Invocación directa |
| `rag_lmbd_obtener_alertas` | Obtiene alertas activas desde PostgreSQL | Invocación directa / API |

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
│  │  │ rag_lmbd_embeddings-async   │  rag_lmbd_query     │        │   │
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
aws logs tail /aws/lambda/rag_lmbd_embeddings-async-dev --follow

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

## 📧 Alertas documentales (RAG) y notificaciones por correo

Flujo operativo usado para validar matches de corpus (ANMAT / boletín) y encolar envíos de mail sin tocar destinatarios productivos.

### Script `scripts/alerts_semantic_matches.py`

- Invoca `rag_lmbd_obtener_alertas` y, por cada alerta, `rag_lmbd_query` (búsqueda semántica + LLM).
- Genera un JSON con `corridas[].resultados` (o `resultados`) y un array `notificaciones` por cada alerta con chunks recuperados.

**Modo prueba (destinatario único):**

- `--testing-email usuario@dominio.com` — Sustituye en cada resultado `mail`, `cuenta.mail` y `destinatarios` por ese correo, y deja traza en `meta.testing_email_override` y `meta.testing_email`. Así los mensajes publicados en SQS llevan `message.to` solo a esa dirección (no a clientes productivos).
- Requiere que el correo contenga `@` (validación del CLI).

**Publicación a la cola de emails:**

- `--publish-email-queue` — Tras escribir `-o/--output`, envía un mensaje SQS por notificación (JSON UTF-8).
- Cola por defecto: `email-sender-record-email-processor-prod` (sobrescribible con `--email-sqs-queue QUEUE_NAME`).
- Para generar el archivo sin enviar: `--publish-email-queue` junto con `--no-email-queue-send`.

**Ejemplos (prod, perfil `asap_main`, región `us-east-1`):**

```bash
# ANMAT: ventana de fechas created_at (UTC civil) + testing email + cola
python3 scripts/alerts_semantic_matches.py \
  --profile asap_main --env prod \
  --corrida anmat=scripts/anmat_map.json \
  --s3-bucket rag-documents-prod-913123310997 \
  --max-semantic-distance 0.30 \
  --created-at-start 2026-04-26 \
  --created-at-end 2026-05-02 \
  --testing-email alguien@asap-consulting.net \
  -o alerts_anmat_run.json \
  --publish-email-queue
```

```bash
# Boletín oficial (misma idea; mapa tenant_boletin)
python3 scripts/alerts_semantic_matches.py \
  --profile asap_main --env prod \
  --corrida boletin=scripts/boletin_map.json \
  --s3-bucket rag-documents-prod-913123310997 \
  --max-semantic-distance 0.30 \
  --created-at-start 2026-04-26 \
  --created-at-end 2026-05-02 \
  --testing-email alguien@asap-consulting.net \
  -o alerts_boletin_run.json \
  --publish-email-queue
```

Las Lambdas en prod siguen el naming `rag_lmbd_obtener_alertas-prod` y `rag_lmbd_query-prod` (según `--env prod`).

### Template SES `alert_aviso`

El consumidor de la cola suele armar el envío con **Amazon SES** usando un template. En este proyecto el nombre del template es **`alert_aviso`** (no existe `alerta_aviso` en SES).

**Placeholders usados en el cuerpo/asunto:** `{{ nombre_alerta }}`, `{{ keywords }}`, `{{ url }}` (en SES van con espacios alrededor del nombre, según el template cargado).

**Descargar el template actual a JSON (para revisión o backup):**

```bash
aws ses get-template \
  --template-name alert_aviso \
  --profile asap_main \
  --region us-east-1 \
  --output json > ses_template_alert_aviso_from_ses.json
```

**Subir de nuevo un archivo en formato `GetTemplate` / `update-template` (objeto raíz `Template` con `TemplateName`, `SubjectPart`, `TextPart`, `HtmlPart`):**

```bash
aws ses update-template \
  --cli-input-json file://ses_template_alert_aviso_from_ses.json \
  --profile asap_main \
  --region us-east-1
```

En el repositorio se mantiene una copia de referencia en la raíz: `ses_template_alert_aviso_from_ses.json` (sincronizar con SES cuando se editen asunto o HTML).

## ⏰ Step Functions Boletín / ANMAT (horario diario)

Módulo Terraform `modules/scheduled_boletin_anmat_sfn`: **EventBridge Scheduler** llama a una Lambda que hace `states:StartExecution`.

| Horario (TZ `scheduled_sync_timezone`, default Buenos Aires) | Corpus | Comportamiento |
|-------------------------------------------------------------|--------|----------------|
| **09:00** | Boletín | Para **ayer** y **hoy** (civil en esa TZ), una ejecución SFN por cada sección (`primera`…`cuarta`). Misma carga útil que `scripts/boletin_syncronizer_invoker.py`. |
| **09:30** | ANMAT | **Una** ejecución del SFN `rag-anmat-to-s3writer-*` con `year` = año civil actual (o `anmat_year_override`) y rango de páginas configurable (`anmat_page_start` / `anmat_page_end`, default 1–15). |

**Criterio “hoy y ayer”:** aplica de forma literal al **Boletín** (dos fechas en el payload `date`). El SFN de **ANMAT** hoy sólo acepta **año + páginas** en la Lambda anmatlinks; no hay filtro por fecha de norma en el ASL. Para alinear ANMAT a un rango calendario habría que extender la Lambda/SFN.

**Activar en `terraform apply`:** en el `.tfvars` correspondiente:

```hcl
enable_scheduled_boletin_anmat_sfn = true
# Opcional: UUIDs agente RAG si difieren del default
# scheduled_boletin_rag_agent_id = "..."
# scheduled_anmat_rag_agent_id = "..."
```

Archivos: `terraform/scheduled_boletin_anmat_sfn.tf`, variables `enable_scheduled_*`, outputs `scheduled_boletin_anmat_*`.

## 📝 Notas

- Los workspaces de Terraform permiten manejar múltiples ambientes
- El state de Terraform se guarda localmente por defecto
- Para producción, configurar backend S3 para el state

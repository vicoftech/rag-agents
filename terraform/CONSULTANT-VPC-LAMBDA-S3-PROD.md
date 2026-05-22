# Características VPC, subredes, S3 y Lambda (prod) — referencia para consultor

Resumen de **entorno prod** (`environments/prod.tfvars` + lectura AWS), centrado en **`rag_lmbd_embeddings-async-prod`** y el bucket de documentos.

---

## Cuenta y región

| Campo   | Valor        |
|---------|--------------|
| Región  | `us-east-1`  |
| Cuenta  | `913123310997` (por nombre de bucket / ARNs) |

---

## VPC

| Campo    | Valor                    |
|----------|--------------------------|
| **VPC ID** | `vpc-0220b63692086a550` |
| **CIDR**   | `10.0.0.0/16`           |

Uso: VPC **compartida** con **Aurora existente** (`postgres-aurora-prod`). En prod, Terraform **no** crea la VPC ni el cluster Aurora (`create_aurora_cluster = false`).

---

## Subredes donde corre la Lambda (`rag_lmbd_embeddings-async-prod`)

Todas **privadas** (`MapPublicIpOnLaunch = false`), en **tres AZ**:

| Subnet ID              | AZ        | CIDR         | Nombre (tag)                        |
|------------------------|-----------|--------------|-------------------------------------|
| `subnet-09808b125e81feda6` | us-east-1a | 10.0.1.0/24 | vpc-principal-private-us-east-1a  |
| `subnet-04cc462043523dcb9` | us-east-1b | 10.0.2.0/24 | vpc-principal-private-us-east-1b  |
| `subnet-0254c9d900c8b2fdc` | us-east-1c | 10.0.3.0/24 | vpc-principal-private-us-east-1c  |

**Enrutamiento (relevante):** en esta VPC las tablas de ruta asociadas a esas subredes suelen incluir:

- `0.0.0.0/0` → **NAT Gateway** (salida HTTPS genérica / Internet)
- Prefijo **S3** (pl-*) → **VPC Gateway Endpoint** hacia el endpoint S3 de la cuenta

---

## Security group de las Lambdas RAG (incl. embeddings)

| Campo        | Valor (referencia; el ID se recrea si se destruye el stack) |
|--------------|--------------------------------------------------------------|
| **Nombre**   | `rag-lambda-prod-sg`                                         |
| **Descripción** | RAG Lambdas en VPC: egress a APIs AWS (S3 gateway, Bedrock, Secrets, Textract) |
| **Egress**   | Todo el tráfico IPv4 a `0.0.0.0/0` (HTTPS / APIs)          |
| **Ingress a Postgres** | Regla gestionada por Terraform: tráfico desde este SG hacia el SG de Aurora (puerto **5432**) |

---

## S3 (documentos + disparo de Lambda)

| Campo | Valor |
|--------|--------|
| **Bucket (prod)** | `rag-documents-prod-913123310997` (patrón Terraform: `rag-documents-${environment}-${account_id}`) |
| CORS (prod) | Deshabilitado (`enable_s3_cors = false`) |
| **Notificación** | `s3:ObjectCreated:*` filtrado por sufijo **`.pdf`** → encolador, luego SQS → `rag_lmbd_embeddings-async` |
| **IAM Lambda** | `s3:GetObject` / `s3:ListBucket` sobre bucket y prefijos de paquetes de despliegue |
| **Key de ejemplo (negocio)** | `tenant_*/<agent-uuid>/documents/.../*.pdf` |

**Flags Terraform en bucket (reset / destroy):** variable `s3_bucket_force_destroy` (default `false`); solo `true` para `terraform destroy` con bucket con objetos.

---

## Función `rag_lmbd_embeddings-async-prod`

### Parámetros

| Parámetro | Definido en `environments/prod.tfvars` | Nota |
|-----------|----------------------------------------|------|
| Timeout   | 900 s (p. ej. `prod.tfvars`)           | Verificar drift en consola / `get-function-configuration` |
| Memoria   | 1024 MB                                | |
| Ephemeral | 1024 MB                                | |
| Runtime   | python3.12 (módulo Lambda)             | |

### Concurrencia

En Terraform: `lambda_embeddings_sqs_concurrency = 2`, `lambda_embeddings_reserved_concurrency = 4`, `EMBED_BATCH_SIZE = "2"`. **Comprobar en AWS** con `get-function-concurrency` y el `ScalingConfig` del event source mapping SQS.

### Variables de entorno S3 (cliente boto3 / `prod.tfvars`)

| Variable | Uso típico en prod (tfvars) |
|----------|-----------------------------|
| `S3_USE_REGIONAL_ENDPOINT` | `1` — endpoint regional explícito |
| `S3_CONNECT_TIMEOUT` | `15` |
| `S3_READ_TIMEOUT` | `60` |
| `S3_MAX_ATTEMPTS` | `4` |
| `S3_RETRY_MODE` | `standard` |

Credenciales DB: `DB_SECRET_ID` + `base_db_env_vars` (host, puerto, etc.) según `prod.tfvars`.

### Configuración Terraform relevante (prod)

- `create_vpc_endpoint_s3 = false` — el Gateway S3 **ya existe** en la VPC.
- `create_vpc_endpoint_bedrock = false` — el endpoint Bedrock **ya existe** (evitar duplicados / DNS).
- `create_vpc_endpoint_secrets_textract = true` — **Interface** para Secrets Manager y Textract (gestionado por este proyecto).
- Módulo `s3_vpce_subnet_route_table_associations`: asocia tablas de ruta de `var.subnets` al **Gateway S3 existente** si falta alguna asociación.

---

## VPC endpoints en la VPC (ejemplo de IDs vistos en la cuenta)

| Tipo | Servicio | ID (ejemplo) |
|------|----------|----------------|
| Gateway | `com.amazonaws.us-east-1.s3` | `vpce-0ff53429a66a1dabb` |
| Interface | `com.amazonaws.us-east-1.bedrock-runtime` | `vpce-033b6996a681739c1` |
| Interface | `com.amazonaws.us-east-1.secretsmanager` | `vpce-0f3c193be1d63db23` |
| Interface | `com.amazonaws.us-east-1.textract` | `vpce-00e3074090fd91e1d` |

Los IDs pueden cambiar si se destruyen y recrean recursos; validar con:

`aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=vpc-0220b63692086a550`

---

## Puntos a revisar con el consultor

1. **Drift Lambda:** timeout y reservas de concurrencia en **AWS** vs **Terraform** (`prod.tfvars` + módulo).
2. **Ruta de red:** subredes privadas + **NAT** + **Gateway S3**; el SDK S3 usa endpoint regional configurable.
3. **Tras un `terraform destroy` / `apply` completo:** URLs de **API Gateway** y **Cognito** cambian; clientes deben actualizar endpoints e IDs de pool/cliente.
4. **Aurora** no se destruye con este stack en prod; el **SG de la base** y el **endpoint** siguen siendo los de la cuenta.

---

## Comandos útiles de verificación

```bash
# Lambda: VPC, timeout, memoria
aws lambda get-function-configuration \
  --function-name rag_lmbd_embeddings-async-prod \
  --region us-east-1 --profile asap_main

# Subredes
aws ec2 describe-subnets \
  --subnet-ids subnet-04cc462043523dcb9 subnet-0254c9d900c8b2fdc subnet-09808b125e81feda6 \
  --region us-east-1 --profile asap_main

# Endpoints en la VPC
aws ec2 describe-vpc-endpoints \
  --filters Name=vpc-id,Values=vpc-0220b63692086a550 \
  --region us-east-1 --profile asap_main
```

---

*Generado a partir de la configuración del repositorio `rag-agents` (rama de trabajo) y del entorno prod. Ajustar IDs si el consultor trabaja sobre otro workspace o cuenta.*

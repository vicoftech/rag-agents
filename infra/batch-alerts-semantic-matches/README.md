# Batch programado: `alerts_semantic_matches.py` (Fargate + EventBridge Scheduler)

Dos tareas diarias en **prod**:

| Horario (ART, UTC−3) | Corrida SQS / script |
|----------------------|----------------------|
| **10:30** | Sólo **ANMAT** (`--corrida anmat=scripts/anmat_map.json`) |
| **11:00** | Sólo **Boletín** (`--corrida boletin=scripts/boletin_map.json`) |

EventBridge Scheduler usa **UTC**: `13:30` y `14:00` UTC respectivamente (sin DST en Argentina).

Parámetros del contenedor (`batch/alerts-semantic-matches/entrypoint.sh` + env en `ecs.tf`):

- `--profile ""` (credenciales del **task role**)
- `--env prod`, `--corrida` según `BATCH_CORRIDA`, `--s3-bucket` desde `S3_DOCUMENTS_BUCKET`
- `--parallel` desde `batch_parallel_*` en Terraform
- Opcionales: `--no-created-at-filter`, `--trace-lambda-payloads`, `--include-zero-chunk-resultados`, `--testing-email` (solo si `batch_testing_email`), o `--testing-email-to` / `--testing-email-cc` vía env `BATCH_TESTING_EMAIL_TO` / `BATCH_TESTING_EMAIL_CC` en `ecs.tf` (`batch_testing_email_to` / `batch_testing_email_cc`). Default vacío = destinatarios reales en `busqueda`.
- **`--publish-email-queue` / `--publish-alert-creation-queue`** si `batch_publish_email_queue` / `batch_publish_alert_creation_queue` son `true` (default)
- Salida en `/tmp/alerts_matches_prod_fullcorpus_<UTC>.json` dentro del contenedor (`-o` requerido para publicar a colas)

## Requisitos

- Docker, Terraform ≥ 1.5, AWS CLI con permisos de admin o equivalente.
- VPC con salida estable a **ECR** y **CloudWatch Logs** desde las subnets donde corre Fargate: NAT + rutas válidas **o**, en la misma cuenta/VPC que el proyecto RAG, aplicar **`create_vpc_endpoint_ecr_logs = true`** en el Terraform raíz (`terraform/`): crea VPC endpoints Interface para **`ecr.api`**, **`ecr.dkr`** y **`logs`**, más un SG que permite HTTPS desde el CIDR de la VPC (útiles cuando el pull de imagen vía IPs públicas no es confiable por NACL). S3 suele tener ya un Gateway VPC endpoint para capas del registry.

## Pasos

1. **Terraform**

   **`aws_profile` en `terraform.tfvars`** (default `asap_main`) debe apuntar a la cuenta donde viven las Lambdas (`913123310997`). Si Terraform usa otro usuario/acción (`AWS_PROFILE` global o cadena por defecto), el `plan` puede dirigirse a la cuenta equivocada.

   ```bash
   cd infra/batch-alerts-semantic-matches
   cp terraform.tfvars.example terraform.tfvars
   # VPC/subnets: las del ejemplo coinciden con rag_lmbd_query-prod

   terraform init
   terraform apply
   ```

2. **Build y push de imagen** (desde la **raíz del repo** `rag-agents`):

   ```bash
   ECR_URL=$(cd infra/batch-alerts-semantic-matches && terraform output -raw ecr_repository_url)
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$(echo "$ECR_URL" | cut -d/ -f1)"

   docker build -f batch/alerts-semantic-matches/Dockerfile -t "${ECR_URL}:latest" .
   docker push "${ECR_URL}:latest"
   ```

3. **Nueva revisión de task definition** tras cambiar la imagen:

   ```bash
   cd infra/batch-alerts-semantic-matches && terraform apply
   ```

4. **Logs**

   ```bash
   aws logs tail "$(terraform output -raw cloudwatch_log_group)" --follow --region us-east-1
   ```

## Estado de Terraform

Por defecto no hay backend remoto en este directorio (estado **local**). Para S3+DynamoDB, copiá el patrón del módulo `terraform/` principal.

## Ejecución manual (una corrida)

Sustituí subnets y SG si hace falta:

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
TASK_ARN=$(aws ecs list-task-definitions --family-prefix rag-batch-alerts-prod-anmat --sort DESC --max-items 1 --query taskDefinitionArns[0] --output text --region us-east-1)

aws ecs run-task --region us-east-1 --cluster "$CLUSTER" \
  --launch-type FARGATE \
  --task-definition "$TASK_ARN" \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-zzz],assignPublicIp=DISABLED}"
```
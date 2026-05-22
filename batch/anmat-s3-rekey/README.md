# Batch ECS: rekey ANMAT S3 desde `public.disposicion`

Copia PDFs listados en el manifiesto (`tenant_anmat_s3_not_in_documents_*.json`) a una **nueva key** en el mismo bucket, con carpeta `YYYYMMDD` tomada de `disposicion` (`fechayhora_revision` por defecto).

Dispara el encolador de embeddings (`ObjectCreated:Copy`) si la notificación S3 ya está configurada.

## CI (GitHub Actions)

Push a `main`, `master` o `tenant_boletin` que toque `batch/anmat-s3-rekey/**` o `scripts/rekey_anmat_s3_from_disposicion.py` dispara [`.github/workflows/batch-anmat-s3-rekey-docker.yml`](../../.github/workflows/batch-anmat-s3-rekey-docker.yml) → ECR **`rag-batch-anmat-s3-rekey-prod`**.

Requisitos:

1. `terraform apply` en `infra/batch-alerts-semantic-matches/` (crea repo ECR + permiso OIDC).
2. Secret del repo: `AWS_BATCH_ECR_ROLE_ARN` (mismo que el batch de alertas).

También podés lanzarlo manualmente: **Actions → Batch ANMAT S3 rekey — Docker → ECR → Run workflow**.

## Build local

```bash
cd /path/to/rag-agents
docker build -f batch/anmat-s3-rekey/Dockerfile -t rag-batch-anmat-s3-rekey:latest .
```

## Manifiesto

Subir el JSON (~47 MB) a S3 (recomendado):

```bash
aws s3 cp tenant_anmat_s3_not_in_documents_202605212328.json \
  s3://rag-documents-prod-913123310997/manifests/tenant_anmat_s3_not_in_documents_202605212328.json \
  --profile asap_main
```

## Variables ECS (task definition)

| Variable | Ejemplo | Descripción |
|----------|---------|-------------|
| `S3_DOCUMENTS_BUCKET` | `rag-documents-prod-913123310997` | Bucket RAG |
| `MANIFEST_S3_URI` | `s3://.../manifests/tenant_anmat_s3_not_in_documents_202605212328.json` | Manifiesto de entrada |
| `DB_SECRET_ARN` | ARN Secrets Manager postgres | Credenciales BD |
| `DISPERSION_DATE_FIELD` | `fechayhora_revision` | o `fecha_de_publicacion` |
| `DRY_RUN` | `1` | Prueba sin copiar |
| `DELETE_SOURCE` | `0` | `1` = borrar key vieja tras copiar |
| `MAX_ITEMS` | `100` | Límite (0 = todos) |
| `REKEY_REPORT_PATH` | `/tmp/rekey_anmat_report.json` | Reporte JSON de salida |
| `REKEY_LOG_S3_PREFIX` | `manifests/rekey-runs/` | Prefijo S3 para `ok_<run_id>.txt` y `errors_<run_id>.txt` |

## Logs y trazas

- **CloudWatch:** líneas `[STEP nn]` (fases del job) e `[ITEM i/n] [SUBSTEP]` por archivo.
- **S3:** al finalizar sube dos TSV:
  - `s3://<bucket>/<REKEY_LOG_S3_PREFIX>ok_<run_id>.txt` — copiados / dry-run / ya existían
  - `s3://<bucket>/<REKEY_LOG_S3_PREFIX>errors_<run_id>.txt` — errores S3, sin disposicion, key inválida, etc.

Columnas: `status`, `basename`, `partition`, `src_key`, `dst_key`, `detail`.

## IAM (rol de tarea ECS)

Además de lo que ya tenga el batch:

- `s3:GetObject` en manifiesto y PDFs origen
- `s3:PutObject` / `s3:CopyObject` en `tenant_anmat/*`
- `s3:DeleteObject` (solo si `DELETE_SOURCE=1`)
- `s3:HeadObject` (skip existing)
- `secretsmanager:GetSecretValue` (DB)

## Prueba local

```bash
export AWS_PROFILE=asap_main
export DB_SECRET_ID=arn:aws:secretsmanager:us-east-1:913123310997:secret:rag-agents/prod/postgres-...

python3 scripts/rekey_anmat_s3_from_disposicion.py \
  --manifest tenant_anmat_s3_not_in_documents_202605212328.json \
  --bucket rag-documents-prod-913123310997 \
  --dry-run --max-items 5
```

## Flujo recomendado

1. `DRY_RUN=1`, `MAX_ITEMS=20` en ECS
2. Revisar `/tmp/rekey_anmat_report.json` en logs CloudWatch / artefacto
3. Corrida completa con `DRY_RUN=0`, `DELETE_SOURCE=0` (mantener origen hasta validar embeddings)
4. Opcional: segunda pasada con `DELETE_SOURCE=1`

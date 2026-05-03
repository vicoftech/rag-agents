#!/usr/bin/env bash
# Importa todas las Lambdas del stack prod que usan modules/lambda y ya existen en AWS.
# Ejecutar desde el directorio terraform/ con workspace prod:
#   cd terraform && terraform workspace select prod
#   AWS_PROFILE=asap_main AWS_REGION=us-east-1 ./scripts/import_prod_lambdas_all.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
SCRIPT="${ROOT}/scripts/import_prod_lambda_module.sh"
chmod +x "${SCRIPT}"

run() {
  echo ""
  echo "######################################## ${1}"
  "${SCRIPT}" "${@:2}"
}

# Orden: primero enqueue (cola SQS referenciada por otras), embeddings consumer, query, etc.
run "enqueue" module.lambda_embeddings_enqueue rag_lmbd_embeddings_enqueue-prod custom
run "embeddings-async" module.lambda_embeddings_async rag_lmbd_embeddings-async-prod vpc,custom,s3deploy,sqs
run "query" module.lambda_query rag_lmbd_query-prod vpc,custom,s3deploy
run "obtener_alertas" module.lambda_obtener_alertas rag_lmbd_obtener_alertas-prod vpc,s3deploy
run "parser" module.lambda_parser rag_lmbd_parser-prod ""
run "s3writer" module.lambda_s3writer rag_lmbd_s3writer-prod custom,sqs
run "dbwriter" module.lambda_dbwriter rag_lmbd_dbwriter-prod custom
run "notifier" module.lambda_notifier rag_lmbd_notifier-prod custom
run "fetcher" module.lambda_fetcher rag_lmbd_fetcher-prod ""
run "bolinks" module.lambda_bolinks rag_lmbd_bolinks-prod ""
run "anmatlinks" module.lambda_anmatlinks rag_lmbd_anmatlinks-prod s3deploy
run "stepfunction" module.lambda_stepfunction rag_lmbd_stepfunction-prod custom

VARFILE="${ROOT}/environments/prod.tfvars"
if ! terraform state show -no-color aws_sqs_queue.embeddings_ingest &>/dev/null; then
  echo ""
  echo "######################################## aws_sqs_queue.embeddings_ingest"
  QU="$(aws sqs get-queue-url --queue-name "rag-embeddings-ingest-prod" \
    --profile "${AWS_PROFILE:-asap_main}" --region "${AWS_REGION:-us-east-1}" \
    --query QueueUrl --output text 2>/dev/null || true)"
  if [[ -n "${QU}" && "${QU}" != "None" ]]; then
    terraform import -var-file="${VARFILE}" aws_sqs_queue.embeddings_ingest "${QU}"
  else
    echo "WARN: no se pudo resolver URL de rag-embeddings-ingest (¿nombre distinto?). Import manual."
  fi
fi

echo ""
echo "Hecho. Luego:"
echo "  terraform plan -var-file=environments/prod.tfvars"

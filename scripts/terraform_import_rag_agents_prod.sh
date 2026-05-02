#!/usr/bin/env bash
# Une el state remoto Terraform (workspace prod) con infra ya existente en AWS.
# Uso desde la carpeta terraform:
#   cd terraform && terraform workspace select prod
#   bash ../scripts/terraform_import_rag_agents_prod.sh 2>&1 | tee import-prod.log
# No encadenar con `| tail` u otros consumidores lentos: puede llenar el pipe
# y bloquear terraform import (deadlock).
#
# Credenciales: export AWS_PROFILE=asap_main (o el que coincida con prod.tfvars)
set -eu

TF_ROOT="$(cd "$(dirname "$0")/../terraform" && pwd)"
TFVARS="${TFVARS:-$TF_ROOT/environments/prod.tfvars}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ACCOUNT="${ACCOUNT_ID:-913123310997}"
BUCKET="${DOCS_BUCKET:-rag-documents-prod-${ACCOUNT}}"

BASIC_POLICY="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
VPC_POLICY="arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
SQS_POLICY="arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"

cd "$TF_ROOT"
terraform workspace select prod

VARFILE=( -var-file="$TFVARS" )

imi() {
  ADDR="$1"; ID="$2"
  echo "import $ADDR <-- $ID"
  if terraform state list -no-color 2>/dev/null | grep -qxF "$ADDR"; then
    echo "  (ya en state, skip)"
    return 0
  fi
  terraform import "${VARFILE[@]}" "$ADDR" "$ID" || echo "  WARN: fallo import $ADDR"
}

queue_url() {
  aws sqs get-queue-url --region "$REGION" --queue-name "$1" --query QueueUrl --output text
}

echo "=== 0) Quita del state SES (ya no están en .tf — evitar destroy accidental) ==="
for R in \
  'aws_cloudwatch_event_rule.ses_to_logs[0]' \
  'aws_cloudwatch_event_target.ses_eventbridge_audit_logs[0]' \
  'aws_cloudwatch_log_group.ses_eventbridge[0]' \
  'aws_cloudwatch_log_resource_policy.ses_eventbridge_write[0]' \
  'aws_sesv2_configuration_set.observability[0]' \
  'aws_sesv2_configuration_set_event_destination.cloudwatch_metrics[0]' \
  'aws_sesv2_configuration_set_event_destination.eventbridge[0]' \
  'data.aws_cloudwatch_event_bus.ses_default_bus[0]' \
  'module.lambda_query.data.archive_file.lambda' \
  'module.lambda_query.data.aws_iam_policy_document.assume_role' \
  'module.lambda_query.null_resource.build_lambda_unix[0]'
do
  terraform state rm "$R" >/dev/null 2>&1 && echo "state rm $R" || true
done

echo "=== 1) DynamoDB / SQS / SNS / VPC ==="
imi aws_dynamodb_table.documents rag-documents-prod

imi aws_sqs_queue.embeddings_ingest_dlq "$(queue_url "rag-embeddings-ingest-dlq-prod")"
imi aws_sqs_queue.embeddings_ingest "$(queue_url "rag-embeddings-ingest-prod")"
imi aws_sqs_queue.alert_s3writer_dlq "$(queue_url "alert-s3writer-dlq-prod")"
imi aws_sqs_queue.alert_s3writer "$(queue_url "alert-s3writer-prod")"

imi aws_sns_topic.rag_notifications "arn:aws:sns:${REGION}:${ACCOUNT}:rag-pipeline-notifications-prod"

imi aws_security_group.rag_interface_endpoints[0] sg-095fdf56946ec5b8a
imi aws_vpc_endpoint.secretsmanager[0] vpce-0f3c193be1d63db23
imi aws_vpc_endpoint.textract[0] vpce-00e3074090fd91e1d

imi aws_vpc_security_group_ingress_rule.rds_from_rag_lambda sgr-09729b9b575e169ea

echo "=== 2) Chromium layer + S3 object + layer version ==="
imi module.sparticuz_chromium_layer.aws_s3_object.layer_zip "${BUCKET}/lambda-layers/sparticuz-chromium/prod/layer.zip"
imi module.sparticuz_chromium_layer.aws_lambda_layer_version.this \
  "arn:aws:lambda:${REGION}:${ACCOUNT}:layer:rag-sparticuz-chromium-prod:2"

lambda_simple() {
  local MOD="$1" FN="$2"
  imi "${MOD}.aws_iam_role.lambda" "${FN}-role"
  imi "${MOD}.aws_iam_role_policy.custom[0]" "${FN}-role:${FN}-custom-policy"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_basic" "${FN}-role/${BASIC_POLICY}"
  imi "${MOD}.aws_lambda_function.this" "${FN}"
  imi "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"
}

lambda_vpc_only() {
  local MOD="$1" FN="$2"
  lambda_simple "$MOD" "$FN"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_vpc[0]" "${FN}-role/${VPC_POLICY}"
}

lambda_sqs_only() {
  local MOD="$1" FN="$2"
  lambda_simple "$MOD" "$FN"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_sqs[0]" "${FN}-role/${SQS_POLICY}"
}

lambda_vpc_sqs() {
  local MOD="$1" FN="$2" ES="$3"
  lambda_vpc_only "$MOD" "$FN"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_sqs[0]" "${FN}-role/${SQS_POLICY}"
  imi "${MOD}.aws_lambda_event_source_mapping.sqs[0]" "$ES"
}

lambda_s3deploy_vpc_policies() {
  local MOD="$1" FN="$2" KEY_SUFFIX="$3"
  local KEY="lambda-packages/${FN}/${KEY_SUFFIX}"
  imi "${MOD}.aws_iam_role.lambda" "${FN}-role"
  imi "${MOD}.aws_iam_role_policy.custom[0]" "${FN}-role:${FN}-custom-policy"
  imi "${MOD}.aws_iam_role_policy.s3_deployment[0]" "${FN}-role:${FN}-s3-deployment-policy"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_basic" "${FN}-role/${BASIC_POLICY}"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_vpc[0]" "${FN}-role/${VPC_POLICY}"
  imi "${MOD}.aws_s3_object.lambda_package[0]" "${BUCKET}/${KEY}"
  imi "${MOD}.aws_lambda_function.this" "${FN}"
  imi "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"
}

lambda_s3deploy_nop_vpc_policies_sqs() {
  local MOD="$1" FN="$2" KEY_SUFFIX="$3" ES="$4"
  imi "${MOD}.aws_iam_role.lambda" "${FN}-role"
  imi "${MOD}.aws_iam_role_policy.custom[0]" "${FN}-role:${FN}-custom-policy"
  imi "${MOD}.aws_iam_role_policy.s3_deployment[0]" "${FN}-role:${FN}-s3-deployment-policy"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_basic" "${FN}-role/${BASIC_POLICY}"
  imi "${MOD}.aws_iam_role_policy_attachment.lambda_sqs[0]" "${FN}-role/${SQS_POLICY}"
  imi "${MOD}.aws_s3_object.lambda_package[0]" "${BUCKET}/${KEY}"
  imi "${MOD}.aws_lambda_function.this" "${FN}"
  imi "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"
  imi "${MOD}.aws_lambda_event_source_mapping.sqs[0]" "$ES"
}

echo "=== 3) Lambdas sin VPC ==="
lambda_simple module.lambda_parser rag_lmbd_parser-prod
lambda_simple module.lambda_notifier rag_lmbd_notifier-prod
lambda_simple module.lambda_fetcher rag_lmbd_fetcher-prod
lambda_simple module.lambda_bolinks rag_lmbd_bolinks-prod

echo "=== 4) dbwriter ==="
lambda_simple module.lambda_dbwriter rag_lmbd_dbwriter-prod

echo "=== 5) s3writer (SQS) ==="
lambda_sqs_only module.lambda_s3writer rag_lmbd_s3writer-prod
imi module.lambda_s3writer.aws_lambda_event_source_mapping.sqs[0] "fe83d203-0abf-4daa-96ff-7aee4d1cae73"

echo "=== 6) stepfunction orchestrator ==="
lambda_simple module.lambda_stepfunction rag_lmbd_stepfunction-prod

echo "=== 7) embeddings async (VPC+SQS+S3 ZIP) ==="
lambda_s3deploy_vpc_policies module.lambda_embeddings_async rag_lmbd_embeddings-async-prod \
  ea2b19ceed650f11b07cfb633831d9390ecc3d42b484f6cedeeebfc03ad7704d.zip
imi module.lambda_embeddings_async.aws_iam_role_policy_attachment.lambda_sqs[0] "rag_lmbd_embeddings-async-prod-role/${SQS_POLICY}"
imi module.lambda_embeddings_async.aws_lambda_event_source_mapping.sqs[0] "e22c3ae0-f3df-4292-8e42-bdbc74493182"

echo "=== 8) embeddings enqueue + S3 notificación ==="
FN=rag_lmbd_embeddings_enqueue-prod
MOD=module.lambda_embeddings_enqueue
imi "${MOD}.aws_iam_role.lambda" "${FN}-role"
imi "${MOD}.aws_iam_role_policy.custom[0]" "${FN}-role:${FN}-custom-policy"
imi "${MOD}.aws_iam_role_policy_attachment.lambda_basic" "${FN}-role/${BASIC_POLICY}"
imi "${MOD}.aws_lambda_function.this" "${FN}"
imi "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"

imi aws_lambda_permission.s3_invoke_embeddings_enqueue "${FN}/AllowS3InvokeEmbeddingsEnqueue"

imi aws_s3_bucket_notification.documents_to_embeddings_queue "$BUCKET"

echo "=== 9) obtener_alertas / query / anmatlinks (S3 ZIP) ==="
lambda_s3deploy_vpc_policies module.lambda_obtener_alertas rag_lmbd_obtener_alertas-prod \
  d9229bc40a168f92934cd4230e19b0d67f1d6a2680775a3c94d84f518e3aedce.zip
lambda_s3deploy_vpc_policies module.lambda_query rag_lmbd_query-prod \
  33d01d62ebdfd6837650a172abb440ad3e402d1c078df8b66345fd148766459d.zip

MOD=module.lambda_anmatlinks
FN=rag_lmbd_anmatlinks-prod
imi "${MOD}.aws_iam_role.lambda" "${FN}-role"
imi "${MOD}.aws_iam_role_policy.custom[0]" "${FN}-role:${FN}-custom-policy"
imi "${MOD}.aws_iam_role_policy.s3_deployment[0]" "${FN}-role:${FN}-s3-deployment-policy"
imi "${MOD}.aws_iam_role_policy_attachment.lambda_basic" "${FN}-role/${BASIC_POLICY}"
imi "${MOD}.aws_s3_object.lambda_package[0]" \
  "${BUCKET}/lambda-packages/${FN}/bd51157d92376c748c0277a9327d42e5afb42b9cb8639338bce478a0b76f9cbb.zip"
imi "${MOD}.aws_lambda_function.this" "${FN}"
imi "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"

echo "=== 10) Cognito query ==="
imi module.cognito_query.aws_cognito_user_pool.this "us-east-1_gBR4eccsd"
imi module.cognito_query.aws_cognito_user_pool_client.this "us-east-1_gBR4eccsd/mc8ierh922qbe205t9jnksm77"

echo "=== 11) API Gateway query ==="
API=nbgcg3rn1m
imi module.api_gateway_query.aws_apigatewayv2_api.this "$API"
imi module.api_gateway_query.aws_cloudwatch_log_group.api_gateway "/aws/apigateway/rag-query-api-prod"

imi module.api_gateway_query.aws_apigatewayv2_authorizer.jwt "${API}/mojrh5"
imi module.api_gateway_query.aws_apigatewayv2_integration.lambda "${API}/yjdmr02"

imi module.api_gateway_query.aws_apigatewayv2_route.query "${API}/mz88nks"
imi module.api_gateway_query.aws_apigatewayv2_route.query_options "${API}/h3p596k"
imi module.api_gateway_query.aws_apigatewayv2_route.presigned_url "${API}/je8l80q"
imi module.api_gateway_query.aws_apigatewayv2_route.presigned_url_options "${API}/covihwl"

imi module.api_gateway_query.aws_apigatewayv2_stage.this "${API}/prod"
imi module.api_gateway_query.aws_lambda_permission.api_gateway \
  "rag_lmbd_query-prod/AllowAPIGatewayInvokeQuery"

BM="Alerts-BoletinOficialSyncronizer-prod"
echo "=== 12) SFN bolletín + permisos ==="
imi module.boletin_oficial_sfn.aws_iam_role.sfn "${BM}-sfn-exec"
imi module.boletin_oficial_sfn.aws_iam_role_policy.sfn "${BM}-sfn-exec:invoke-bolinks-s3writer-dbwriter"
imi module.boletin_oficial_sfn.aws_sfn_state_machine.boletin \
  "arn:aws:states:${REGION}:${ACCOUNT}:stateMachine:${BM}"
imi module.boletin_oficial_sfn.aws_lambda_permission.sfn_bolinks \
  "rag_lmbd_bolinks-prod/AllowStepFunctions-boletin-oficial-${BM}"
imi module.boletin_oficial_sfn.aws_lambda_permission.sfn_s3writer \
  "rag_lmbd_s3writer-prod/AllowStepFunctions-boletin-s3w-${BM}"
imi module.boletin_oficial_sfn.aws_lambda_permission.sfn_dbwriter \
  "rag_lmbd_dbwriter-prod/AllowStepFunctions-boletin-dbw-${BM}"

ASFN="rag-anmat-to-s3writer-prod"
echo "=== 13) SFN anmat→SQS + permiso ==="
imi module.anmat_s3_stepfunction.aws_iam_role.sfn "${ASFN}-sfn-role"
imi module.anmat_s3_stepfunction.aws_iam_role_policy.sfn "${ASFN}-sfn-role:${ASFN}-sfn-policy"
imi module.anmat_s3_stepfunction.aws_sfn_state_machine.anmat_to_s3 \
  "arn:aws:states:${REGION}:${ACCOUNT}:stateMachine:${ASFN}"
imi module.anmat_s3_stepfunction.aws_lambda_permission.sfn_invoke_anmat \
  "rag_lmbd_anmatlinks-prod/AllowExecutionFromStepFunctions-${ASFN}"

echo "=== Fin imports. Ejecutá: terraform plan -var-file=environments/prod.tfvars ==="
echo "Si el plan muestra sólo diffs benignos/null_resource Sparticuz, aplicá con cuidado: terraform apply"
terraform state list | wc -l

#!/usr/bin/env bash
# Importa un módulo ./modules/lambda ya desplegado en AWS al estado de Terraform.
# Uso (desde terraform/):
#   ./scripts/import_prod_lambda_module.sh module.lambda_query rag_lmbd_query-prod vpc,custom,s3deploy
#
# FLAGS (coma-separados, sin espacios): vpc | custom | s3deploy | sqs
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VARFILE="${TF_VAR_FILE:-${ROOT}/environments/prod.tfvars}"
TFIMPORT=(terraform import -var-file="${VARFILE}")

MOD="${1:?module path}"
FN="${2:?function name e.g. rag_lmbd_query-prod}"
FLAGS="${3:-}"

ROLE="${FN}-role"
has() { [[ ",${FLAGS}," == *",$1,"* ]] || [[ "${FLAGS}" == "$1" ]]; }

echo "==> ${MOD} (${FN}) flags=${FLAGS:-none}"

"${TFIMPORT[@]}" "${MOD}.aws_iam_role.lambda" "${ROLE}"

"${TFIMPORT[@]}" "${MOD}.aws_iam_role_policy_attachment.lambda_basic" \
  "${ROLE}/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

if has vpc; then
  "${TFIMPORT[@]}" "${MOD}.aws_iam_role_policy_attachment.lambda_vpc[0]" \
    "${ROLE}/arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
fi

if has custom; then
  "${TFIMPORT[@]}" "${MOD}.aws_iam_role_policy.custom[0]" "${ROLE}:${FN}-custom-policy"
fi

if has s3deploy; then
  "${TFIMPORT[@]}" "${MOD}.aws_iam_role_policy.s3_deployment[0]" "${ROLE}:${FN}-s3-deployment-policy"
fi

if has sqs; then
  "${TFIMPORT[@]}" "${MOD}.aws_iam_role_policy_attachment.lambda_sqs[0]" \
    "${ROLE}/arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
fi

"${TFIMPORT[@]}" "${MOD}.aws_lambda_function.this" "${FN}"

"${TFIMPORT[@]}" "${MOD}.aws_cloudwatch_log_group.lambda" "/aws/lambda/${FN}"

if has sqs; then
  MID="$(aws lambda list-event-source-mappings --function-name "${FN}" \
    --profile "${AWS_PROFILE:-asap_main}" --region "${AWS_REGION:-us-east-1}" \
    --query 'EventSourceMappings[0].UUID' --output text)"
  if [[ -z "${MID}" || "${MID}" == "None" ]]; then
    echo "WARN: no event source mapping for ${FN}; omit import sqs mapping"
  else
    "${TFIMPORT[@]}" "${MOD}.aws_lambda_event_source_mapping.sqs[0]" "${MID}"
  fi
fi

echo "==> OK ${MOD}"

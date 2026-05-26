#!/bin/sh
set -eu
# BATCH_CORRIDA: anmat | boletin (ECS task definition). Opciones vía env (Terraform): BATCH_PARALLEL,
# BATCH_TRACE_LAMBDA_PAYLOADS, BATCH_INCLUDE_ZERO_CHUNK, BATCH_NO_CREATED_AT_FILTER,
# BATCH_TESTING_EMAIL_TO + BATCH_TESTING_EMAIL_CC | BATCH_TESTING_EMAIL (solo to, legacy),
# BATCH_PUBLISH_EMAIL_QUEUE, BATCH_PUBLISH_ALERT_CREATION_QUEUE (1 = publicar a SQS).
CORRIDA="${BATCH_CORRIDA:-}"
case "$CORRIDA" in
  anmat)  CORRIDA_ARG="anmat=scripts/anmat_map.json" ;;
  boletin) CORRIDA_ARG="boletin=scripts/boletin_map.json" ;;
  *) echo "entrypoint: BATCH_CORRIDA must be anmat or boletin, got ${CORRIDA}" >&2; exit 1 ;;
esac

PARALLEL="${BATCH_PARALLEL:-2}"
TRACE_PATH="/tmp/${CORRIDA}_lambda_trace.json"
OUT="/tmp/alerts_matches_prod_fullcorpus_$(date -u +%Y%m%dT%H%M%SZ).json"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
BATCH_DATE_TZ="${BATCH_DATE_TZ:-America/Argentina/Buenos_Aires}"
TODAY=$(TZ="${BATCH_DATE_TZ}" date +%Y-%m-%d)

cd /app
echo "entrypoint: BATCH_CORRIDA=${CORRIDA} BATCH_PARALLEL=${PARALLEL} created_at=${TODAY}..${TODAY} tz=${BATCH_DATE_TZ} BATCH_TRACE_LAMBDA_PAYLOADS=${BATCH_TRACE_LAMBDA_PAYLOADS:-1} BATCH_INCLUDE_ZERO_CHUNK=${BATCH_INCLUDE_ZERO_CHUNK:-0} BATCH_NO_CREATED_AT_FILTER=${BATCH_NO_CREATED_AT_FILTER:-0} BATCH_TESTING_EMAIL=${BATCH_TESTING_EMAIL:-} BATCH_TESTING_EMAIL_TO=${BATCH_TESTING_EMAIL_TO:-} BATCH_TESTING_EMAIL_CC=${BATCH_TESTING_EMAIL_CC:-} BATCH_PUBLISH_EMAIL_QUEUE=${BATCH_PUBLISH_EMAIL_QUEUE:-0} BATCH_PUBLISH_ALERT_CREATION_QUEUE=${BATCH_PUBLISH_ALERT_CREATION_QUEUE:-0} output=${OUT} trace=${TRACE_PATH}" >&2

set -- python3 scripts/alerts_semantic_matches.py \
  --profile "" \
  --env prod \
  --corrida "${CORRIDA_ARG}" \
  --s3-bucket "${S3_DOCUMENTS_BUCKET}" \
  --parallel "${PARALLEL}" \
  -o "${OUT}"

if [ "${BATCH_NO_CREATED_AT_FILTER:-0}" = "1" ]; then
  set -- "$@" --no-created-at-filter
else
  set -- "$@" --created-at-start "${TODAY}" --created-at-end "${TODAY}"
fi

if [ "${BATCH_TRACE_LAMBDA_PAYLOADS:-1}" = "1" ]; then
  set -- "$@" --trace-lambda-payloads --output-trace "${TRACE_PATH}"
fi

if [ "${BATCH_INCLUDE_ZERO_CHUNK:-0}" = "1" ]; then
  set -- "$@" --include-zero-chunk-resultados
fi

if [ -n "${BATCH_TESTING_EMAIL_TO:-}" ]; then
  set -- "$@" --testing-email-to "${BATCH_TESTING_EMAIL_TO}"
  if [ -n "${BATCH_TESTING_EMAIL_CC:-}" ]; then
    set -- "$@" --testing-email-cc "${BATCH_TESTING_EMAIL_CC}"
  fi
elif [ -n "${BATCH_TESTING_EMAIL:-}" ]; then
  set -- "$@" --testing-email "${BATCH_TESTING_EMAIL}"
fi

if [ "${BATCH_PUBLISH_EMAIL_QUEUE:-0}" = "1" ]; then
  set -- "$@" --publish-email-queue
fi

if [ "${BATCH_PUBLISH_ALERT_CREATION_QUEUE:-0}" = "1" ]; then
  set -- "$@" --publish-alert-creation-queue
fi

exec "$@"

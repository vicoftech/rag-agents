#!/bin/sh
set -eu
# BATCH_CORRIDA: anmat | boletin (ECS task definition). Opciones vía env (Terraform): BATCH_PARALLEL,
# BATCH_TRACE_LAMBDA_PAYLOADS, BATCH_INCLUDE_ZERO_CHUNK, BATCH_NO_CREATED_AT_FILTER.
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

cd /app
echo "entrypoint: BATCH_CORRIDA=${CORRIDA} BATCH_PARALLEL=${PARALLEL} BATCH_TRACE_LAMBDA_PAYLOADS=${BATCH_TRACE_LAMBDA_PAYLOADS:-1} BATCH_INCLUDE_ZERO_CHUNK=${BATCH_INCLUDE_ZERO_CHUNK:-0} BATCH_NO_CREATED_AT_FILTER=${BATCH_NO_CREATED_AT_FILTER:-0} output=${OUT} trace=${TRACE_PATH}" >&2

set -- python3 scripts/alerts_semantic_matches.py \
  --profile "" \
  --env prod \
  --corrida "${CORRIDA_ARG}" \
  --s3-bucket "${S3_DOCUMENTS_BUCKET}" \
  --parallel "${PARALLEL}" \
  -o "${OUT}"

if [ "${BATCH_NO_CREATED_AT_FILTER:-0}" = "1" ]; then
  set -- "$@" --no-created-at-filter
fi

if [ "${BATCH_TRACE_LAMBDA_PAYLOADS:-1}" = "1" ]; then
  set -- "$@" --trace-lambda-payloads --output-trace "${TRACE_PATH}"
fi

if [ "${BATCH_INCLUDE_ZERO_CHUNK:-0}" = "1" ]; then
  set -- "$@" --include-zero-chunk-resultados
fi

exec "$@"

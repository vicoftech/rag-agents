#!/bin/sh
set -eu
# BATCH_CORRIDA: anmat | boletin (set by ECS task definition)
CORRIDA="${BATCH_CORRIDA:-}"
case "$CORRIDA" in
  anmat)  CORRIDA_ARG="anmat=scripts/anmat_map.json" ;;
  boletin) CORRIDA_ARG="boletin=scripts/boletin_map.json" ;;
  *) echo "entrypoint: BATCH_CORRIDA must be anmat or boletin, got ${CORRIDA}" >&2; exit 1 ;;
esac

OUT="/tmp/alerts_matches_prod_fullcorpus_$(date -u +%Y%m%dT%H%M%SZ).json"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

cd /app
echo "entrypoint: BATCH_CORRIDA=${CORRIDA} AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION} output=${OUT}" >&2

exec python3 scripts/alerts_semantic_matches.py \
  --profile "" \
  --env prod \
  --corrida "${CORRIDA_ARG}" \
  --s3-bucket "${S3_DOCUMENTS_BUCKET}" \
  --no-created-at-filter \
  --parallel 2 \
  --publish-email-queue \
  --publish-alert-creation-queue \
  -o "${OUT}"

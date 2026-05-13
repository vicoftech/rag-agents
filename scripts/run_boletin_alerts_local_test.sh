#!/usr/bin/env bash
# Boletín prod desde tu máquina: destinatarios sustituidos por --testing-email (no publica SQS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TEST_EMAIL="${TEST_EMAIL:-viglesias@asap-consulting.net}"
OUT="${OUT:-boletin_resultado_local_test.json}"

exec python3 scripts/alerts_semantic_matches.py \
  --profile "${AWS_PROFILE:-asap_main}" \
  --env prod \
  --allow-weekend-run \
  --corrida "boletin=scripts/boletin_map.json" \
  --s3-bucket "${S3_BUCKET:-rag-documents-prod-913123310997}" \
  --testing-email "$TEST_EMAIL" \
  --trace-lambda-payloads \
  --output-trace "${OUT%.json}_lambda_trace.json" \
  -o "$OUT"

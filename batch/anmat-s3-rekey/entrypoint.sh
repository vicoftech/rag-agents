#!/bin/sh
set -eu

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
cd /app

MANIFEST_LOCAL="${MANIFEST_PATH:-/tmp/manifest.json}"
REPORT="${REKEY_REPORT_PATH:-/tmp/rekey_anmat_report.json}"
LOG_PREFIX="${REKEY_LOG_S3_PREFIX:-manifests/rekey-runs/}"
DRY_RUN="${DRY_RUN:-0}"
DELETE_SOURCE="${DELETE_SOURCE:-0}"
MAX_ITEMS="${MAX_ITEMS:-0}"
DATE_FIELD="${DISPERSION_DATE_FIELD:-fechayhora_revision}"
RESUME_OK_PREFIX="${REKEY_RESUME_OK_S3_PREFIX:-manifests/rekey-runs/}"

if [ -n "${MANIFEST_S3_URI:-}" ]; then
  echo "entrypoint: descargando manifiesto ${MANIFEST_S3_URI}" >&2
  aws s3 cp "${MANIFEST_S3_URI}" "${MANIFEST_LOCAL}"
fi

if [ ! -f "${MANIFEST_LOCAL}" ]; then
  echo "entrypoint: falta manifiesto (${MANIFEST_LOCAL} o MANIFEST_S3_URI)" >&2
  exit 1
fi

set -- python3 scripts/rekey_anmat_s3_from_disposicion.py \
  --manifest "${MANIFEST_LOCAL}" \
  --bucket "${S3_DOCUMENTS_BUCKET:?S3_DOCUMENTS_BUCKET requerido}" \
  --date-field "${DATE_FIELD}" \
  --report "${REPORT}" \
  --log-s3-prefix "${LOG_PREFIX}"

[ "${DRY_RUN}" = "1" ] && set -- "$@" --dry-run
[ "${DELETE_SOURCE}" = "1" ] && set -- "$@" --delete-source
[ -n "${MAX_ITEMS}" ] && [ "${MAX_ITEMS}" != "0" ] && set -- "$@" --max-items "${MAX_ITEMS}"
[ "${REKEY_RESUME:-1}" != "0" ] && [ -n "${RESUME_OK_PREFIX}" ] && \
  set -- "$@" --resume-ok-s3-prefix "${RESUME_OK_PREFIX}"

echo "entrypoint: $*" >&2
exec "$@"

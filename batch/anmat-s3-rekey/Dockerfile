# Build desde la raíz del repo:
#   docker build -f batch/anmat-s3-rekey/Dockerfile -t rag-batch-anmat-s3-rekey:latest .
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends awscli \
    && rm -rf /var/lib/apt/lists/*

COPY batch/anmat-s3-rekey/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY scripts/rekey_anmat_s3_from_disposicion.py scripts/rekey_anmat_s3_from_disposicion.py

COPY batch/anmat-s3-rekey/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && useradd --create-home --uid 1000 batch \
    && chown -R batch:batch /app
USER batch

ENTRYPOINT ["/entrypoint.sh"]

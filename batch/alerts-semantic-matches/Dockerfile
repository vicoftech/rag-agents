# Build from repository root:
#   docker build -f batch/alerts-semantic-matches/Dockerfile -t rag-batch-alerts:latest .
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY batch/alerts-semantic-matches/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY scripts/alerts_semantic_matches.py scripts/alerts_semantic_matches.py
COPY scripts/boletin_map.json scripts/boletin_map.json
COPY scripts/anmat_map.json scripts/anmat_map.json


COPY batch/alerts-semantic-matches/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd --create-home --uid 1000 batch && chown -R batch:batch /app
USER batch

ENTRYPOINT ["/entrypoint.sh"]

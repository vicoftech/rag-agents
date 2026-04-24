#!/usr/bin/env python3
"""
Recorre un CSV (columnas: key, s3_uri, size opcional) y envía a la cola
`rag-embeddings-ingest-*` el JSON de evento S3 que el encolador pondría en el
body, para reprocesar sin copiar objetos en S3.

Uso (prod):
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --dry-run
  # Por defecto: solo filas con prefix=tenant_boletin (el CSV mezcla tenant_anmat + tenant_boletin)
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main
  # Enviar todos los prefix del CSV, o filtrar solo ANMAT:
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --all-prefixes
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --only-prefix tenant_anmat
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import string
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Iterator

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print("Falta boto3. Instala: pip install -r requirements.txt (desde scripts/)", file=sys.stderr)
    raise SystemExit(1) from e


def _build_message_body(
    bucket: str,
    key: str,
    size: int,
    region: str,
) -> str:
    """Cuerpo JSON con Records[0] compatible con rag_lmbd_embeddings (desenroscado SQS)."""
    key_encoded = urllib.parse.quote(key, safe="/")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    seq = "".join(random.choices(string.digits, k=12))
    record: dict[str, Any] = {
        "eventVersion": "2.1",
        "eventSource": "aws:s3",
        "awsRegion": region,
        "eventTime": now,
        "eventName": "ObjectCreated:Put",
        "userIdentity": {"principalId": "csv-replay"},
        "requestParameters": {"sourceIPAddress": "0.0.0.0"},
        "responseElements": {
            "x-amz-request-id": "REPLAY",
            "x-amz-id-2": "REPLAY/REPLAY",
        },
        "s3": {
            "s3SchemaVersion": "1.0",
            "configurationId": "csv-replay",
            "bucket": {
                "name": bucket,
                "arn": f"arn:aws:s3:::{bucket}",
                "ownerIdentity": {"principalId": "REPLAY"},
            },
            "object": {
                "key": key_encoded,
                "size": int(size) if size else 0,
                "eTag": "csv-replay",
                "sequencer": seq,
            },
        },
    }
    return json.dumps({"Records": [record]}, ensure_ascii=False)


def _row_key_size(row: dict[str, str]) -> tuple[str | None, int]:
    k = (row.get("key") or "").strip()
    if not k and (row.get("s3_uri") or "").strip():
        u = row["s3_uri"].strip()
        if u.startswith("s3://"):
            rest = u[5:].split("/", 1)
            if len(rest) == 2:
                k = rest[1]
        else:
            k = u
    if not k:
        return None, 0
    sz = 0
    if (row.get("size") or "").strip():
        try:
            sz = int(str(row["size"]).strip())
        except ValueError:
            sz = 0
    return k, sz


def iter_csv_keys(
    path: str, *, pdf_only: bool, only_prefix: str | None
) -> Iterator[tuple[str, int]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fn = [x.strip() for x in (reader.fieldnames or []) if x]
        if not fn:
            raise SystemExit("CSV vacío o sin cabecera")
        if "key" not in fn and "s3_uri" not in fn:
            raise SystemExit("El CSV debe incluir columna 'key' o 's3_uri'")
        if only_prefix is not None and "prefix" not in fn:
            raise SystemExit(
                "Filtro --only-prefix requiere columna 'prefix' en el CSV (o use --all-prefixes)"
            )
        for row in reader:
            if only_prefix is not None:
                if row.get("prefix", "").strip() != only_prefix:
                    continue
            key, sz = _row_key_size(row)
            if not key:
                continue
            if pdf_only and not key.lower().endswith(".pdf"):
                continue
            yield key, sz


def main() -> int:
    p = argparse.ArgumentParser(
        description="Enviar eventos S3 sintéticos a la cola de ingest de embeddings (CSV de URIs)."
    )
    p.add_argument(
        "--csv",
        default="s3_prod_tenant_anmat_boletin_uris.csv",
        help="Ruta al CSV (convive en scripts/ con el listado S3).",
    )
    p.add_argument(
        "--queue-url",
        default="https://sqs.us-east-1.amazonaws.com/913123310997/rag-embeddings-ingest-prod",
        help="URL de rag-embeddings-ingest-ENV",
    )
    p.add_argument("--bucket", default="rag-documents-prod-913123310997", help="Bucket de documentos")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--profile", default=None, help="Perfil de credenciales AWS")
    p.add_argument("--limit", type=int, default=0, help="Máx. filas a enviar (0 = todas)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo mostrar un ejemplo de MessageBody, no enviar a SQS",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Segundos de pausa entre cada batch de 10 mensajes",
    )
    p.add_argument(
        "--include-non-pdf",
        action="store_true",
        help="También encolar claves que no terminen en .pdf",
    )
    p.add_argument(
        "--only-prefix",
        default="tenant_boletin",
        metavar="NAME",
        help=(
            "Solo filas donde la columna 'prefix' coincide (p. ej. tenant_boletin). "
            "Por defecto: tenant_boletin. Vacío: sin filtrar."
        ),
    )
    p.add_argument(
        "--all-prefixes",
        action="store_true",
        help="Incluir todas las filas; ignora --only-prefix.",
    )
    args = p.parse_args()

    if args.all_prefixes:
        only_prefix: str | None = None
    else:
        op = (args.only_prefix or "").strip()
        only_prefix = op if op else None

    rows = list(
        iter_csv_keys(args.csv, pdf_only=not args.include_non_pdf, only_prefix=only_prefix)
    )
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    n = len(rows)
    if n == 0:
        print("Nada que enviar (CSV vacío o sin claves / PDFs).", file=sys.stderr)
        return 1

    print(f"Enviando {n} mensajes a {args.queue_url} (bucket={args.bucket})")

    if args.dry_run:
        k0, s0 = rows[0]
        body = _build_message_body(args.bucket, k0, s0, args.region)
        print("Primer MessageBody (ejemplo):")
        print((body[:800] + "…\n") if len(body) > 800 else body)
        return 0

    session = boto3.session.Session(profile_name=args.profile, region_name=args.region)
    sqs = session.client("sqs", region_name=args.region)

    batch_size = 10
    successful = 0
    for i in range(0, n, batch_size):
        chunk = rows[i : i + batch_size]
        entries: list[dict[str, str]] = []
        for j, (key, size) in enumerate(chunk):
            body = _build_message_body(args.bucket, key, size, args.region)
            # Id único en el lote: alfanumérico, máx. 80 chars
            entries.append(
                {
                    "Id": f"k{i + j:08d}",
                    "MessageBody": body,
                }
            )
        try:
            resp = sqs.send_message_batch(QueueUrl=args.queue_url, Entries=entries)
        except ClientError as e:
            print(f"Error send_message_batch en offset {i}: {e}", file=sys.stderr)
            return 1
        for fail in resp.get("Failed", []):
            print(f"Fallo: {fail}", file=sys.stderr)
        successful += len(resp.get("Successful", []))
        if args.sleep > 0:
            time.sleep(args.sleep)
        done = min(i + batch_size, n)
        if done % 500 < batch_size or done == n:
            print(f"  … {done}/{n}")

    print(f"Listo. Mensajes aceptados: {successful}")
    return 0 if successful == n else 1


if __name__ == "__main__":
    raise SystemExit(main())

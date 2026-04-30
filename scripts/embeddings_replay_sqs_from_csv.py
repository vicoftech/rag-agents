#!/usr/bin/env python3
"""
Recorre un CSV (columnas: key, s3_uri, size opcional) y dispara StartExecution
de una State Machine por cada fila para reprocesar ingestas.

Uso (QA):
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --dry-run
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main
  # Enviar todos los prefix del CSV, o filtrar solo ANMAT:
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --all-prefixes
  cd scripts && python embeddings_replay_sqs_from_csv.py --profile asap_main --only-prefix tenant_anmat
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print("Falta boto3. Instala: pip install -r requirements.txt (desde scripts/)", file=sys.stderr)
    raise SystemExit(1) from e


def _safe_name_part(value: str) -> str:
    safe = []
    for c in value:
        if c.isalnum() or c in "-_":
            safe.append(c)
        else:
            safe.append("-")
    out = "".join(safe).strip("-")
    return out[:40] if out else "doc"


def _run_suffix() -> str:
    """
    Sufijo corto por corrida para evitar ExecutionAlreadyExists al reintentar.
    """
    return datetime.now(timezone.utc).strftime("%m%d%H%M%S")


def _from_key(key: str, default_tenant: str, default_agent: str) -> dict[str, str]:
    """
    Intenta inferir tenant/agent/document_name desde key.
    Estructura esperada típica: <tenant>/<agent>/.../<document_name>.
    """
    clean = key.lstrip("/")
    parts = [p for p in clean.split("/") if p]
    tenant_id = default_tenant
    agent_id = default_agent
    if len(parts) >= 1 and parts[0]:
        tenant_id = parts[0]
    if len(parts) >= 2 and parts[1]:
        agent_id = parts[1]
    document_name = parts[-1] if parts else clean
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "document_name": document_name,
    }


def _build_sfn_input(
    bucket: str,
    key: str,
    default_tenant: str,
    default_agent: str,
) -> dict[str, Any]:
    attrs = _from_key(key, default_tenant, default_agent)
    return {
        "bucket": bucket,
        "key": urllib.parse.unquote_plus(key),
        "tenant_id": attrs["tenant_id"],
        "agent_id": attrs["agent_id"],
        "document_id": str(uuid.uuid4()),
        "document_name": attrs["document_name"],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


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
        description="Disparar StartExecution de SFN por cada key del CSV."
    )
    p.add_argument(
        "--csv",
        default="s3_prod_tenant_anmat_boletin_uris.csv",
        help="Ruta al CSV (convive en scripts/ con el listado S3).",
    )
    p.add_argument(
        "--state-machine-arn",
        required=True,
        help="ARN de la State Machine de ingesta RAG.",
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
        help="Segundos de pausa entre cada StartExecution",
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
    p.add_argument(
        "--default-tenant-id",
        default="tenant_boletin",
        help="Tenant default si no se puede inferir desde key.",
    )
    p.add_argument(
        "--default-agent-id",
        default="25abefca-8e5c-4c6e-973d-2fad3af8b469",
        help="Agent default si no se puede inferir desde key.",
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

    print(f"Disparando {n} ejecuciones en {args.state_machine_arn} (bucket={args.bucket})")

    if args.dry_run:
        k0, _ = rows[0]
        payload = _build_sfn_input(
            args.bucket, k0, args.default_tenant_id, args.default_agent_id
        )
        print("Primer input SFN (ejemplo):")
        body = json.dumps(payload, ensure_ascii=False)
        print((body[:800] + "…\n") if len(body) > 800 else body)
        return 0

    session = boto3.session.Session(profile_name=args.profile, region_name=args.region)
    sfn = session.client("stepfunctions", region_name=args.region)
    run_suffix = _run_suffix()

    successful = 0
    for i, (key, _size) in enumerate(rows):
        payload = _build_sfn_input(
            args.bucket, key, args.default_tenant_id, args.default_agent_id
        )
        doc = _safe_name_part(payload["document_name"])
        name = f"csv-{run_suffix}-{i:06d}-{doc}"
        try:
            sfn.start_execution(
                stateMachineArn=args.state_machine_arn,
                name=name,
                input=json.dumps(payload, ensure_ascii=False),
            )
        except ClientError as e:
            print(f"Error start_execution en fila {i} key={key}: {e}", file=sys.stderr)
            return 1
        successful += 1
        if args.sleep > 0:
            time.sleep(args.sleep)
        done = i + 1
        if done % 200 == 0 or done == n:
            print(f"  … {done}/{n}")

    print(f"Listo. Ejecuciones iniciadas: {successful}")
    return 0 if successful == n else 1


if __name__ == "__main__":
    raise SystemExit(main())

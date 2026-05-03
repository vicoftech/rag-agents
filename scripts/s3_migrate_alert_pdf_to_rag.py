#!/usr/bin/env python3
"""
Copia objetos desde el bucket de alertas hacia el bucket RAG con layout canónico:

    {tenant}/{agent_uuid}/documents/{YYYYMMDD}/[<ruta relativa>]<archivo>

El primer segmento bajo ``documents/`` en formato YYYYMMDD define ``created_at`` al
insertar chunks (ver ``apps/rag_lmbd_embeddings/s3_rag_key.parse_s3_rag_key``).

La copia usa ``copy_object`` (evento S3 ``ObjectCreated:Copy``), suficiente para
colas/reglas que escuchen creación de objetos.

Fecha de partición por defecto: ``LastModified`` del objeto origen en UTC (YYYYMMDD).
Opcional: leer una clave de metadata del origen (ej. fecha documental ya cargada).

Ejemplo (defaults del proyecto prod):

  python3 scripts/s3_migrate_alert_pdf_to_rag.py --profile asap_main --dry-run
  python3 scripts/s3_migrate_alert_pdf_to_rag.py --profile asap_main
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    raise SystemExit(
        "Se requiere boto3 (pip install boto3). " + str(e)
    ) from e

DATE8_RE = re.compile(r"^\d{8}$")


def _parse_date_to_yyyymmdd(raw: str) -> str:
    s = (raw or "").strip()
    if DATE8_RE.match(s):
        return s
    # ISO fecha al inicio (YYYY-MM-DD o ISO-8601 con hora)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        day = s[:10]
        try:
            dt = datetime.strptime(day, "%Y-%m-%d")
            return dt.strftime("%Y%m%d")
        except ValueError:
            pass
    raise ValueError(f"No se pudo interpretar como fecha (use YYYYMMDD o YYYY-MM-DD): {raw!r}")


def _partition_yyyymmdd(
    head: dict,
    *,
    metadata_key: str | None,
) -> str:
    if metadata_key:
        meta = head.get("Metadata") or {}
        # boto3 devuelve keys en minúsculas a veces
        k = metadata_key.strip().lower()
        raw = None
        for mk, mv in meta.items():
            if mk.lower() == k:
                raw = mv
                break
        if raw:
            return _parse_date_to_yyyymmdd(raw)
    lm = head["LastModified"]
    if lm.tzinfo is None:
        lm = lm.replace(tzinfo=timezone.utc)
    return lm.astimezone(timezone.utc).strftime("%Y%m%d")


def _relative_suffix(source_key: str, source_prefix: str) -> str:
    p = source_prefix.rstrip("/") + "/"
    if source_key.startswith(p):
        rel = source_key[len(p) :].lstrip("/")
    else:
        rel = source_key.rsplit("/", 1)[-1]
    return rel or source_key.rsplit("/", 1)[-1]


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--profile", default="", help="Perfil AWS CLI (vacío = default/env)")
    p.add_argument("--region", default="us-east-1")
    p.add_argument(
        "--source-bucket",
        default="alert-backend-prod",
        help="Bucket origen",
    )
    p.add_argument(
        "--source-prefix",
        default="pdf/pdf/",
        help="Prefijo origen (termina en /)",
    )
    p.add_argument(
        "--dest-bucket",
        default="rag-documents-prod-913123310997",
        help="Bucket RAG destino",
    )
    p.add_argument(
        "--dest-base-key",
        default="tenant_anmat/51d1efe8-448e-4c58-8e3d-f74df1301e81",
        help=(
            "Prefijo destino sin /documents (se añade "
            "/documents/{YYYYMMDD}/...)"
        ),
    )
    p.add_argument(
        "--metadata-date-key",
        default="",
        metavar="KEY",
        help=(
            "Si se indica, intentar leer esta clave de metadata del objeto origen "
            "como fecha (YYYYMMDD o ISO); si falta o falla, usar LastModified."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo listar acciones, sin copiar",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="No sobrescribir si ya existe la misma key destino",
    )
    p.add_argument(
        "--max-keys",
        type=int,
        default=0,
        help="Máximo de objetos a procesar (0 = sin límite)",
    )
    args = p.parse_args()

    session = (
        boto3.Session(profile_name=args.profile, region_name=args.region)
        if args.profile
        else boto3.Session(region_name=args.region)
    )
    s3 = session.client("s3")

    src_bucket = args.source_bucket.strip()
    src_prefix = args.source_prefix
    if src_prefix and not src_prefix.endswith("/"):
        src_prefix += "/"
    dst_bucket = args.dest_bucket.strip()
    dest_base = args.dest_base_key.strip().strip("/")

    meta_key = (args.metadata_date_key or "").strip() or None

    paginator = s3.get_paginator("list_objects_v2")
    copied = 0
    skipped = 0
    errors = 0
    seen = 0

    for page in paginator.paginate(Bucket=src_bucket, Prefix=src_prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if key.endswith("/"):
                continue
            seen += 1
            if args.max_keys and seen > args.max_keys:
                print(
                    f"Límite --max-keys={args.max_keys} alcanzado; fin.",
                    file=sys.stderr,
                )
                print(
                    f"Resumen: copiados={copied} omitidos={skipped} errores={errors}",
                    file=sys.stderr,
                )
                raise SystemExit(0)

            try:
                head = s3.head_object(Bucket=src_bucket, Key=key)
            except ClientError as e:
                print(f"[ERROR] head {key}: {e}", file=sys.stderr)
                errors += 1
                continue

            try:
                ymd = _partition_yyyymmdd(head, metadata_key=meta_key)
            except ValueError as e:
                print(f"[ERROR] fecha {key}: {e}", file=sys.stderr)
                errors += 1
                continue

            rel = _relative_suffix(key, src_prefix)
            dest_key = f"{dest_base}/documents/{ymd}/{rel}"

            dest_uri = f"s3://{dst_bucket}/{dest_key}"
            src_uri = f"s3://{src_bucket}/{key}"

            if args.skip_existing:
                try:
                    s3.head_object(Bucket=dst_bucket, Key=dest_key)
                    print(f"[SKIP exists] {dest_uri}")
                    skipped += 1
                    continue
                except ClientError as e:
                    code = e.response.get("Error", {}).get("Code", "")
                    if code not in ("404", "NotFound", "NoSuchKey"):
                        print(f"[WARN] head dest {dest_key}: {e}", file=sys.stderr)

            merged_meta: dict[str, str] = {}
            for mk, mv in (head.get("Metadata") or {}).items():
                merged_meta[mk] = mv
            merged_meta["rag-migrated-from"] = src_uri
            merged_meta["rag-destination-uri"] = dest_uri
            merged_meta["rag-partition-date"] = ymd
            merged_meta["rag-destination-key"] = dest_key

            content_type = head.get("ContentType") or "application/octet-stream"

            if args.dry_run:
                print(f"[DRY-RUN] {src_uri} -> {dest_uri} (partition={ymd})")
                copied += 1
                continue

            try:
                s3.copy_object(
                    Bucket=dst_bucket,
                    Key=dest_key,
                    CopySource={"Bucket": src_bucket, "Key": key},
                    MetadataDirective="REPLACE",
                    Metadata=merged_meta,
                    ContentType=content_type,
                )
                print(f"[OK] {dest_uri}")
                copied += 1
            except ClientError as e:
                print(f"[ERROR] copy {key} -> {dest_key}: {e}", file=sys.stderr)
                errors += 1

    print(
        f"Listos: vistos={seen} copiados(o dry-run)={copied} "
        f"omitidos={skipped} errores={errors}",
        file=sys.stderr,
    )
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()

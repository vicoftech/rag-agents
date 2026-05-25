#!/usr/bin/env python3
"""
Re-dispara ingestión de embeddings copiando cada PDF sobre sí mismo en S3.

``copy_object`` al mismo bucket/key genera ``ObjectCreated:Copy``; la notificación
S3 → ``rag_lmbd_embeddings_enqueue`` → SQS → ``rag_lmbd_embeddings-async`` inserta
en ``tenant_*.documents``.

Pensado para manifiestos tipo ``tenant_boletin_s3_not_in_documents_*.json``
(ítems con ``s3_key`` / ``document_name``). No usa ``disposicion`` ni cambia la ruta.

Uso:
  python scripts/retrigger_s3_embeddings_from_manifest.py \\
    --manifest tenant_boletin_s3_not_in_documents_202605251132.json \\
    --profile asap_main --dry-run --max-items 5

  python scripts/retrigger_s3_embeddings_from_manifest.py \\
    --manifest tenant_boletin_s3_not_in_documents_202605251132.json \\
    --profile asap_main --delay-ms 100
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOG = logging.getLogger("retrigger_s3_embeddings")

_LOG_HEADER = "status\tdocument_name\ts3_key\tdetail\n"
_OK_STATUSES = frozenset({"copied", "dry_run"})
_ERROR_STATUSES = frozenset({"error", "missing_s3_key", "invalid_key"})


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"URI S3 inválida: {uri!r}")
    return p.netloc, p.path.lstrip("/")


def download_manifest_s3(uri: str, dest: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    boto3.client("s3").download_file(bucket, key, dest)


def load_manifest(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with open(path, encoding="utf-8") as f:
        meta = json.load(f)
    items = meta.get("items")
    if not isinstance(items, list):
        raise ValueError("Manifiesto sin lista 'items'")
    return meta, items


def _match_key_src(src_key: str) -> str:
    return f"src:{(src_key or '').strip()}"


def parse_ok_tsv_line(line: str) -> tuple[str, set[str]] | None:
    line = line.strip()
    if not line or line.startswith("status\t"):
        return None
    parts = line.split("\t")
    if len(parts) < 3:
        return None
    status = parts[0].strip()
    src_key = parts[2].strip() if len(parts) > 2 else ""
    keys: set[str] = set()
    if src_key:
        keys.add(_match_key_src(src_key))
    return status, keys


def load_completed_keys_from_ok_files(paths: list[str]) -> set[str]:
    completed: set[str] = set()
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                parsed = parse_ok_tsv_line(line)
                if not parsed:
                    continue
                status, keys = parsed
                if status in _OK_STATUSES:
                    completed |= keys
    return completed


def download_ok_logs_from_s3_prefix(
    s3_client: Any,
    *,
    bucket: str,
    prefix: str,
    dest_dir: str = "/tmp/retrigger_ok_logs",
) -> list[str]:
    prefix = prefix.strip().rstrip("/") + "/"
    os.makedirs(dest_dir, exist_ok=True)
    local_paths: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key") or ""
            base = key.rsplit("/", 1)[-1]
            if not base.startswith("ok_") or not base.endswith(".txt"):
                continue
            local = os.path.join(dest_dir, base.replace("/", "_"))
            s3_client.download_file(bucket, key, local)
            local_paths.append(local)
    return local_paths


def retrigger_copy_same_key(
    s3: Any,
    *,
    bucket: str,
    key: str,
    dry_run: bool,
    max_retries: int = 5,
    retry_base_sec: float = 2.0,
) -> str:
    key = (key or "").strip()
    if not key:
        return "invalid_key"
    if dry_run:
        return "dry_run"
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            meta = {str(k): str(v) for k, v in (head.get("Metadata") or {}).items()}
            content_type = head.get("ContentType") or "application/pdf"
            s3.copy_object(
                Bucket=bucket,
                Key=key,
                CopySource={"Bucket": bucket, "Key": key},
                MetadataDirective="REPLACE",
                Metadata=meta,
                ContentType=content_type,
            )
            return "copied"
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return "missing_s3_key"
            last_exc = e
        except BotoCoreError as e:
            last_exc = e
        if attempt < max_retries:
            time.sleep(retry_base_sec * (2**attempt))
    if last_exc is not None:
        raise last_exc
    return "error"


def _format_log_line(
    status: str,
    *,
    document_name: str = "",
    s3_key: str = "",
    detail: str = "",
) -> str:
    def esc(s: str) -> str:
        return (s or "").replace("\t", " ").replace("\n", " ")

    return f"{esc(status)}\t{esc(document_name)}\t{esc(s3_key)}\t{esc(detail)}\n"


class RunLog:
    def __init__(self) -> None:
        self.ok_lines: list[str] = []
        self.error_lines: list[str] = []

    def record(
        self,
        status: str,
        *,
        document_name: str = "",
        s3_key: str = "",
        detail: str = "",
    ) -> None:
        line = _format_log_line(
            status, document_name=document_name, s3_key=s3_key, detail=detail
        )
        if status in _OK_STATUSES:
            self.ok_lines.append(line)
        else:
            self.error_lines.append(line)

    def write_local(self, ok_path: str, error_path: str) -> None:
        with open(ok_path, "w", encoding="utf-8") as f:
            f.write(_LOG_HEADER)
            f.writelines(self.ok_lines)
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(_LOG_HEADER)
            f.writelines(self.error_lines)

    def upload_s3(
        self,
        s3: Any,
        *,
        bucket: str,
        prefix: str,
        run_id: str,
        ok_local: str,
        error_local: str,
    ) -> dict[str, str]:
        prefix = prefix.strip().rstrip("/") + "/"
        ok_key = f"{prefix}ok_{run_id}.txt"
        err_key = f"{prefix}errors_{run_id}.txt"
        s3.upload_file(ok_local, bucket, ok_key)
        s3.upload_file(error_local, bucket, err_key)
        return {
            "ok_s3_uri": f"s3://{bucket}/{ok_key}",
            "errors_s3_uri": f"s3://{bucket}/{err_key}",
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", help="Ruta local al JSON manifiesto")
    p.add_argument("--manifest-s3", help="s3://bucket/key del manifiesto")
    p.add_argument("--bucket", help="Bucket (default: campo bucket del manifiesto)")
    p.add_argument("--profile", default=None)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--delay-ms", type=int, default=0, help="Pausa entre copias (evitar picos)")
    p.add_argument("--max-retries", type=int, default=5, help="Reintentos por ítem ante fallo de red")
    p.add_argument(
        "--checkpoint-every",
        type=int,
        default=50,
        help="Subir ok parcial a S3 cada N ítems (0 = solo al final)",
    )
    p.add_argument("--report", default="/tmp/retrigger_s3_report.json")
    p.add_argument(
        "--log-s3-prefix",
        default=os.environ.get("RETRIGGER_LOG_S3_PREFIX", "manifests/retrigger-runs/"),
    )
    p.add_argument("--no-upload-logs", action="store_true")
    p.add_argument("--resume-ok", action="append", default=[], metavar="PATH")
    p.add_argument("--resume-ok-s3-prefix", default="")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    _configure_logging(args.verbose)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    LOG.info("Inicio retrigger run_id=%s dry_run=%s", run_id, args.dry_run)

    manifest_path = args.manifest
    if args.manifest_s3:
        manifest_path = manifest_path or "/tmp/retrigger_manifest.json"
        download_manifest_s3(args.manifest_s3, manifest_path)
    if not manifest_path or not os.path.isfile(manifest_path):
        LOG.error("Manifiesto no encontrado")
        return 2

    meta, items = load_manifest(manifest_path)
    bucket = (args.bucket or meta.get("bucket") or "").strip()
    if not bucket:
        LOG.error("Bucket no definido")
        return 2

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client("s3")

    ok_paths = list(args.resume_ok or [])
    if args.resume_ok_s3_prefix:
        ok_paths.extend(
            download_ok_logs_from_s3_prefix(
                s3, bucket=bucket, prefix=args.resume_ok_s3_prefix
            )
        )
    if ok_paths:
        completed = load_completed_keys_from_ok_files(ok_paths)
        before = len(items)
        items = [it for it in items if _match_key_src(it.get("s3_key") or "") not in completed]
        LOG.info("Resume: %s -> %s pendientes (ok logs)", before, len(items))

    if args.max_items and args.max_items > 0:
        items = items[: args.max_items]

    run_log = RunLog()
    counts: dict[str, int] = {}
    total = len(items)
    ok_local = f"/tmp/retrigger_ok_{run_id}.txt"
    err_local = f"/tmp/retrigger_errors_{run_id}.txt"
    run_log.write_local(ok_local, err_local)

    def maybe_checkpoint(i: int) -> None:
        if args.dry_run or args.no_upload_logs or not args.checkpoint_every:
            return
        if i % args.checkpoint_every != 0:
            return
        run_log.write_local(ok_local, err_local)
        run_log.upload_s3(
            s3,
            bucket=bucket,
            prefix=args.log_s3_prefix,
            run_id=f"{run_id}_checkpoint_{i}",
            ok_local=ok_local,
            error_local=err_local,
        )
        LOG.info("Checkpoint S3 tras %s ítems", i)

    for i, item in enumerate(items, start=1):
        key = (item.get("s3_key") or "").strip()
        if not key and (item.get("s3_uri") or "").strip().startswith("s3://"):
            _, key = _parse_s3_uri(item["s3_uri"])
        doc = (item.get("document_name") or "").strip()
        try:
            status = retrigger_copy_same_key(
                s3,
                bucket=bucket,
                key=key,
                dry_run=args.dry_run,
                max_retries=args.max_retries,
            )
        except (ClientError, BotoCoreError) as e:
            status = "error"
            detail = str(e)
            run_log.record(status, document_name=doc, s3_key=key, detail=detail)
            counts[status] = counts.get(status, 0) + 1
            LOG.warning("[%s/%s] %s %s: %s", i, total, status, key, detail)
            run_log.write_local(ok_local, err_local)
            raise
        counts[status] = counts.get(status, 0) + 1
        run_log.record(status, document_name=doc, s3_key=key)
        if i == 1 or i % 100 == 0 or i == total:
            LOG.info("[%s/%s] %s %s", i, total, status, key)
        if args.delay_ms > 0 and status == "copied":
            time.sleep(args.delay_ms / 1000.0)
        maybe_checkpoint(i)

    run_log.write_local(ok_local, err_local)

    log_uris: dict[str, str] = {}
    if not args.no_upload_logs and not args.dry_run:
        log_uris = run_log.upload_s3(
            s3,
            bucket=bucket,
            prefix=args.log_s3_prefix,
            run_id=run_id,
            ok_local=ok_local,
            error_local=err_local,
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "manifest": manifest_path,
        "bucket": bucket,
        "dry_run": args.dry_run,
        "processed": total,
        "counts": counts,
        "ok_local": ok_local,
        "errors_local": err_local,
        **log_uris,
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    LOG.info("Reporte: %s", args.report)
    LOG.info("Conteos: %s", counts)

    err_n = sum(counts.get(s, 0) for s in _ERROR_STATUSES)
    return 1 if err_n else 0


if __name__ == "__main__":
    raise SystemExit(main())

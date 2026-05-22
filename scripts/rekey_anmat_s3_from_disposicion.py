#!/usr/bin/env python3
"""
Reubica PDFs de ANMAT en S3 con partición YYYYMMDD según public.disposicion.

Lee un manifiesto JSON (p. ej. tenant_anmat_s3_not_in_documents_202605212328.json),
por cada ítem:
  1) Extrae el nombre de archivo (basename) desde document_name / s3_key
  2) Busca en disposicion por nombre_pdf
  3) Obtiene la fecha (fechayhora_revision o fallback fecha_de_publicacion)
  4) Copia el objeto en el mismo bucket bajo una key con esa fecha en la ruta documents/

Pensado para ECS Fargate (rol de tarea: S3 + Secrets Manager/DB). Sin --profile.

Variables de entorno:
  S3_DOCUMENTS_BUCKET     Bucket destino (default del manifiesto)
  DB_SECRET_ARN / DB_*    Conexión PostgreSQL
  DISPERSION_DATE_FIELD   fechayhora_revision | fecha_de_publicacion
  REKEY_LOG_S3_PREFIX     Prefijo S3 para ok.txt / errors.txt (default: manifests/rekey-runs/)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

try:
    import psycopg2
    from psycopg2.extensions import connection as PgConnection

    _PSYCOPG2 = True
except ImportError:
    _PSYCOPG2 = False
    PgConnection = Any  # type: ignore[misc, assignment]

LOG = logging.getLogger("rekey_anmat_s3")

DATE8_RE = re.compile(r"^\d{8}$")
DOCUMENTS_MARKER = "/documents/"

# Cabecera TSV para archivos en S3
_LOG_HEADER = "status\tbasename\tpartition\tsrc_key\tdst_key\tdetail\n"

# Estados que van a ok.txt (procesado sin fallo operativo)
_OK_STATUSES = frozenset({"copied", "dry_run", "skipped_same", "skipped_exists"})

# Estados que van a errors.txt
_ERROR_STATUSES = frozenset(
    {"error", "skipped_no_disposicion", "missing_s3_key", "invalid_key"}
)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def log_step(step: str, message: str, *args: Any, level: int = logging.INFO) -> None:
    """Traza numerada de pasos del job (visible en CloudWatch)."""
    LOG.log(level, "[STEP %s] %s", step, message % args if args else message)


def log_item_step(
    index: int,
    total: int,
    substep: str,
    message: str,
    *args: Any,
    level: int = logging.DEBUG,
) -> None:
    LOG.log(level, "[ITEM %s/%s] [%s] %s", index, total, substep, message % args if args else message)


def _connect_postgres() -> PgConnection:
    if not _PSYCOPG2:
        raise RuntimeError("psycopg2 no instalado")

    arn = (os.environ.get("DB_SECRET_ARN") or os.environ.get("DB_SECRET_ID") or "").strip()
    if arn:
        sm = boto3.client("secretsmanager")
        raw = sm.get_secret_value(SecretId=arn)
        secret = json.loads(raw.get("SecretString") or "{}")
        return psycopg2.connect(
            host=secret.get("host"),
            port=int(secret.get("port", 5432)),
            dbname=secret.get("dbname") or secret.get("database"),
            user=secret.get("username") or secret.get("user"),
            password=secret.get("password"),
            sslmode=os.environ.get("DB_SSLMODE", "require"),
            connect_timeout=30,
        )

    host = os.environ.get("DB_HOST", "").strip()
    dbname = os.environ.get("DB_NAME", "").strip()
    user = os.environ.get("DB_USER", "").strip()
    password = os.environ.get("DB_PASSWORD", "")
    port = int(os.environ.get("DB_PORT", "5432"))
    if not all([host, dbname, user, password]):
        raise RuntimeError("Faltan DB_SECRET_ARN o DB_HOST/DB_NAME/DB_USER/DB_PASSWORD")
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=str(password),
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=30,
    )


def _file_basename(name_or_key: str) -> str:
    s = (name_or_key or "").strip().replace("\\/", "/")
    if "/" in s:
        return s.rsplit("/", 1)[-1].strip()
    return s


def _timestamp_to_yyyymmdd(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y%m%d")


def load_disposicion_dates(
    conn: PgConnection,
    *,
    date_field: str,
) -> dict[str, str]:
    if date_field not in ("fechayhora_revision", "fecha_de_publicacion"):
        raise ValueError(f"date_field inválido: {date_field}")
    other = (
        "fecha_de_publicacion"
        if date_field == "fechayhora_revision"
        else "fechayhora_revision"
    )
    sql = f"""
        SELECT
            lower(trim(nombre_pdf)) AS archivo,
            max({date_field}) AS fecha_pri,
            max({other}) AS fecha_alt
        FROM public.disposicion
        WHERE coalesce(eliminado, false) = false
          AND nombre_pdf IS NOT NULL
          AND trim(nombre_pdf) <> ''
        GROUP BY lower(trim(nombre_pdf))
    """
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for archivo, fecha_pri, fecha_alt in cur.fetchall():
            ymd = _timestamp_to_yyyymmdd(fecha_pri) or _timestamp_to_yyyymmdd(fecha_alt)
            if archivo and ymd:
                out[str(archivo)] = ymd
    return out


def build_new_key(old_key: str, yyyymmdd: str) -> str:
    if not DATE8_RE.match(yyyymmdd):
        raise ValueError(f"YYYYMMDD inválido: {yyyymmdd!r}")
    idx = old_key.find(DOCUMENTS_MARKER)
    if idx < 0:
        raise ValueError(f"Key sin {DOCUMENTS_MARKER!r}: {old_key!r}")
    prefix = old_key[: idx + len(DOCUMENTS_MARKER)]
    rel = old_key[idx + len(DOCUMENTS_MARKER) :]
    parts = [p for p in rel.split("/") if p]
    if not parts:
        raise ValueError(f"Key sin archivo bajo documents/: {old_key!r}")
    if DATE8_RE.match(parts[0]):
        parts[0] = yyyymmdd
    else:
        parts.insert(0, yyyymmdd)
    return prefix + "/".join(parts)


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


def copy_object(
    s3,
    *,
    bucket: str,
    src_key: str,
    dst_key: str,
    dry_run: bool,
    skip_existing: bool,
) -> str:
    if src_key == dst_key:
        return "skipped_same"
    if skip_existing and not dry_run:
        try:
            s3.head_object(Bucket=bucket, Key=dst_key)
            return "skipped_exists"
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
    if dry_run:
        return "dry_run"
    s3.copy_object(
        Bucket=bucket,
        Key=dst_key,
        CopySource={"Bucket": bucket, "Key": src_key},
    )
    return "copied"


def _format_log_line(
    status: str,
    *,
    basename: str = "",
    partition: str = "",
    src_key: str = "",
    dst_key: str = "",
    detail: str = "",
) -> str:
    def esc(s: str) -> str:
        return (s or "").replace("\t", " ").replace("\n", " ")

    return (
        f"{esc(status)}\t{esc(basename)}\t{esc(partition)}\t"
        f"{esc(src_key)}\t{esc(dst_key)}\t{esc(detail)}\n"
    )


class RunLog:
    """Acumula líneas ok / error y las sube a S3 al finalizar."""

    def __init__(self) -> None:
        self.ok_lines: list[str] = []
        self.error_lines: list[str] = []

    def record(
        self,
        status: str,
        *,
        basename: str = "",
        partition: str = "",
        src_key: str = "",
        dst_key: str = "",
        detail: str = "",
    ) -> None:
        line = _format_log_line(
            status,
            basename=basename,
            partition=partition,
            src_key=src_key,
            dst_key=dst_key,
            detail=detail,
        )
        if status in _OK_STATUSES:
            self.ok_lines.append(line)
        elif status in _ERROR_STATUSES:
            self.error_lines.append(line)
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
            "ok_count": len(self.ok_lines),
            "errors_count": len(self.error_lines),
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", help="Ruta local al JSON manifiesto")
    p.add_argument("--manifest-s3", help="s3://bucket/key del manifiesto (ECS)")
    p.add_argument("--bucket", help="Bucket (default: manifiesto o S3_DOCUMENTS_BUCKET)")
    p.add_argument(
        "--date-field",
        default=os.environ.get("DISPERSION_DATE_FIELD", "fechayhora_revision"),
        choices=("fechayhora_revision", "fecha_de_publicacion"),
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delete-source", action="store_true")
    p.add_argument("--skip-existing", action="store_true", default=True)
    p.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--report", default="/tmp/rekey_anmat_report.json")
    p.add_argument(
        "--log-s3-prefix",
        default=os.environ.get("REKEY_LOG_S3_PREFIX", "manifests/rekey-runs/"),
        help="Prefijo en el bucket para ok_*.txt y errors_*.txt",
    )
    p.add_argument(
        "--no-upload-logs",
        action="store_true",
        help="No subir txt a S3 (solo escribir en /tmp)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    _configure_logging(args.verbose)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_step("00", "Inicio job rekey ANMAT run_id=%s dry_run=%s", run_id, args.dry_run)

    manifest_path = args.manifest
    if args.manifest_s3:
        log_step("01", "Descargar manifiesto desde %s", args.manifest_s3)
        manifest_path = manifest_path or "/tmp/anmat_rekey_manifest.json"
        download_manifest_s3(args.manifest_s3, manifest_path)
        log_step("01", "Manifiesto local: %s", manifest_path)
    elif manifest_path:
        log_step("01", "Manifiesto local: %s", manifest_path)
    else:
        log_step("01", "ERROR: falta --manifest o --manifest-s3", level=logging.ERROR)
        return 2

    if not manifest_path or not os.path.isfile(manifest_path):
        log_step("01", "ERROR: manifiesto no encontrado", level=logging.ERROR)
        return 2

    log_step("02", "Cargar manifiesto JSON")
    meta, items = load_manifest(manifest_path)
    bucket = (args.bucket or os.environ.get("S3_DOCUMENTS_BUCKET") or meta.get("bucket") or "").strip()
    if not bucket:
        log_step("02", "ERROR: bucket no definido", level=logging.ERROR)
        return 2
    log_step("02", "Ítems en manifiesto: %s | bucket: %s", len(items), bucket)

    if args.max_items > 0:
        items = items[: args.max_items]
        log_step("02", "Límite --max-items: procesando %s ítems", len(items))

    log_step("03", "Conectar PostgreSQL (disposicion)")
    conn = _connect_postgres()
    try:
        log_step("04", "Cargar mapa nombre_pdf → YYYYMMDD (campo=%s)", args.date_field)
        date_by_file = load_disposicion_dates(conn, date_field=args.date_field)
        log_step("04", "Entradas en mapa disposicion: %s", len(date_by_file))
    finally:
        conn.close()
        log_step("03", "Conexión PostgreSQL cerrada")

    s3 = boto3.client("s3")
    run_log = RunLog()
    stats: dict[str, int] = {
        "total": len(items),
        "copied": 0,
        "dry_run": 0,
        "skipped_same": 0,
        "skipped_exists": 0,
        "skipped_no_disposicion": 0,
        "errors": 0,
        "deleted_source": 0,
    }
    total = len(items)

    log_step("05", "Procesar ítems (total=%s)", total)
    for i, item in enumerate(items, 1):
        src_key = (item.get("s3_key") or "").strip()
        doc_name = (item.get("document_name") or "").strip()

        if not src_key:
            stats["errors"] += 1
            log_item_step(i, total, "VALIDATE", "sin s3_key en manifiesto", level=logging.WARNING)
            run_log.record(
                "missing_s3_key",
                src_key="",
                detail=json.dumps(item, ensure_ascii=False)[:500],
            )
            continue

        log_item_step(i, total, "EXTRACT", "document_name=%s s3_key=%s", doc_name, src_key)
        basename = _file_basename(doc_name or src_key).lower()
        log_item_step(i, total, "EXTRACT", "basename=%s", basename)

        log_item_step(i, total, "LOOKUP", "buscar en disposicion")
        ymd = date_by_file.get(basename)
        if ymd is None:
            stats["skipped_no_disposicion"] += 1
            log_item_step(
                i,
                total,
                "LOOKUP",
                "sin match en disposicion para basename=%s",
                basename,
                level=logging.WARNING,
            )
            run_log.record(
                "skipped_no_disposicion",
                basename=basename,
                src_key=src_key,
                detail="no hay nombre_pdf con fecha en disposicion",
            )
            continue

        log_item_step(i, total, "LOOKUP", "partition YYYYMMDD=%s", ymd)

        try:
            log_item_step(i, total, "BUILD_KEY", "calcular nueva key")
            dst_key = build_new_key(src_key, ymd)
            log_item_step(i, total, "BUILD_KEY", "dst_key=%s", dst_key)
        except ValueError as e:
            stats["errors"] += 1
            log_item_step(i, total, "BUILD_KEY", "ERROR: %s", e, level=logging.ERROR)
            run_log.record(
                "invalid_key",
                basename=basename,
                partition=ymd,
                src_key=src_key,
                detail=str(e),
            )
            continue

        try:
            log_item_step(i, total, "S3_COPY", "copiar (dry_run=%s)", args.dry_run)
            action = copy_object(
                s3,
                bucket=bucket,
                src_key=src_key,
                dst_key=dst_key,
                dry_run=args.dry_run,
                skip_existing=args.skip_existing,
            )
            stats[action] = stats.get(action, 0) + 1
            log_item_step(i, total, "S3_COPY", "resultado=%s", action, level=logging.INFO)

            run_log.record(
                action,
                basename=basename,
                partition=ymd,
                src_key=src_key,
                dst_key=dst_key,
                detail="delete_source=%s" % args.delete_source if action == "copied" else "",
            )

            if action == "copied" and args.delete_source and not args.dry_run:
                log_item_step(i, total, "S3_DELETE", "borrar origen %s", src_key)
                s3.delete_object(Bucket=bucket, Key=src_key)
                stats["deleted_source"] += 1
                log_item_step(i, total, "S3_DELETE", "origen eliminado")

        except ClientError as e:
            stats["errors"] += 1
            err_msg = str(e)
            log_item_step(i, total, "S3_COPY", "ERROR ClientError: %s", err_msg, level=logging.ERROR)
            run_log.record(
                "error",
                basename=basename,
                partition=ymd,
                src_key=src_key,
                dst_key=dst_key,
                detail=err_msg,
            )

        if i % 500 == 0:
            log_step("05", "Progreso %s/%s | stats=%s", i, total, stats)

    log_step("05", "Fin procesamiento ítems | stats=%s", stats)

    ok_local = f"/tmp/rekey_ok_{run_id}.txt"
    err_local = f"/tmp/rekey_errors_{run_id}.txt"
    log_step("06", "Escribir logs locales ok=%s errors=%s", ok_local, err_local)
    run_log.write_local(ok_local, err_local)
    log_step("06", "Líneas ok=%s errors=%s", len(run_log.ok_lines), len(run_log.error_lines))

    s3_log_uris: dict[str, Any] = {}
    if not args.no_upload_logs:
        log_step("07", "Subir logs a s3://%s/%s", bucket, args.log_s3_prefix)
        try:
            s3_log_uris = run_log.upload_s3(
                s3,
                bucket=bucket,
                prefix=args.log_s3_prefix,
                run_id=run_id,
                ok_local=ok_local,
                error_local=err_local,
            )
            log_step("07", "OK subido: %s", s3_log_uris.get("ok_s3_uri"))
            log_step("07", "Errores subido: %s", s3_log_uris.get("errors_s3_uri"))
        except ClientError as e:
            log_step("07", "ERROR al subir logs a S3: %s", e, level=logging.ERROR)
            s3_log_uris = {"upload_error": str(e)}
    else:
        log_step("07", "Omitido upload S3 (--no-upload-logs)")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "bucket": bucket,
        "manifest": manifest_path,
        "date_field": args.date_field,
        "dry_run": args.dry_run,
        "delete_source": args.delete_source,
        "stats": stats,
        "log_files_local": {"ok": ok_local, "errors": err_local},
        "log_files_s3": s3_log_uris,
        "log_format": "TSV columns: status, basename, partition, src_key, dst_key, detail",
    }
    log_step("08", "Escribir reporte JSON %s", args.report)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log_step("09", "Resumen final: %s", json.dumps(stats, ensure_ascii=False))
    log_step("09", "Reporte JSON: %s", args.report)
    if s3_log_uris.get("ok_s3_uri"):
        log_step("09", "Log OK en S3: %s (%s líneas)", s3_log_uris["ok_s3_uri"], s3_log_uris.get("ok_count"))
    if s3_log_uris.get("errors_s3_uri"):
        log_step(
            "09",
            "Log errores en S3: %s (%s líneas)",
            s3_log_uris["errors_s3_uri"],
            s3_log_uris.get("errors_count"),
        )

    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

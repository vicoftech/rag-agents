"""
SQS-triggered Lambda: persiste alertas en public.* leyendo chunks desde tenant_anmat.documents.
Una conexión por invocación; un commit por mensaje SQS (transacción aislada).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION = (
    os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
).strip()
_secrets_client = boto3.client("secretsmanager", region_name=_REGION)
_secret_cache: dict[str, Any] | None = None


def _get_db_secret() -> dict[str, Any]:
    global _secret_cache
    arn = (os.environ.get("DB_SECRET_ARN") or "").strip()
    if not arn:
        raise ValueError("DB_SECRET_ARN no está definido o está vacío")
    if _secret_cache is None:
        try:
            resp = _secrets_client.get_secret_value(SecretId=arn)
        except ClientError as e:
            raise RuntimeError(f"No se pudo leer el secreto de BD: {e}") from e
        raw = resp.get("SecretString") or "{}"
        _secret_cache = json.loads(raw)
    return _secret_cache


def _connect_from_env() -> PgConnection:
    """Conexión con variables planas (Terraform sin Secrets Manager, mismo patrón otras Lambdas)."""
    host = (os.environ.get("DB_HOST") or "").strip()
    dbname = (os.environ.get("DB_NAME") or "").strip()
    user = (os.environ.get("DB_USER") or "").strip()
    password = os.environ.get("DB_PASSWORD")
    port_s = (os.environ.get("DB_PORT") or "5432").strip()
    if not host or not dbname or not user or password is None or str(password) == "":
        raise ValueError(
            "Sin DB_SECRET_ARN: se requieren DB_HOST, DB_NAME, DB_USER y DB_PASSWORD"
        )
    try:
        port_i = int(port_s)
    except ValueError as e:
        raise ValueError(f"DB_PORT inválido: {port_s!r}") from e
    return psycopg2.connect(
        host=host,
        port=port_i,
        dbname=dbname,
        user=user,
        password=str(password),
        sslmode=(os.environ.get("DB_SSLMODE") or "require").strip() or "require",
        connect_timeout=30,
    )


def _connect() -> PgConnection:
    arn = (os.environ.get("DB_SECRET_ARN") or "").strip()
    if arn:
        s = _get_db_secret()
        host = s.get("host")
        dbname = s.get("dbname") or s.get("database")
        username = s.get("username") or s.get("user")
        password = s.get("password")
        port = s.get("port", 5432)
        if not host or not dbname or not username or not password:
            raise ValueError(
                "El secreto debe incluir host, dbname (o database), username y password"
            )
        try:
            port_i = int(port)
        except (TypeError, ValueError) as e:
            raise ValueError(f"port inválido en secreto: {port!r}") from e
        return psycopg2.connect(
            host=host,
            port=port_i,
            dbname=dbname,
            user=username,
            password=password,
            sslmode="require",
            connect_timeout=30,
        )
    return _connect_from_env()


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    # ISO con o sin Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"No se pudo interpretar como fecha/hora: {value!r}")


def _vector_sql_param(embedding: Any) -> Any:
    """Produce literal aceptado por ::vector o None."""
    if embedding is None:
        return None
    if isinstance(embedding, (bytes, memoryview)):
        embedding = embedding.tobytes().decode("utf-8", errors="replace")
    if isinstance(embedding, str):
        t = embedding.strip()
        if not t:
            return None
        if t.startswith("[") and t.endswith("]"):
            return t
        # a veces pg devuelve '{1,2,3}' estilo postgres
        if t.startswith("{") and t.endswith("}"):
            inner = t[1:-1]
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            return "[" + ",".join(parts) + "]"
        return t
    if isinstance(embedding, (list, tuple)):
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"
    raise TypeError(f"Tipo de embedding no soportado: {type(embedding)!r}")


def _validate_payload(data: dict[str, Any]) -> None:
    if "busqueda_id" not in data or data["busqueda_id"] is None:
        raise ValueError("Falta busqueda_id en el mensaje")
    disp = data.get("disposicion")
    if not isinstance(disp, dict):
        raise ValueError("disposicion debe ser un objeto con disposicion_id")
    did = disp.get("disposicion_id")
    if did is None or (isinstance(did, str) and not did.strip()):
        raise ValueError("Falta disposicion.disposicion_id")
    if "matched_chunk_ids" not in data:
        raise ValueError("Falta matched_chunk_ids en el mensaje")
    mids = data["matched_chunk_ids"]
    if not isinstance(mids, list):
        raise ValueError("matched_chunk_ids debe ser una lista")


def _process_one_record(conn: PgConnection, data: dict[str, Any]) -> None:
    _validate_payload(data)
    busqueda_id = int(data["busqueda_id"])
    disp = data["disposicion"]
    disposicion_id_str = str(disp["disposicion_id"]).strip()
    matched_ids = data["matched_chunk_ids"]
    estado_alerta = data.get("estado_alerta")
    fh_occ = _parse_timestamp(data.get("fechayhora_ocurrencia"))

    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO public.disposicion (
                descripcion,
                disposicion_id,
                eliminado,
                fecha_de_aparicion,
                fecha_de_publicacion,
                fechayhora_revision,
                nombre_pdf,
                revisado,
                url,
                archivo
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (disposicion_id) DO NOTHING
            """,
            (
                disp.get("descripcion"),
                disposicion_id_str,
                False,
                _parse_timestamp(disp.get("fecha_de_aparicion")),
                _parse_timestamp(disp.get("fecha_de_publicacion")),
                None,
                disp.get("nombre_pdf"),
                False,
                disp.get("url"),
                disp.get("archivo"),
            ),
        )
        cur.execute(
            "SELECT id FROM public.disposicion WHERE disposicion_id = %s",
            (disposicion_id_str,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(
                f"No se encontró disposicion_id={disposicion_id_str!r} tras upsert"
            )
        disposicion_pk = int(row[0])

        chunks_inserted = 0
        for chunk_id in matched_ids:
            if isinstance(chunk_id, str) and not re.fullmatch(r"-?\d+", chunk_id.strip()):
                logger.warning(
                    "matched_chunk_ids tiene entrada no numérica; se omite: %r",
                    chunk_id,
                )
                continue
            cid = int(chunk_id)
            cur.execute(
                """
                SELECT chunk_text, embedding
                FROM tenant_anmat.documents
                WHERE id = %s
                """,
                (cid,),
            )
            doc_row = cur.fetchone()
            if not doc_row:
                logger.warning(
                    "Chunk id=%s no existe en tenant_anmat.documents; se omite.",
                    cid,
                )
                continue
            chunk_text, embedding = doc_row
            vparam = _vector_sql_param(embedding)
            if vparam is None:
                cur.execute(
                    """
                    INSERT INTO public.disposicion_contenido
                        (contenido, disposicion_id, embedding_vector)
                    VALUES (%s, %s, NULL)
                    """,
                    (chunk_text, disposicion_pk),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO public.disposicion_contenido
                        (contenido, disposicion_id, embedding_vector)
                    VALUES (%s, %s, %s::vector)
                    """,
                    (chunk_text, disposicion_pk, vparam),
                )
            chunks_inserted += 1

        cur.execute(
            """
            INSERT INTO public.alerta_generada (
                eliminado,
                enviada,
                estado_alerta,
                fechayhora_ocurrencia,
                leido,
                busqueda_id,
                disposicion_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                False,
                False,
                estado_alerta,
                fh_occ,
                False,
                busqueda_id,
                disposicion_pk,
            ),
        )
        alerta_row = cur.fetchone()
        if not alerta_row:
            raise RuntimeError("INSERT en alerta_generada no devolvió id")
        alerta_id = int(alerta_row[0])

        conn.commit()
        logger.info(
            "Alerta creada: alerta_id=%s disposicion_id=%s busqueda_id=%s chunks_insertados=%s",
            alerta_id,
            disposicion_pk,
            busqueda_id,
            chunks_inserted,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    records = event.get("Records") or []
    failures: list[dict[str, str]] = []

    try:
        conn = _connect()
    except Exception as e:
        logger.exception("No se pudo conectar a la base de datos: %s", e)
        for rec in records:
            mid = rec.get("messageId")
            if mid:
                failures.append({"itemIdentifier": mid})
        return {"batchItemFailures": failures}

    try:
        for rec in records:
            if rec.get("eventSource") != "aws:sqs":
                continue
            mid = rec.get("messageId") or ""
            try:
                body_raw = rec.get("body") or "{}"
                if isinstance(body_raw, str):
                    payload = json.loads(body_raw)
                else:
                    payload = body_raw
                if not isinstance(payload, dict):
                    raise ValueError("El cuerpo del mensaje debe ser un objeto JSON")
                _process_one_record(conn, payload)
            except json.JSONDecodeError as e:
                logger.error("JSON inválido messageId=%s: %s", mid, e)
                if mid:
                    failures.append({"itemIdentifier": mid})
            except (ValueError, TypeError) as e:
                logger.error(
                    "Validación o datos inválidos messageId=%s: %s", mid, e
                )
                if mid:
                    failures.append({"itemIdentifier": mid})
            except Exception as e:
                logger.exception("Fallo al procesar messageId=%s: %s", mid, e)
                if mid:
                    failures.append({"itemIdentifier": mid})
    finally:
        conn.close()

    return {"batchItemFailures": failures}

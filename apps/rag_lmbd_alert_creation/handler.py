"""
SQS-triggered Lambda: persiste alertas en public.* leyendo chunks desde tenant_anmat.documents.
Una conexión por invocación; un commit por mensaje SQS (transacción aislada).

AL-05: si el mensaje trae enviada=true (email ya publicado por el batch RAG), en la misma transacción
se intenta UPDATE en public.busqueda (activo=false si aplica, last_fired_at / estado_alerta reconocidos).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
import psycopg2
from psycopg2 import errors as pg_errors
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


_PG_IDENT_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _pg_ident_ok(name: str) -> bool:
    return bool(name and _PG_IDENT_OK.match(name))


def _resolve_busqueda_table(cur: Any) -> tuple[str, str] | None:
    raw = (os.environ.get("ALERT_BUSQUEDA_TABLE") or "").strip()
    candidates: list[str] = []
    if raw and "." in raw:
        candidates.append(raw)
    env_key = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "dev").strip().upper() or "DEV"
    sch = (os.environ.get(f"DB_SCHEMA_{env_key}") or os.environ.get("DB_SCHEMA") or "public").strip()
    if _pg_ident_ok(sch):
        candidates.append(f"{sch}.busqueda")
    candidates.append("public.busqueda")
    seen: set[str] = set()
    for fq in candidates:
        if fq in seen:
            continue
        seen.add(fq)
        cur.execute("SELECT to_regclass(%s::text)", (fq,))
        row = cur.fetchone()
        if row and row[0]:
            s = str(row[0])
            if "." in s:
                a, b = s.split(".", 1)
                a, b = a.strip('"'), b.strip('"')
            else:
                a, b = "public", s.strip('"')
            if _pg_ident_ok(a) and _pg_ident_ok(b):
                return (a, b)
    return None


def _busqueda_column_types(cur: Any, schema: str, table: str) -> dict[str, str]:
    cur.execute(
        """
        SELECT lower(column_name), lower(data_type)
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {str(r[0]): str(r[1]) for r in cur.fetchall()}


def _type_is_integerish(dt: str) -> bool:
    return any(
        x in dt
        for x in (
            "integer",
            "smallint",
            "bigint",
            "serial",
            "bigserial",
            "smallserial",
        )
    )


def _type_is_textish(dt: str) -> bool:
    return "char" in dt or dt == "text" or "varchar" in dt


def _type_is_boolean(dt: str) -> bool:
    return dt == "boolean"


def _busqueda_fired_set_clause_and_params(
    col_types: dict[str, str], fired_at: datetime
) -> tuple[str, list[Any]] | None:
    parts: list[str] = []
    vals: list[Any] = []
    ct = {k.lower(): v.lower() for k, v in col_types.items()}

    if "last_fired_at" in ct:
        parts.append("last_fired_at = %s")
        vals.append(fired_at)
    for alt in ("fechayhora_ultimo_disparo", "fecha_ultimo_disparo", "ultimo_disparo_at"):
        if alt in ct:
            parts.append(f"{alt} = %s")
            vals.append(fired_at)

    fired_int_s = (os.environ.get("ALERT_BUSQUEDA_ESTADO_FIRED") or "2").strip()
    try:
        fired_int = int(fired_int_s)
    except ValueError:
        fired_int = 2
    fired_txt = (os.environ.get("ALERT_BUSQUEDA_ESTADO_FIRED_TEXT") or "FIRED").strip() or "FIRED"

    if "estado_alerta" in ct:
        dt = ct["estado_alerta"]
        if _type_is_integerish(dt):
            parts.append("estado_alerta = %s")
            vals.append(fired_int)
        elif _type_is_textish(dt):
            parts.append("estado_alerta = %s")
            vals.append(fired_txt)

    if "estado" in ct and "estado_alerta" not in ct:
        dt = ct["estado"]
        if _type_is_integerish(dt):
            parts.append("estado = %s")
            vals.append(fired_int)
        elif _type_is_textish(dt):
            parts.append("estado = %s")
            vals.append(fired_txt)

    if "status" in ct and "estado" not in ct and "estado_alerta" not in ct:
        dt = ct["status"]
        if _type_is_textish(dt) or _type_is_integerish(dt):
            parts.append("status = %s")
            vals.append(fired_txt if _type_is_textish(dt) else fired_int)

    if "activo" in ct and _type_is_boolean(ct["activo"]):
        if "permanente" in ct and _type_is_boolean(ct["permanente"]):
            parts.append(
                "activo = CASE WHEN COALESCE(permanente, false) THEN activo ELSE false END"
            )
        else:
            parts.append("activo = false")

    if not parts:
        return None
    return ", ".join(parts), vals


def _apply_busqueda_fired_update(cur: Any, busqueda_id: int, fired_at: datetime) -> int:
    """AL-05: marca busqueda disparada en la misma transacción que alerta_generada. Retorna rowcount."""
    rel = _resolve_busqueda_table(cur)
    if not rel:
        logger.warning(
            "AL-05: no se encontró tabla busqueda (to_regclass); omito UPDATE alert_id=%s",
            busqueda_id,
        )
        return 0
    schema, table = rel
    types_map = _busqueda_column_types(cur, schema, table)
    built = _busqueda_fired_set_clause_and_params(types_map, fired_at)
    if not built:
        logger.warning(
            "AL-05: busqueda sin columnas reconocibles para disparo (activo/last_fired_at/estado); "
            "omito UPDATE alert_id=%s",
            busqueda_id,
        )
        return 0
    set_sql, set_params = built
    cur.execute(
        f'UPDATE "{schema}"."{table}" SET {set_sql} WHERE id = %s',
        [*set_params, busqueda_id],
    )
    return int(cur.rowcount or 0)


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    """Normaliza flags booleanos opcionales recibidos por SQS."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"1", "true", "t", "yes", "y", "si", "sí"}:
            return True
        if s in {"0", "false", "f", "no", "n"}:
            return False
    return default


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


def _sync_sequence(cur: Any, table_name: str, pk_column: str = "id") -> None:
    """
    Re-sincroniza la secuencia SERIAL/BIGSERIAL al MAX(id) actual.
    Necesario en esquemas legacy con secuencias desfasadas.
    """
    cur.execute(
        """
        SELECT setval(
            pg_get_serial_sequence(%s, %s),
            GREATEST((SELECT COALESCE(MAX(id), 1) FROM {}), 1),
            true
        )
        """.format(table_name),
        (table_name, pk_column),
    )


def _process_one_record(conn: PgConnection, data: dict[str, Any]) -> None:
    _validate_payload(data)
    busqueda_id = int(data["busqueda_id"])
    disp = data["disposicion"]
    disposicion_id_str = str(disp["disposicion_id"]).strip()
    matched_ids = data["matched_chunk_ids"]
    estado_alerta = data.get("estado_alerta")
    fh_occ = _parse_timestamp(data.get("last_fired_at") or data.get("fechayhora_ocurrencia"))
    enviada = _parse_bool(data.get("enviada"), default=False)

    cur = conn.cursor()
    try:
        _sync_sequence(cur, "public.disposicion", "id")
        _sync_sequence(cur, "public.disposicion_contenido", "id")
        _sync_sequence(cur, "public.alerta_generada", "id")

        cur.execute(
            "SELECT id FROM public.disposicion WHERE disposicion_id = %s ORDER BY id ASC LIMIT 1",
            (disposicion_id_str,),
        )
        row = cur.fetchone()
        if row:
            disposicion_pk = int(row[0])
        else:
            insert_params = (
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
            )
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
                    RETURNING id
                    """,
                    insert_params,
                )
            except pg_errors.UniqueViolation:
                # Esquemas legacy pueden tener la secuencia de PK desfasada.
                conn.rollback()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT setval(
                        pg_get_serial_sequence('public.disposicion', 'id'),
                        GREATEST((SELECT COALESCE(MAX(id), 1) FROM public.disposicion), 1),
                        true
                    )
                    """
                )
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
                    RETURNING id
                    """,
                    insert_params,
                )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(
                    f"No se pudo crear/obtener disposicion_id={disposicion_id_str!r}"
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
                enviada,
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

        fired_ts = fh_occ if fh_occ is not None else datetime.now(timezone.utc)
        if enviada:
            busqueda_rc = _apply_busqueda_fired_update(cur, busqueda_id, fired_ts)
            if busqueda_rc == 0:
                logger.warning(
                    "AL-05: UPDATE busqueda sin filas afectadas para alert_id=%s",
                    busqueda_id,
                )

        conn.commit()
        logger.info(
            "Alerta creada: alerta_generada_id=%s disposicion_pk=%s busqueda_id=%s chunks_insertados=%s enviada=%s",
            alerta_id,
            disposicion_pk,
            busqueda_id,
            chunks_inserted,
            enviada,
        )
        if enviada:
            logger.info(
                "ALERT_FIRED: alert_id=%s status actualizado a FIRED",
                busqueda_id,
            )
        else:
            logger.info(
                "ALERT_PENDING: alert_id=%s status pendiente (enviada=false)",
                busqueda_id,
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

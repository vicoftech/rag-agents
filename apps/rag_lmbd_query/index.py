import os
import json
import math
import random
from time import sleep
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
import boto3
from botocore.exceptions import ClientError
import psycopg2
from lib.llmClient import LLMClient
from string import Template
import numpy as np
from pgvector.psycopg2 import register_vector

from lib.bedrock_embeddings import parse_embedding_vector
from lib.tenant_schema import resolve_schema_name
# AWS Session Setup (for local testing)
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID_DEV', "")
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY_DEV', "")

CORS_HEADERS = {
     "Access-Control-Allow-Origin": "*",
     "Access-Control-Allow-Headers": "*",
     "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
 }

session_args = {"region_name": AWS_REGION}

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    session_args.update({
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
        "region_name": AWS_REGION 
    })

endpoint_url = f"https://s3.{AWS_REGION}.amazonaws.com"
s3 = boto3.client('s3', endpoint_url=endpoint_url, **session_args)

bedrock = boto3.client("bedrock-runtime", **session_args)

# 🔐 Se deben pasar estas variables al Lambda (ENV VARS)
DB_NAME = os.getenv("DB_NAME","postgres")
DB_USER = os.getenv("DB_USER","postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD","postgres")
DB_HOST = os.getenv("DB_HOST","localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
MAIN_LLM_MODEL = os.getenv("MAIN_LLM_MODEL", "openai.gpt-oss-120b-1:0")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "openai.gpt-oss-20b-1:0")
#EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "cohere.embed-v4:0")
OUTPUT_TOKENS = os.getenv("OUTPUT_TOKENS", "2048")
MAX_EMBED_TEXT_LENGTH = 20000
BEDROCK_EMBED_MAX_ATTEMPTS = int(os.getenv("BEDROCK_EMBED_MAX_ATTEMPTS", "8"))
BEDROCK_EMBED_RETRY_BASE_SEC = float(os.getenv("BEDROCK_EMBED_RETRY_BASE_SEC", "2.0"))
BEDROCK_EMBED_RETRY_MAX_SEC = float(os.getenv("BEDROCK_EMBED_RETRY_MAX_SEC", "45.0"))
COHERE_TRUNCATE = os.getenv("COHERE_TRUNCATE", "RIGHT")
EXPECTED_EMBEDDING_DIM = int(os.getenv("EXPECTED_EMBEDDING_DIM", "1536"))
# Tamaño de página por defecto (chunks por página) y tope máximo.
DEFAULT_PAGE_SIZE = max(1, min(100, int(os.getenv("DEFAULT_PAGE_SIZE", "20"))))
MAX_PAGE_SIZE = max(1, min(500, int(os.getenv("MAX_PAGE_SIZE", "100"))))
# Retrocompat: si no se envía page_size, la búsqueda semántica usa SEMANTIC_TOP_K como fallback.
SEMANTIC_TOP_K = max(1, min(50, int(os.getenv("SEMANTIC_TOP_K", str(DEFAULT_PAGE_SIZE)))))
# Opcional: si MAX_SEMANTIC_DISTANCE está definido y > 0, filtrar vecinos por distancia coseno (<=).
# Sin variable o valor 0/off/none → no se filtra: se devuelven los SEMANTIC_TOP_K más cercanos.
_MAX_SEM_DIST_RAW = os.getenv("MAX_SEMANTIC_DISTANCE", "").strip().lower()
if _MAX_SEM_DIST_RAW in ("", "0", "none", "off", "false"):
    MAX_SEMANTIC_DISTANCE = None
else:
    try:
        MAX_SEMANTIC_DISTANCE = float(_MAX_SEM_DIST_RAW)
    except ValueError:
        MAX_SEMANTIC_DISTANCE = None
    if MAX_SEMANTIC_DISTANCE is not None and MAX_SEMANTIC_DISTANCE <= 0:
        MAX_SEMANTIC_DISTANCE = None

DOCUMENTS_S3_BUCKET = os.getenv("DOCUMENTS_S3_BUCKET", "")
PRESIGNED_URL_EXPIRES_SECONDS = int(os.getenv("PRESIGNED_URL_EXPIRES_SECONDS", "3600"))


def _http_json_response(status_code, payload, is_http_event=True):
    body = json.dumps(payload)
    if not is_http_event:
        return {"statusCode": status_code, "body": body}
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **CORS_HEADERS},
        "body": body,
    }


def _normalize_s3_key(raw_key: str) -> str:
    """Decode query param and reject traversal / empty keys."""
    if raw_key is None or not str(raw_key).strip():
        raise ValueError("key es requerido")
    key = urllib.parse.unquote(str(raw_key).strip(), errors="strict")
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError("key inválido")
    return key


def handle_presigned_download(event, is_http_event=True):
    """
    GET /presigned-url?key=<object-key>
    Devuelve JSON con URL firmada para descargar (GetObject) del bucket de documentos.
    """
    if not DOCUMENTS_S3_BUCKET:
        return _http_json_response(
            500,
            {"error": "DOCUMENTS_S3_BUCKET no configurado"},
            is_http_event,
        )

    params = event.get("queryStringParameters") or {}
    raw_key = params.get("key")
    try:
        object_key = _normalize_s3_key(raw_key)
    except ValueError as e:
        return _http_json_response(400, {"error": str(e)}, is_http_event)

    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": DOCUMENTS_S3_BUCKET, "Key": object_key},
            ExpiresIn=PRESIGNED_URL_EXPIRES_SECONDS,
        )
    except ClientError as e:
        return _http_json_response(
            500,
            {"error": "No se pudo generar la URL firmada", "detail": str(e)},
            is_http_event,
        )

    return _http_json_response(
        200,
        {
            "url": url,
            "expires_in": PRESIGNED_URL_EXPIRES_SECONDS,
            "bucket": DOCUMENTS_S3_BUCKET,
            "key": object_key,
        },
        is_http_event,
    )


def _is_presigned_url_route(event, http_method: str) -> bool:
    route_key = (event.get("routeKey") or "").strip()
    if route_key == "GET /presigned-url":
        return True
    path = (
        event.get("requestContext", {}).get("http", {}).get("path")
        or event.get("path")
        or ""
    )
    return http_method == "GET" and path.rstrip("/").endswith("presigned-url")


def _cohere_embed_extras():
    if "cohere" in EMBEDDINGS_MODEL.lower():
        return {"truncate": COHERE_TRUNCATE, "embedding_types": ["float"]}
    return {}


def parse_created_at_day(raw):
    """
    Opcional: filtra chunks por día de created_at en BD.

    Sin fecha efectiva (None, vacío, JSON null ya viene como None, o strings
    sentinela como 'null'/'none') → **no** se aplica filtro por día: la búsqueda
    vectorial usa toda la historia disponible para el resto de filtros
    (tenant, agent_id, document_name, etc.). No hay default al día anterior.
    Acepta 'YYYY-MM-DD' o ISO datetime (se usa solo el día civil en UTC).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.lower() in ("null", "none"):
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    except ValueError as e:
        raise ValueError(
            "created_at inválido: use YYYY-MM-DD o ISO-8601 (ej. 2026-03-15 o 2026-03-15T12:00:00Z)"
        ) from e


def resolve_created_at_bounds(created_at_raw, from_raw, to_raw):
    """
    Devuelve (inicio_utc_naive, fin_exclusivo_utc_naive) para filtrar created_at,
    o (None, None) si no hay filtro de fechas.

    - ``created_at_from`` / ``created_at_to`` (o ``fecha_desde`` / ``fecha_hasta`` en el body):
      rango inclusive de días civiles en UTC [from, to].
    - ``created_at`` solo: un día (compatibilidad).
    Si hay from o to, tienen prioridad sobre ``created_at`` solo.
    """
    d_from = parse_created_at_day(from_raw)
    d_to = parse_created_at_day(to_raw)
    if d_from is not None or d_to is not None:
        if d_from is not None and d_to is not None:
            if d_from > d_to:
                raise ValueError("created_at_from no puede ser posterior a created_at_to")
            start = datetime.combine(d_from, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
            end = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(
                tzinfo=None
            )
            return start, end
        if d_from is not None:
            start = datetime.combine(d_from, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
            return start, None
        end = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(
            tzinfo=None
        )
        return None, end

    d_single = parse_created_at_day(created_at_raw)
    if d_single is not None:
        start = datetime.combine(d_single, time.min, tzinfo=timezone.utc).replace(tzinfo=None)
        end = datetime.combine(d_single + timedelta(days=1), time.min, tzinfo=timezone.utc).replace(
            tzinfo=None
        )
        return start, end
    return None, None


def normalize_page(page) -> int:
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    return max(1, p)


def normalize_page_size(page_size) -> int:
    try:
        s = int(page_size)
    except (TypeError, ValueError):
        s = DEFAULT_PAGE_SIZE
    if s < 1:
        s = DEFAULT_PAGE_SIZE
    return min(MAX_PAGE_SIZE, s)


def pagination_meta(total_count: int, page: int, page_size: int) -> dict:
    total_pages = math.ceil(total_count / page_size) if page_size > 0 else 0
    return {
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }


def _documents_where_filters(document_name, agent_id, chunk_text, date_start, date_end):
    filters = []
    params = []
    if document_name:
        filters.append("document_name = %s")
        params.append(document_name)
    if agent_id:
        filters.append("agent_id = %s")
        params.append(agent_id)
    if chunk_text:
        filters.append("chunk_text = %s")
        params.append(chunk_text)
    if date_start is not None:
        filters.append("created_at >= %s")
        params.append(date_start)
    if date_end is not None:
        filters.append("created_at < %s")
        params.append(date_end)
    return filters, params


def _keyword_ilike_pattern(text: str) -> str:
    t = str(text).strip()
    if len(t) < 1:
        raise ValueError("La query no puede estar vacía para búsqueda por palabra clave")
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


# --- Database connection helper ---
def get_connection():
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )
    register_vector(conn)
    return conn


def normalize(v):
    v = np.array(v, dtype=np.float32).squeeze()
    n = np.linalg.norm(v)
    return v if n == 0 else v / n

def to_pgvector(vec):
    return "(" + ",".join(str(v) for v in vec) + ")"


def _is_bedrock_throttle(exc: BaseException) -> bool:
    if not isinstance(exc, ClientError):
        return False
    code = (exc.response.get("Error") or {}).get("Code", "")
    return code in ("ThrottlingException", "TooManyRequestsException")


def embed(text: str, input_type: str = "search_query"):
    """Consultas de búsqueda deben usar search_query (Cohere v4 / asimétrico)."""
    if len(text) > MAX_EMBED_TEXT_LENGTH:
        text = text[:MAX_EMBED_TEXT_LENGTH]

    payload = {"texts": [text], "input_type": input_type, **_cohere_embed_extras()}
    body = json.dumps(payload)

    last_exc = None
    for attempt in range(BEDROCK_EMBED_MAX_ATTEMPTS):
        try:
            response = bedrock.invoke_model(
                modelId=EMBEDDINGS_MODEL,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            vec = parse_embedding_vector(result, 0)
            return normalize(vec).tolist()
        except ClientError as e:
            last_exc = e
            if not _is_bedrock_throttle(e) or attempt >= BEDROCK_EMBED_MAX_ATTEMPTS - 1:
                raise
            delay = min(
                BEDROCK_EMBED_RETRY_BASE_SEC * (2**attempt) + random.uniform(0, 0.75),
                BEDROCK_EMBED_RETRY_MAX_SEC,
            )
            sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("embed: reintentos agotados sin excepción registrada")




# --- Semantic Search adaptado al nuevo esquema ---
def semantic_search(
    query,
    tenant_id,
    document_name=None,
    agent_id=None,
    chunk_text=None,
    date_start=None,
    date_end=None,
    page=1,
    page_size=None,
):
    """
    kNN semántico con conteo total y paginación.

    ``date_start`` / ``date_end``: límites en TIMESTAMP naive UTC (fin exclusivo).
    ``page`` 1-based; ``page_size`` por defecto DEFAULT_PAGE_SIZE o SEMANTIC_TOP_K si se pasa None.
    """
    page = normalize_page(page)
    if page_size is None:
        page_size = SEMANTIC_TOP_K
    page_size = normalize_page_size(page_size)
    offset = (page - 1) * page_size

    q_emb = embed(query, input_type="search_query")

    if not isinstance(q_emb, list):
        raise ValueError("El embedding debe ser una lista")
    if len(q_emb) != EXPECTED_EMBEDDING_DIM:
        raise ValueError(
            f"Embedding query tiene {len(q_emb)} dims; se esperaban {EXPECTED_EMBEDDING_DIM} "
            "(ajuste EXPECTED_EMBEDDING_DIM o output_dimension del modelo)"
        )

    q_emb_str = "[" + ",".join(str(float(x)) for x in q_emb) + "]"

    schema = resolve_schema_name(tenant_id)
    filters, fp = _documents_where_filters(
        document_name, agent_id, chunk_text, date_start, date_end
    )
    filters.append("embedding IS NOT NULL")
    where_sql = " AND ".join(filters)

    conn = get_connection()
    cur = conn.cursor()

    count_sql = f"SELECT COUNT(*) FROM {schema}.documents WHERE {where_sql}"
    cur.execute(count_sql, fp)
    total_count = int(cur.fetchone()[0])

    select_sql = f"""
        SELECT
            chunk_text,
            document_name,
            embedding <=> %s::vector AS distance
        FROM {schema}.documents
        WHERE {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s OFFSET %s
    """
    cur.execute(select_sql, [q_emb_str] + fp + [q_emb_str, page_size, offset])
    rows = cur.fetchall()
    cur.close()
    conn.close()

    matched_rows = [row for row in rows if row[2] is not None]
    if MAX_SEMANTIC_DISTANCE is not None:
        matched_rows = [row for row in matched_rows if row[2] <= MAX_SEMANTIC_DISTANCE]

    chunks = [row[0] for row in matched_rows]
    documents = sorted(set(row[1] for row in matched_rows))

    return chunks, documents, total_count


def keyword_search(
    query,
    tenant_id,
    document_name=None,
    agent_id=None,
    chunk_text=None,
    date_start=None,
    date_end=None,
    page=1,
    page_size=None,
):
    """
    Búsqueda por palabra clave en chunk_text (ILIKE case-insensitive).
    Cuenta todas las coincidencias con los mismos filtros y pagina (ORDER BY created_at DESC).
    """
    page = normalize_page(page)
    if page_size is None:
        page_size = DEFAULT_PAGE_SIZE
    page_size = normalize_page_size(page_size)
    offset = (page - 1) * page_size

    pattern = _keyword_ilike_pattern(query)
    schema = resolve_schema_name(tenant_id)
    filters, fp = _documents_where_filters(
        document_name, agent_id, chunk_text, date_start, date_end
    )
    filters.insert(0, "chunk_text ILIKE %s ESCAPE '\\'")
    fp_kw = [pattern] + fp
    where_sql = " AND ".join(filters)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {schema}.documents WHERE {where_sql}", fp_kw)
    total_count = int(cur.fetchone()[0])

    select_sql = f"""
        SELECT chunk_text, document_name, NULL::double precision
        FROM {schema}.documents
        WHERE {where_sql}
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT %s OFFSET %s
    """
    cur.execute(select_sql, fp_kw + [page_size, offset])
    rows = cur.fetchall()
    cur.close()
    conn.close()

    chunks = [row[0] for row in rows]
    documents = sorted(set(row[1] for row in rows))
    return chunks, documents, total_count




# --- Get prompt template of the agent ---
def get_prompt_template(tenant_id, agent_id):
    schema = resolve_schema_name(tenant_id)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        f"SELECT prompt_template FROM {schema}.agents WHERE agent_id = %s",
        (agent_id,)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        raise Exception("Agente no encontrado para ese tenant.")

    return row[0]

def apply_prompt_template(prompt_template: str, context: str, query: str) -> str:
    """
    Inserta {context} y {query} en un prompt template sin romper llaves adicionales.
    Incluye manejo de errores para casos donde el template esté malformado.
    """

    try:
        if not isinstance(prompt_template, str):
            raise ValueError("El prompt_template debe ser un string.")

        # 1. Escapar TODAS las llaves del template
        safe_template = (
            prompt_template
            .replace("{", "{{")
            .replace("}", "}}")
        )

        # 2. Restaurar SOLO las llaves de {context} y {query}
        safe_template = safe_template.replace("{{context}}", "{context}")
        safe_template = safe_template.replace("{{query}}", "{query}")

        # 3. Intentar aplicar format()
        final_prompt = safe_template.format(
            context=context,
            query=query
        )

        return final_prompt

    except KeyError as e:
        # Error típico cuando falta un placeholder
        raise Exception(f"El template contiene un placeholder no soportado: {e}")

    except ValueError as e:
        # Error típico sobre el tipo de datos
        raise Exception(f"Error en el template o los valores: {e}")

    except Exception as e:
        # Último recurso: errores desconocidos
        raise Exception(f"Error al aplicar el prompt template: {str(e)}")

# --- Main Lambda Handler ---
def handler(event, context):
    http_method = None
    try:
        http_method = (
            event.get("requestContext", {})
            .get("http", {})
            .get("method")
        )
    except Exception:
        http_method = None

    if not http_method:
        http_method = event.get("httpMethod")

    method_upper = str(http_method or "").upper()

    if http_method and method_upper == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            },
            "body": "",
        }

    is_http_event = bool(http_method)

    if is_http_event and _is_presigned_url_route(event, method_upper):
        return handle_presigned_download(event, is_http_event=True)

    if is_http_event:
        body = event.get("body") or "{}"
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return {
                    "statusCode": 400,
                    "headers": {
                        "Content-Type": "application/json",
                        **CORS_HEADERS,
                    },
                    "body": json.dumps({"error": "Invalid JSON body"}),
                }
        src = body
    else:
        src = event

    tenant_id = src.get("tenant_id")
    agent_id = src.get("agent_id")
    query = src.get("query")
    document_name = src.get("document_name")
    chunk_text = src.get("chunk_text")
    created_at_raw = src.get("created_at")
    if created_at_raw is None:
        created_at_raw = src.get("create_at")
    created_from = src.get("created_at_from") or src.get("fecha_desde")
    created_to = src.get("created_at_to") or src.get("fecha_hasta")
    search_type = str(src.get("search_type") or "semantic").strip().lower()
    page = src.get("page", 1)
    raw_page_size = src.get("page_size")

    if not tenant_id or not agent_id or not query:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": "Faltan tenant_id, agent_id o query"}),
        }
        if is_http_event:
            resp["headers"] = {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            }
        return resp

    try:
        resolve_schema_name(tenant_id)
    except ValueError as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            }
        return resp

    if search_type not in ("semantic", "keyword"):
        resp = {
            "statusCode": 400,
            "body": json.dumps(
                {
                    "error": "search_type inválido: use 'semantic' o 'keyword'",
                }
            ),
        }
        if is_http_event:
            resp["headers"] = {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            }
        return resp

    try:
        date_start, date_end = resolve_created_at_bounds(
            created_at_raw, created_from, created_to
        )
    except ValueError as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            }
        return resp

    page = normalize_page(page)
    if raw_page_size is None:
        page_size = DEFAULT_PAGE_SIZE
    else:
        page_size = normalize_page_size(raw_page_size)

    try:
        if search_type == "keyword":
            chunks, documents, total_count = keyword_search(
                query,
                tenant_id,
                document_name,
                agent_id,
                chunk_text,
                date_start,
                date_end,
                page=page,
                page_size=page_size,
            )
        else:
            chunks, documents, total_count = semantic_search(
                query,
                tenant_id,
                document_name,
                agent_id,
                chunk_text,
                date_start,
                date_end,
                page=page,
                page_size=page_size,
            )
    except ValueError as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {
                "Content-Type": "application/json",
                **CORS_HEADERS,
            }
        return resp

    pagination = pagination_meta(total_count, page, page_size)
    context_text = "\n\n".join(chunks)

    # Obtener prompt del agente
    agent_prompt = get_prompt_template(tenant_id, agent_id)

    # Construir prompt final
    prompt = apply_prompt_template(
        agent_prompt,
        context=context_text,
        query=query
    )

    # Llamar al modelo
    llmClient = LLMClient(bedrock,MAIN_LLM_MODEL,FALLBACK_LLM_MODEL)
    response = llmClient.generate(prompt)
    print(response)
    resp = {
        "statusCode": 200,
        "body": json.dumps(
            {
                "response": response,
                "contexts": chunks,
                "documents": documents,
                "total_ocurrencias": total_count,
                "total_paginas": pagination["total_pages"],
                "pagination": pagination,
                "search_type": search_type,
            }
        ),
    }
    if is_http_event:
        resp["headers"] = {
            "Content-Type": "application/json",
            **CORS_HEADERS,
        }
    return resp

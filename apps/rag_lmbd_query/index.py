import os
import json
import time
import re
import urllib.parse
from datetime import date, datetime, time as dt_time, timedelta, timezone
import boto3
from botocore.exceptions import ClientError
import psycopg2
from lib.llmClient import LLMClient
from string import Template
import numpy as np
from pgvector.psycopg2 import register_vector
from typing import Any
from decimal import Decimal

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
secretsmanager = boto3.client("secretsmanager", **session_args)

# 🔐 Se deben pasar estas variables al Lambda (ENV VARS)
DB_NAME = os.getenv("DB_NAME","postgres")
DB_USER = os.getenv("DB_USER","postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD","postgres")
DB_HOST = os.getenv("DB_HOST","localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_SECRET_ID = os.getenv("DB_SECRET_ID", "")
MAIN_LLM_MODEL = os.getenv("MAIN_LLM_MODEL", "openai.gpt-oss-120b-1:0")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "openai.gpt-oss-20b-1:0")
#EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "cohere.embed-v4:0")
OUTPUT_TOKENS = os.getenv("OUTPUT_TOKENS", "2048")
MAX_EMBED_TEXT_LENGTH = 20000
COHERE_TRUNCATE = os.getenv("COHERE_TRUNCATE", "RIGHT")
EXPECTED_EMBEDDING_DIM = int(os.getenv("EXPECTED_EMBEDDING_DIM", "1536"))
MAX_SEMANTIC_DISTANCE = float(os.getenv("MAX_SEMANTIC_DISTANCE", "0.45"))
# Si el umbral descarta todo, aún devolver al menos 1 (el mejor) si la SQL devolvió filas.
# N=0 en env se trata como 1 (nunca dejar contexto vacío cuando hay al menos 1 fila de vector search).
SEMANTIC_FALLBACK_TOP_N = int(os.getenv("SEMANTIC_FALLBACK_TOP_N", "5"))
# Pesos RRF por canal (fts spanish puede perder dígitos / barras → pata literal substring).
HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.45"))
HYBRID_LEXICAL_WEIGHT = float(os.getenv("HYBRID_LEXICAL_WEIGHT", "0.35"))
HYBRID_LITERAL_WEIGHT = float(os.getenv("HYBRID_LITERAL_WEIGHT", "0.35"))
# No ejecutar POSITION(substr) sobre consultas muy cortas (noise + full scan más caro proporcionalmente).
HYBRID_LITERAL_MIN_CHARS = int(os.getenv("HYBRID_LITERAL_MIN_CHARS", "3"))
HYBRID_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
# Por sesión: limita paralelismo del planner en la búsqueda híbrida (consultas grandes + disco
# del cluster sin margen pueden fallar en pgsql_tmp; ver logs "parallel worker").
# Vacío / "server" → no se envía SET (comportamiento por defecto del servidor).
_PG_MAX_PARALLEL_PER_GATHER_RAW = os.getenv("PG_MAX_PARALLEL_WORKERS_PER_GATHER", "0").strip()
_DB_SECRET_CACHE = None

def _pg_max_parallel_workers_per_gather_override() -> int | None:
    r = _PG_MAX_PARALLEL_PER_GATHER_RAW.lower()
    if not r or r in ("server", "default"):
        return None
    try:
        n = int(r)
    except ValueError:
        print(f"[retrieval] PG_MAX_PARALLEL_WORKERS_PER_GATHER inválido {_PG_MAX_PARALLEL_PER_GATHER_RAW!r}")
        return None
    return n if n >= 0 else None


def _apply_pg_retrieval_session_tuning(cursor) -> None:
    cap = _pg_max_parallel_workers_per_gather_override()
    if cap is None:
        return
    try:
        cursor.execute(
            "SET max_parallel_workers_per_gather = %s",
            (cap,),
        )
    except Exception as e:
        print(f"[retrieval] SET max_parallel_workers_per_gather={cap}: {e}")

DOCUMENTS_S3_BUCKET = os.getenv("DOCUMENTS_S3_BUCKET", "")
PRESIGNED_URL_EXPIRES_SECONDS = int(os.getenv("PRESIGNED_URL_EXPIRES_SECONDS", "3600"))
# Si el cliente no envía retrieval_limit, se usa este tope (híbrido más barato con valores menores).
DEFAULT_RETRIEVAL_LIMIT = int(os.getenv("DEFAULT_RETRIEVAL_LIMIT", "25"))
QUERY_JOB_TABLE_NAME = os.getenv("QUERY_JOB_TABLE_NAME", "").strip()
# BU-02: criterio validado localmente para TASK_390.
# Default: relevancia semántica pura (menor vector_distance primero).
# HYBRID conserva el ranking RRF legacy como alternativa explícita.
SEARCH_SORT_RELEVANCE = "relevance"
SEARCH_SORT_HYBRID = "hybrid"
SEARCH_SORT_DATE_DESC = "date_desc"
SEARCH_SORT_ALLOWED = {SEARCH_SORT_RELEVANCE, SEARCH_SORT_HYBRID, SEARCH_SORT_DATE_DESC}


API_V2_MAX_PAGE_SIZE = 50
API_V2_DEFAULT_PAGE_SIZE = 10


def _unversioned_query_api_version() -> str:
    """
    Versión usada por /query sin prefijo.

    Default de producto: v2. Se mantiene configurable para rollback puntual con
    UNVERSIONED_QUERY_API_VERSION=v1 sin requerir rutas nuevas.
    """
    version = str(os.getenv("UNVERSIONED_QUERY_API_VERSION", "v2")).strip().lower()
    if re.fullmatch(r"v\d+", version):
        return version
    return "v2"


def _extract_version_from_path(event: dict) -> str:
    explicit_version = str(event.get("api_version") or "").strip().lower()
    if re.fullmatch(r"v\d+", explicit_version):
        return explicit_version

    path = (
        event.get("requestContext", {}).get("http", {}).get("path")
        or event.get("rawPath")
        or event.get("path")
        or ""
    )
    m = re.search(r"/(v\d+)/query", path.rstrip("/"))
    if m:
        return m.group(1)
    if path.rstrip("/").endswith("/query"):
        return _unversioned_query_api_version()
    return "v1"


def _normalize_v2_body(body: dict) -> dict:
    """
    Normaliza body v2 para estrategia fetch-complete con paginación in-memory.

    TASK-399: Siempre obtiene 100 contexts de la BD (retrieval_limit=100),
    luego pagina en memoria según page/pageSize solicitados.
    """
    body = dict(body)
    page_size_raw = body.get("pageSize")
    if page_size_raw is not None:
        try:
            page_size = int(page_size_raw)
        except (TypeError, ValueError):
            raise ValueError("pageSize debe ser un entero")
    else:
        page_size = API_V2_DEFAULT_PAGE_SIZE
    if page_size < 1 or page_size > API_V2_MAX_PAGE_SIZE:
        raise ValueError(
            f"pageSize debe estar entre 1 y {API_V2_MAX_PAGE_SIZE}"
        )
    page_raw = body.get("page")
    if page_raw is not None:
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            raise ValueError("page debe ser un entero")
    else:
        page = 1
    if page < 1:
        raise ValueError("page debe ser >= 1")
    # TASK-399: Fetch completo de 100 contexts para paginación in-memory
    body["retrieval_limit"] = 100
    body["_page"] = page
    body["_page_size"] = page_size
    sort_raw = body.get("sort")
    if sort_raw is not None and str(sort_raw).strip():
        body["sort_by"] = str(sort_raw).strip()
    return body


def _build_v2_response(v1_body: dict, page: int, page_size: int) -> dict:
    """
    Construye respuesta v2 con formato estándar PAGINADO_ESTANDAR.md.

    TASK-399: Formato simplificado sin campo documents.
    - data: array de context_items paginados en memoria
    - pagination: {page, pageSize, hasNext, hasPrevious}
    - metadata: {response, retrieval_config}
    """
    full_context_items = v1_body.get("context_items", [])
    response_text = v1_body.get("response")
    retrieval_config = v1_body.get("retrieval_config", {})

    # Paginar context_items en memoria
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_context_items = full_context_items[start_idx:end_idx]

    # Calcular hasNext/hasPrevious
    total_items = len(full_context_items)
    has_next = end_idx < total_items
    has_previous = page > 1

    return {
        "data": page_context_items,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "hasNext": has_next,
            "hasPrevious": has_previous,
        },
        "metadata": {
            "response": response_text,
            "retrieval_config": retrieval_config,
        },
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dynamo_numbers(obj):
    """Convierte floats anidados a Decimal para atributos DynamoDB tipo M."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamo_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamo_numbers(v) for v in obj]
    return obj


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
    try:
        key = urllib.parse.unquote(str(raw_key).strip(), errors="strict")
    except UnicodeDecodeError as e:
        raise ValueError("key con codificación porcentual inválida") from e
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError("key inválido")
    return key


def _presigned_query_params(event: dict[str, Any]) -> dict[str, str]:
    """queryStringParameters puede ser null en API Gateway HTTP API; fallback a rawQueryString."""
    qp = event.get("queryStringParameters")
    if qp and isinstance(qp, dict):
        return {str(k): "" if v is None else str(v) for k, v in qp.items()}
    raw = (event.get("rawQueryString") or "").strip()
    if not raw:
        return {}
    parsed = urllib.parse.parse_qsl(raw, keep_blank_values=True, strict_parsing=False)
    return {k: v for k, v in parsed}


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

    params = _presigned_query_params(event)
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


def _document_dedupe_key(row) -> str:
    """Clave estable BU-01 para colapsar chunks del mismo documento."""
    document_name = str(row[2] or "").strip()
    if document_name:
        return f"name:{document_name}"
    document_id = str(row[5] or "").strip() if len(row) > 5 else ""
    if document_id:
        return f"id:{document_id}"
    chunk_id = str(row[0] or "").strip()
    return f"chunk:{chunk_id}"


def dedupe_rows_by_document(rows: list, *, limit: int | None = None) -> list:
    """
    BU-01: conserva solo el mejor chunk por documento.

    Recibe filas ya ordenadas por relevancia (rrf_score DESC, vector_distance ASC) y
    preserva la primera aparición de cada document_name/document_id.
    """
    seen: set[str] = set()
    out = []
    for row in rows:
        key = _document_dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if limit is not None and len(out) >= limit:
            break
    return out


def normalize_search_sort_by(raw_sort_by: Any) -> str:
    """Valida sort_by con allowlist para no construir ORDER BY arbitrario."""
    sort_by = str(raw_sort_by or SEARCH_SORT_RELEVANCE).strip().lower()
    if not sort_by:
        sort_by = SEARCH_SORT_RELEVANCE
    if sort_by not in SEARCH_SORT_ALLOWED:
        allowed = ", ".join(sorted(SEARCH_SORT_ALLOWED))
        raise ValueError(f"sort_by inválido: {sort_by!r}. Valores permitidos: {allowed}")
    return sort_by


def search_order_clause(sort_by: str) -> str:
    """
    BU-02: orden final de resultados.

    - relevance: menor vector_distance primero; tie-break por RRF.
    - hybrid: ranking RRF legacy; tie-break por vector_distance.
    - date_desc: documentos más recientes primero; tie-break por relevancia.
    """
    normalized = normalize_search_sort_by(sort_by)
    if normalized == SEARCH_SORT_RELEVANCE:
        return "vector_distance ASC NULLS LAST, rrf_score DESC, created_at DESC NULLS LAST"
    if normalized == SEARCH_SORT_DATE_DESC:
        return "created_at DESC NULLS LAST, vector_distance ASC NULLS LAST, rrf_score DESC"
    return "rrf_score DESC, vector_distance ASC NULLS LAST, created_at DESC NULLS LAST"


def ordered_unique_documents(rows: list) -> list[str]:
    """Devuelve nombres de documentos en el mismo orden final de context_items."""
    seen: set[str] = set()
    docs: list[str] = []
    for row in rows:
        doc = str(row[2] or "").strip()
        if doc and doc not in seen:
            seen.add(doc)
            docs.append(doc)
    return docs


def extract_document_date(document_name: str) -> date | None:
    """
    BU-04: Extrae fecha del documento desde document_name.

    Patrones soportados (en orden de prioridad):
    1. ANMAT aviso: aviso_YYYY_YYYYMMDD_default_NNNNNN.pdf → YYYY-MM-DD
    2. YYYYMMDD (8 dígitos consecutivos): 20260512/aviso_...pdf → 2026-05-12
    3. YYYY-MM-DD con guiones: informe_2026-05-15.pdf → 2026-05-15
    4. Dispo_NNNN-YY: Dispo_3618-24.pdf → 2024-01-01 (solo año)

    Args:
        document_name: Nombre del documento (puede incluir path)

    Returns:
        date object si se puede extraer, None si no se encuentra patrón válido.

    Examples:
        >>> extract_document_date("aviso_2010_20100601_default_035149.pdf")
        date(2010, 6, 1)
        >>> extract_document_date("20260512/segunda/aviso_segunda_20260512.pdf")
        date(2026, 5, 12)
        >>> extract_document_date("Dispo_3618-24.pdf")
        date(2024, 1, 1)
        >>> extract_document_date("documento_sin_fecha.pdf")
        None
    """
    if not document_name or not isinstance(document_name, str):
        return None

    # Limpiar query strings (ej: "20260511?anexos=1/primera/aviso...")
    filename = document_name.split('?')[0].strip().lower()

    # Patrón 1: ANMAT aviso (más específico: aviso_YYYY_YYYYMMDD_default_NNNNNN.pdf)
    match = re.search(r'aviso_\d{4}_(\d{8})_default_\d+\.pdf', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d').date()
        except ValueError:
            pass  # Fecha inválida (ej: 20261332), continuar con otros patrones

    # Patrón 2: YYYYMMDD genérico (8 dígitos consecutivos) - Boletín Oficial
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d').date()
        except ValueError:
            pass  # No es una fecha válida

    # Patrón 3: YYYY-MM-DD con guiones
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', filename)
    if match:
        try:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(y, m, d)
        except ValueError:
            pass

    # Patrón 4: Dispo_NNNN-YY (solo año, menos preciso)
    match = re.search(r'dispo_\d+-(\d{2})\.pdf', filename)
    if match:
        year = 2000 + int(match.group(1))
        if 2000 <= year <= 2099:  # Validar rango razonable
            return date(year, 1, 1)  # Default al 1 de enero

    # No se pudo extraer fecha
    return None


def parse_created_at_day(raw):
    """
    Opcional: filtra chunks por día de created_at en BD.
    None / vacío → sin filtro (búsqueda general).
    Acepta 'YYYY-MM-DD' o ISO datetime (se usa solo el día civil en UTC).
    """
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    s = str(raw).strip()
    if s.lower() in {"null", "none"}:
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


def resolve_created_at_bounds(
    single_raw,
    created_at_start: str | None,
    created_at_end: str | None,
) -> tuple[datetime | None, datetime | None]:
    """
    Devuelve (inicio_inclusivo, fin_exclusivo) en tiempo naive UTC para filtrar ``created_at`` en SQL.
    Rango ``created_at_start``/``created_at_end`` (YYYY-MM-DD o ISO día) tiene prioridad sobre un solo día.
    """
    cs = (created_at_start or "").strip() if isinstance(created_at_start, str) else ""
    ce = (created_at_end or "").strip() if isinstance(created_at_end, str) else ""
    if cs and ce:
        d0 = parse_created_at_day(cs)
        d1 = parse_created_at_day(ce)
        if d1 < d0:
            raise ValueError(
                "created_at_end debe ser >= created_at_start "
                f"(obtuve {d1.isoformat()} < {d0.isoformat()})"
            )
        start = datetime.combine(d0, dt_time.min, tzinfo=timezone.utc)
        end_exc = datetime.combine(d1 + timedelta(days=1), dt_time.min, tzinfo=timezone.utc)
        return start.replace(tzinfo=None), end_exc.replace(tzinfo=None)
    if single_raw is None or (isinstance(single_raw, str) and not str(single_raw).strip()):
        return None, None
    d = parse_created_at_day(single_raw)
    if d is None:
        return None, None
    start = datetime.combine(d, dt_time.min, tzinfo=timezone.utc)
    end_exc = start + timedelta(days=1)
    return start.replace(tzinfo=None), end_exc.replace(tzinfo=None)


def pagination_meta(total_count: int, page_num: int, page_size: int) -> dict[str, Any]:
    """Metadatos de paginación (``page_num`` 1-based)."""
    psz = max(1, int(page_size))
    tcp = max(0, int(total_count))
    total_pages = (tcp + psz - 1) // psz if tcp > 0 else 0
    pn = max(1, int(page_num))
    has_next = bool(total_pages and pn < total_pages)
    return {"total_count": tcp, "total_pages": total_pages, "has_next": has_next}


def _resolve_db_credentials():
    global _DB_SECRET_CACHE
    if DB_SECRET_ID:
        if _DB_SECRET_CACHE is None:
            resp = secretsmanager.get_secret_value(SecretId=DB_SECRET_ID)
            raw = resp.get("SecretString", "{}")
            payload = json.loads(raw)
            user = payload.get("username") or payload.get("user")
            password = payload.get("password") or payload.get("pass")
            if not user or not password:
                raise ValueError("Secret must include username/user and password/pass")
            _DB_SECRET_CACHE = (user, password)
        return _DB_SECRET_CACHE
    return DB_USER, DB_PASSWORD


# --- Database connection helper ---
def get_connection():
    user, password = _resolve_db_credentials()
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=user,
        password=password,
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

def embed(text: str, input_type: str = "search_query"):
    """Consultas de búsqueda deben usar search_query (Cohere v4 / asimétrico)."""
    if len(text) > MAX_EMBED_TEXT_LENGTH:
        text = text[:MAX_EMBED_TEXT_LENGTH]

    payload = {"texts": [text], "input_type": input_type, **_cohere_embed_extras()}

    response = bedrock.invoke_model(
        modelId=EMBEDDINGS_MODEL,
        body=json.dumps(payload),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    vec = parse_embedding_vector(result, 0)
    return normalize(vec).tolist()




# --- Semantic Search adaptado al nuevo esquema (pgvector + FTS + RRF) ---
def semantic_search(
    query,
    tenant_id,
    document_name=None,
    agent_id=None,
    chunk_text=None,
    created_at_day=None,
    created_at_start=None,
    created_at_end=None,
    k=50,
    *,
    rrf_k=None,
    vector_weight=None,
    lexical_weight=None,
    literal_weight=None,
    literal_keyword_overlap=True,
    literal_min_chars_override=None,
    max_semantic_distance=None,
    semantic_fallback_top_n=None,
    sort_by=None,
):
    sort_by_norm = normalize_search_sort_by(sort_by)
    order_sql = search_order_clause(sort_by_norm)
    max_sd = (
        MAX_SEMANTIC_DISTANCE if max_semantic_distance is None else float(max_semantic_distance)
    )
    fb_n = (
        SEMANTIC_FALLBACK_TOP_N
        if semantic_fallback_top_n is None
        else int(semantic_fallback_top_n)
    )

    rk = HYBRID_RRF_K if rrf_k is None else int(rrf_k)
    vw = HYBRID_VECTOR_WEIGHT if vector_weight is None else float(vector_weight)
    lw = HYBRID_LEXICAL_WEIGHT if lexical_weight is None else float(lexical_weight)
    if literal_weight is not None:
        lit_w = float(literal_weight)
    elif literal_keyword_overlap is False:
        lit_w = 0.0
    else:
        lit_w = float(HYBRID_LITERAL_WEIGHT)

    _t_semantic0 = time.perf_counter()
    _t_embed0 = time.perf_counter()
    q_emb = embed(query, input_type="search_query")
    _embed_ms = (time.perf_counter() - _t_embed0) * 1000.0

    if not isinstance(q_emb, list):
        raise ValueError("El embedding debe ser una lista")
    if len(q_emb) != EXPECTED_EMBEDDING_DIM:
        raise ValueError(
            f"Embedding query tiene {len(q_emb)} dims; se esperaban {EXPECTED_EMBEDDING_DIM}"
        )

    q_emb_str = "[" + ",".join(str(float(x)) for x in q_emb) + "]"

    filter_clauses: list[str] = []
    filter_params: list = []

    if document_name:
        filter_clauses.append("d.document_name = %s")
        filter_params.append(document_name)
    if agent_id:
        filter_clauses.append("d.agent_id = %s")
        filter_params.append(agent_id)
    if chunk_text:
        filter_clauses.append("d.chunk_text = %s")
        filter_params.append(chunk_text)

    ca_lo, ca_hi_exc = resolve_created_at_bounds(
        created_at_day, created_at_start, created_at_end
    )
    if ca_lo is not None and ca_hi_exc is not None:
        filter_clauses.append("d.created_at >= %s AND d.created_at < %s")
        filter_params.extend([ca_lo, ca_hi_exc])

    where_sql = ("WHERE " + " AND ".join(filter_clauses)) if filter_clauses else ""

    _t_db0 = time.perf_counter()
    schema = resolve_schema_name(tenant_id)
    conn = get_connection()
    cur = conn.cursor()
    _apply_pg_retrieval_session_tuning(cur)

    q_plain = (query or "").strip()
    lit_min = (
        int(literal_min_chars_override)
        if literal_min_chars_override is not None
        else HYBRID_LITERAL_MIN_CHARS
    )
    include_literal = lit_w > 0 and len(q_plain) >= max(1, lit_min)
    lit_sql_weight = float(lit_w) if include_literal else 0.0
    # BU-01: sobre-muestrear candidatos para poder deduplicar por documento
    # sin quedarse sin resultados únicos cuando varios chunks del mismo PDF rankean arriba.
    candidate_limit = min(max(int(k) * 3, int(k)), 500)

    if include_literal:
        # No reutilizar where_sql aquí: ya incluye "WHERE"; hay que fusionar una sola cláusula.
        literal_where_parts = [
            "POSITION(LOWER(%s::text) IN LOWER(d.chunk_text)) > 0",
            *filter_clauses,
        ]
        literal_where_sql = "WHERE " + " AND ".join(literal_where_parts)
        literal_cte = f"""
        literal_ranked AS (
            SELECT
                d.id,
                d.ctid,
                d.chunk_text,
                d.document_name,
                d.document_id,
                d.created_at,
                ROW_NUMBER() OVER (
                    ORDER BY POSITION(LOWER(%s::text) IN LOWER(d.chunk_text)) ASC,
                             d.ctid
                ) AS lit_rank
            FROM {schema}.documents AS d
            {literal_where_sql}
            LIMIT %s
        ),
        """
        # Orden de %s al leer el texto: OVER … POSITION, WHERE POSITION, filtros..., LIMIT.
        literal_params = [query, query, *filter_params, candidate_limit]
    else:
        literal_cte = f"""
        literal_ranked AS (
            SELECT d.id, d.ctid, d.chunk_text, d.document_name, d.document_id, d.created_at,
                   1::bigint AS lit_rank
            FROM {schema}.documents AS d
            WHERE FALSE
            LIMIT 0
        ),
        """
        literal_params = []

    sql = f"""
        WITH base AS (
            SELECT
                d.id,
                d.ctid,
                d.chunk_text,
                d.document_name,
                d.document_id,
                d.created_at,
                d.embedding <=> %s::vector AS vector_distance
            FROM {schema}.documents AS d
            {where_sql}
        ),

        vector_ranked AS (
            SELECT
                id,
                ctid,
                chunk_text,
                document_name,
                document_id,
                created_at,
                vector_distance,
                ROW_NUMBER() OVER (ORDER BY vector_distance ASC) AS vec_rank
            FROM base
            ORDER BY vector_distance ASC
            LIMIT %s
        ),

        lexical_ranked AS (
            SELECT
                d.id,
                d.ctid,
                d.chunk_text,
                d.document_name,
                d.document_id,
                d.created_at,
                ts_rank_cd(d.fts_vector, q.query, 32) AS lex_score,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(d.fts_vector, q.query, 32) DESC
                ) AS lex_rank
            FROM {schema}.documents AS d
            CROSS JOIN LATERAL (SELECT plainto_tsquery('spanish', %s) AS query) AS q
            {where_sql}
            ORDER BY lex_score DESC
            LIMIT %s
        ),

        {literal_cte}

        all_keys AS (
            SELECT ctid FROM vector_ranked
            UNION
            SELECT ctid FROM lexical_ranked
            UNION
            SELECT ctid FROM literal_ranked
        ),

        merged AS (
            SELECT
                k.ctid,
                COALESCE(v.id, l.id, lit.id) AS chunk_id,
                COALESCE(v.chunk_text, l.chunk_text, lit.chunk_text) AS chunk_text,
                COALESCE(v.document_name, l.document_name, lit.document_name) AS document_name,
                COALESCE(v.document_id, l.document_id, lit.document_id) AS document_id,
                COALESCE(v.created_at, l.created_at, lit.created_at) AS created_at,
                v.vector_distance,
                v.vec_rank,
                l.lex_rank,
                lit.lit_rank
            FROM all_keys k
            LEFT JOIN vector_ranked   v   ON v.ctid   = k.ctid
            LEFT JOIN lexical_ranked  l   ON l.ctid   = k.ctid
            LEFT JOIN literal_ranked  lit ON lit.ctid = k.ctid
        ),

        rrf AS (
            SELECT
                chunk_id,
                chunk_text,
                document_name,
                document_id,
                created_at,
                vector_distance,
                (
                    CASE WHEN vec_rank IS NOT NULL
                        THEN %s::double precision / (%s + vec_rank::double precision) ELSE 0 END
                  + CASE WHEN lex_rank IS NOT NULL
                        THEN %s::double precision / (%s + lex_rank::double precision) ELSE 0 END
                  + CASE WHEN lit_rank IS NOT NULL
                        THEN %s::double precision / (%s + lit_rank::double precision) ELSE 0 END
                ) AS rrf_score
            FROM merged
        )

        SELECT chunk_id, chunk_text, document_name, vector_distance, rrf_score, document_id, created_at
        FROM rrf
        ORDER BY {order_sql}
        LIMIT %s
    """

    params = [
        q_emb_str,
        *filter_params,
        candidate_limit,
        query,
        *filter_params,
        candidate_limit,
        *literal_params,
        vw,
        rk,
        lw,
        rk,
        lit_sql_weight,
        rk,
        candidate_limit,
    ]

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[retrieval] ERROR en hybrid search: {e}")
        raise
    finally:
        cur.close()
        conn.close()

    _db_ms = (time.perf_counter() - _t_db0) * 1000.0
    _semantic_total_ms = (time.perf_counter() - _t_semantic0) * 1000.0
    print(
        f"[timing] semantic_search tenant_id={tenant_id!r} embed_ms={_embed_ms:.1f} "
        f"db_ms={_db_ms:.1f} total_ms={_semantic_total_ms:.1f} rows={len(rows)} k={k}"
    )

    print(
        f"[retrieval] hybrid search returned {len(rows)} rows "
        f"(k={k}, schema={schema}, sort_by={sort_by_norm}, vector_w={vw}, lexical_w={lw}, "
        f"literal_w={lit_sql_weight}, literal_substring_leg={include_literal})"
    )

    matched_rows = [
        row for row in rows if row[3] is None or row[3] <= max_sd
    ]

    if not matched_rows and rows:
        n = min(max(1, fb_n), len(rows))
        matched_rows = rows[:n]
        dists = [round(float(r[3]), 4) for r in matched_rows if r[3] is not None]
        print(
            f"[retrieval] no chunk under MAX_SEMANTIC_DISTANCE={max_sd}; "
            f"using best {n} by rrf_score, vector_distances={dists}"
        )
    before_dedupe = len(matched_rows)
    matched_rows = dedupe_rows_by_document(matched_rows, limit=k)
    duplicates_removed = before_dedupe - len(matched_rows)
    if duplicates_removed > 0:
        print(
            f"[retrieval] BU-01 dedupe removed {duplicates_removed} duplicate chunk(s) "
            f"by document; unique_docs={len(matched_rows)}"
        )
    elif not rows:
        print(
            "[retrieval] 0 rows: revisá tenant_id, agent_id, columna fts_vector, "
            "document_name/chunk_text/created_at o datos en BD"
        )

    # BU-04: Filtrar por fecha del documento (extraída de document_name)
    skipped_out_of_range = 0
    skipped_no_date = 0
    if ca_lo is not None and ca_hi_exc is not None:
        date_filtered_rows = []

        for row in matched_rows:
            doc_name = str(row[2] or "").strip()
            doc_date = extract_document_date(doc_name)

            if doc_date is None:
                # No se pudo extraer fecha: incluir en resultados con warning
                date_filtered_rows.append(row)
                skipped_no_date += 1
                continue

            # Convertir bounds a date para comparación
            date_lo = ca_lo.date() if hasattr(ca_lo, 'date') else ca_lo
            date_hi = ca_hi_exc.date() if hasattr(ca_hi_exc, 'date') else ca_hi_exc

            if date_lo <= doc_date < date_hi:
                date_filtered_rows.append(row)
            else:
                skipped_out_of_range += 1

        before_date_filter = len(matched_rows)
        matched_rows = date_filtered_rows

        if skipped_out_of_range > 0 or skipped_no_date > 0:
            print(
                f"[retrieval] BU-04 document_date filter: "
                f"before={before_date_filter}, after={len(matched_rows)}, "
                f"out_of_range={skipped_out_of_range}, no_date_extracted={skipped_no_date}"
            )

    n_sql = len(rows)
    after_sim = sum(1 for r in rows if r[3] is None or float(r[3]) <= max_sd)
    semantic_fallback_used = after_sim == 0 and bool(rows) and bool(matched_rows)

    chunks = [row[1] for row in matched_rows]
    documents = ordered_unique_documents(matched_rows)
    context_items: list[dict[str, Any]] = []
    for i, row in enumerate(matched_rows):
        rs = row[4]
        context_items.append(
            {
                "rank": i,
                "chunk_id": int(row[0]) if row[0] is not None else None,
                "chunk_text": row[1],
                "document_name": row[2] or "",
                "document_id": str(row[5]) if len(row) > 5 and row[5] is not None else "",
                "created_at": row[6].isoformat() if len(row) > 6 and hasattr(row[6], "isoformat") else (str(row[6]) if len(row) > 6 and row[6] is not None else None),
                "distance": row[3],
                "rrf_score": float(rs) if rs is not None else None,
            }
        )

    ca_s = (created_at_start or "").strip() if isinstance(created_at_start, str) else ""
    ca_e = (created_at_end or "").strip() if isinstance(created_at_end, str) else ""
    retrieval_config: dict[str, Any] = {
        "hybrid_search": True,
        "retrieval_limit": k,
        "sort_by": sort_by_norm,
        "max_semantic_distance": max_sd,
        "semantic_fallback_top_n": fb_n,
        "retrieval_sql_row_count": n_sql,
        "retrieval_candidate_limit": candidate_limit,
        "chunks_after_similarity_gate": after_sim,
        "chunks_before_document_dedupe": before_dedupe,
        "duplicate_chunks_removed_by_document": duplicates_removed,
        "unique_documents_returned": len(matched_rows),
        "semantic_fallback_neighbor_used": semantic_fallback_used,
        "literal_keyword_overlap_applied": bool(literal_keyword_overlap and lit_w > 0),
        "literal_substring_leg_sql": include_literal,
        "literal_weight_applied": lit_sql_weight,
        "literal_min_chars": lit_min,
        "vector_weight": vw,
        "lexical_weight": lw,
        "rrf_k": rk,
        "created_at_start": ca_s or None,
        "created_at_end": ca_e or None,
        "created_at_single_day": created_at_day.isoformat() if created_at_day else None,
        "document_date_filter_applied": bool(ca_lo and ca_hi_exc),
        "documents_filtered_by_date": skipped_out_of_range if ca_lo and ca_hi_exc else 0,
        "documents_without_extractable_date": skipped_no_date if ca_lo and ca_hi_exc else 0,
    }

    return chunks, documents, context_items, retrieval_config




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


def sqs_handler(event, context):
    """Proceso async: ejecuta la misma lógica que invocación directa y persiste resultado en DynamoDB."""
    tbl = boto3.resource("dynamodb").Table(QUERY_JOB_TABLE_NAME)

    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
        except Exception as e:
            print(f"[async-query] Mensaje JSON inválido: {e}")
            continue

        job_id = body.get("job_id")
        if not job_id:
            print("[async-query] Falta job_id en mensaje SQS")
            continue

        req = {k: v for k, v in body.items() if k != "job_id"}
        now = _utc_now_iso()
        try:
            out = handler(req, context)
        except Exception as e:
            err_txt = str(e)
            print(f"[async-query] Excepción en pipeline job_id={job_id}: {err_txt}")
            try:
                tbl.update_item(
                    Key={"id": job_id},
                    UpdateExpression="SET #st = :e, updated_at = :u, #r = :res",
                    ExpressionAttributeNames={"#st": "status", "#r": "result"},
                    ExpressionAttributeValues={
                        ":e": "Error",
                        ":u": _utc_now_iso(),
                        ":res": {"message": err_txt[:4000]},
                    },
                )
            except Exception as ddb_e:
                print(f"[async-query] Error persistiendo Error en Dynamo job_id={job_id}: {ddb_e}")
            continue

        status_code = int(out.get("statusCode") or 500)
        payload_raw = out.get("body")
        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except Exception:
            payload = {"error": "Respuesta inválida del pipeline", "raw": payload_raw}

        try:
            if status_code != 200:
                err_txt = payload.get("error") if isinstance(payload, dict) else str(payload)
                tbl.update_item(
                    Key={"id": job_id},
                    UpdateExpression="SET #st = :e, updated_at = :u, #r = :res",
                    ExpressionAttributeNames={"#st": "status", "#r": "result"},
                    ExpressionAttributeValues={
                        ":e": "Error",
                        ":u": now,
                        ":res": {"message": err_txt[:4000]},
                    },
                )
            else:
                tbl.update_item(
                    Key={"id": job_id},
                    UpdateExpression="SET #st = :ok, updated_at = :u, #r = :res",
                    ExpressionAttributeNames={"#st": "status", "#r": "result"},
                    ExpressionAttributeValues={
                        ":ok": "Ready",
                        ":u": now,
                        ":res": _to_dynamo_numbers(payload),
                    },
                )
        except Exception as e:
            print(f"[async-query] Error actualizando Dynamo job_id={job_id}: {e}")

    return {}


# --- Main Lambda Handler ---
def handler(event, context):
    if event.get("Records") and QUERY_JOB_TABLE_NAME:
        return sqs_handler(event, context)

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

    api_version = _extract_version_from_path(event)

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

        if api_version == "v2":
            try:
                body = _normalize_v2_body(body)
            except ValueError as e:
                return {
                    "statusCode": 400,
                    "headers": {
                        "Content-Type": "application/json",
                        **CORS_HEADERS,
                    },
                    "body": json.dumps({"error": str(e)}),
                }

        tenant_id = body.get("tenant_id")
        agent_id = body.get("agent_id")
        query = body.get("query")
        document_name = body.get("document_name")
        chunk_text = body.get("chunk_text")
        created_at_raw = body.get("created_at")
        if created_at_raw is None:
            created_at_raw = body.get("create_at")
        req_src = body
    else:
        tenant_id = event.get("tenant_id")
        agent_id = event.get("agent_id")
        query = event.get("query")
        document_name = event.get("document_name")  # opcional
        chunk_text = event.get("chunk_text")  # opcional
        created_at_raw = event.get("created_at")
        if created_at_raw is None:
            created_at_raw = event.get("create_at")
        req_src = event

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

    ca_start = str(
        req_src.get("created_at_start") or req_src.get("start_at") or ""
    ).strip()
    ca_end = str(
        req_src.get("created_at_end") or req_src.get("end_at") or ""
    ).strip()
    if bool(ca_start) ^ bool(ca_end):
        resp = {
            "statusCode": 400,
            "body": json.dumps(
                {
                    "error": "Si usás ventana por fechas enviá start_at y end_at juntos "
                    "(o created_at_start y created_at_end), en YYYY-MM-DD o ISO día."
                }
            ),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    created_at_day = None
    try:
        if not (ca_start and ca_end):
            created_at_day = parse_created_at_day(created_at_raw)
        else:
            created_at_day = None
            resolve_created_at_bounds(None, ca_start, ca_end)
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

    k_lim = req_src.get("retrieval_limit")
    try:
        k_req = int(k_lim) if k_lim is not None else DEFAULT_RETRIEVAL_LIMIT
    except (TypeError, ValueError):
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": "retrieval_limit debe ser entero"}),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp
    if k_req < 1 or k_req > 500:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": "retrieval_limit debe estar entre 1 y 500"}),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    msd_raw = req_src.get("max_semantic_distance")
    sfb_raw = req_src.get("semantic_fallback_top_n")
    try:
        msd_eff = float(msd_raw) if msd_raw is not None else None
        if msd_eff is not None:
            if msd_eff > 2.0:
                msd_eff /= 100.0
            if not (0 < msd_eff <= 2.0):
                raise ValueError(f"max_semantic_distance fuera de rango: {msd_eff!r}")
    except (TypeError, ValueError) as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    sfb_eff = None
    try:
        if sfb_raw is not None:
            sfb_eff = int(sfb_raw)
            if sfb_eff < 0:
                raise ValueError("semantic_fallback_top_n no puede ser negativo")
    except (TypeError, ValueError) as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    lk_ov_raw = req_src.get("literal_keyword_overlap")
    literal_overlap = True if lk_ov_raw is None else bool(lk_ov_raw)

    lk_ml_raw = req_src.get("literal_keyword_min_length")
    literal_ml = None
    try:
        if lk_ml_raw is not None:
            literal_ml = int(lk_ml_raw)
            if literal_ml < 1 or literal_ml > 256:
                raise ValueError("literal_keyword_min_length inválido en payload")
    except (TypeError, ValueError) as e:
        resp = {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    try:
        sort_by_eff = normalize_search_sort_by(req_src.get("sort_by"))
    except ValueError as e:
        resp = {"statusCode": 400, "body": json.dumps({"error": str(e)})}
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    retrieval_config: dict[str, Any] = {}
    request_id = getattr(context, "aws_request_id", "") if context else ""
    try:
        _t_search0 = time.perf_counter()
        chunks, documents, context_items, retrieval_config = semantic_search(
            query,
            tenant_id,
            document_name,
            agent_id,
            chunk_text,
            created_at_day,
            ca_start if ca_start else None,
            ca_end if ca_end else None,
            k=k_req,
            max_semantic_distance=msd_eff,
            semantic_fallback_top_n=sfb_eff,
            literal_keyword_overlap=literal_overlap,
            literal_min_chars_override=literal_ml,
            sort_by=sort_by_eff,
        )
        _search_ms = (time.perf_counter() - _t_search0) * 1000.0
    except ValueError as e:
        resp = {"statusCode": 400, "body": json.dumps({"error": str(e)})}
        if is_http_event:
            resp["headers"] = {"Content-Type": "application/json", **CORS_HEADERS}
        return resp

    context_text = "\n\n".join(chunks)

    _t_prompt0 = time.perf_counter()
    agent_prompt = get_prompt_template(tenant_id, agent_id)
    _prompt_fetch_ms = (time.perf_counter() - _t_prompt0) * 1000.0

    prompt = apply_prompt_template(
        agent_prompt,
        context=context_text,
        query=query
    )

    llmClient = LLMClient(bedrock, MAIN_LLM_MODEL, FALLBACK_LLM_MODEL)
    _t_llm0 = time.perf_counter()
    response = llmClient.generate(prompt)
    _llm_ms = (time.perf_counter() - _t_llm0) * 1000.0
    _handler_work_ms = _search_ms + _prompt_fetch_ms + _llm_ms
    print(
        f"[timing] handler request_id={request_id} tenant_id={tenant_id!r} "
        f"semantic_search_ms={_search_ms:.1f} prompt_template_ms={_prompt_fetch_ms:.1f} "
        f"llm_generate_ms={_llm_ms:.1f} handler_after_validate_ms={_handler_work_ms:.1f}"
    )
    print(response)
    resp_body = {
        "response": response,
        "contexts": chunks,
        "documents": documents,
        "context_items": context_items,
        "retrieval_config": retrieval_config,
    }

    if api_version == "v2":
        page = int(req_src.get("_page", 1))
        page_size = int(req_src.get("_page_size", API_V2_DEFAULT_PAGE_SIZE))
        resp_body = _build_v2_response(resp_body, page, page_size)

    resp = {
        "statusCode": 200,
        "body": json.dumps(resp_body),
    }
    if is_http_event:
        resp["headers"] = {
            "Content-Type": "application/json",
            **CORS_HEADERS,
        }
    return resp

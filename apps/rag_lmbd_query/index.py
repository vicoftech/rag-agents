import os
import json
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
_DB_SECRET_CACHE = None

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
    None / vacío → sin filtro (búsqueda general).
    Acepta 'YYYY-MM-DD' o ISO datetime (se usa solo el día civil en UTC).
    """
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    s = str(raw).strip()
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
    k=50,
    *,
    rrf_k=None,
    vector_weight=None,
    lexical_weight=None,
    literal_weight=None,
    max_semantic_distance=None,
    semantic_fallback_top_n=None,
):
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
    lit_w = HYBRID_LITERAL_WEIGHT if literal_weight is None else float(literal_weight)

    q_emb = embed(query, input_type="search_query")

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

    if created_at_day is not None:
        start_utc = datetime.combine(created_at_day, time.min, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)
        filter_clauses.append("d.created_at >= %s AND d.created_at < %s")
        filter_params.append(start_utc.replace(tzinfo=None))
        filter_params.append(end_utc.replace(tzinfo=None))

    where_sql = ("WHERE " + " AND ".join(filter_clauses)) if filter_clauses else ""

    schema = resolve_schema_name(tenant_id)
    conn = get_connection()
    cur = conn.cursor()

    q_plain = (query or "").strip()
    include_literal = lit_w > 0 and len(q_plain) >= HYBRID_LITERAL_MIN_CHARS
    lit_sql_weight = float(lit_w) if include_literal else 0.0

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
                d.ctid,
                d.chunk_text,
                d.document_name,
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
        literal_params = [query, query, *filter_params, k]
    else:
        literal_cte = f"""
        literal_ranked AS (
            SELECT d.ctid, d.chunk_text, d.document_name,
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
                d.ctid,
                d.chunk_text,
                d.document_name,
                d.embedding <=> %s::vector AS vector_distance
            FROM {schema}.documents AS d
            {where_sql}
        ),

        vector_ranked AS (
            SELECT
                ctid,
                chunk_text,
                document_name,
                vector_distance,
                ROW_NUMBER() OVER (ORDER BY vector_distance ASC) AS vec_rank
            FROM base
            ORDER BY vector_distance ASC
            LIMIT %s
        ),

        lexical_ranked AS (
            SELECT
                d.ctid,
                d.chunk_text,
                d.document_name,
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
                COALESCE(v.chunk_text, l.chunk_text, lit.chunk_text) AS chunk_text,
                COALESCE(v.document_name, l.document_name, lit.document_name) AS document_name,
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
                chunk_text,
                document_name,
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

        SELECT chunk_text, document_name, vector_distance, rrf_score
        FROM rrf
        ORDER BY rrf_score DESC
        LIMIT %s
    """

    params = [
        q_emb_str,
        *filter_params,
        k,
        query,
        *filter_params,
        k,
        *literal_params,
        vw,
        rk,
        lw,
        rk,
        lit_sql_weight,
        rk,
        k,
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

    print(
        f"[retrieval] hybrid search returned {len(rows)} rows "
        f"(k={k}, schema={schema}, vector_w={vw}, lexical_w={lw}, "
        f"literal_w={lit_sql_weight}, literal_substring_leg={include_literal})"
    )

    matched_rows = [
        row for row in rows if row[2] is None or row[2] <= max_sd
    ]

    if not matched_rows and rows:
        n = min(max(1, fb_n), len(rows))
        matched_rows = rows[:n]
        dists = [round(float(r[2]), 4) for r in matched_rows if r[2] is not None]
        print(
            f"[retrieval] no chunk under MAX_SEMANTIC_DISTANCE={max_sd}; "
            f"using best {n} by rrf_score, vector_distances={dists}"
        )
    elif not rows:
        print(
            "[retrieval] 0 rows: revisá tenant_id, agent_id, columna fts_vector, "
            "document_name/chunk_text/created_at o datos en BD"
        )

    chunks = [row[0] for row in matched_rows]
    documents = sorted(set(row[1] for row in matched_rows))

    return chunks, documents




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

        tenant_id = body.get("tenant_id")
        agent_id = body.get("agent_id")
        query = body.get("query")
        document_name = body.get("document_name")
        chunk_text = body.get("chunk_text")
        created_at_raw = body.get("created_at")
        if created_at_raw is None:
            created_at_raw = body.get("create_at")
    else:
        tenant_id = event.get("tenant_id")
        agent_id = event.get("agent_id")
        query = event.get("query")
        document_name = event.get("document_name")  # opcional
        chunk_text = event.get("chunk_text")  # opcional
        created_at_raw = event.get("created_at")
        if created_at_raw is None:
            created_at_raw = event.get("create_at")

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

    created_at_day = None
    try:
        created_at_day = parse_created_at_day(created_at_raw)
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

    # Obtener chunks relevantes
    chunks, documents = semantic_search(
        query,
        tenant_id,
        document_name,
        agent_id,
        chunk_text,
        created_at_day,
    )
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
        "body": json.dumps({
            "response": response,
            "contexts": chunks,
            "documents": documents
        }),
    }
    if is_http_event:
        resp["headers"] = {
            "Content-Type": "application/json",
            **CORS_HEADERS,
        }
    return resp

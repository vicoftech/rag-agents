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
COHERE_TRUNCATE = os.getenv("COHERE_TRUNCATE", "RIGHT")
EXPECTED_EMBEDDING_DIM = int(os.getenv("EXPECTED_EMBEDDING_DIM", "1536"))
MAX_SEMANTIC_DISTANCE = float(os.getenv("MAX_SEMANTIC_DISTANCE", "0.45"))

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




# --- Semantic Search adaptado al nuevo esquema ---
def semantic_search(
    query,
    tenant_id,
    document_name=None,
    agent_id=None,
    chunk_text=None,
    created_at_day=None,
    k=50,
):
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
    conn = get_connection()
    cur = conn.cursor()

    # Base query
    sql = f"""
        SELECT 
            chunk_text,
            document_name,
            embedding <=> %s::vector AS distance
        FROM {schema}.documents
    """

    params = [q_emb_str]

    # Filtros opcionales
    filters = []
    if document_name:
        filters.append("document_name = %s")
        params.append(document_name)

    if agent_id:
        filters.append("agent_id = %s")
        params.append(agent_id)

    if chunk_text:
        filters.append("chunk_text = %s")
        params.append(chunk_text)

    if created_at_day is not None:
        # Día civil UTC; created_at es timestamp sin TZ guardado como instante UTC (NOW() en Lambda).
        # Rango [start, end) usa índice btree en created_at (AT TIME ZONE no es IMMUTABLE → no indexable).
        start_utc = datetime.combine(created_at_day, time.min, tzinfo=timezone.utc)
        end_utc = start_utc + timedelta(days=1)
        filters.append("created_at >= %s AND created_at < %s")
        params.append(start_utc.replace(tzinfo=None))
        params.append(end_utc.replace(tzinfo=None))

    if filters:
        sql += " WHERE " + " AND ".join(filters)

    sql += " ORDER BY embedding <=> %s::vector LIMIT %s"

    params.append(q_emb_str)
    params.append(k)

    cur.execute(sql, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    # Filtra vecinos semánticos por umbral de distancia.
    # Con cosine distance (<=>), valores más bajos son más similares.
    matched_rows = [row for row in rows if row[2] is not None and row[2] <= MAX_SEMANTIC_DISTANCE]

    # Extraer chunks y documentos únicos solo de matches válidos
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
    chunks, documents = semantic_search(query, tenant_id, document_name, agent_id, chunk_text)
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

import os
import json
import boto3
from botocore.exceptions import ClientError
import psycopg2
from lib.llmClient import LLMClient
from string import Template
import numpy as np
from pgvector.psycopg2 import register_vector
# AWS Session Setup (for local testing)
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID_DEV', "")
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY_DEV', "")

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

def embed(text: str):
    if len(text) > MAX_EMBED_TEXT_LENGTH:
        text = text[:MAX_EMBED_TEXT_LENGTH]

    payload = {
        "texts": [text],
        "input_type": "search_document"
    }

    response = bedrock.invoke_model(
        modelId=EMBEDDINGS_MODEL,
        body=json.dumps(payload),
        contentType="application/json",
        accept="application/json"
    )

    result = json.loads(response["body"].read())

    # ----- ADAPTACIÓN A TU CASO REAL -----
    # El modelo está devolviendo algo así como:
    # { "float": [[ ... ]] }
    #
    # Por lo tanto: tomar la primera clave y su primer vector.
    # --------------------------------------
    if isinstance(result, dict) and len(result) == 1:
        key = list(result.keys())[0]
        raw = result[key]

        # caso típico: [[floats]]
        if isinstance(raw, list) and len(raw) > 0 and isinstance(raw[0], list):
            vec = raw[0]
        else:
            raise RuntimeError(f"Formato inesperado para embedding en key '{key}': {raw}")

    elif "embeddings" in result:
        float_list = result["embeddings"]
        vec = float_list["float"][0]


    else:
        raise RuntimeError(f"No se encontró un vector de embeddings en: {result}")

    # normalizar
    return normalize(vec).tolist()




# --- Semantic Search adaptado al nuevo esquema ---
def semantic_search(query, tenant_id, document_id=None, agent_id=None, k=50):
    # 1) Obtener embedding del query
    q_emb = embed(query)  # <-- tu función embed()
    
    if not isinstance(q_emb, list):
        raise ValueError("El embedding debe ser una lista")
    if len(q_emb) != 1536:
        raise ValueError(f"Embedding query tiene {len(q_emb)} dims y deben ser 1536")

    # Convertimos a formato pgvector: [0.1,0.2,...]
    q_emb_str = "[" + ",".join(str(float(x)) for x in q_emb) + "]"

    schema = f"tenant_{tenant_id}"
    conn = get_connection()
    cur = conn.cursor()

    # Base query
    sql = f"""
        SELECT 
            chunk_text,
            embedding <=> %s::vector AS distance
        FROM {schema}.documents
    """

    params = [q_emb_str]

    # Filtros opcionales
    filters = []
    if document_id:
        filters.append("document_id = %s")
        params.append(document_id)

    if agent_id:
        filters.append("agent_id = %s")
        params.append(agent_id)

    if filters:
        sql += " WHERE " + " AND ".join(filters)

    sql += " ORDER BY embedding <=> %s::vector LIMIT %s"

    params.append(q_emb_str)
    params.append(k)

    cur.execute(sql, params)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows




# --- Get prompt template of the agent ---
def get_prompt_template(tenant_id, agent_id):
    schema = f"tenant_{tenant_id}"

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
    tenant_id = event.get("tenant_id")
    agent_id = event.get("agent_id")
    query = event.get("query")
    document_id = event.get("document_id")  # opcional

    if not tenant_id or not agent_id or not query:
        return {
            "statusCode": 400,
            "body": "Faltan tenant_id, agent_id o query"
        }

    # Obtener chunks relevantes
    contexts = semantic_search(query, tenant_id, document_id , agent_id)
    context_text = "\n\n".join([c[0] for c in contexts])

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
    return {
        "statusCode": 200,
        "body": response
    }

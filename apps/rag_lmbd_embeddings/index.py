import os
import json
import re
import boto3
import pdfplumber
import psycopg2
from psycopg2.extras import execute_values
from langchain_text_splitters import RecursiveCharacterTextSplitter
from botocore.exceptions import ClientError
import uuid
import io
import time
import numpy as np
from urllib.parse import unquote_plus

from lib.bedrock_embeddings import parse_embedding_vector, parse_embedding_vectors
from s3_rag_key import parse_s3_rag_key

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
textract = boto3.client('textract',  **session_args)
secretsmanager = boto3.client("secretsmanager", **session_args)

# 🔐 Se deben pasar estas variables al Lambda (ENV VARS)
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_SECRET_ID = os.getenv("DB_SECRET_ID", "")
_DB_SECRET_CACHE = None
# Por contenedor: evita round-trips a DB en cargas masivas (mismo tenant/agente)
_TENANT_SCHEMA_READY: set[tuple[str, str]] = set()
#EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "cohere.embed-v4:0")
# Truncado en el modelo Cohere (Bedrock); alineado con chunks por caracteres.
COHERE_TRUNCATE = os.getenv("COHERE_TRUNCATE", "RIGHT")
MAX_EMBED_TEXT_LENGTH = 20000
EMBED_BATCH_SIZE = min(96, int(os.getenv("EMBED_BATCH_SIZE", "96")))
# ivfflat por defecto (Aurora/pgvector antiguo). Si la instancia soporta HNSW: PGVECTOR_INDEX_TYPE=hnsw
PGVECTOR_INDEX_TYPE = os.getenv("PGVECTOR_INDEX_TYPE", "ivfflat").lower()
# Textract = API lenta (job async, minutos). Por defecto off; usar "true" si hay PDFs escaneados puros.
USE_TEXTRACT = os.getenv("USE_TEXTRACT", "false").lower() in ("1", "true", "yes")


def _cohere_embed_extras():
    if "cohere" in EMBEDDINGS_MODEL.lower():
        return {"truncate": COHERE_TRUNCATE, "embedding_types": ["float"]}
    return {}


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
    if not (DB_PASSWORD or "").strip():
        raise ValueError("DB_PASSWORD vacío: defina master_password o DB_SECRET_ID")
    return DB_USER, DB_PASSWORD


def get_connection():
    user, password = _resolve_db_credentials()
    return psycopg2.connect(
        dbname=DB_NAME,
        user=user,
        password=password,
        host=DB_HOST,
        port=DB_PORT,
    )


def ensure_tenant_schema_exists(tenant_id: str, agent_id: str):
    """
    Verifica si el esquema del tenant existe, y si no, lo crea junto con
    las tablas necesarias (agents, documents), los índices y un agente por defecto.
    
    Args:
        tenant_id: Identificador del tenant (se usará como nombre del esquema)
        agent_id: Identificador del agente para crear el registro por defecto
    """
    if (tenant_id, agent_id) in _TENANT_SCHEMA_READY:
        return
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # Verificar si el esquema existe
        cur.execute("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = %s
            )
        """, (tenant_id,))
        
        schema_exists = cur.fetchone()[0]
        
        if not schema_exists:
            print(f"[INFO] Creando esquema para tenant: {tenant_id}")
            
            # Habilitar extensión pgvector (necesaria para tipo VECTOR)
            print("[INFO] Habilitando extensión pgvector...")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            
            # Crear esquema
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {tenant_id}")
            
            # Crear tabla de agentes
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {tenant_id}.agents (
                    agent_id       UUID PRIMARY KEY,
                    agent_name     TEXT NOT NULL,
                    description    TEXT,
                    prompt_template TEXT NOT NULL,
                    created_at     TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Crear tabla de documentos
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {tenant_id}.documents (
                    id              SERIAL PRIMARY KEY,
                    agent_id        UUID NOT NULL,
                    document_id     UUID NOT NULL,
                    document_name   TEXT NOT NULL,
                    chunk_text      TEXT NOT NULL,
                    embedding       VECTOR(1536),
                    chunk_index     INTEGER,
                    created_at      TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Índice vectorial: IVFFlat por defecto; HNSW mejor recall si pgvector lo soporta.
            # Tras cargas masivas considerar REINDEX en el índice o ajustar lists (IVFFlat).
            idx_emb = f"idx_{tenant_id}_documents_embedding".replace("-", "_")
            if PGVECTOR_INDEX_TYPE == "hnsw":
                try:
                    cur.execute(f"""
                        CREATE INDEX IF NOT EXISTS {idx_emb}
                        ON {tenant_id}.documents
                        USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16, ef_construction = 64)
                    """)
                except Exception as ex:
                    print(f"[WARN] HNSW no disponible ({ex!s}); usando IVFFlat")
                    cur.execute(f"""
                        CREATE INDEX IF NOT EXISTS {idx_emb}
                        ON {tenant_id}.documents
                        USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = 100)
                    """)
            else:
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_emb}
                    ON {tenant_id}.documents
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
            
            # Crear índice para agents
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tenant_id}_agents 
                ON {tenant_id}.agents(agent_id)
            """)
            
            # Crear índice para búsqueda por agent_id en documents
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tenant_id}_documents_agent 
                ON {tenant_id}.documents(agent_id)
            """)
            
            # Crear índice para búsqueda por document_id
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tenant_id}_documents_doc_id 
                ON {tenant_id}.documents(document_id)
            """)

            # Índice único para upsert por documento+chunk
            idxu = f"idx_{tenant_id}_documents_doc_chunk".replace("-", "_")
            cur.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {idxu}
                ON {tenant_id}.documents(document_id, chunk_index)
            """)

            # B-tree en created_at (filtro por rango UTC en rag_lmbd_query; AT TIME ZONE no es IMMUTABLE en índices)
            idx_created = f"idx_{tenant_id}_documents_created_at".replace("-", "_")
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_created}
                ON {tenant_id}.documents (created_at)
            """)
            
            # Insertar agente por defecto
            default_prompt_template = f"""Eres un asistente especializado para el tenant {tenant_id}. 
Responde basándote únicamente en el contexto proporcionado. Si no encuentras información relevante, indica que no tienes datos suficientes.

--- CONTEXTO ---
{{context}}

--- PREGUNTA ---
{{query}}

Responde con precisión y sin inventar información que no esté en el contexto."""

            cur.execute(f"""
                INSERT INTO {tenant_id}.agents (
                    agent_id,
                    agent_name,
                    description,
                    prompt_template
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (agent_id) DO NOTHING
            """, (
                agent_id,
                f'Agente Principal - {tenant_id}',
                f'Agente por defecto para el tenant {tenant_id}',
                default_prompt_template
            ))
            
            conn.commit()
            print(f"[INFO] Esquema {tenant_id} creado exitosamente con agente por defecto")
        else:
            print(f"[INFO] Esquema {tenant_id} ya existe")
            
            # Verificar si el agente existe, si no, crearlo
            cur.execute(f"""
                SELECT EXISTS(
                    SELECT 1 FROM {tenant_id}.agents 
                    WHERE agent_id = %s
                )
            """, (agent_id,))
            
            agent_exists = cur.fetchone()[0]
            
            if not agent_exists:
                print(f"[INFO] Creando agente {agent_id} en esquema existente {tenant_id}")
                
                default_prompt_template = f"""Eres un asistente especializado para el tenant {tenant_id}. 
Responde basándote únicamente en el contexto proporcionado. Si no encuentras información relevante, indica que no tienes datos suficientes.

--- CONTEXTO ---
{{context}}

--- PREGUNTA ---
{{query}}

Responde con precisión y sin inventar información que no esté en el contexto."""

                cur.execute(f"""
                    INSERT INTO {tenant_id}.agents (
                        agent_id,
                        agent_name,
                        description,
                        prompt_template
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (agent_id) DO NOTHING
                """, (
                    agent_id,
                    f'Agente - {agent_id[:8]}',
                    f'Agente para el tenant {tenant_id}',
                    default_prompt_template
                ))
                
                conn.commit()
                print(f"[INFO] Agente {agent_id} creado exitosamente")

            idx_created = f"idx_{tenant_id}_documents_created_at".replace("-", "_")
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_created}
                ON {tenant_id}.documents (created_at)
            """)

            # Self-heal del esquema en tenants existentes: columna e índice para upsert por chunk.
            cur.execute(
                f"ALTER TABLE {tenant_id}.documents ADD COLUMN IF NOT EXISTS chunk_index INTEGER"
            )
            idxu = f"idx_{tenant_id}_documents_doc_chunk".replace("-", "_")
            cur.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {idxu}
                ON {tenant_id}.documents(document_id, chunk_index)
            """)
            conn.commit()

        _TENANT_SCHEMA_READY.add((tenant_id, agent_id))
            
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Error al crear esquema/agente {tenant_id}: {str(e)}")
        raise
    finally:
        cur.close()
        conn.close()


def normalize(v):
    v = np.array(v, dtype=np.float32).squeeze()
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


def embed(text: str, input_type: str = "search_document"):
    """Corpus (chunks): input_type=search_document. Consultas puntuales: search_query."""
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


def embed_texts_batch(texts: list, input_type: str = "search_document") -> list:
    """Varios textos en una o más llamadas Bedrock (máx. EMBED_BATCH_SIZE por request)."""
    if not texts:
        return []
    out: list = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        batch = [t[:MAX_EMBED_TEXT_LENGTH] if len(t) > MAX_EMBED_TEXT_LENGTH else t for t in batch]
        payload = {"texts": batch, "input_type": input_type, **_cohere_embed_extras()}
        response = bedrock.invoke_model(
            modelId=EMBEDDINGS_MODEL,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        rows = parse_embedding_vectors(result)
        if len(rows) != len(batch):
            raise RuntimeError(
                f"Bedrock devolvió {len(rows)} vectores, se enviaron {len(batch)} textos"
            )
        for r in rows:
            out.append(normalize(np.array(r, dtype=np.float32)).tolist())
    return out


def semantic_search(tenant_id, query, k=3):
    """tenant_id: nombre de esquema PostgreSQL (ej. tenant_gp), igual que en S3."""
    q_emb = embed(query, input_type="search_query")
    q_emb_str = "[" + ",".join(str(x) for x in q_emb) + "]"

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        f"""
        SELECT
            chunk_text,
            embedding <=> %s::vector AS distance
        FROM {tenant_id}.documents
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
        """,
        (q_emb_str, q_emb_str, k),
    )

    return cur.fetchall()

def pdf_has_more_than_50_pages(bucket, key):
    """
    Detecta si un PDF tiene más de 50 páginas usando pdfplumber.
    Retorna True si tiene más de 50, False en caso contrario.
    """
    # 1️⃣ Leer PDF desde S3
    pdf_obj = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = pdf_obj["Body"].read()

    # 2️⃣ Usar pdfplumber para contar páginas
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            num_pages = len(pdf.pages)
            print(f"[INFO] Páginas detectadas: {num_pages}")
            return num_pages > 50

    except Exception as e:
        print(f"[ERROR] No se pudieron detectar páginas con pdfplumber: {e}")
        return False

def extract_pdf_pages(bucket, key):
    """
    Llama a Textract detect_document_text para un PDF en S3
    y devuelve un array donde cada elemento es el texto de una página.
    """
    
    pages = {}  # page_number -> texto

    # 1) Iniciar el análisis asincrónico
    response = textract.start_document_text_detection(
        DocumentLocation={
            'S3Object': {'Bucket': bucket, 'Name': key}
        }
    )

    job_id = response['JobId']

    # 2) Polling hasta que termine
    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status = result['JobStatus']

        if status in ['SUCCEEDED', 'FAILED']:
            break
        
        time.sleep(1)

    if status == 'FAILED':
        raise Exception("Textract job failed")

    # 3) Construir un array por página
    pages = {}
    next_token = None

    while True:
        if next_token:
            result = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)
        else:
            result = textract.get_document_text_detection(JobId=job_id)

        for block in result['Blocks']:
            if block['BlockType'] == 'LINE':
                page = block['Page']
                if page not in pages:
                    pages[page] = []
                pages[page].append(block['Text'])

        next_token = result.get('NextToken')
        if not next_token:
            break

    # Convertir cada página en un string completo
    ordered_pages = [ "\n".join(pages[p]) for p in sorted(pages.keys()) ]
    return ordered_pages

# Patrones para detectar títulos y subtítulos
TITLE_PATTERNS = [
    r'^#{1,6}\s+.+$',                           # Markdown headers
    r'^\d+\.[\d\.]*\s+[A-ZÁÉÍÓÚÑ].*$',          # Numeración: 1. Título, 1.1 Subtítulo
    r'^[IVXLCDM]+\.\s+.+$',                     # Numeración romana: I. Título
    r'^[A-Z][A-Z\s]{3,}$',                      # TÍTULOS EN MAYÚSCULAS (mín 4 chars)
    r'^(?:Capítulo|Sección|Artículo|Anexo)\s+\d*.*$',  # Palabras clave de sección
    r'^(?:Chapter|Section|Article|Annex)\s+\d*.*$',    # Palabras clave en inglés
]

def _detect_title_separators(text: str) -> list:
    """
    Detecta patrones de títulos en el texto y genera separadores personalizados.
    """
    separators = []
    lines = text.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        for pattern in TITLE_PATTERNS:
            if re.match(pattern, line_stripped, re.MULTILINE):
                # Crear separador único para este título
                sep = f"\n{line_stripped}\n"
                if sep not in separators and len(line_stripped) > 3:
                    separators.append(sep)
                break
    
    return separators

def _get_chunk_config(num_pages: int) -> dict:
    """
    Retorna configuración óptima de chunking basada en el número de páginas.
    Prioridad 1: Tamaño del archivo
    """
    if num_pages <= 10:
        # Archivos muy pequeños: chunks finos para máxima precisión semántica
        return {
            "chunk_size": 800,
            "chunk_overlap": 150,
            "use_textract": False
        }
    elif num_pages <= 50:
        # Archivos medianos: balance entre precisión y eficiencia
        return {
            "chunk_size": 1200,
            "chunk_overlap": 150,
            "use_textract": False
        }
    elif num_pages <= 150:
        # Archivos grandes: chunks más amplios
        return {
            "chunk_size": 1800,
            "chunk_overlap": 100,
            "use_textract": True
        }
    else:
        # Archivos muy grandes: maximizar eficiencia
        return {
            "chunk_size": 2500,
            "chunk_overlap": 80,
            "use_textract": True
        }

def _build_separators(custom_title_seps: list) -> list:
    """
    Construye lista de separadores priorizando títulos y subtítulos.
    Prioridad 2: Títulos y subtítulos como puntos de corte preferidos
    """
    # Separadores base ordenados por prioridad semántica
    base_separators = [
        "\n\n\n",           # Triple salto = cambio de sección mayor
        "\n\n",             # Doble salto = nuevo párrafo/sección
        "\n",               # Salto de línea simple
        ". ",               # Fin de oración
        "? ",               # Pregunta
        "! ",               # Exclamación
        "; ",               # Punto y coma
        ", ",               # Coma
        " ",                # Espacio
    ]
    
    # Insertar separadores de títulos detectados al inicio (máxima prioridad)
    # Ordenar por longitud descendente para que títulos más específicos se procesen primero
    sorted_titles = sorted(custom_title_seps, key=len, reverse=True)
    
    return sorted_titles + base_separators

def _get_page_count(bucket: str, key: str, local_path: str | None = None) -> int:
    """
    Obtiene el número de páginas del PDF. Prefiere /tmp (ya bajado por el handler) para no leer otra vez desde S3.
    """
    if local_path and os.path.isfile(local_path):
        try:
            with pdfplumber.open(local_path) as pdf:
                return len(pdf.pages)
        except Exception as e:
            print(f"[WARN] Páginas desde disco falló ({e}), leyendo desde S3")
    pdf_obj = s3.get_object(Bucket=bucket, Key=key)
    pdf_bytes = pdf_obj["Body"].read()
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception as e:
        print(f"[ERROR] No se pudieron detectar páginas: {e}")
        return 0

def _extract_text_with_structure(local_path: str) -> str:
    """
    Extrae texto preservando estructura visual para mejor detección de títulos.
    """
    full_text_parts = []
    
    with pdfplumber.open(local_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                full_text_parts.append(page_text)
            full_text_parts.append("\n\n")  # Separador entre páginas
    
    return "".join(full_text_parts)


def _extract_text_pymupdf(local_path: str) -> str:
    """PyMuPDF: rápido, sin llamadas AWS; vuelve texto por página. Malo en escaneos sin OCR."""
    import fitz  # PyMuPDF

    doc = fitz.open(local_path)
    try:
        parts: list[str] = []
        for page in doc:
            t = page.get_text() or ""
            if t.strip():
                parts.append(t)
            parts.append("\n\n")
        return "".join(parts)
    finally:
        doc.close()


def _extract_text_local_preferred(local_path: str) -> str:
    """Camino crítico local: PyMuPDF primero; si falla, pdfplumber (misma semántica que antes)."""
    try:
        text = _extract_text_pymupdf(local_path)
        if text.strip():
            return text
    except Exception as e:
        print(f"[WARN] PyMuPDF falló: {e}; reintento con pdfplumber")
    return _extract_text_with_structure(local_path)

def generate_semantic_chunks(bucket, key, local_path=None):
    """
    Devuelve chunks semánticos optimizados.
    
    Prioridad 1: Tamaño del archivo → determina configuración de chunks
    Prioridad 2: Títulos y subtítulos → puntos de corte semánticos preferidos
    """
    # 1️⃣ Obtener número de páginas y configuración óptima (reusa archivo local si existe)
    num_pages = _get_page_count(bucket, key, local_path=local_path)
    config = _get_chunk_config(num_pages)
    
    use_aws_textract = config["use_textract"] and USE_TEXTRACT
    print(
        f"[INFO] PDF con {num_pages} páginas → chunk_size={config['chunk_size']}, "
        f"use_textract_config={config['use_textract']}, use_aws_textract={use_aws_textract}"
    )
    
    chunks = []
    
    # 2️⃣ Texto: Textract (AWS) solo si explícitamente USE_TEXTRACT=true; si no, todo local (PyMuPDF + fallback).
    if use_aws_textract:
        page_texts = extract_pdf_pages(bucket, key)
        full_text = "\n\n".join([t for t in page_texts if t and t.strip()])
    else:
        if local_path is None:
            raise Exception("local_path es obligatorio para extracción local de PDFs.")
        full_text = _extract_text_local_preferred(local_path)
    
    if not full_text.strip():
        return []
    
    # 3️⃣ Detectar títulos y construir separadores personalizados
    title_separators = _detect_title_separators(full_text)
    separators = _build_separators(title_separators)
    
    print(f"[INFO] Detectados {len(title_separators)} patrones de títulos/subtítulos")
    
    # 4️⃣ Crear splitter con configuración optimizada
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["chunk_size"],
        chunk_overlap=config["chunk_overlap"],
        separators=separators,
        length_function=len,
        is_separator_regex=False
    )
    
    # 5️⃣ Generar chunks
    raw_chunks = splitter.split_text(full_text)
    
    # 6️⃣ Limpiar y filtrar chunks vacíos o muy pequeños
    min_chunk_size = 50  # Mínimo de caracteres útiles
    for chunk in raw_chunks:
        cleaned = chunk.strip()
        if cleaned and len(cleaned) >= min_chunk_size:
            chunks.append(cleaned)
    
    print(f"[INFO] Generados {len(chunks)} chunks semánticos")
    
    return chunks

def to_pgvector(vec):
    return "[" + ",".join(str(x) for x in vec) + "]"


def _unwrap_sqs_to_s3_event(event: dict) -> dict:
    """
    Evento SQS estándar: Records[].body = JSON con {"Records": [ <evento S3> ]}
    (enviado por rag_lmbd_embeddings_enqueue).
    """
    merged: list = []
    for r in event.get("Records", []):
        if r.get("eventSource") != "aws:sqs":
            continue
        body = r.get("body", "")
        try:
            inner = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"body SQS no es JSON válido: {e}") from e
        if isinstance(inner, dict) and "Records" in inner:
            merged.extend(inner["Records"])
        elif isinstance(inner, dict) and inner.get("s3"):
            merged.append(inner)
    if not merged:
        raise ValueError("SQS: body sin records S3")
    return {"Records": merged}


def handler(event, context):
    print(f"Event received: {event}")
    start_time = time.time()

    from_sqs = bool(
        event.get("Records")
        and event["Records"]
        and event["Records"][0].get("eventSource") == "aws:sqs"
    )
    if from_sqs:
        try:
            event = _unwrap_sqs_to_s3_event(event)
        except Exception as e:
            print(f"[ERROR] desenrollar SQS: {e}")
            raise

    # Invocación directa (agente): payload con "text"; opcional "input_type" (default search_document).
    if not event.get("Records"):
        text = event.get("text")
        input_type = event.get("input_type", "search_document")
        if isinstance(event.get("body"), str):
            try:
                body = json.loads(event["body"])
                text = text if text is not None else body.get("text")
                input_type = body.get("input_type", input_type)
            except json.JSONDecodeError:
                body = {}
        elif isinstance(event.get("body"), dict):
            body = event["body"]
            text = text if text is not None else body.get("text")
            input_type = body.get("input_type", input_type)
        if text is not None:
            try:
                vec = embed(str(text), input_type=input_type)
                return {"statusCode": 200, "body": json.dumps({"embedding": vec})}
            except Exception as e:
                print(f"[ERROR] embed directo: {e}")
                return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Se esperaba evento S3 (Records) o campo text"}),
        }

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key_raw = record["s3"]["object"]["key"]
    key = unquote_plus(key_raw).lstrip("/")

    print(f"[INFO] Bucket: {bucket}")
    print(f"[INFO] Key raw: {key_raw}")
    print(f"[INFO] Key decoded: {key}")

    try:
        tenant_id, agent_id, document_name, created_at_partition = parse_s3_rag_key(key)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}

    print(f"[INFO] created_at desde partición S3: {created_at_partition or 'NOW() (sin YYYYMMDD en ruta)'}")

    document_id = str(uuid.uuid4())

    local_path = f"/tmp/{key.split('/')[-1]}"
    try:
        s3.download_file(bucket, key, local_path)
        print("HEAD OK")
    except ClientError as e:
        print("HEAD ERROR:", e.response)
        if from_sqs:
            raise
        return {"statusCode": 500, "body": json.dumps({"error": "No se pudo descargar el PDF"})}

    chunks = generate_semantic_chunks(bucket, key, local_path)

    if not chunks:
        print("[WARN] Sin chunks extraídos; no se eliminan ni insertan filas")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "PDF sin texto extraíble; base sin cambios"}),
        }

    ensure_tenant_schema_exists(tenant_id, agent_id)

    # Reemplazo lógico por documento: mismo agente + nombre de archivo → borrar chunks viejos (A3).
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        DELETE FROM {tenant_id}.documents
        WHERE agent_id = %s::uuid AND document_name = %s
        """,
        (agent_id, document_name),
    )

    # Texto embebido con prefijo ligero de archivo; chunk_text almacenado sin prefijo (M5).
    texts_for_embed = [f"[{document_name}]\n{c}" for c in chunks]
    embeddings = embed_texts_batch(texts_for_embed, input_type="search_document")

    rows = [
        (
            agent_id,
            document_id,
            document_name,
            chunk,
            to_pgvector(embedding),
            created_at_partition,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]
    execute_values(
        cur,
        f"""
        INSERT INTO {tenant_id}.documents (
            agent_id, document_id, document_name, chunk_text, embedding, created_at
        ) VALUES %s
        """,
        rows,
        template="""(%s::uuid, %s::uuid, %s, %s, %s::vector, COALESCE(%s::timestamp, NOW()))""",
        page_size=len(rows) if rows else 1,
    )

    conn.commit()
    cur.close()
    conn.close()

    elapsed_time = time.time() - start_time
    print(f"[INFO] Handler completado en {elapsed_time:.2f} segundos")

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "PDF procesado correctamente"}),
    }

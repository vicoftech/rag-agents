import os
import json
import boto3
import pdfplumber
import psycopg2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from botocore.exceptions import ClientError
import uuid
import io
import time
import numpy as np
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

# 🔐 Se deben pasar estas variables al Lambda (ENV VARS)
DB_NAME = os.getenv("DB_NAME","postgres")
DB_USER = os.getenv("DB_USER","postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD","postgres")
DB_HOST = os.getenv("DB_HOST","localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
#EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "cohere.embed-v4:0")

MAX_EMBED_TEXT_LENGTH = 20000

def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )

def normalize(v):
    v = np.array(v, dtype=np.float32).squeeze()
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


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


'''
def embed(text: str):
    """
    Embed robusto compatible con modelos Titan/OpenAI en Bedrock.
    Incluye:
      - recorte si el texto es demasiado largo
      - estructura correcta del JSON
      - normalización del vector (OBLIGATORIO)
    """

    # 1) Seguridad contra textos enormes
    if len(text) > MAX_EMBED_TEXT_LENGTH:
        text = text[:MAX_EMBED_TEXT_LENGTH]
    
    payload = {
        "inputText": text    # PARA TITAN
        # "input": text      # PARA OPENAI/OSS
    }


    payload = {
        "texts": [text],
        "input_type": "search_document"
    }

    response = bedrock.invoke_model(
        modelId=EMBEDDINGS_MODEL,
        body=json.dumps(payload)
    )

    body = response["body"].read()
    result = json.loads(body)

    # Titan v1/v2 → embedding está en "embedding"
    if "embeddings" in result:
        vec = result["embeddings"]

    # OpenAI compatible en Bedrock (gpt-oss-*) → embedding está en: result["data"][0]["embedding"]
    elif "data" in result and "embedding" in result["data"][0]:
        vec = result["data"][0]["embedding"]

    else:
        raise Exception(f"Formato inesperado en respuesta de embeddings: {result}")

    # Normalizar SIEMPRE
    vec_norm = normalize(np.array(vec))

    return vec_norm.tolist()
'''


def semantic_search(tenant_id,query, k=3):
    # Generar embedding desde el LLM
    q_emb = embed(query)

    # Convertir la lista de floats al formato textual esperado por pgvector: [x,y,z,...]
    q_emb_str = "[" + ",".join(str(x) for x in q_emb) + "]"

    conn = get_connection()
    cur = conn.cursor()

    # Hacer la búsqueda semántica casteando explícitamente a vector
    cur.execute(f"""
        SELECT 
            chunk_text, 
            embedding <=> %s::vector AS distance
        FROM {tenant_id}.documents
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """, (q_emb_str, q_emb_str, k))

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

def generate_semantic_chunks(bucket, key, local_path=None):
    """
    Devuelve chunks semánticos optimizados según tamaño del PDF.
    - Menos de 50 páginas → extrae todo el texto y hace chunk con semántica fina.
    - Más de 50 páginas → usa Textract por página para evitar pérdida de info.
    """

    # 1️⃣ Detectar páginas
    is_large = pdf_has_more_than_50_pages(bucket, key)

    chunks = []

    # 2️⃣ Configurar splitter adaptativo
    # Archivos chicos → chunk semántico fino
    # Archivos grandes → chunk más amplio para evitar explosión de chunks
    if is_large:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=2000,       # más grande para reducir cantidad de chunks
            chunk_overlap=100,
            separators=["\n\n", "\n", ".", "!", "?", " "],
            length_function=len
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,      # más pequeño → mejor semántica
            chunk_overlap=150,
            separators=["\n\n", "\n", ".", "!", "?", ",", " "],
            length_function=len
        )

    # 3️⃣ Proceso según tamaño
    if is_large:
        # --- PDFs grandes ---
        blocks = extract_pdf_pages(bucket, key)   # Devuelve texto por página

        for block in blocks:
            if not block or not block.strip():
                continue
            subchunks = splitter.split_text(block)
            chunks.extend(subchunks)

    else:
        # --- PDFs chicos ---
        if local_path is None:
            raise Exception("local_path es obligatorio para PDFs pequeños.")

        pdf = pdfplumber.open(local_path)
        full_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
        pdf.close()

        subchunks = splitter.split_text(full_text)
        chunks.extend(subchunks)

    return chunks

def to_pgvector(vec):
    return "[" + ",".join(str(x) for x in vec) + "]"

def handler(event, context):
    # 1️⃣ Obtener bucket y key del evento S3
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"].lstrip("/")
    parts = key.split("/")
    tenant_id = parts[0]       # "123"
    agent_id = parts[1]        # "456"
    file_name = parts[-1]
    document_id = str(uuid.uuid4())  

    # 2️⃣ Descargar PDF a /tmp
    local_path = f"/tmp/{key.split('/')[-1]}"
    try:
        s3.download_file(bucket, key, local_path)
        print("HEAD OK")
    except ClientError as e:
        print("HEAD ERROR:", e.response)

    chunks = generate_semantic_chunks(bucket, key, local_path)
    # 5️⃣ Insertar embeddings en Aurora PostgreSQL
    conn = get_connection()
    cur = conn.cursor()
    
    for chunk in chunks:
        embedding = embed(chunk)
                
        cur.execute(
            f"""
            INSERT INTO {tenant_id}.documents (
                agent_id,
                document_id,
                document_name,
                chunk_text,
                embedding
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (agent_id, document_id, file_name, chunk, to_pgvector(embedding))
        )

    conn.commit()
    cur.close()
    conn.close()

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "PDF procesado correctamente"})
    }

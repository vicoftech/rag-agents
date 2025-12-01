import os
import json
import boto3
import pdfplumber
import psycopg2
from langchain.text_splitter import RecursiveCharacterTextSplitter
from bedrock import EmbeddingClient

s3 = boto3.client("s3")
client = EmbeddingClient(region="us-east-1")

# 🔐 Se deben pasar estas variables al Lambda (ENV VARS)
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_HOST = os.environ["DB_HOST"]
DB_PORT = os.environ.get("DB_PORT", "5432")

def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )

def embed(text):
    resp = client.embed(
        model="amazon.titan-embed-text-v2",
        input=text
    )
    return resp["embedding"]

def lambda_handler(event, context):
    # 1️⃣ Obtener bucket y key del evento S3
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    # 2️⃣ Descargar PDF a /tmp
    local_path = f"/tmp/{key.split('/')[-1]}"
    s3.download_file(bucket, key, local_path)

    # 3️⃣ Extraer texto del PDF
    pdf = pdfplumber.open(local_path)
    full_text = "\n".join(
        [page.extract_text() or "" for page in pdf.pages]
    )
    pdf.close()

    # 4️⃣ Split en chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=500
    )
    chunks = splitter.split_text(full_text)

    # 5️⃣ Insertar embeddings en Aurora PostgreSQL
    conn = get_connection()
    cur = conn.cursor()

    for chunk in chunks:
        embedding = embed(chunk)

        cur.execute(
            """
            INSERT INTO documents (chunk_text, embedding)
            VALUES (%s, %s)
            """,
            (chunk, embedding)
        )

    conn.commit()
    cur.close()
    conn.close()

    return {
        "statusCode": 200,
        "body": json.dumps({"message": "PDF procesado correctamente"})
    }

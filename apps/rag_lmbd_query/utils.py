from datetime import datetime
import hashlib
from pathlib import Path
import mimetypes
import time
import re 
import jwt
from urllib.parse import urlparse, parse_qs
import json
import base64
import sys

def format_date(dt: datetime) -> str:
    """Format datetime to ISO 8601 string"""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def generate_document_id(key, length=12):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:length]


def get_extension_from_key(key: str) -> str:
    return Path(key).suffix


def get_mime_type_from_extension(extension: str) -> str:
    """
    Retorna el MIME type a partir de una extensión de archivo.
    
    Args:
        extension (str): La extensión del archivo, con o sin punto (ej: '.pdf' o 'pdf')
    
    Returns:
        str: El MIME type correspondiente o 'application/octet-stream' si no se encuentra
    """
    # Asegurarse de que la extensión comience con un punto
    if not extension.startswith('.'):
        extension = f'.{extension}'
    
    mime_type, _ = mimetypes.guess_type(f'file{extension}')
    return mime_type or 'application/octet-stream'




import time
import boto3

def extract_text(client, bucket, key, max_attempts=30, base_interval=5):
    try:
        response = client.start_document_text_detection(
            DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
        )
        job_id = response['JobId']

        for attempt in range(max_attempts):
            result = client.get_document_text_detection(JobId=job_id)
            status = result['JobStatus']
            if status == 'SUCCEEDED':
                return result
            elif status == 'FAILED':
                break
            time.sleep(base_interval * (2 ** attempt))  # backoff exponencial

        # fallback síncrono
        response = client.detect_document_text(
            Document={'S3Object': {'Bucket': bucket, 'Name': key}}
        )
        lines = [b['Text'] for b in response['Blocks'] if b['BlockType'] == 'LINE']
        return "\n".join(lines)
    except Exception as e:
        print(f"Error: {e} extracting document: {key}")
    


def detect_qr_with_textract(client,bucket, key):
    response = client.detect_document_text(
        Document={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    lines = [block['Text'] for block in response['Blocks'] if block['BlockType'] == 'LINE']

    # Buscar patrones típicos de contenido QR
    for line in lines:
        if re.search(r'(https?://\S+|WIFI:|otpauth://)', line, re.IGNORECASE):
            return line.strip()
    return None


def decode_base64url_json(token: str) -> dict:
    padding = '=' * (-len(token) % 4)
    token += padding
    try:
        decoded_bytes = base64.urlsafe_b64decode(token)
        decoded_str = decoded_bytes.decode('utf-8')
        return json.loads(decoded_str)
    except Exception as e:
        print(f"Error decoding base64 JSON token: {e}")
        return {}


def decode_jwt_to_json(token: str) -> dict:
    """
    Decode a JWT token without signature verification and return its payload as a dict.
    If token is not a valid JWT (not enough segments), decode as base64url JSON.
    """
    if token:
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload
        except jwt.DecodeError as e:
            if "Not enough segments" in str(e):
                print("Token no tiene el formato JWT, intentando decodificar como base64url JSON...")
                return decode_base64url_json(token)
            else:
                print(f"Error decoding JWT: {e}")
                return {}
        except Exception as e:
            print(f"Error decoding JWT: {e}")
            return {}
    else:
        raise Exception(f"Token is None") 
    
def extract_jwt_from_url(url: str) -> str:
    """
    Extrae el token JWT del parámetro 'p' de una URL.
    Devuelve el JWT como string o None si no se encuentra.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    jwt_list = query_params.get('p')
    if jwt_list and len(jwt_list) > 0:
        return jwt_list[0]
    return None

def save_text(document_id, extracted_text, max_ddb_item_size,s3_client,bucket_name):
    # Medir tamaño aproximado del texto en bytes

    blocks = extracted_text['Blocks']

    # Extraer solo el texto de los bloques LINE
    all_text = "\n".join(block['Text'] for block in blocks if block['BlockType'] == 'LINE')

    len(all_text.encode('utf-8'))

    if sys.getsizeof(all_text) / 1024 > max_ddb_item_size:
        # Generar un nombre de archivo único en S3
        s3_key = f'extracted_text/{document_id}.txt'

        # Guardar en S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=extracted_text.encode('utf-8')
        )
        return s3_key
    else:
        return all_text

import json
import os
import requests
import boto3
import re
from urllib.parse import urlparse, unquote
from datetime import datetime
from typing import List, Dict, Optional
import hashlib

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
# No usar credenciales hardcodeadas - usar rol de ejecución de Lambda
# if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
#     session_args.update({
#         'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
#         'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
#     })

# AWS Clients
s3_client = boto3.client('s3', **session_args)

# Environment variables
S3_BUCKET = os.getenv('S3_BUCKET_NAME')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '60'))
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', str(50 * 1024 * 1024)))  # 50MB

# Headers para descargar archivos
DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/pdf,application/octet-stream,*/*',
    'Accept-Language': 'es-AR,es;q=0.8,en-US;q=0.5,en;q=0.3',
}

def generate_site_id(url: str) -> str:
    """
    Genera un site_id a partir de la URL (dominio normalizado)
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    # Remover www. si existe
    if domain.startswith('www.'):
        domain = domain[4:]
    # Reemplazar caracteres no válidos
    site_id = domain.replace('.', '_').replace('-', '_')
    
    # Si no hay dominio válido, usar un valor por defecto
    if not site_id:
        site_id = 'boletin_oficial'
    
    return site_id

def extract_date_from_context(context: Dict) -> Optional[str]:
    """
    Extrae fecha del contexto (page_date, o de URLs)
    """
    # Intentar obtener del page_date
    page_date = context.get('page_date')
    if page_date:
        return normalize_date(page_date)
    
    # Intentar extraer de las URLs de PDFs
    pdf_links = context.get('pdf_links', [])
    for pdf in pdf_links:
        url = pdf.get('url', '')
        date_match = extract_date_from_url(url)
        if date_match:
            return date_match
    
    # Si no hay fecha, usar fecha actual
    return datetime.now().strftime('%Y-%m-%d')

def normalize_date(date_str: str) -> str:
    """
    Normaliza diferentes formatos de fecha a YYYY-MM-DD
    """
    date_patterns = [
        r'(\d{2})/(\d{2})/(\d{4})',  # DD/MM/YYYY
        r'(\d{2})-(\d{2})-(\d{4})',  # DD-MM-YYYY
        r'(\d{4})-(\d{2})-(\d{2})',  # YYYY-MM-DD
        r'(\d{4})/(\d{2})/(\d{2})',  # YYYY/MM/DD
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_str)
        if match:
            groups = match.groups()
            if len(groups[0]) == 4:  # YYYY-MM-DD format
                return f"{groups[0]}-{groups[1]}-{groups[2]}"
            else:  # DD-MM-YYYY format
                return f"{groups[2]}-{groups[1]}-{groups[0]}"
    
    return date_str  # Return original if no pattern matches

def extract_date_from_url(url: str) -> Optional[str]:
    """
    Extrae fecha de una URL
    """
    # Buscar patrones de fecha en la URL
    import re
    date_patterns = [
        r'(\d{4})-(\d{2})-(\d{2})',  # YYYY-MM-DD
        r'(\d{2})-(\d{2})-(\d{4})',  # DD-MM-YYYY
        r'(\d{4})(\d{2})(\d{2})',    # YYYYMMDD
        r'(\d{2})(\d{2})(\d{4})',    # DDMMYYYY
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, url)
        if match:
            groups = match.groups()
            if len(groups[0]) == 4:  # YYYY-MM-DD format
                return f"{groups[0]}-{groups[1]}-{groups[2]}"
            else:  # DD-MM-YYYY format
                return f"{groups[2]}-{groups[1]}-{groups[0]}"
    
    return None

def generate_filename(pdf_info: Dict, index: int) -> str:
    """
    Genera nombre de archivo para el PDF
    """
    # Intentar usar el título del PDF
    title = pdf_info.get('title', '').strip()
    if title:
        # Limpiar título para usar como filename
        filename = re.sub(r'[^\w\-_\.]', '_', title)
        filename = re.sub(r'_+', '_', filename)
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        return filename
    
    # Si no hay título, usar el nombre del archivo de la URL
    url = pdf_info.get('url', '')
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    
    if not filename or not filename.lower().endswith('.pdf'):
        # Usar índice como fallback
        filename = f"document_{index}.pdf"
    
    return filename

def download_pdf(url: str) -> Optional[bytes]:
    """
    Descarga un PDF desde una URL
    """
    try:
        print(f"Downloading PDF from: {url}")
        response = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        response.raise_for_status()
        
        # Verificar tamaño del archivo
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > MAX_FILE_SIZE:
            print(f"File too large: {content_length} bytes")
            return None
        
        # Descargar contenido
        content = b''
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                content += chunk
                if len(content) > MAX_FILE_SIZE:
                    print(f"File exceeded maximum size: {len(content)} bytes")
                    return None
        
        # Verificar que sea un PDF válido
        if not content.startswith(b'%PDF'):
            print("Downloaded file is not a valid PDF")
            return None
        
        return content
        
    except requests.RequestException as e:
        print(f"Error downloading PDF: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error downloading PDF: {e}")
        return None

def upload_to_s3(content: bytes, bucket: str, key: str) -> bool:
    """
    Sube contenido a S3
    """
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType='application/pdf',
            ServerSideEncryption='AES256'
        )
        print(f"Successfully uploaded to S3: s3://{bucket}/{key}")
        return True
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False

def generate_filename_from_url(pdf_url: str, index: int, date_str: str, section: str) -> str:
    """
    Genera nombre de archivo para PDF basado en URL, fecha y sección
    """
    # Extraer ID del aviso de la URL
    # Ej: https://www.boletinoficial.gob.ar/pdf/aviso/primera/339534/20260317
    # -> aviso_339534_20260317_primera.pdf
    parts = pdf_url.strip('/').split('/')
    if len(parts) >= 6:
        aviso_id = parts[5]  # El ID del aviso
    else:
        aviso_id = f"aviso_{index:03d}"
    
    # Limpiar URL de parámetros
    clean_url = pdf_url.split('?')[0]
    
    # Generar nombre único
    timestamp = datetime.now().strftime('%H%M%S')
    filename = f"aviso_{aviso_id}_{date_str}_{section}_{timestamp}.pdf"
    
    return filename

def process_bolinks_output(bolinks_output: Dict) -> Dict:
    """
    Procesa el output de bolinks y sube los PDFs a S3
    """
    try:
        # Validar que bolinks tuvo éxito
        if not bolinks_output.get('success', False):
            return {
                'success': False,
                'error': 'Bolinks output indicates failure',
                'bolinks_output': bolinks_output
            }
        
        # Extraer información del contexto
        pdf_links = bolinks_output.get('pdf_links', [])
        date = bolinks_output.get('received_params', {}).get('date', '')
        section = bolinks_output.get('received_params', {}).get('section', 'primera')
        
        if not pdf_links:
            return {
                'success': True,
                'message': 'No PDF links found to process',
                'processed_count': 0,
                'uploaded_files': []
            }
        
        # Generar metadata
        site_id = 'boletin_oficial'
        date_str = date
        
        print(f"Processing {len(pdf_links)} PDFs for site: {site_id}, date: {date_str}, section: {section}")
        
        uploaded_files = []
        processed_count = 0
        failed_count = 0
        
        for index, pdf_url in enumerate(pdf_links):
            if not pdf_url:
                continue
            
            # Descargar PDF
            pdf_content = download_pdf(pdf_url)
            if not pdf_content:
                failed_count += 1
                continue
            
            # Generar nombre de archivo
            filename = generate_filename_from_url(pdf_url, index, date_str, section)
            
            # Subir a S3
            s3_key = f"{site_id}/{date_str}/{section}/{filename}"
            if upload_to_s3(pdf_content, S3_BUCKET, s3_key):
                uploaded_files.append({
                    'url': pdf_url,
                    's3_key': s3_key,
                    'filename': filename,
                    'size': len(pdf_content),
                    'metadata': {
                        'date': date_str,
                        'section': section,
                        'site_id': site_id
                    }
                })
                processed_count += 1
            else:
                failed_count += 1
        
        return {
            'success': True,
            'site_id': site_id,
            'date': date_str,
            'section': section,
            'processed_count': processed_count,
            'failed_count': failed_count,
            'total_found': len(pdf_links),
            'uploaded_files': uploaded_files,
            's3_bucket': S3_BUCKET
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing bolinks output: {str(e)}',
            'exception': str(e)
        }

def handler(event, context):
    """
    Lambda handler para procesar output del parser y subir PDFs a S3
    """
    # CORS headers
    CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
    }
    
    # Detectar si es un evento HTTP (API Gateway) o directo
    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")
    
    if http_method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": ""
        }
    
    try:
        # Extraer parámetros del request
        if http_method:
            # Request HTTP
            body = json.loads(event.get("body") or "{}")
            bolinks_output = body.get("bolinks_output")
        else:
            # Invocación directa (desde Step Function)
            bolinks_output = event.get("bolinks_output")
        
        # Validar parámetro bolinks_output
        if not bolinks_output:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: bolinks_output"})
            }
        
        # Procesar output de bolinks
        result = process_bolinks_output(bolinks_output)
        
        # Preparar respuesta
        if result['success']:
            response = {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(result)
            }
        else:
            response = {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(result)
            }
        
        return response
        
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps({"error": "Invalid JSON in request body"})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json", **CORS_HEADERS},
            "body": json.dumps({"error": f"Internal server error: {str(e)}"})
        }

if __name__ == "__main__":
    # Para testing local
    test_parser_output = {
        "success": True,
        "url": "https://www.boletinoficial.gob.ar/seccion/primera",
        "page_title": "BOLETIN OFICIAL REPUBLICA ARGENTINA",
        "page_date": "06/03/2026",
        "pdf_links": [
            {
                "url": "https://www.boletinoficial.gob.ar/documentos/boletin-2026-03-06.pdf",
                "text": "Boletín Completo",
                "title": "Boletín Completo",
                "date": "06/03/2026",
                "section": "primera"
            }
        ],
        "pdf_links_count": 1
    }
    
    test_event = {
        "parser_output": test_parser_output
    }
    
    result = handler(test_event, None)
    print("Result:", json.dumps(result, indent=2))

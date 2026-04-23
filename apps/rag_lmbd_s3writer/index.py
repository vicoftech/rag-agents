import json
import os
import socket
import time
import requests
import boto3
import re
import urllib3
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
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))
S3WRITER_SQS_MAX_RETRIES = int(os.getenv('S3WRITER_SQS_MAX_RETRIES', '3'))
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', str(50 * 1024 * 1024)))  # 50MB
# Pausa entre descargas (serie); reduce presión al origen (no es paralelo).
S3WRITER_PDF_DOWNLOAD_DELAY_SEC = float(os.getenv('S3WRITER_PDF_DOWNLOAD_DELAY_SEC', '0.25'))
ANMAT_HOSTNAME = "buscadispo.anmat.gob.ar"
ANMAT_HOST_IPV4 = "190.210.84.134"


def _normalize_tenant_prefix(tenant_id: str) -> str:
    """
    Asegura el prefijo canónico esperado por el pipeline de embeddings:
    tenant_<slug>/<agent_id>/documents
    """
    tenant = str(tenant_id or "").strip()
    if not tenant:
        return tenant
    return tenant if tenant.startswith("tenant_") else f"tenant_{tenant}"

# Headers para descargar archivos
DOWNLOAD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/pdf,application/octet-stream,*/*',
    'Accept-Language': 'es-AR,es;q=0.8,en-US;q=0.5,en;q=0.3',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache'
}


def resolve_batch_date_yyyymmdd(
    bolinks_output: Dict,
    uploaded_files: List[Dict],
    pdf_links: List[Dict],
) -> str:
    """
    Fecha de corrida en YYYYMMDD para DynamoDB (GSI EntityDateIndex).
    Prioriza received_params.date del bolinks, luego metadata de uploads.
    """
    rp = bolinks_output.get("received_params") or {}
    raw = rp.get("date")
    if raw:
        s = str(raw).strip()
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            try:
                return datetime.strptime(s, "%Y-%m-%d").strftime("%Y%m%d")
            except ValueError:
                pass
        if len(s) == 8 and s.isdigit():
            return s
    if uploaded_files:
        md = uploaded_files[0].get("metadata") or {}
        d2 = md.get("date")
        if d2:
            return str(d2)
    if pdf_links:
        d3 = pdf_links[0].get("date")
        if d3:
            return str(d3)
    return ""


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


def _resolve_ipv4(host: str, port: int) -> str:
    if host == ANMAT_HOSTNAME:
        return ANMAT_HOST_IPV4
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"no IPv4 address for {host}")
    return infos[0][4][0]


def _download_pdf_via_resolved_tls(
    clean_url: str,
) -> Optional[bytes]:
    """
    Conecta a la IPv4 resolvida con SNI/cabecera Host correctos. En Lambda a veces
    requests/urllib3 fallan en DNS (NameResolutionError) aunque getaddrinfo funcione.
    """
    p = urlparse(clean_url)
    host = p.hostname
    if not host:
        return None
    port = p.port or 443
    path = p.path or '/'
    if p.query:
        path = f"{path}?{p.query}"

    ip = _resolve_ipv4(host, port)
    print(f"download_pdf: {host} -> {ip} (TLS SNI={host})")

    headers = {**DOWNLOAD_HEADERS, 'Host': host}
    timeout = urllib3.Timeout(connect=min(REQUEST_TIMEOUT, 45), read=REQUEST_TIMEOUT)

    pool = urllib3.HTTPSConnectionPool(
        host=ip,
        port=port,
        server_hostname=host,
        maxsize=1,
        block=True,
        cert_reqs='CERT_REQUIRED',
    )
    r = pool.request(
        'GET',
        path,
        headers=headers,
        timeout=timeout,
        preload_content=False,
        retries=False,
    )
    try:
        if r.status >= 400:
            print(f"HTTP error: {r.status}")
            return None
        cl = r.headers.get('content-length')
        if cl and int(cl) > MAX_FILE_SIZE:
            print(f"File too large: {cl} bytes")
            return None
        content = b''
        chunk_count = 0
        for chunk in r.stream(4096):
            if chunk:
                content += chunk
                chunk_count += 1
                if chunk_count % 50 == 0:
                    print(f"Downloaded {len(content)} bytes so far...")
                if len(content) > MAX_FILE_SIZE:
                    print(f"File exceeded maximum size: {len(content)} bytes")
                    return None
        print(f"Successfully downloaded {len(content)} bytes in {chunk_count} chunks (urllib3/TLS)")
        if not content.startswith(b'%PDF'):
            print("Warning: Downloaded content may not be a valid PDF")
        return content
    finally:
        r.release_conn()


def download_pdf(url: str) -> Optional[bytes]:
    """
    Descarga un PDF desde una URL (serie; no hay paralelismo aquí).
    Prioriza resolución IPv4 + HTTPS con SNI para evitar NameResolutionError en Lambda.
    """
    clean_url = url.split('?')[0]
    print(f"Downloading PDF from: {url}")
    print(f"Clean URL for download: {clean_url}")

    try:
        return _download_pdf_via_resolved_tls(clean_url)
    except OSError as e:
        print(f"Resolved-IP path DNS error: {e}")
    except urllib3.exceptions.HTTPError as e:
        print(f"Resolved-IP path HTTP error: {e}")
    except Exception as e:
        print(f"Resolved-IP path error: {e}")

    try:
        response = requests.get(
            clean_url,
            headers=DOWNLOAD_HEADERS,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()
        cl = response.headers.get('content-length')
        if cl and int(cl) > MAX_FILE_SIZE:
            print(f"File too large: {cl} bytes")
            return None
        content = b''
        chunk_count = 0
        for chunk in response.iter_content(chunk_size=4096):
            if chunk:
                content += chunk
                chunk_count += 1
                if chunk_count % 50 == 0:
                    print(f"Downloaded {len(content)} bytes so far...")
                if len(content) > MAX_FILE_SIZE:
                    print(f"File exceeded maximum size: {len(content)} bytes")
                    return None
        print(f"Successfully downloaded {len(content)} bytes (requests fallback)")
        if not content.startswith(b'%PDF'):
            print("Warning: Downloaded content may not be a valid PDF")
        return content
    except requests.RequestException as e:
        print(f"Error downloading PDF (requests fallback): {e}")
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

def process_bolinks_output(bolinks_output: Dict, tenant_id: str, agent_id: str) -> Dict:
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
        #date = bolinks_output.get('received_params', {}).get('date', '')
        #section = bolinks_output.get('received_params', {}).get('section', 'primera')
        
        if not pdf_links:
            return {
                'success': True,
                'message': 'No PDF links found to process',
                'processed_count': 0,
                'uploaded_files': []
            }
        
        # Generar metadata (prefijo S3 canónico para RAG)
        tenant_prefix = _normalize_tenant_prefix(tenant_id)
        site_id = f"{tenant_prefix}/{agent_id}/documents"
        
        uploaded_files = []
        processed_count = 0
        failed_count = 0
        
        # Limitar el número de PDFs a procesar para evitar timeouts
        max_pdfs = min(len(pdf_links), 20)  # Procesar máximo 20 PDFs
        pdf_links_to_process = pdf_links[:max_pdfs]
        
        print(f"Processing {len(pdf_links_to_process)} PDFs (limited from {len(pdf_links)} total) for site: {site_id}")
        
        for index, pdf in enumerate(pdf_links_to_process):
            if not pdf.get("url"):
                continue

            if index > 0 and S3WRITER_PDF_DOWNLOAD_DELAY_SEC > 0:
                time.sleep(S3WRITER_PDF_DOWNLOAD_DELAY_SEC)

            date_str = pdf.get("date") or ""
            section = pdf.get("section") or "default"
            
            print(f"Processing PDF {index + 1}/{len(pdf_links_to_process)}: {pdf['url']}")
            
            # Descargar PDF
            pdf_content = download_pdf(pdf["url"])
            if not pdf_content:
                print(f"Failed to download PDF {index + 1}")
                failed_count += 1
                continue
            
            # Generar nombre de archivo
            filename = generate_filename_from_url(pdf["url"], index, date_str, section)
            # Subir a S3
            s3_key = f"{site_id}/{date_str}/{section}/{filename}"
            if upload_to_s3(pdf_content, S3_BUCKET, s3_key):
                s3_uri = f"s3://{S3_BUCKET}/{s3_key}" if S3_BUCKET else ""
                uploaded_files.append({
                    'url': pdf["url"],
                    'original_url': pdf["url"],
                    's3_key': s3_key,
                    's3_uri': s3_uri,
                    'filename': filename,
                    'size': len(pdf_content),
                    'metadata': {
                        'date': date_str,
                        'section': section,
                        'site_id': site_id
                    }
                })
                processed_count += 1
                print(f"Successfully uploaded PDF {index + 1}/{len(pdf_links_to_process)}")
            else:
                print(f"Failed to upload PDF {index + 1}/{len(pdf_links_to_process)}")
                failed_count += 1
        
        print(f"Processing complete: {processed_count} successful, {failed_count} failed")

        batch_date = resolve_batch_date_yyyymmdd(
            bolinks_output, uploaded_files, pdf_links
        )

        return {
            'success': True,
            'site_id': site_id,
            'date': batch_date,
            'processed_count': processed_count,
            'failed_count': failed_count,
            'total_found': len(pdf_links),
            'processed_limit': max_pdfs,
            'uploaded_files': uploaded_files,
            's3_bucket': S3_BUCKET
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing bolinks output: {str(e)}',
            'exception': str(e)
        }


def process_single_pdf(pdf: Dict, tenant_id: str, agent_id: str) -> Dict:
    """
    Sube un único PDF (mensaje SQS mode=single_pdf desde Step Functions Map).
    """
    try:
        if not pdf.get('url'):
            return {'success': False, 'error': 'missing url'}
        tenant_prefix = _normalize_tenant_prefix(tenant_id)
        site_id = f"{tenant_prefix}/{agent_id}/documents"
        date_str = pdf.get('date') or ''
        section = pdf.get('section') or 'default'
        print(f"single_pdf: {pdf['url']}")
        pdf_content = download_pdf(pdf['url'])
        if not pdf_content:
            return {
                'success': False,
                'error': 'download failed',
                'url': pdf.get('url'),
            }
        filename = generate_filename_from_url(pdf['url'], 0, date_str, section)
        s3_key = f"{site_id}/{date_str}/{section}/{filename}"
        if not upload_to_s3(pdf_content, S3_BUCKET, s3_key):
            return {
                'success': False,
                'error': 's3 upload failed',
                'url': pdf.get('url'),
            }
        s3_uri = f"s3://{S3_BUCKET}/{s3_key}" if S3_BUCKET else ""
        uploaded = [{
            'url': pdf['url'],
            'original_url': pdf['url'],
            's3_key': s3_key,
            's3_uri': s3_uri,
            'filename': filename,
            'size': len(pdf_content),
            'metadata': {
                'date': date_str,
                'section': section,
                'site_id': site_id,
            },
        }]
        return {
            'success': True,
            'site_id': site_id,
            'date': date_str or '',
            'processed_count': 1,
            'failed_count': 0,
            'uploaded_files': uploaded,
            's3_bucket': S3_BUCKET,
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'exception': str(e),
        }


def process_single_pdf_with_retries(
    pdf: Dict, tenant_id: str, agent_id: str
) -> Dict:
    last: Optional[Dict] = None
    for attempt in range(S3WRITER_SQS_MAX_RETRIES):
        result = process_single_pdf(pdf, tenant_id, agent_id)
        if result.get('success'):
            return result
        last = result
        if attempt < S3WRITER_SQS_MAX_RETRIES - 1:
            delay = 2 ** attempt
            print(
                f"single_pdf reintento {attempt + 2}/{S3WRITER_SQS_MAX_RETRIES} "
                f"tras {delay}s..."
            )
            time.sleep(delay)
    return last or {'success': False, 'error': 'process_single_pdf_with_retries: empty'}


def process_bolinks_with_retries(
    bolinks_output: Dict, tenant_id: str, agent_id: str
) -> Dict:
    """
    Reintentos con backoff exponencial (1s, 2s) ante resultado fallido.
    Tras S3WRITER_SQS_MAX_RETRIES devuelve el último resultado (el caller puede lanzar).
    """
    last: Optional[Dict] = None
    for attempt in range(S3WRITER_SQS_MAX_RETRIES):
        result = process_bolinks_output(bolinks_output, tenant_id, agent_id)
        if result.get('success'):
            return result
        last = result
        if attempt < S3WRITER_SQS_MAX_RETRIES - 1:
            delay = 2 ** attempt
            print(
                f"process_bolinks reintento {attempt + 2}/{S3WRITER_SQS_MAX_RETRIES} "
                f"tras {delay}s (success=false)..."
            )
            time.sleep(delay)
    return last or {'success': False, 'error': 'process_bolinks_with_retries: empty result'}


def _is_sqs_event(event) -> bool:
    r = event.get('Records')
    return bool(r and isinstance(r, list) and r[0].get('eventSource') == 'aws:sqs')


def _handle_sqs(event) -> Dict:
    """
    Cola alert-s3writer:
    - mode=single_pdf + pdf: un archivo (Step Function Map).
    - bolinks_output: lote legacy (varios PDFs en un mensaje).
    """
    results = []
    for record in event.get('Records') or []:
        if record.get('eventSource') != 'aws:sqs':
            continue
        body = json.loads(record['body'])
        tenant_id = body.get('tenant_id')
        agent_id = body.get('agent_id')
        if not tenant_id or not agent_id:
            raise ValueError('SQS message must include tenant_id and agent_id')

        single = body.get('mode') == 'single_pdf' or (
            body.get('pdf') is not None and body.get('bolinks_output') is None
        )
        if single:
            pdf = body.get('pdf')
            if not isinstance(pdf, dict) or not pdf.get('url'):
                raise ValueError('single_pdf message needs pdf.url')
            result = process_single_pdf_with_retries(pdf, tenant_id, agent_id)
        else:
            bolinks_output = body.get('bolinks_output')
            if not bolinks_output:
                raise ValueError(
                    'SQS message needs bolinks_output or single_pdf payload'
                )
            result = process_bolinks_with_retries(bolinks_output, tenant_id, agent_id)

        if not result.get('success'):
            raise RuntimeError(
                f"s3writer falló tras reintentos: {result.get('error', result)}"
            )
        results.append(result)
    return {
        'statusCode': 200,
        'body': json.dumps({'success': True, 'results': results}),
    }


def handler(event, context):
    """
    Lambda handler para procesar output del parser y subir PDFs a S3
    """
    print(f"handler event (raw): {json.dumps(event, default=str)}")

    if _is_sqs_event(event):
        return _handle_sqs(event)

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
            tenant_id = body.get("tenant_id")
            agent_id = body.get("agent_id")
        else:
            # Invocación directa (desde Step Function)
            bolinks_output = event.get("bolinks_output")
            tenant_id = event.get("tenant_id")
            agent_id = event.get("agent_id")
            # Algunas SFN solo envían bolinks_output; tenant/agent vienen en received_params.
            if isinstance(bolinks_output, dict):
                rp = bolinks_output.get("received_params") or {}
                if not tenant_id:
                    tenant_id = rp.get("tenant_id")
                if not agent_id:
                    agent_id = rp.get("agent_id")

        # Validar parámetro bolinks_output
        if not bolinks_output:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: bolinks_output"})
            }
        if not tenant_id:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: tenant_id"})
            }
        if not agent_id:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: agent_id"})
            }
        
        # Procesar output de bolinks
        result = process_bolinks_output(bolinks_output, tenant_id, agent_id)
        
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

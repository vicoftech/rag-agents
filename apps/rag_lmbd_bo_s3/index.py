from abc import ABC, abstractmethod
import json
import os
from playwright.sync_api import sync_playwright
import boto3
from datetime import datetime
import re
from typing import List, Dict, Optional


session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
S3_BUCKET = os.getenv('S3_BUCKET_NAME', "")

class FileStorage(ABC):
    @abstractmethod
    def upload(self, content: bytes, key: str) -> bool:
        pass

class FakeFileStorage(FileStorage):
    def upload(self, content: bytes, key: str) -> bool:
        print(f"Fake upload: {key}, {len(content)} bytes.")
        return True


class FileS3Storage(FileStorage):
    def __init__(self, bucket: str):
        # AWS Clients
        self.s3_client = boto3.client('s3', **session_args)
        self.bucket = bucket


    def upload(self, content: bytes, key: str) -> bool:
        return self.upload_to_s3(content, self.bucket, key)

    def upload_to_s3(self, content: bytes, bucket: str, key: str) -> bool:
        """
        Sube contenido a S3
        """
        try:
            self.s3_client.put_object(
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


def _normalize_tenant_prefix(tenant_id: str) -> str:
    """
    Asegura el prefijo canónico esperado por el pipeline de embeddings:
    tenant_<slug>/<agent_id>/documents
    """
    tenant = str(tenant_id or "").strip()
    if not tenant:
        return tenant
    return tenant if tenant.startswith("tenant_") else f"tenant_{tenant}"

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


def download_boletin_pdf(fecha, seccion, tenant_id, agent_id, storage: FileStorage):
    """
    Navega al Boletín Oficial, selecciona la fecha y descarga el PDF de la sección.
    fecha: str en formato YYYY-mm-dd
    seccion: str (primera, segunda, tercera, cuarta)
    """
    seccion = seccion.lower().strip()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--single-process']
        )
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        
        # 1. Navegamos a la página principal
        page.goto("https://www.boletinoficial.gob.ar/", wait_until="networkidle")
        
        # 2. Convertimos formato YYYY-mm-dd para el JS Date
        parts = fecha.split("-")
        if len(parts) == 3:
            year = int(parts[0])
            month = int(parts[1]) - 1 # Meses en JS son 0-11
            day = int(parts[2])
            fecha_ymd = f"{parts[0]}{parts[1]}{parts[2]}"
        else:
            raise Exception("Formato de fecha debe ser YYYY-mm-dd")
            
        # Primero navegar a la sección para establecer el referer correcto
        page.goto(f"https://www.boletinoficial.gob.ar/seccion/{seccion}", wait_until="networkidle")
        
        # 3. Simulamos el click en el calendario usando un objeto Date real.
        # Esto dispara correctamente los eventos internos de la página que actualizan 
        # la sesión del lado del servidor para descargar el PDF de la fecha correcta.
        page.evaluate(f"$('#divCalendario').datepicker('setDate', new Date({year}, {month}, {day}))")
        


        # Hacer la petición POST con headers correctos
        response = page.request.post(
            "https://www.boletinoficial.gob.ar/pdf/download_section",
            form={
                "nombreSeccion": seccion,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.boletinoficial.gob.ar/"
            }
        )
        response_json = response.json()
        
        # Si recibimos el PDF en base64, guardarlo directamente
        if response_json and 'pdfBase64' in response_json:
            import base64
            pdf_bytes = base64.b64decode(response_json['pdfBase64'])
            

            # Generar metadata (prefijo S3 canónico para RAG)
            tenant_prefix = _normalize_tenant_prefix(tenant_id)
            site_id = f"{tenant_prefix}/{agent_id}/documents"
            date_str = normalize_date(fecha).replace("-", "")
            
            # Generar nombre de archivo
            filename = generate_filename_from_url(f"https://www.boletinoficial.gob.ar/pdf/download_section", 0, date_str, seccion)
            # Subir a S3
            s3_key = f"{site_id}/{date_str}/{seccion}/{filename}"
            success = storage.upload(pdf_bytes, s3_key)
            if not success:
                raise Exception("Error al subir el PDF a S3")
            return filename

        else:
            raise Exception("No se recibió el PDF en base64")
        
            
        browser.close()
        
# Config
if S3_BUCKET:
    storage = FileS3Storage(S3_BUCKET)
else:
    storage = FakeFileStorage()

def lambda_handler(event, context):
    try:
        # Extraemos fecha y sección del evento
        fecha = event.get('fecha')
        seccion = event.get('seccion')
        tenant_id = event.get('tenant_id')
        agent_id = event.get('agent_id')

        if not fecha or not seccion:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Parámetros "fecha" y "seccion" son requeridos.'})
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

            
        file_path = download_boletin_pdf(fecha, seccion, tenant_id, agent_id, storage)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'fecha': fecha,
                'seccion': seccion,
                'file_path': file_path,
                'mensaje': 'PDF descargado exitosamente.'
            })
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

if __name__ == "__main__":
    # Evento de prueba simulado
    evento_de_prueba = {
        "fecha": "2026-05-05", 
        "seccion": "primera",
        "tenant_id": "boletin",
        "agent_id": "f45e11cb-1460-4317-9398-12d20e200328"
    }
    
    contexto_de_prueba = {}
    print("Iniciando prueba local...")
    storage = FakeFileStorage()

    respuesta = lambda_handler(evento_de_prueba, contexto_de_prueba)
    print("\n--- RESPUESTA ---")
    print("STATUS CODE:", respuesta.get('statusCode'))
    if respuesta.get('body'):
        print(json.dumps(json.loads(respuesta['body']), indent=4, ensure_ascii=False))

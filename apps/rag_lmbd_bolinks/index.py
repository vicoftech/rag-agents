import json
import os
import boto3
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    session_args.update({
        'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
    })

# Environment variables
BOLETIN_BASE_URL = os.getenv('BOLETIN_BASE_URL', 'https://www.boletinoficial.gob.ar')
DEFAULT_SECTION = os.getenv('DEFAULT_SECTION', 'primera')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))


def normalize_date_to_yyyymmdd(date_str: str | None) -> tuple[str | None, str | None]:
    """
    Devuelve (YYYYMMDD, None) o (None, mensaje de error).
    Acepta YYYYMMDD o YYYY-MM-DD (como envía la Step Function / el invoker).
    """
    if not date_str:
        yesterday = datetime.now() - timedelta(days=1)
        return yesterday.strftime("%Y%m%d"), None
    s = str(date_str).strip()
    if len(s) == 8 and s.isdigit():
        return s, None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%Y%m%d"), None
        except ValueError:
            return None, f"Fecha inválida: {date_str!r}"
    return None, (
        f"Formato de fecha no soportado: {date_str!r}. "
        "Usá YYYYMMDD o YYYY-MM-DD."
    )


# Headers para simular un navegador real
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-AR,es;q=0.8,en-US;q=0.5,en;q=0.3',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def get_pdf_links(target_date: str, seccion: str = 'primera'):
    """
    Extrae los links de los PDFs del Boletín Oficial para una fecha dada.
    Formato de parametro fecha: YYYYMMDD
    """
    if len(target_date) == 8:
        formatted_date = f"{target_date[6:8]}-{target_date[4:6]}-{target_date[:4]}"
    else:
        print("La fecha debe estar en formato YYYYMMDD (ej. 20260317)")
        return []

    print(f"Obteniendo boletín para la fecha: {formatted_date}...")
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    # 1. Establecer fecha en la sesión
    update_url = f'https://www.boletinoficial.gob.ar/edicion/actualizar/{formatted_date}'
    res = session.get(update_url)
    
    if res.status_code != 200:
        print("Error al actualizar la fecha en el servidor.")
        return []

    # 2. Obtener la página principal de la Sección especificada
    res_seccion = session.get(f'https://www.boletinoficial.gob.ar/seccion/{seccion}')
    soup = BeautifulSoup(res_seccion.text, 'html.parser')
    
    # Buscar todos los enlaces de avisos
    links = soup.find_all('a', href=True)
    pdf_links = []
    pdf_links_dict = []
    
    # URL base para la descarga de los PDFs individuales
    base_pdf_url = "https://www.boletinoficial.gob.ar/pdf/aviso/"
    
    for link in links:
        href = link["href"]
        if "/detalleAviso/" not in href:
            continue
        if f"/detalleAviso/{seccion}/" not in href and f"detalleAviso/{seccion}/" not in href:
            continue
        parts = [p for p in href.strip("/").split("/") if p]
        try:
            idx = parts.index("detalleAviso")
        except ValueError:
            continue
        if len(parts) < idx + 4:
            continue
        sec_link = parts[idx + 1]
        id_aviso = parts[idx + 2]
        fecha_aviso = parts[idx + 3]

        pdf_url = f"{base_pdf_url}{sec_link}/{id_aviso}/{fecha_aviso}"
        if pdf_url not in pdf_links:
            try:
                response = requests.head(
                    pdf_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36"
                        )
                    },
                    timeout=3,
                )
                content_type = response.headers.get("content-type", "").lower()
                if "application/pdf" in content_type:
                    pdf_links.append(pdf_url)
                    pdf_links_dict.append(
                        {"url": pdf_url, "section": sec_link, "date": fecha_aviso}
                    )
                    print(f"Added valid PDF: {pdf_url}")
                else:
                    print(
                        f"Skipping non-PDF link: {pdf_url} "
                        f"(Content-Type: {content_type})"
                    )
            except requests.RequestException as e:
                print(f"Error checking PDF link {pdf_url}: {e}")
                continue

    print(f"Found {len(pdf_links)} valid PDF links in section '{seccion}'")
    return pdf_links_dict

def handler(event, context):
    """Lambda handler: extrae enlaces PDF del Boletín Oficial por fecha y sección."""
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
        else:
            # Invocación directa
            body = event
        
        section = body.get("section", "primera")
        date_raw = body.get("date")
        date_str, date_err = normalize_date_to_yyyymmdd(date_raw)
        if date_err:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(
                    {
                        "success": False,
                        "message": date_err,
                        "received_params": body,
                        "pdf_links": [],
                    }
                ),
            }

        try:
            date_obj = datetime.strptime(date_str, "%Y%m%d")
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(
                    {
                        "success": False,
                        "message": f"Fecha inválida: {date_str}",
                        "received_params": body,
                        "pdf_links": [],
                        "error": str(e),
                    }
                ),
            }

        if date_obj.weekday() in (5, 6):
            print(
                f"Date {date_str} is weekend ({date_obj.strftime('%A')}), "
                "returning empty PDF links"
            )
            pdf_links = []
            result = {
                "success": True,
                "message": (
                    f"No hay boletín (fin de semana): {date_str} "
                    f"({date_obj.strftime('%A')})"
                ),
                "timestamp": datetime.now().isoformat(),
                "received_params": body,
                "pdf_links": pdf_links,
                "is_weekend": True,
                "day_of_week": date_obj.strftime("%A"),
                "date_normalized": date_str,
            }
        else:
            print(
                f"Date {date_str} is weekday ({date_obj.strftime('%A')}), "
                "extracting PDF links"
            )
            pdf_links = get_pdf_links(date_str, section)
            result = {
                "success": True,
                "message": f"Extraídos {len(pdf_links)} enlaces PDF",
                "timestamp": datetime.now().isoformat(),
                "received_params": body,
                "pdf_links": pdf_links,
                "is_weekend": False,
                "day_of_week": date_obj.strftime("%A"),
                "date_normalized": date_str,
            }
        
        # Preparar respuesta
        response = {
            "statusCode": 200,
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
    test_event = {
        "date": "20260408",
        "section": "primera"
    }
    print(handler(test_event, None))

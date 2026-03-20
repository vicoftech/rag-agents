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
    
    # URL base para la descarga de los PDFs individuales
    base_pdf_url = "https://www.boletinoficial.gob.ar/pdf/aviso/"
    
    for link in links:
        href = link['href']
        if f'/detalleAviso/{seccion}/' in href:
            parts = href.strip('/').split('/')
            if len(parts) >= 4:
                seccion = parts[1]
                id_aviso = parts[2]
                fecha_aviso = parts[3]
                
                pdf_url = f"{base_pdf_url}{seccion}/{id_aviso}/{fecha_aviso}"
                if pdf_url not in pdf_links:
                    pdf_links.append(pdf_url)

    # print(f"Se encontraron {len(pdf_links)} enlaces a PDFs en la sección '{seccion}'.")
    return pdf_links

def handler(event, context):
    """
    Lambda handler para rag_lmbd_bolinks
    
    TODO: Agregar aquí la lógica específica para procesar enlaces del Boletín Oficial
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
        else:
            # Invocación directa
            body = event
        
        # TODO: Implementar aquí la lógica específica de rag_lmbd_bolinks
        # Por ahora, retornar una respuesta básica
        date_str = body.get('date')
        section = body.get('section', 'primera')
        
        # Validar formato de fecha y verificar si es fin de semana
        if date_str and len(date_str) == 8 and date_str.isdigit():
            try:
                # Convertir YYYYMMDD a datetime
                date_obj = datetime.strptime(date_str, '%Y%m%d')
                
                # Verificar si es sábado (5) o domingo (6)
                if date_obj.weekday() in [5, 6]:  # 5 = sábado, 6 = domingo
                    print(f"Date {date_str} is weekend ({date_obj.strftime('%A')}), returning empty PDF links")
                    pdf_links = []
                    result = {
                        'success': True,
                        'message': f'No PDF links available for weekend date: {date_str} ({date_obj.strftime("%A")})',
                        'timestamp': datetime.now().isoformat(),
                        'received_params': body,
                        'pdf_links': pdf_links,
                        'is_weekend': True,
                        'day_of_week': date_obj.strftime('%A')
                    }
                else:
                    print(f"Date {date_str} is weekday ({date_obj.strftime('%A')}), proceeding with PDF extraction")
                    pdf_links = get_pdf_links(date_str, section)
                    result = {
                        'success': True,
                        'message': 'rag_lmbd_bolinks Lambda is ready for implementation',
                        'timestamp': datetime.now().isoformat(),
                        'received_params': body,
                        'pdf_links': pdf_links,
                        'is_weekend': False,
                        'day_of_week': date_obj.strftime('%A')
                    }
            except ValueError as e:
                print(f"Invalid date format: {date_str}, error: {e}")
                pdf_links = []
                result = {
                    'success': False,
                    'message': f'Invalid date format: {date_str}. Expected format: YYYYMMDD',
                    'timestamp': datetime.now().isoformat(),
                    'received_params': body,
                    'pdf_links': pdf_links,
                    'error': str(e)
                }
        else:
            # Fecha no proporcionada o formato inválido, proceder con extracción normal
            pdf_links = get_pdf_links(date_str, section)
            result = {
                'success': True,
                'message': 'rag_lmbd_bolinks Lambda is ready for implementation',
                'timestamp': datetime.now().isoformat(),
                'received_params': body,
                'pdf_links': pdf_links
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
        "url": "https://www.boletinoficial.gob.ar/seccion/primera"
    }
    print(handler(test_event, None))

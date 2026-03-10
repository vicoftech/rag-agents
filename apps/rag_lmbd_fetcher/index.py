import json
import os
import boto3
import requests
from datetime import datetime
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
DEFAULT_SECTION = os.getenv('DEFAULT_SECTION', 'primera')  # primera, segunda, tercera, cuarta
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

def fetch_boletin_by_url(url):
    """
    Obtiene el HTML de una URL específica del Boletín Oficial
    
    Args:
        url (str): URL completa del sitio a obtener
    
    Returns:
        dict: Contenido HTML encontrado y metadatos
    """
    try:
        # Validar URL
        if not url:
            return {
                'success': False,
                'error': 'Missing required parameter: url'
            }
        
        # Validar que sea una URL válida
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            return {
                'success': False,
                'error': 'Invalid URL format'
            }
        
        print(f"Fetching URL: {url}")
        
        # Obtener página
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        # Parsear HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extraer información de la página
        page_title = ''
        title_tag = soup.find('title')
        if title_tag:
            page_title = title_tag.get_text(strip=True)
        
        # Extraer fecha del contenido si existe
        page_date = datetime.now().strftime('%d/%m/%Y')
        
        return {
            'success': True,
            'url': url,
            'page_title': page_title,
            'page_date': page_date,
            'content': [{'title': 'Page content fetched', 'description': 'HTML content successfully retrieved', 'link': url}],
            'total_items': 1,
            'raw_html': response.text
        }
        
    except requests.RequestException as e:
        return {
            'success': False,
            'error': f'Error fetching content: {str(e)}',
            'url': url
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Unexpected error: {str(e)}',
            'url': url
        }

def find_content_by_date(soup, target_date):
    """
    Busca contenido en el HTML que corresponda a la fecha objetivo
    
    Args:
        soup: BeautifulSoup object del HTML parseado
        target_date: datetime object con la fecha buscada
    
    Returns:
        list: Lista de items encontrados para esa fecha
    """
    content_items = []
    
    # Formatos de fecha posibles en el Boletín
    date_formats = [
        target_date.strftime('%d/%m/%Y'),  # 06/03/2026
        target_date.strftime('%d-%m-%Y'),  # 06-03-2026
        target_date.strftime('%d de %B de %Y'),  # 6 de marzo de 2026
        target_date.strftime('%d de %b de %Y'),  # 6 de mar de 2026
    ]
    
    # Buscar patrones de fecha en el contenido
    for date_format in date_formats:
        # Buscar elementos que contengan la fecha
        date_elements = soup.find_all(text=re.compile(re.escape(date_format), re.IGNORECASE))
        
        for element in date_elements:
            parent = element.parent
            if parent:
                # Extraer información del aviso
                item_info = extract_item_info(parent, date_format)
                if item_info:
                    content_items.append(item_info)
    
    # Si no encontró por texto, buscar por atributos de fecha
    if not content_items:
        # Buscar elementos con data-date o atributos similares
        date_elements = soup.find_all(attrs={'data-date': True})
        for element in date_elements:
            date_attr = element.get('data-date')
            if date_attr and target_date.strftime('%Y-%m-%d') in date_attr:
                item_info = extract_item_info(element)
                if item_info:
                    content_items.append(item_info)
    
    return content_items

def extract_item_info(element, date_text=None):
    """
    Extrae información de un elemento del boletín
    
    Args:
        element: BeautifulSoup element
        date_text: Texto de la fecha encontrado
    
    Returns:
        dict: Información del item
    """
    try:
        # Buscar título/enlace
        link = element.find('a')
        if link:
            title = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Construir URL completa si es relativa
            if href and not href.startswith('http'):
                href = f"{BOLETIN_BASE_URL}{href}"
        else:
            title = element.get_text(strip=True)
            href = ''
        
        # Buscar descripción adicional
        description = ''
        next_sibling = element.next_sibling
        while next_sibling and len(description) < 500:
            if hasattr(next_sibling, 'get_text'):
                sibling_text = next_sibling.get_text(strip=True)
                if sibling_text:
                    description += sibling_text + ' '
            next_sibling = next_sibling.next_sibling
        
        return {
            'title': title[:200],  # Limitar longitud
            'description': description[:500],
            'link': href,
            'date_found': date_text,
            'html_snippet': str(element)[:1000]  # Limitar longitud
        }
    except Exception as e:
        print(f"Error extracting item info: {e}")
        return None

def try_advanced_search(date_str, section):
    """
    Intenta búsqueda avanzada si el método directo no funciona
    
    Args:
        date_str (str): Fecha en formato YYYY-MM-DD
        section (str): Sección del boletín
    
    Returns:
        dict: Resultado de la búsqueda
    """
    try:
        # URL de búsqueda avanzada
        search_url = f"{BOLETIN_BASE_URL}/busquedaAvanzada/{section}"
        
        # Parámetros de búsqueda (esto puede variar según el sitio)
        params = {
            'fecha': date_str,
            'seccion': section
        }
        
        response = requests.get(search_url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        return {
            'success': True,
            'date': date_str,
            'section': section,
            'url': search_url,
            'content': [{'title': 'Advanced search result', 'description': 'Content found via advanced search', 'link': search_url}],
            'total_items': 1,
            'raw_html': str(soup),
            'method': 'advanced_search'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Advanced search failed: {str(e)}',
            'date': date_str,
            'section': section
        }

def handler(event, context):
    """
    Lambda handler para fetch del Boletín Oficial
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
            url = body.get("url")
        else:
            # Invocación directa
            url = event.get("url")
        
        # Validar parámetro URL
        if not url:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: url"})
            }
        
        # Llamar a la función principal
        result = fetch_boletin_by_url(url)
        
        # Preparar respuesta
        if result['success']:
            response = {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps(result)
            }
        else:
            response = {
                "statusCode": 404,
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

import json
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional

# CORS headers
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "OPTIONS,POST,GET",
}

def extract_pdf_links(html_content: str, base_url: str = None) -> List[Dict[str, str]]:
    """
    Extrae todos los links a documentos PDF del contenido HTML
    
    Args:
        html_content: String con el contenido HTML
        base_url: URL base para resolver links relativos
    
    Returns:
        Lista de diccionarios con información de cada PDF encontrado
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        pdf_links = []
        
        # Patrones comunes para identificar PDFs
        pdf_patterns = [
            r'\.pdf($|\?)',
            r'boletin.*\.pdf',
            r'document.*\.pdf',
            r'archivo.*\.pdf',
            r'edicion.*\.pdf',
        ]
        
        # Buscar todos los links
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            
            # Verificar si es un PDF
            is_pdf = any(re.search(pattern, href.lower(), re.IGNORECASE) for pattern in pdf_patterns)
            
            # También verificar por el texto del link
            if not is_pdf:
                is_pdf = any(re.search(pattern, text.lower(), re.IGNORECASE) for pattern in pdf_patterns)
            
            if is_pdf:
                # Construir URL completa si es relativa
                if base_url and not href.startswith('http'):
                    full_url = urljoin(base_url, href)
                else:
                    full_url = href
                
                # Extraer información adicional
                pdf_info = {
                    'url': full_url,
                    'text': text,
                    'title': text[:100],  # Limitar longitud
                    'original_href': href
                }
                
                # Intentar extraer fecha del texto o URL
                date_match = extract_date_from_text(text + ' ' + href)
                if date_match:
                    pdf_info['date'] = date_match
                
                # Intentar extraer número/sección
                section_match = extract_section_from_text(text + ' ' + href)
                if section_match:
                    pdf_info['section'] = section_match
                
                pdf_links.append(pdf_info)
        
        # Eliminar duplicados por URL
        unique_pdfs = {}
        for pdf in pdf_links:
            url = pdf['url']
            if url not in unique_pdfs or len(pdf['text']) > len(unique_pdfs[url]['text']):
                unique_pdfs[url] = pdf
        
        return {
            'success': True,
            'pdf_links': list(unique_pdfs.values())
        }
        
    except Exception as e:
        print(f"Error parsing HTML: {e}")
        return {
            'success': False,
            'error': f'Error parsing HTML: {str(e)}',
            'pdf_links': []
        }

def extract_date_from_text(text: str) -> Optional[str]:
    """
    Extrae fecha del texto usando patrones comunes
    """
    date_patterns = [
        r'(\d{2}/\d{2}/\d{4})',  # DD/MM/YYYY
        r'(\d{2}-\d{2}-\d{4})',  # DD-MM-YYYY
        r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})',  # 6 de marzo de 2026
        r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def extract_section_from_text(text: str) -> Optional[str]:
    """
    Extrae sección del texto (primera, segunda, tercera, cuarta)
    """
    section_patterns = [
        r'(primera\s+sección|sección\s+primera)',
        r'(segunda\s+sección|sección\s+segunda)',
        r'(tercera\s+sección|sección\s+tercera)',
        r'(cuarta\s+sección|sección\s+cuarta)',
        r'(primera|segunda|tercera|cuarta)',
    ]
    
    for pattern in section_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    
    return None

def parse_html_content(html_content: str, base_url: str = None) -> Dict:
    """
    Función principal que parsea el HTML y extrae información
    """
    try:
        # Extraer PDFs
        pdf_links = extract_pdf_links(html_content, base_url)
        
        # Extraer metadatos adicionales del HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Buscar título de la página
        title_tag = soup.find('title')
        page_title = title_tag.get_text(strip=True) if title_tag else ''
        
        # Buscar fecha en la página
        page_date = extract_date_from_text(html_content)
        
        # Contar enlaces totales
        total_links = len(soup.find_all('a', href=True))
        
        return {
            'success': True,
            'page_title': page_title,
            'page_date': page_date,
            'section': extract_section_from_text(html_content),
            'total_links_found': total_links,
            'pdf_links_count': len(pdf_links),
            'pdf_links': pdf_links,
            'base_url': base_url
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error parsing HTML: {str(e)}',
            'pdf_links': []
        }

def handler(event, context):
    """
    Lambda handler para parsear HTML y extraer PDFs
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
            html_content = body.get("raw_html")  # Cambiado de 'html' a 'raw_html'
            base_url = body.get("url")  # Cambiado de 'base_url' a 'url'
        else:
            # Invocación directa (desde Step Function)
            html_content = event.get("raw_html")  # Cambiado de 'html' a 'raw_html'
            base_url = event.get("url")  # Cambiado de 'base_url' a 'url'
        
        # Validar parámetro HTML
        if not html_content:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: raw_html"})
            }
        
        # Limitar tamaño del HTML (máximo 5MB)
        if len(html_content) > 5 * 1024 * 1024:
            return {
                "statusCode": 413,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "HTML content too large (max 5MB)"})
            }
        
        # Parsear contenido
        result = parse_html_content(html_content, base_url)
        
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
    test_html = """
    <html>
    <head><title>Boletín Oficial</title></head>
    <body>
        <h1>Primera Sección - 06/03/2026</h1>
        <a href="/documentos/boletin-2026-03-06.pdf">Boletín Completo</a>
        <a href="https://www.boletinoficial.gob.ar/edicion/primera/20260306.pdf">Edición Primera</a>
        <a href="/secciones/segunda/20260306.pdf">Segunda Sección</a>
        <a href="/otros/documento.pdf">Otro Documento</a>
    </body>
    </html>
    """
    
    test_event = {
        "raw_html": test_html,
        "base_url": "https://www.boletinoficial.gob.ar"
    }
    
    result = handler(test_event, None)
    print("Result:", json.dumps(result, indent=2))

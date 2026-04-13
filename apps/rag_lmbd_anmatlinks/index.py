import json
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

def extraer_fecha_url(url, year, meses):
    """
    Extrae la fecha en formato YYYYMMDD de una URL de ANMAT.
    
    Args:
        url (str): URL del PDF
        year (str): Año de búsqueda como fallback
        meses (dict): Diccionario de meses en español a números
        
    Returns:
        str: Fecha en formato YYYYMMDD
    """
    # Formato URL: .../BuscaDispoPDF/2026/marzo/...
    parts = url.split('/')
    fecha_aviso = f"{year}0101"  # Default fallback
    
    try:
        # Buscar el año (4 dígitos) y el mes en el path
        for i, part in enumerate(parts):
            if part.isdigit() and len(part) == 4 and part.startswith('20'):
                year_from_url = part
                # El mes debería estar después del año
                if i + 1 < len(parts):
                    month_name = parts[i + 1].lower()
                    if month_name in meses:
                        month_num = meses[month_name]
                        fecha_aviso = f"{year_from_url}{month_num}01"
                        break
    except Exception as e:
        print(f"Error extrayendo fecha de URL: {e}")
        fecha_aviso = f"{year}0101"  # Fallback al año de búsqueda
    
    return fecha_aviso

def scrape_anmat(year, muestra=1):
    """
    Extrae PDFs de ANMAT para un año específico.
    
    Args:
        year (int): Año a buscar
        muestra (int): 0=producción (descarga todas las páginas), 1=pruebas (limitado a 10 páginas)
    """
    print(f"Iniciando scraping para el año {year}...")
    print(f"Modo: {'PRODUCCIÓN (todas las páginas)' if muestra == 0 else 'PRUEBAS (limitado)'}")
    
    # Mapeo de meses en español a números
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    with sync_playwright() as p:
        # Iniciamos el navegador en modo headless
        # En AWS Lambda, pueden ser necesarios argumentos adicionales (e.g. args=['--disable-gpu', '--single-process']) 
        # dependiendo de la capa (layer) de Chromium que estés utilizando.
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--single-process']
        )
        context = browser.new_context()
        page = context.new_page()
        
        # 1. Navegamos a la página
        print("Cargando sitio web...")
        page.goto("https://buscadispo.anmat.gob.ar/", wait_until="networkidle")
        
        # 2. Llenamos el año en el input correspondiente
        page.fill("id=ctl00_MainContent_txtAnioDispo", str(year))
        
        # 3. Hacemos click en el botón de búsqueda
        print(f"Buscando disposiciones del año {year}...")
        with page.expect_navigation(wait_until="load"):
            page.click("id=ctl00_MainContent_btnBusqueda")
        
        try:
            resultados_texto = page.locator("id=ctl00_MainContent_lblCantFiltrado").inner_text(timeout=5000)
            print(f"Estado: {resultados_texto}")
            
            # Intentar extraer el número del texto "Se encontraron X registros"
            import re
            match = re.search(r'\d+', resultados_texto)
            total_records = int(match.group()) if match else 0
            
            # Calculamos las páginas totales aproximadas (la grilla muestra 100 registros por página)
            total_pages_approx = (total_records // 100) + (1 if total_records % 100 > 0 else 0)
            print(f"El sitio informa un total aproximado de {total_pages_approx} páginas a procesar.")
            
        except Exception:
            print("No se encontró mensaje de cantidad de registros.")
            total_pages_approx = "Desconocido"
            total_records = 0
            
        # Límite para pruebas o producción
        if muestra == 1:
            max_paginas = 10  # Modo pruebas: limitado a 10 páginas
            print(f"Límite de páginas: {max_paginas}")
        else:
            max_paginas = None  # Modo producción: sin límite
            print("Modo producción: sin límite de páginas")
        
        pdf_links = set()
        pdf_links_dict = []
        page_num = 1
        
        while True:
            if max_paginas is not None and page_num > max_paginas:
                print(f"Límite de prueba de {max_paginas} páginas alcanzado. Deteniendo scraping.")
                break
                
            print(f"Procesando página {page_num}...")
            # Extraemos los links de la tabla actual
            rows = page.locator("a[id*='lnkPDF']").all()
            
            for row in rows:
                href = row.get_attribute("href")
                if href:
                    # Limpiar y formatear la URL
                    clean_href = href.replace("\\", "/")
                    
                    # Asegurar que sea una URL completa
                    if clean_href.startswith("//"):
                        full_url = "https:" + clean_href
                    elif clean_href.startswith("/"):
                        full_url = "https://buscadispo.anmat.gob.ar" + clean_href
                    elif clean_href.startswith("http"):
                        full_url = clean_href
                    else:
                        full_url = "https://buscadispo.anmat.gob.ar/" + clean_href
                    
                    pdf_links.add(full_url)
                    
                    # Extraer fecha de la URL usando la función auxiliar
                    fecha_aviso = extraer_fecha_url(full_url, year, meses)
                    pdf_links_dict.append({"url": full_url, "date": fecha_aviso, "section": "default"})
                    
            # Buscamos el elemento span dentro del bloque de paginación que nos dice la pagina actual
            next_page_str = str(page_num + 1)
            
            # Buscamos un enlace con el texto exacto de la siguiente pagina
            next_link = page.locator(f"tr.paginacion a:has-text(' {next_page_str} '), td a:text-is('{next_page_str}')")
            
            if next_link.count() > 0:
                with page.expect_navigation(wait_until="load", timeout=60000):
                    next_link.first.click()
                page_num += 1
            else:
                # A veces el paginador requiere clickear en "..."
                dots_link = page.locator("td a:text-is('...')").last
                if dots_link.count() > 0:
                    with page.expect_navigation(wait_until="load", timeout=60000):
                        dots_link.click()
                    page_num += 1 
                else:
                    # No hay ni mas números ni puntos suspensivos avanzando
                    break
                
        browser.close()
        
    return pdf_links_dict, total_pages_approx, total_records

def handler(event, context):
    try:
        # Extraemos el año del evento (puede venir de body, queryStringParameters, o directamente)
        # Ajusta esto dependiendo de cómo expongas tu Lambda (API Gateway, llamado directo, etc)
        year = None
        
        if event.get('queryStringParameters') and 'year' in event['queryStringParameters']:
            year = event['queryStringParameters']['year']
        elif 'year' in event:
            year = event['year']
        elif event.get('body'):
            body = json.loads(event['body'])
            year = body.get('year')
            
        if not year:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Parámetro "year" es requerido.'})
            }
            
        # Determinar modo de ejecución (producción=0, pruebas=1)
        modo_muestra = event.get('muestra', 0)  # Default: modo produccion
        
        # Ejecutamos el scraper
        links, total_pages, total_records = scrape_anmat(year, modo_muestra)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'success': True,
                'timestamp': datetime.now().isoformat(),
                'received_params': {
                    'year': year,
                    'date': f"{year}0101",  # Formato YYYYMMDD (1/1/year)
                    'section': 'default'
                },
                'total_records': total_records,
                'total_pages_approx': total_pages,
                'pdfs_collected': len(links),
                'pdf_links': links
            })
        }
    except Exception as e:
        print(f"Error procesando: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            })
        }

if __name__ == "__main__":
    # Evento de prueba simulado como si el año viniera en el "queryStringParameters" o "body"
    evento_de_prueba = {
        "year": "2026",  # Puedes cambiar este año
        "muestra": 1  # 0=producción (todas las páginas), 1=pruebas (limitado a 10 páginas)
    }
    
    # Contexto ficticio que exige la estructura Lambda (aunque no lo usemos en el código)
    contexto_de_prueba = {}
    
    print("Iniciando prueba local simulando el evento Lambda...")
    
    # Invocamos la función igual a como Amazon AWS la ejecutaría
    respuesta = handler(evento_de_prueba, contexto_de_prueba)
    
    print("\n--- RESPUESTA DE LA LAMBDA ---")
    print("STATUS CODE:", respuesta.get('statusCode'))
    
    # Imprimimos el body de manera más estética
    if respuesta.get('body'):
        body_parseado = json.loads(respuesta['body'])
        print(json.dumps(body_parseado, indent=4, ensure_ascii=False))
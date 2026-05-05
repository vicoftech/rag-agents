import json
import os
from playwright.sync_api import sync_playwright

def download_boletin_pdf(fecha, seccion):
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
        print("Response Status: ", response.status)
        print("Response Headers: ", response.headers)
        response_json = response.json()
        print("Response JSON: ", response_json)
        
        # Si recibimos el PDF en base64, guardarlo directamente
        if response_json and 'pdfBase64' in response_json:
            import base64
            pdf_bytes = base64.b64decode(response_json['pdfBase64'])
            with open(file_path, 'wb') as f:
                f.write(pdf_bytes)
            print("PDF guardado desde base64")
            return file_path

        # Esperamos a que la petición AJAX interna de la página actualice la sesión
        page.wait_for_timeout(5000)
        
        file_path = f"/tmp/{fecha}_{seccion}.pdf"
        
        try:
            # 4. Forzamos la descarga haciendo la petición de POST con la fecha actualizada
            with page.expect_download(timeout=90000) as download_info:
                page.evaluate(f"descargarPDFSeccion('{seccion}', '{fecha_ymd}', '/pdf/download_section', '')")
            
            download = download_info.value
            print("URL: ", download.url)
            download.save_as(file_path)
        except Exception as e:
            browser.close()
            raise Exception("No se pudo descargar el PDF para esta fecha y sección.")
            
        browser.close()
        
        if os.path.exists(file_path):
            return file_path
        else:
            raise Exception("PDF no encontrado o falló la descarga")

def lambda_handler(event, context):
    try:
        # Extraemos fecha y sección del evento
        fecha = event.get('fecha')
        seccion = event.get('seccion')
        
        if not fecha or not seccion:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Parámetros "fecha" y "seccion" son requeridos.'})
            }
            
        file_path = download_boletin_pdf(fecha, seccion)
        
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
        "fecha": "2026-04-27", 
        "seccion": "primera"
    }
    
    contexto_de_prueba = {}
    print("Iniciando prueba local...")
    respuesta = lambda_handler(evento_de_prueba, contexto_de_prueba)
    print("\n--- RESPUESTA ---")
    print("STATUS CODE:", respuesta.get('statusCode'))
    if respuesta.get('body'):
        print(json.dumps(json.loads(respuesta['body']), indent=4, ensure_ascii=False))

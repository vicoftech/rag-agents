import json
from index import handler

# Test handler
def test_parser():
    # Test con HTML de ejemplo
    test_html = """
    <html>
    <head><title>Boletín Oficial de la República Argentina</title></head>
    <body>
        <h1>Primera Sección - 06/03/2026</h1>
        <div class="content">
            <a href="/documentos/boletin-2026-03-06.pdf">Boletín Completo</a>
            <a href="https://www.boletinoficial.gob.ar/edicion/primera/20260306.pdf">Edición Primera</a>
            <a href="/secciones/segunda/20260306.pdf">Segunda Sección</a>
            <a href="/otros/documento.pdf">Otro Documento</a>
            <a href="/pagina.html">Página HTML (no PDF)</a>
            <a href="/download.php?file=resolucion-123.pdf">Resolución 123</a>
        </div>
    </body>
    </html>
    """
    
    # Test como evento HTTP (API Gateway)
    test_event_http = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "body": json.dumps({
            "html": test_html,
            "base_url": "https://www.boletinoficial.gob.ar"
        })
    }
    
    context = {}
    result = handler(test_event_http, context)
    print("HTTP Event Result:", json.dumps(result, indent=2))
    
    # Test como invocación directa (Lambda)
    test_event_direct = {
        "html": test_html,
        "base_url": "https://www.boletinoficial.gob.ar"
    }
    
    result_direct = handler(test_event_direct, context)
    print("Direct Event Result:", json.dumps(result_direct, indent=2))

if __name__ == "__main__":
    test_parser()

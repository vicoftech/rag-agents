import json
from index import handler

# Test handler
def test_s3writer():
    # Test con output de ejemplo del parser
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
            },
            {
                "url": "https://www.boletinoficial.gob.ar/edicion/segunda/20260306.pdf",
                "text": "Segunda Sección",
                "title": "Segunda Sección",
                "date": "06/03/2026",
                "section": "segunda"
            }
        ],
        "pdf_links_count": 2,
        "total_links_found": 15
    }
    
    # Test como evento HTTP (API Gateway)
    test_event_http = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "body": json.dumps({
            "parser_output": test_parser_output
        })
    }
    
    context = {}
    result = handler(test_event_http, context)
    print("HTTP Event Result:", json.dumps(result, indent=2))
    
    # Test como invocación directa (desde Step Function)
    test_event_direct = {
        "parser_output": test_parser_output
    }
    
    result_direct = handler(test_event_direct, context)
    print("Direct Event Result:", json.dumps(result_direct, indent=2))

if __name__ == "__main__":
    test_s3writer()

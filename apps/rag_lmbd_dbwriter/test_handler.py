import json
from index import handler

# Test handler
def test_dbwriter():
    # Test con output de ejemplo del s3writer
    test_s3writer_output = {
        "success": True,
        "site_id": "boletinoficial_gob_ar",
        "date": "2026-03-06",
        "processed_count": 2,
        "failed_count": 0,
        "total_found": 2,
        "uploaded_files": [
            {
                "original_url": "https://www.boletinoficial.gob.ar/documentos/boletin-2026-03-06.pdf",
                "s3_key": "boletinoficial_gob_ar/2026-03-06/Boletín_Completo.pdf",
                "s3_uri": "s3://rag-documents-dev-913123310997/boletinoficial_gob_ar/2026-03-06/Boletín_Completo.pdf",
                "filename": "Boletín_Completo.pdf",
                "size": 1048576,
                "metadata": {
                    "title": "Boletín Completo",
                    "date": "06/03/2026",
                    "section": "primera"
                }
            },
            {
                "original_url": "https://www.boletinoficial.gob.ar/edicion/segunda/20260306.pdf",
                "s3_key": "boletinoficial_gob_ar/2026-03-06/Segunda_Sección.pdf",
                "s3_uri": "s3://rag-documents-dev-913123310997/boletinoficial_gob_ar/2026-03-06/Segunda_Sección.pdf",
                "filename": "Segunda_Sección.pdf",
                "size": 524288,
                "metadata": {
                    "title": "Segunda Sección",
                    "date": "06/03/2026",
                    "section": "segunda"
                }
            }
        ],
        "s3_bucket": "rag-documents-dev-913123310997"
    }
    
    # Test como evento HTTP (API Gateway)
    test_event_http = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "body": json.dumps({
            "s3writer_output": test_s3writer_output
        })
    }
    
    context = {}
    result = handler(test_event_http, context)
    print("HTTP Event Result:", json.dumps(result, indent=2))
    
    # Test como invocación directa (desde Step Function)
    test_event_direct = {
        "s3writer_output": test_s3writer_output
    }
    
    result_direct = handler(test_event_direct, context)
    print("Direct Event Result:", json.dumps(result_direct, indent=2))

if __name__ == "__main__":
    test_dbwriter()

import json
import os
from index import handler

# Test handler
def test_fetcher():
    # Test como evento HTTP (API Gateway)
    test_event_http = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "body": json.dumps({
            "url": "https://www.boletinoficial.gob.ar/seccion/primera"
        })
    }
    
    context = {}
    result = handler(test_event_http, context)
    print("HTTP Event Result:", json.dumps(result, indent=2))
    
    # Test como invocación directa (Lambda)
    test_event_direct = {
        "url": "https://www.boletinoficial.gob.ar/seccion/primera"
    }
    
    result_direct = handler(test_event_direct, context)
    print("Direct Event Result:", json.dumps(result_direct, indent=2))

if __name__ == "__main__":
    test_fetcher()

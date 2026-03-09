import json
from index import handler

# Test handler
def test_notifier():
    # Test de éxito completo
    test_success_data = {
        "success": True,
        "site_id": "boletinoficial_gob_ar",
        "date": "2026-03-06",
        "total_found": 5,
        "processed_count": 5,
        "failed_count": 0,
        "uploaded_files_count": 5,
        "db_records_count": 6,  # 1 site + 5 documents
        "s3_bucket": "rag-documents-dev-913123310997",
        "dynamodb_table": "rag-documents-dev",
        "sample_files": [
            {
                "filename": "Boletín_Completo.pdf",
                "s3_uri": "s3://rag-documents-dev-913123310997/boletinoficial_gob_ar/2026-03-06/Boletín_Completo.pdf"
            }
        ],
        "execution_context": "Step Function execution completed successfully"
    }
    
    # Test de fallo
    test_failure_data = {
        "success": False,
        "site_id": "boletinoficial_gob_ar",
        "date": "2026-03-06",
        "total_found": 3,
        "processed_count": 0,
        "failed_count": 3,
        "error_type": "FETCH_ERROR",
        "error_message": "Failed to fetch content from URL: Connection timeout",
        "failed_step": "fetcher",
        "execution_context": "HTTP 503 Service Unavailable"
    }
    
    # Test de éxito parcial
    test_partial_data = {
        "success": True,
        "site_id": "boletinoficial_gob_ar",
        "date": "2026-03-06",
        "total_found": 5,
        "processed_count": 3,
        "failed_count": 2,
        "uploaded_files_count": 3,
        "db_records_count": 4,  # 1 site + 3 documents
        "s3_bucket": "rag-documents-dev-913123310997",
        "dynamodb_table": "rag-documents-dev",
        "execution_context": "Some files exceeded size limit"
    }
    
    # Test HTTP - Éxito
    test_event_http = {
        "requestContext": {
            "http": {
                "method": "POST"
            }
        },
        "body": json.dumps({
            "execution_data": test_success_data
        })
    }
    
    context = {}
    result = handler(test_event_http, context)
    print("HTTP Success Test Result:", json.dumps(result, indent=2))
    
    # Test Direct - Fallo
    test_event_failure = {
        "execution_data": test_failure_data
    }
    
    result_failure = handler(test_event_failure, context)
    print("Direct Failure Test Result:", json.dumps(result_failure, indent=2))
    
    # Test Direct - Éxito Parcial
    test_event_partial = {
        "execution_data": test_partial_data
    }
    
    result_partial = handler(test_event_partial, context)
    print("Direct Partial Success Test Result:", json.dumps(result_partial, indent=2))

if __name__ == "__main__":
    test_notifier()

import json
import os
import boto3
from datetime import datetime
from typing import List, Dict, Optional
from decimal import Decimal

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
# No usar credenciales hardcodeadas - usar rol de ejecución de Lambda
# if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
#     session_args.update({
#         'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
#         'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
#     })

# AWS Clients
dynamodb_client = boto3.client('dynamodb', **session_args)
dynamodb_resource = boto3.resource('dynamodb', **session_args)

# Environment variables
DYNAMODB_TABLE = os.getenv('DYNAMODB_TABLE_NAME')

def convert_to_dynamodb_format(obj):
    """
    Convierte un objeto a formato compatible con DynamoDB
    """
    if isinstance(obj, dict):
        return {k: convert_to_dynamodb_format(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_dynamodb_format(v) for v in obj]
    elif isinstance(obj, (int, float)):
        return Decimal(str(obj))
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj

def generate_partition_key(site_id: str, date_str: str) -> str:
    """
    Genera partition key para DynamoDB
    """
    return f"{site_id}#{date_str}"

def generate_sort_key(filename: str) -> str:
    """
    Genera sort key para DynamoDB
    """
    return filename

def create_document_item(s3writer_output: Dict, file_info: Dict) -> Dict:
    """
    Crea un item de documento para DynamoDB
    """
    timestamp = datetime.utcnow().isoformat()
    
    item = {
        'PK': generate_partition_key(
            s3writer_output.get('site_id', ''),
            s3writer_output.get('date', '')
        ),
        'SK': generate_sort_key(file_info.get('filename', '')),
        'entity_type': 'document',
        'site_id': s3writer_output.get('site_id', ''),
        'date': s3writer_output.get('date', ''),
        'filename': file_info.get('filename', ''),
        'original_url': file_info.get('original_url', ''),
        's3_key': file_info.get('s3_key', ''),
        's3_uri': file_info.get('s3_uri', ''),
        'file_size': file_info.get('size', 0),
        'file_metadata': file_info.get('metadata', {}),
        'created_at': timestamp,
        'updated_at': timestamp,
        'processing_status': 'completed',
        'source': 'rag_lmbd_s3writer'
    }
    
    return convert_to_dynamodb_format(item)

def create_site_item(s3writer_output: Dict) -> Dict:
    """
    Crea un item de sitio para DynamoDB
    """
    timestamp = datetime.utcnow().isoformat()
    
    item = {
        'PK': generate_partition_key(
            s3writer_output.get('site_id', ''),
            s3writer_output.get('date', '')
        ),
        'SK': 'site#info',
        'entity_type': 'site',
        'site_id': s3writer_output.get('site_id', ''),
        'date': s3writer_output.get('date', ''),
        'processed_count': s3writer_output.get('processed_count', 0),
        'failed_count': s3writer_output.get('failed_count', 0),
        'total_found': s3writer_output.get('total_found', 0),
        's3_bucket': s3writer_output.get('s3_bucket', ''),
        'created_at': timestamp,
        'updated_at': timestamp,
        'source': 'rag_lmbd_s3writer'
    }
    
    return convert_to_dynamodb_format(item)

def upsert_item(table_name: str, item: Dict) -> bool:
    """
    Realiza upsert de un item en DynamoDB
    """
    try:
        table = dynamodb_resource.Table(table_name)
        
        response = table.put_item(
            Item=item,
            ReturnValues='ALL_OLD'
        )
        
        print(f"Successfully upserted item: {item.get('PK')}#{item.get('SK')}")
        return True
        
    except Exception as e:
        print(f"Error upserting item to DynamoDB: {e}")
        return False

def batch_upsert_items(table_name: str, items: List[Dict]) -> Dict:
    """
    Realiza batch upsert de múltiples items en DynamoDB
    """
    try:
        table = dynamodb_resource.Table(table_name)
        
        # Preparar batch write
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)
        
        print(f"Successfully batch upserted {len(items)} items")
        return {
            'success': True,
            'processed_count': len(items)
        }
        
    except Exception as e:
        print(f"Error batch upserting items to DynamoDB: {e}")
        return {
            'success': False,
            'error': str(e),
            'processed_count': 0
        }

def process_s3writer_output(s3writer_output: Dict) -> Dict:
    """
    Procesa el output del s3writer y guarda en DynamoDB
    """
    try:
        # Validar que el s3writer tuvo éxito
        if not s3writer_output.get('success', False):
            return {
                'success': False,
                'error': 'S3Writer output indicates failure',
                's3writer_output': s3writer_output
            }
        
        # Extraer información
        uploaded_files = s3writer_output.get('uploaded_files', [])
        
        if not uploaded_files:
            return {
                'success': True,
                'message': 'No files uploaded to process',
                'processed_count': 0
            }
        
        # Preparar items para DynamoDB
        items_to_upsert = []
        
        # Agregar item del sitio
        site_item = create_site_item(s3writer_output)
        items_to_upsert.append(site_item)
        
        # Agregar items de documentos
        for file_info in uploaded_files:
            doc_item = create_document_item(s3writer_output, file_info)
            items_to_upsert.append(doc_item)
        
        # Realizar batch upsert
        result = batch_upsert_items(DYNAMODB_TABLE, items_to_upsert)
        
        if result['success']:
            return {
                'success': True,
                'site_id': s3writer_output.get('site_id', ''),
                'date': s3writer_output.get('date', ''),
                'processed_count': result['processed_count'],
                'documents_count': len(uploaded_files),
                'site_item_created': True,
                'dynamodb_table': DYNAMODB_TABLE
            }
        else:
            return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing s3writer output: {str(e)}'
        }

def handler(event, context):
    """
    Lambda handler para procesar output del s3writer y guardar en DynamoDB
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
            s3writer_output = body.get("s3writer_output")
        else:
            # Invocación directa (desde Step Function)
            s3writer_output = event.get("s3writer_output")
        
        # Validar parámetro s3writer_output
        if not s3writer_output:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: s3writer_output"})
            }
        
        # Procesar output del s3writer
        result = process_s3writer_output(s3writer_output)
        
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
    
    test_event = {
        "s3writer_output": test_s3writer_output
    }

    test_anmat_event = {
        "s3writer_output": {
            "success": True,
            "site_id": "anmat",
            "uploaded_files": [
                "https://buscadispo.anmat.gob.ar:443//BuscaDispoPDF/2024/abril/Dispo_3618-24.pdf",
                "https://buscadispo.anmat.gob.ar:443//BuscaDispoPDF/2024/abril/Dispo_3724-24.pdf",
                "https://buscadispo.anmat.gob.ar:443//BuscaDispoPDF/2024/abril/Dispo_3304-24.pdf"
            ]
        }
    }
    
    result = handler(test_anmat_event, None)
    print("Result:", json.dumps(result, indent=2))

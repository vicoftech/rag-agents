import json
import os
import boto3
from datetime import datetime
from typing import Dict, Any, Optional, List

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
# No usar credenciales hardcodeadas - usar rol de ejecución de Lambda
# if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
#     session_args.update({
#         'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
#         'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
#     })

# AWS Clients
lambda_client = boto3.client('lambda', **session_args)

# Environment variables
BOLINKS_FUNCTION = os.getenv('BOLINKS_FUNCTION_NAME', 'rag_lmbd_bolinks-dev')
S3WRITER_FUNCTION = os.getenv('S3WRITER_FUNCTION_NAME', 'rag_lmbd_s3writer-dev')
DBWRITER_FUNCTION = os.getenv('DBWRITER_FUNCTION_NAME', 'rag_lmbd_dbwriter-dev')
NOTIFIER_FUNCTION = os.getenv('NOTIFIER_FUNCTION_NAME', 'rag_lmbd_notifier-dev')


def flatten_bolinks_pdf_links(pdf_links_field: Any) -> List[Dict[str, Any]]:
    """Lista plana desde pdf_links legacy o dict por sección (CD-01 / bolinks)."""
    if isinstance(pdf_links_field, dict):
        out: List[Dict[str, Any]] = []
        for _sec, items in pdf_links_field.items():
            if isinstance(items, list):
                out.extend(items)
        return out
    if isinstance(pdf_links_field, list):
        return pdf_links_field
    return []


def invoke_lambda(function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Invoca una función Lambda con el payload dado
    """
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        response_payload = json.loads(response['Payload'].read())
        
        # Si la respuesta tiene statusCode, extraer el body
        if 'statusCode' in response_payload and 'body' in response_payload:
            body = json.loads(response_payload['body'])
            return body
        else:
            return response_payload
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Error invoking {function_name}: {str(e)}'
        }

def extract_bolinks_result(bolinks_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae el resultado de bolinks de la respuesta Lambda
    """
    # Si la respuesta tiene statusCode, extraer del body
    if 'statusCode' in bolinks_response and 'body' in bolinks_response:
        body = json.loads(bolinks_response['body'])
        return body
    else:
        return bolinks_response

def execute_pipeline(date: str, section: str = 'primera') -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo: bolinks → s3writer → dbwriter → notifier
    """
    execution_data = {
        'date': date,
        'section': section,
        'start_time': datetime.now().isoformat(),
        'steps': []
    }
    
    # Step 1: Bolinks (Fetcher + Parser combinado)
    print(f"Step 1: Getting PDF links for date {date}, section {section}")
    
    # Validar formato de fecha YYYYMMDD
    if len(date) != 8 or not date.isdigit():
        error_msg = f"Invalid date format: {date}. Expected format: YYYYMMDD"
        print(error_msg)
        execution_data['success'] = False
        execution_data['error_message'] = error_msg
        execution_data['end_time'] = datetime.now().isoformat()
        return execution_data
    
    bolinks_payload = {
        "date": date,
        "section": section
    }
    bolinks_result = invoke_lambda(BOLINKS_FUNCTION, bolinks_payload)

    execution_data['steps'].append({
        'step': 'bolinks',
        'success': bolinks_result.get('success', False),
        'result': bolinks_result
    })

    pdf_links_flat = flatten_bolinks_pdf_links(bolinks_result.get('pdf_links', []))

    if not bolinks_result.get('success', False) and not pdf_links_flat:
        # Pipeline falló en bolinks - notificar y salir
        execution_data['success'] = False
        execution_data['failed_step'] = 'bolinks'
        execution_data['error_message'] = bolinks_result.get('error', 'Unknown error')
        execution_data['end_time'] = datetime.now().isoformat()
        
        # Notificar fallo
        notify_result = invoke_lambda(NOTIFIER_FUNCTION, {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps({"execution_data": execution_data})
        })
        
        return execution_data
    
    # Step 2: S3Writer (procesar PDFs desde bolinks)
    print("Step 2: Processing PDF links from bolinks result")
    
    # Extraer pdf_links del resultado de bolinks (lista plana para s3writer)
    pdf_links = pdf_links_flat

    # Crear payload para s3writer con los PDFs
    s3writer_payload = {
        "bolinks_output": bolinks_result,
        "pdf_links": pdf_links,
        "date": date,
        "section": section
    }
    s3writer_result = invoke_lambda(S3WRITER_FUNCTION, s3writer_payload)
    
    execution_data['steps'].append({
        'step': 's3writer',
        'success': s3writer_result.get('success', False),
        'result': s3writer_result
    })
    
    if not s3writer_result.get('success'):
        # Pipeline falló en s3writer - notificar y salir
        execution_data['success'] = False
        execution_data['failed_step'] = 's3writer'
        execution_data['error_message'] = s3writer_result.get('error', 'Unknown error')
        execution_data['end_time'] = datetime.now().isoformat()
        
        # Notificar fallo
        notify_result = invoke_lambda(NOTIFIER_FUNCTION, {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps({"execution_data": execution_data})
        })
        
        return execution_data
    
    # Step 3: DBWriter
    print("Step 3: Writing metadata to DynamoDB")
    dbwriter_payload = {
        "s3writer_output": s3writer_result
    }
    dbwriter_result = invoke_lambda(DBWRITER_FUNCTION, dbwriter_payload)
    
    execution_data['steps'].append({
        'step': 'dbwriter',
        'success': dbwriter_result.get('success', False),
        'result': dbwriter_result
    })
    
    if not dbwriter_result.get('success'):
        # Pipeline falló en dbwriter - notificar y salir
        execution_data['success'] = False
        execution_data['failed_step'] = 'dbwriter'
        execution_data['error_message'] = dbwriter_result.get('error', 'Unknown error')
        execution_data['end_time'] = datetime.now().isoformat()
        
        # Notificar fallo
        notify_result = invoke_lambda(NOTIFIER_FUNCTION, {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps({"execution_data": execution_data})
        })
        
        return execution_data
    
    # Step 4: Notifier (éxito completo)
    print("Step 4: Sending success notification")
    execution_data['success'] = True
    execution_data['end_time'] = datetime.now().isoformat()
    
    # Notificar éxito
    notify_result = invoke_lambda(NOTIFIER_FUNCTION, {
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({"execution_data": execution_data})
    })
    
    # Pipeline exitoso - preparar datos de éxito
    execution_data.update({
        'success': True,
        'site_id': s3writer_result.get('site_id', 'boletin_oficial'),
        'date': date,
        'section': section,
        'total_found': len(pdf_links),
        'processed_count': s3writer_result.get('processed_count', 0),
        'failed_count': s3writer_result.get('failed_count', 0),
        'uploaded_files_count': s3writer_result.get('processed_count', 0),
        'db_records_count': dbwriter_result.get('records_count', 0),
        's3_bucket': s3writer_result.get('s3_bucket', ''),
        'dynamodb_table': dbwriter_result.get('dynamodb_table', ''),
        'sample_files': s3writer_result.get('uploaded_files', [])[:3],  # Primeros 3 archivos
        'end_time': datetime.now().isoformat()
    })
    
    return execution_data

def handler(event, context):
    """
    Lambda handler para orquestar el pipeline completo
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
            date = body.get("date")
            section = body.get("section", "primera")
        else:
            # Invocación directa
            date = event.get("date")
            section = event.get("section", "primera")
        
        # Validar parámetro date
        if not date:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: date. Expected format: YYYYMMDD"})
            }
        
        # Ejecutar pipeline completo
        result = execute_pipeline(date, section)
        
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
    test_event = {
        "url": "https://www.boletinoficial.gob.ar/seccion/primera"
    }
    
    result = handler(test_event, None)
    print("Result:", json.dumps(result, indent=2))

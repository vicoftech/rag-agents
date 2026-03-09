import json
import os
import boto3
from datetime import datetime
from typing import Dict, Optional

# AWS Session
session_args = {'region_name': os.getenv('AWS_REGION', 'us-east-1')}
if os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'):
    session_args.update({
        'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY')
    })

# AWS Clients
sns_client = boto3.client('sns', **session_args)

# Environment variables
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL', '')

def create_success_notification(execution_data: Dict) -> Dict:
    """
    Crea notificación de éxito
    """
    subject = f"✅ RAG Pipeline Success - {execution_data.get('site_id', 'Unknown Site')}"
    
    message = f"""
RAG Pipeline Execution Completed Successfully

📊 Execution Summary:
• Site ID: {execution_data.get('site_id', 'N/A')}
• Date: {execution_data.get('date', 'N/A')}
• Total Documents Found: {execution_data.get('total_found', 0)}
• Documents Processed: {execution_data.get('processed_count', 0)}
• Files Uploaded to S3: {execution_data.get('uploaded_files_count', 0)}

📁 S3 Details:
• Bucket: {execution_data.get('s3_bucket', 'N/A')}
• Path Pattern: site_id/date/filename.pdf

🗄️ Database:
• Records Created/Updated: {execution_data.get('db_records_count', 0)}
• Table: {execution_data.get('dynamodb_table', 'N/A')}

⏰ Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

🔗 Access Files:
{chr(10).join([f"• {file.get('filename', 'Unknown')}: {file.get('s3_uri', 'N/A')}" for file in execution_data.get('sample_files', [])])}

---
This is an automated notification from RAG Pipeline System
    """.strip()
    
    return {
        'subject': subject,
        'message': message,
        'status': 'success',
        'priority': 'normal'
    }

def create_failure_notification(execution_data: Dict) -> Dict:
    """
    Crea notificación de fallo
    """
    error_type = execution_data.get('error_type', 'UNKNOWN_ERROR')
    site_id = execution_data.get('site_id', 'Unknown Site')
    
    subject = f"❌ RAG Pipeline Failed - {site_id} ({error_type})"
    
    message = f"""
RAG Pipeline Execution Failed

🚨 Error Details:
• Site ID: {site_id}
• Error Type: {error_type}
• Error Message: {execution_data.get('error_message', 'No error message provided')}
• Failed Step: {execution_data.get('failed_step', 'Unknown')}

📊 Attempt Summary:
• Date: {execution_data.get('date', 'N/A')}
• Total Documents Found: {execution_data.get('total_found', 0)}
• Documents Attempted: {execution_data.get('processed_count', 0)}

🔧 Debug Information:
• Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
• Execution Context: {execution_data.get('execution_context', 'Not available')}

📧 Support Information:
• Check AWS CloudWatch logs for detailed error information
• Contact support if this error persists

---
This is an automated notification from RAG Pipeline System
    """.strip()
    
    return {
        'subject': subject,
        'message': message,
        'status': 'failure',
        'priority': 'high'
    }

def create_partial_success_notification(execution_data: Dict) -> Dict:
    """
    Crea notificación de éxito parcial
    """
    site_id = execution_data.get('site_id', 'Unknown Site')
    
    subject = f"⚠️ RAG Pipeline Partial Success - {site_id}"
    
    message = f"""
RAG Pipeline Completed with Warnings

📊 Execution Summary:
• Site ID: {site_id}
• Date: {execution_data.get('date', 'N/A')}
• Total Documents Found: {execution_data.get('total_found', 0)}
• Documents Processed: {execution_data.get('processed_count', 0)}
• Files Failed: {execution_data.get('failed_count', 0)}
• Files Uploaded to S3: {execution_data.get('uploaded_files_count', 0)}

⚠️ Issues Found:
• Some documents failed to process or upload
• Check individual file status in database

📁 S3 Details:
• Bucket: {execution_data.get('s3_bucket', 'N/A')}
• Successful uploads available in database

🗄️ Database:
• Records Created/Updated: {execution_data.get('db_records_count', 0)}
• Table: {execution_data.get('dynamodb_table', 'N/A')}

⏰ Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

---
This is an automated notification from RAG Pipeline System
    """.strip()
    
    return {
        'subject': subject,
        'message': message,
        'status': 'partial_success',
        'priority': 'normal'
    }

def publish_notification(notification: Dict) -> bool:
    """
    Publica notificación a SNS
    """
    try:
        # Preparar mensaje para SNS
        sns_message = {
            'default': notification['message'],
            'email': notification['message']
        }
        
        # Publicar a SNS
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(sns_message),
            Subject=notification['subject'],
            MessageStructure='json'
        )
        
        print(f"Successfully published notification to SNS: {response['MessageId']}")
        return True
        
    except Exception as e:
        print(f"Error publishing notification to SNS: {e}")
        return False

def process_execution_result(execution_data: Dict) -> Dict:
    """
    Procesa el resultado de ejecución y determina tipo de notificación
    """
    try:
        # Determinar tipo de resultado
        success = execution_data.get('success', False)
        processed_count = execution_data.get('processed_count', 0)
        total_found = execution_data.get('total_found', 0)
        failed_count = execution_data.get('failed_count', 0)
        
        # Crear notificación apropiada
        if success and failed_count == 0:
            # Éxito completo
            notification = create_success_notification(execution_data)
        elif success and failed_count > 0:
            # Éxito parcial
            notification = create_partial_success_notification(execution_data)
        else:
            # Fallo completo
            notification = create_failure_notification(execution_data)
        
        # Publicar notificación
        notification_published = publish_notification(notification)
        
        return {
            'success': notification_published,
            'notification_type': notification['status'],
            'subject': notification['subject'],
            'message_id': notification_published,
            'execution_summary': {
                'site_id': execution_data.get('site_id'),
                'date': execution_data.get('date'),
                'success': success,
                'processed_count': processed_count,
                'total_found': total_found,
                'failed_count': failed_count
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Error processing execution result: {str(e)}',
            'execution_data': execution_data
        }

def handler(event, context):
    """
    Lambda handler para enviar notificaciones vía SNS
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
            execution_data = body.get("execution_data")
        else:
            # Invocación directa (desde Step Function)
            execution_data = event.get("execution_data")
        
        # Validar parámetro execution_data
        if not execution_data:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": "Missing required parameter: execution_data"})
            }
        
        # Procesar resultado y enviar notificación
        result = process_execution_result(execution_data)
        
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
        "dynamodb_table": "rag-documents-dev"
        "execution_context": "Some files exceeded size limit"
    }
    
    # Test HTTP
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
    print("Success Test Result:", json.dumps(result, indent=2))
    
    # Test fallo
    test_event_failure = {
        "execution_data": test_failure_data
    }
    
    result_failure = handler(test_event_failure, context)
    print("Failure Test Result:", json.dumps(result_failure, indent=2))
    
    # Test éxito parcial
    test_event_partial = {
        "execution_data": test_partial_data
    }
    
    result_partial = handler(test_event_partial, context)
    print("Partial Success Test Result:", json.dumps(result_partial, indent=2))

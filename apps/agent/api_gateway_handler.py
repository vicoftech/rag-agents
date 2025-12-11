"""
Handler para API Gateway que invoca el agente Bedrock Agent Core
Este handler convierte las peticiones HTTP de API Gateway al formato esperado por el agente
"""
import json
import os
import sys

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import run_agent

def lambda_handler(event, context):
    """
    Handler Lambda para API Gateway.
    
    Args:
        event: Evento de API Gateway
        context: Contexto de Lambda
        
    Returns:
        Respuesta en formato API Gateway
    """
    try:
        # Extraer el body de la petición
        body = event.get("body", "{}")
        if isinstance(body, str):
            body = json.loads(body)
        
        # Extraer parámetros del body
        prompt = body.get("prompt", "")
        tenant_id = body.get("tenant_id", "")
        agent_id = body.get("agent_id", "")
        
        # Validar parámetros requeridos
        if not prompt:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization",
                    "Access-Control-Allow-Methods": "POST,OPTIONS"
                },
                "body": json.dumps({
                    "error": "Se requiere el campo 'prompt'"
                })
            }
        
        if not tenant_id:
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization",
                    "Access-Control-Allow-Methods": "POST,OPTIONS"
                },
                "body": json.dumps({
                    "error": "Se requiere el campo 'tenant_id'"
                })
            }
        
        # Invocar el agente directamente
        result_text = run_agent(
            query=prompt,
            tenant_id=tenant_id,
            agent_id=agent_id or ""
        )
        
        # Retornar respuesta en formato API Gateway
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "POST,OPTIONS"
            },
            "body": json.dumps({
                "statusCode": 200,
                "result": result_text,
                "tenant_id": tenant_id,
                "agent_id": agent_id
            })
        }
        
    except json.JSONDecodeError as e:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "POST,OPTIONS"
            },
            "body": json.dumps({
                "error": f"Error al parsear JSON: {str(e)}"
            })
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "POST,OPTIONS"
            },
            "body": json.dumps({
                "error": f"Error interno: {str(e)}"
            })
        }


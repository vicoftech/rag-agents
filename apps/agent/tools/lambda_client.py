"""
Cliente para invocar las Lambdas RAG
"""
import json
import boto3
from config import (
    AWS_REGION,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    LAMBDA_EMBEDDINGS,
    LAMBDA_QUERY,
)

# AWS Session Setup
session_args = {"region_name": AWS_REGION}

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    session_args.update({
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
    })

lambda_client = boto3.client("lambda", **session_args)


def invoke_embeddings_lambda(text: str) -> list:
    """
    Invoca la Lambda de embeddings para generar el vector de un texto.
    
    Args:
        text: Texto a convertir en embedding
        
    Returns:
        Lista de floats representando el embedding
    """
    payload = {"text": text}
    
    response = lambda_client.invoke(
        FunctionName=LAMBDA_EMBEDDINGS,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    
    response_payload = json.loads(response["Payload"].read())
    
    if "errorMessage" in response_payload:
        raise RuntimeError(f"Error en Lambda embeddings: {response_payload['errorMessage']}")
    
    if "body" in response_payload:
        body = json.loads(response_payload["body"]) if isinstance(response_payload["body"], str) else response_payload["body"]
        return body.get("embedding", [])
    
    return response_payload.get("embedding", [])


def invoke_query_lambda(
    query: str,
    tenant_id: str,
    agent_id: str,
    document_id: str = None,
) -> str:
    """
    Invoca la Lambda de query que realiza búsqueda semántica y genera una respuesta
    procesada por el LLM usando el contexto de la base de conocimiento.
    
    La Lambda:
    1. Busca chunks relevantes por similaridad de vectores
    2. Aplica el prompt template del agente con el contexto encontrado
    3. Genera una respuesta usando el LLM
    
    Args:
        query: Consulta del usuario
        tenant_id: ID del tenant
        agent_id: ID del agente (requerido para obtener el prompt template)
        document_id: ID del documento específico (opcional)
        
    Returns:
        Respuesta generada por el LLM basada en el contexto de la base de conocimiento.
        Si no encuentra información relevante, indica que no hay datos disponibles.
    """
    payload = {
        "query": query,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
    }
    
    if document_id:
        payload["document_id"] = document_id
    
    response = lambda_client.invoke(
        FunctionName=LAMBDA_QUERY,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )
    
    response_payload = json.loads(response["Payload"].read())
    
    if "errorMessage" in response_payload:
        raise RuntimeError(f"Error en Lambda query: {response_payload['errorMessage']}")
    
    # La respuesta es directamente el body (respuesta del LLM)
    if "body" in response_payload:
        body = response_payload["body"]
        # Si body es string JSON, parsearlo
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
                return parsed if isinstance(parsed, str) else json.dumps(parsed)
            except json.JSONDecodeError:
                return body
        return body
    
    return str(response_payload)

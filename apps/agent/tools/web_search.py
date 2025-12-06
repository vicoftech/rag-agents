"""
Herramienta de búsqueda en internet
"""
import json
import boto3
from strands import tool
from config import AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

# AWS Session Setup
session_args = {"region_name": AWS_REGION}

if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    session_args.update({
        "aws_access_key_id": AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
    })

bedrock_agent = boto3.client("bedrock-agent-runtime", **session_args)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Busca información actualizada en internet.
    
    Usa esta herramienta cuando necesites:
    - Información actualizada o en tiempo real
    - Datos que no están en la base de conocimiento interna
    - Verificar información externa o pública
    - Complementar el conocimiento interno con fuentes externas
    
    Args:
        query: Términos de búsqueda o pregunta para buscar en internet
        max_results: Número máximo de resultados a retornar (default: 5)
        
    Returns:
        Resumen de los resultados encontrados en internet con sus fuentes
    """
    try:
        # Usar Bedrock Retrieve and Generate con web search
        response = bedrock_agent.retrieve(
            knowledgeBaseId="WEBSEARCH",  # ID especial para web search
            retrievalQuery={
                "text": query
            },
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": max_results
                }
            }
        )
        
        results = response.get("retrievalResults", [])
        
        if not results:
            return f"No se encontraron resultados en internet para: '{query}'"
        
        formatted_results = []
        for i, result in enumerate(results, 1):
            content = result.get("content", {}).get("text", "")
            source = result.get("location", {}).get("webLocation", {}).get("url", "Fuente desconocida")
            formatted_results.append(f"[{i}] {content}\nFuente: {source}")
        
        return "\n\n---\n\n".join(formatted_results)
        
    except Exception as e:
        # Fallback: si no hay web search configurado, indicarlo
        error_msg = str(e)
        if "WEBSEARCH" in error_msg or "knowledgeBaseId" in error_msg:
            return "La búsqueda web no está configurada en este entorno. Usa tu conocimiento general para responder."
        return f"Error al buscar en internet: {error_msg}"

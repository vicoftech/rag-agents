"""
Herramienta de búsqueda en la base de conocimiento RAG
Invoca la Lambda que realiza búsqueda semántica y genera respuesta con LLM
"""
from strands import tool
from .lambda_client import invoke_query_lambda


@tool
def knowledge_base_search(
    query: str,
    tenant_id: str,
    agent_id: str,
    document_id: str = None,
) -> str:
    """
    Consulta la base de conocimiento empresarial para obtener información específica.
    
    Esta herramienta busca en documentos internos indexados y genera una respuesta
    basada en el contexto encontrado. Es ideal para:
    - Consultas sobre documentos, políticas o procedimientos internos
    - Información específica del negocio o la organización
    - Datos históricos o documentados previamente
    
    IMPORTANTE: Esta herramienta solo responde con información que existe en la base
    de conocimiento. Si no encuentra información relevante, lo indicará claramente.
    
    Args:
        query: La pregunta o consulta sobre información interna
        tenant_id: Identificador del tenant/organización
        agent_id: ID del agente que define el contexto y comportamiento de búsqueda
        document_id: ID de un documento específico para limitar la búsqueda (opcional)
        
    Returns:
        Respuesta generada basada en el contexto de la base de conocimiento.
        Si no hay información relevante, indicará que no encontró datos.
    """
    try:
        response = invoke_query_lambda(
            query=query,
            tenant_id=tenant_id,
            agent_id=agent_id,
            document_id=document_id,
        )
        
        if not response:
            return "No se encontró información relevante en la base de conocimiento para esta consulta."
        
        return response
        
    except Exception as e:
        return f"Error al consultar la base de conocimiento: {str(e)}"

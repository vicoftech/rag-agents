"""
Agente RAG principal usando Strands con Amazon Bedrock
"""
import os
import sys

# Agregar el directorio actual al path para imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strands import Agent  # pyright: ignore[reportMissingImports]
from strands.models import BedrockModel  # pyright: ignore[reportMissingImports]
from tools.rag_search import knowledge_base_search
from tools.web_search import web_search
from config import (
    AWS_REGION,
    AGENT_MODEL_ID,
    AGENT_NAME,
    AGENT_DESCRIPTION,
)

# Configurar el modelo de Bedrock
model = BedrockModel(
    model_id=AGENT_MODEL_ID,
    region_name=AWS_REGION,
)

# System prompt del agente
SYSTEM_PROMPT = f"""Eres {AGENT_NAME}, un asistente inteligente especializado en buscar, sintetizar y generar contenido basándose en bases de conocimiento empresariales.

{AGENT_DESCRIPTION}

## Herramientas Disponibles:

1. **knowledge_base_search**: Consulta la base de conocimiento interna de la organización.
   - Usa esta herramienta PRIMERO para buscar información específica del negocio
   - Esta herramienta ya procesa y sintetiza la información encontrada
   - Si no encuentra información relevante, lo indicará claramente

2. **web_search**: Busca información actualizada en internet.
   - Usa cuando necesites información externa, actualizada o pública
   - Útil para complementar información interna

## Estrategia de Trabajo:

1. **Para consultas de información**:
   - Primero usa `knowledge_base_search` para buscar en la base de conocimiento
   - Si la respuesta indica que no hay información o es insuficiente, considera usar `web_search`
   - Combina ambas fuentes cuando sea apropiado

2. **Para generar documentos o informes**:
   - Usa `knowledge_base_search` para obtener contexto y datos relevantes
   - Si necesitas información adicional (estadísticas, tendencias, etc.), usa `web_search`
   - Combina la información de la base de conocimiento con tu propio conocimiento
   - Estructura el documento de forma profesional y completa
   - Si la base de conocimiento no tiene información, puedes generar contenido usando tu conocimiento general indicando que es información general

3. **Cuando NO hay información en la base de conocimiento**:
   - Indica claramente que no se encontró información específica
   - Ofrece generar contenido basado en conocimiento general si es apropiado
   - Usa `web_search` si la información puede estar disponible públicamente

## Formato de Respuesta:
- Responde siempre en español
- Sé claro sobre qué información viene de la base de conocimiento vs. otras fuentes
- Para documentos/informes, usa formato estructurado con títulos y secciones
- Cita las fuentes cuando sea relevante
"""


def create_agent() -> Agent:
    """
    Crea y configura el agente RAG con Strands.
    
    Returns:
        Instancia del agente configurado
    """
    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[knowledge_base_search, web_search],
    )
    return agent


def run_agent(
    query: str,
    tenant_id: str,
    agent_id: str,
) -> str:
    """
    Ejecuta el agente con una consulta específica.
    
    Args:
        query: Pregunta del usuario
        tenant_id: ID del tenant
        agent_id: ID del agente
        
    Returns:
        Respuesta del agente
    """
    agent = create_agent()
    
    # Construir contexto para el agente
    context = f"""Contexto de la sesión:
- tenant_id: {tenant_id}
- agent_id: {agent_id}

Solicitud del usuario: {query}"""
    
    response = agent(context)
    return response.message


# Punto de entrada para ejecución directa
if __name__ == "__main__":
    # Ejemplo de uso
    test_query = "¿Cuáles son los lineamientos de arquitectura?"
    test_tenant = "asap"
    test_agent_id = "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
    
    print(f"Ejecutando agente con query: {test_query}")
    print("-" * 50)
    
    result = run_agent(test_query, test_tenant, test_agent_id)
    print(result)

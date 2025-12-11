"""
Handler para Amazon Bedrock AgentCore Runtime
Este archivo es el punto de entrada para el despliegue en AgentCore
"""
import os
import sys
import json

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from tools.rag_search import knowledge_base_search
from tools.web_search import web_search
from config import AWS_REGION, AGENT_MODEL_ID, AGENT_NAME

# Crear la aplicación AgentCore
app = BedrockAgentCoreApp()

# System prompt del agente
SYSTEM_PROMPT = f"""Eres {AGENT_NAME}, un asistente inteligente especializado en buscar y sintetizar información de bases de conocimiento empresariales.

## Instrucciones:

1. **Siempre usa la herramienta knowledge_base_search** para buscar información antes de responder preguntas sobre documentos o conocimiento específico.

2. **Parámetros requeridos para knowledge_base_search**: 
   - `query`: La pregunta o términos de búsqueda
   - `tenant_id`: El identificador del tenant/organización
   - `agent_id`: El identificador del agente (requerido)

3. **Formato de respuesta**:
   - Sintetiza la información encontrada de manera clara y estructurada
   - Si no encuentras información, indica que no hay datos disponibles

4. **Comportamiento**:
   - Responde siempre en español
   - Sé conciso pero completo
"""


def create_strands_agent() -> Agent:
    """Crea el agente Strands con el modelo Bedrock."""
    model = BedrockModel(
        model_id=AGENT_MODEL_ID,
        region_name=AWS_REGION,
    )
    
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[knowledge_base_search, web_search],
    )


# Agente singleton
_agent = None


def get_agent() -> Agent:
    """Obtiene o crea el agente singleton."""
    global _agent
    if _agent is None:
        _agent = create_strands_agent()
    return _agent


@app.entrypoint
def invoke(payload: dict) -> dict:
    """
    Punto de entrada principal para AgentCore.
    
    Args:
        payload: Diccionario con:
            - prompt: La consulta del usuario
            - tenant_id: ID del tenant
            - agent_id: ID del agente (opcional)
            
    Returns:
        Diccionario con la respuesta del agente
    """
    app.logger.info(f"Payload recibido: {json.dumps(payload)}")
    
    prompt = payload.get("prompt", "")
    tenant_id = payload.get("tenant_id")
    agent_id = payload.get("agent_id")
    
    if not prompt:
        return {
            "statusCode": 400,
            "error": "Se requiere el campo 'prompt'"
        }
    
    if not tenant_id:
        return {
            "statusCode": 400,
            "error": "Se requiere el campo 'tenant_id'"
        }
    
    try:
        agent = get_agent()
        
        # Construir contexto para el agente
        context = f"Contexto: tenant_id={tenant_id}"
        if agent_id:
            context += f", agent_id={agent_id}"
        
        full_prompt = f"{context}\n\nPregunta: {prompt}"
        
        app.logger.info(f"Ejecutando agente con prompt: {full_prompt[:100]}...")
        
        response = agent(full_prompt)
        
        return {
            "statusCode": 200,
            "result": response.message,
            "tenant_id": tenant_id,
            "agent_id": agent_id
        }
        
    except Exception as e:
        app.logger.error(f"Error ejecutando agente: {str(e)}")
        return {
            "statusCode": 500,
            "error": str(e)
        }


# Para ejecución local
if __name__ == "__main__":
    app.run()


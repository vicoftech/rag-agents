"""
Servidor MCP para exponer el agente RAG como herramienta
Compatible con Amazon Bedrock AgentCore
"""
import os
import sys
import json
import asyncio
from typing import Any

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from tools.lambda_client import invoke_query_lambda
from config import MCP_HOST, MCP_PORT

# Crear servidor MCP
server = Server("rag-knowledge-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Lista las herramientas disponibles en el servidor MCP."""
    return [
        Tool(
            name="knowledge_base_search",
            description="""Consulta la base de conocimiento empresarial para obtener información.
            
Realiza una búsqueda semántica en los documentos indexados y genera una respuesta
procesada basada en el contexto encontrado.

Usa esta herramienta cuando necesites:
- Buscar información en documentos corporativos
- Responder preguntas basadas en conocimiento indexado
- Obtener contexto relevante de la base de conocimiento""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La pregunta o consulta para buscar información relacionada"
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "Identificador del tenant/organización donde buscar"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "ID del agente que define el contexto de búsqueda"
                    },
                    "document_id": {
                        "type": "string",
                        "description": "ID de un documento específico para buscar solo en él (opcional)"
                    }
                },
                "required": ["query", "tenant_id", "agent_id"]
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Ejecuta una herramienta del servidor MCP."""
    
    if name == "knowledge_base_search":
        query = arguments.get("query")
        tenant_id = arguments.get("tenant_id")
        agent_id = arguments.get("agent_id")
        document_id = arguments.get("document_id")
        
        if not query or not tenant_id or not agent_id:
            return [TextContent(
                type="text",
                text="Error: Se requieren 'query', 'tenant_id' y 'agent_id'"
            )]
        
        try:
            # Ejecutar búsqueda semántica via Lambda
            response = invoke_query_lambda(
                query=query,
                tenant_id=tenant_id,
                agent_id=agent_id,
                document_id=document_id,
            )
            
            if not response:
                return [TextContent(
                    type="text",
                    text=f"No se encontró información relevante para: '{query}'"
                )]
            
            return [TextContent(
                type="text",
                text=response
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error al buscar: {str(e)}"
            )]
    
    return [TextContent(
        type="text",
        text=f"Herramienta desconocida: {name}"
    )]


async def main():
    """Punto de entrada principal del servidor MCP."""
    print(f"[MCP Server] Iniciando servidor RAG Knowledge...")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

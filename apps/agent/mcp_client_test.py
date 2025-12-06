"""
Cliente de prueba para el servidor MCP desplegado en AgentCore
"""
import asyncio
import os
import sys
import json

async def test_local_mcp():
    """Prueba el servidor MCP localmente usando stdio."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    
    print("=" * 60)
    print("PRUEBA DEL SERVIDOR MCP LOCAL")
    print("=" * 60)
    
    # Iniciar el servidor MCP como subproceso
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # Listar herramientas disponibles
            print("\n[1] Listando herramientas disponibles...")
            tools_result = await session.list_tools()
            print(f"Herramientas: {[t.name for t in tools_result.tools]}")
            
            # Probar búsqueda en KB
            print("\n[2] Probando búsqueda en Knowledge Base...")
            search_result = await session.call_tool(
                "knowledge_base_search",
                {
                    "query": "arquitectura hexagonal",
                    "tenant_id": "asap",
                    "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
                }
            )
            
            print(f"Resultado: {search_result.content[0].text[:500]}...")


async def test_agentcore_mcp():
    """
    Prueba el servidor MCP desplegado en AgentCore.
    Requiere AGENT_ARN y BEARER_TOKEN como variables de entorno.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    
    print("=" * 60)
    print("PRUEBA DEL SERVIDOR MCP EN AGENTCORE")
    print("=" * 60)
    
    agent_arn = os.getenv('AGENT_ARN')
    bearer_token = os.getenv('BEARER_TOKEN')
    
    if not agent_arn or not bearer_token:
        print("Error: Configura AGENT_ARN y BEARER_TOKEN")
        print("  export AGENT_ARN='arn:aws:bedrock-agentcore:...'")
        print("  export BEARER_TOKEN='tu-token'")
        return
    
    # Construir URL del servidor MCP
    encoded_arn = agent_arn.replace(':', '%3A').replace('/', '%2F')
    region = os.getenv('AWS_REGION', 'us-east-1')
    mcp_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
    
    headers = {
        "authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    
    print(f"URL: {mcp_url}")
    
    async with streamablehttp_client(mcp_url, headers, timeout=120, terminate_on_close=False) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            # Listar herramientas
            print("\n[1] Listando herramientas...")
            tools_result = await session.list_tools()
            print(f"Herramientas disponibles:")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description[:50]}...")
            
            # Probar búsqueda
            print("\n[2] Ejecutando búsqueda de prueba...")
            result = await session.call_tool(
                "knowledge_base_search",
                {
                    "query": "¿Cuáles son los lineamientos de arquitectura?",
                    "tenant_id": "asap",
                    "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
                }
            )
            
            print(f"\nResultado:")
            print(result.content[0].text)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cliente de prueba MCP")
    parser.add_argument(
        "--mode",
        choices=["local", "agentcore"],
        default="local",
        help="Modo: local (stdio) o agentcore (HTTP)"
    )
    
    args = parser.parse_args()
    
    if args.mode == "local":
        asyncio.run(test_local_mcp())
    else:
        asyncio.run(test_agentcore_mcp())


"""
Tests manuales para probar con servicios reales.
NO se ejecutan con pytest automáticamente.

Uso:
    python -m tests.manual.test_live --mode [kb|web|agent|interactive]
"""
import os
import sys
import argparse

# Agregar el directorio del agente al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_knowledge_base_live():
    """Prueba la búsqueda en KB con servicios reales."""
    from tools import knowledge_base_search
    
    print("=" * 60)
    print("TEST LIVE: Knowledge Base Search")
    print("=" * 60)
    
    test_cases = [
        {
            "query": "¿Cuáles son los lineamientos de arquitectura?",
            "tenant_id": "asap",
            "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
        },
        {
            "query": "¿Qué es DDD?",
            "tenant_id": "asap",
            "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'─' * 60}")
        print(f"Test {i}: {test['query']}")
        print(f"Tenant: {test['tenant_id']}, Agent: {test['agent_id'][:8]}...")
        print("─" * 60)
        
        try:
            result = knowledge_base_search(
                query=test["query"],
                tenant_id=test["tenant_id"],
                agent_id=test["agent_id"]
            )
            print(f"\nResultado:\n{result[:500]}...")
        except Exception as e:
            print(f"\nError: {str(e)}")


def test_web_search_live():
    """Prueba la búsqueda web con servicios reales."""
    from tools import web_search
    
    print("=" * 60)
    print("TEST LIVE: Web Search")
    print("=" * 60)
    
    test_queries = [
        "¿Qué es arquitectura hexagonal?",
        "Best practices para microservicios 2024",
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'─' * 60}")
        print(f"Test {i}: {query}")
        print("─" * 60)
        
        try:
            result = web_search(query=query, max_results=3)
            print(f"\nResultado:\n{result}")
        except Exception as e:
            print(f"\nError: {str(e)}")


def test_agent_live():
    """Prueba el agente completo con servicios reales."""
    from agent import run_agent
    
    print("=" * 60)
    print("TEST LIVE: Agente Completo")
    print("=" * 60)
    
    test_cases = [
        {
            "query": "¿Cuáles son los lineamientos de arquitectura?",
            "tenant_id": "asap",
            "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
        },
        {
            "query": "Genera un resumen de las mejores prácticas de DDD",
            "tenant_id": "asap",
            "agent_id": "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'─' * 60}")
        print(f"Test {i}: {test['query']}")
        print("─" * 60)
        
        try:
            result = run_agent(
                query=test["query"],
                tenant_id=test["tenant_id"],
                agent_id=test["agent_id"]
            )
            print(f"\nRespuesta del Agente:\n{result}")
        except Exception as e:
            print(f"\nError: {str(e)}")


def interactive_mode():
    """Modo interactivo para probar el agente."""
    from agent import run_agent
    
    print("=" * 60)
    print("MODO INTERACTIVO - RAG AGENT")
    print("Escribe 'salir' para terminar")
    print("=" * 60)
    
    tenant_id = input("\nIngresa tenant_id [asap]: ").strip() or "asap"
    agent_id = input("Ingresa agent_id [d8c38f93-f4cd-4a85-9c31-297d14ce7009]: ").strip() or "d8c38f93-f4cd-4a85-9c31-297d14ce7009"
    
    print(f"\nConfiguración: tenant={tenant_id}, agent={agent_id[:8]}...")
    print("─" * 60)
    
    while True:
        query = input("\nTu pregunta: ").strip()
        
        if query.lower() in ["salir", "exit", "quit"]:
            print("¡Hasta luego!")
            break
        
        if not query:
            continue
        
        try:
            print("\nProcesando...")
            result = run_agent(query, tenant_id, agent_id)
            print(f"\nAgente: {result}")
        except Exception as e:
            print(f"\nError: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tests manuales del Agente RAG")
    parser.add_argument(
        "--mode",
        choices=["kb", "web", "agent", "interactive"],
        default="agent",
        help="Modo de prueba: kb, web, agent (default), interactive"
    )
    
    args = parser.parse_args()
    
    if args.mode == "kb":
        test_knowledge_base_live()
    elif args.mode == "web":
        test_web_search_live()
    elif args.mode == "agent":
        test_agent_live()
    elif args.mode == "interactive":
        interactive_mode()

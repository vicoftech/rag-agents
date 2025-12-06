"""
Módulo de embeddings para el agente RAG
Usa Lambda para generar embeddings
"""
from .lambda_client import invoke_embeddings_lambda


def embed_text(text: str) -> list:
    """
    Genera embeddings para un texto usando la Lambda de embeddings.
    
    Args:
        text: Texto a convertir en embedding
        
    Returns:
        Lista de floats representando el embedding
    """
    return invoke_embeddings_lambda(text)

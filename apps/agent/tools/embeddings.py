"""
Módulo de embeddings para el agente RAG
Usa Lambda para generar embeddings
"""
from .lambda_client import invoke_embeddings_lambda


def embed_text(text: str, input_type: str = "search_document") -> list:
    """
    Genera embeddings vía Lambda. Ver `invoke_embeddings_lambda` para input_type.
    """
    return invoke_embeddings_lambda(text, input_type=input_type)

"""
Parseo de respuestas de embeddings (Cohere v4 en Bedrock, Titan legacy, etc.).
Mantener sincronizado con apps/rag_lmbd_query/lib/bedrock_embeddings.py.
"""
from __future__ import annotations

from typing import Any, List, Union


def parse_embedding_vectors(result: dict) -> List[List[float]]:
    """
    Extrae todos los vectores float de la respuesta JSON de Bedrock.

    Soporta:
    - Cohere v4 `embeddings_floats`: "embeddings" es list[list[float]]
    - Cohere v4 `embeddings_by_type`: "embeddings": {"float": [[...], ...]}
    - Legacy: un único key top-level cuyo valor es [[...], ...]
    """
    if not isinstance(result, dict):
        raise RuntimeError(f"Respuesta de embedding no es dict: {type(result)}")

    if "embeddings" in result:
        emb = result["embeddings"]
        if isinstance(emb, list):
            if not emb:
                raise RuntimeError("embeddings es lista vacía")
            if isinstance(emb[0], list):
                return [_as_float_list(row) for row in emb]
            if isinstance(emb[0], (int, float)):
                return [_as_float_list(emb)]
            raise RuntimeError(f"Formato embeddings (lista) inesperado: {repr(emb)[:200]}")
        if isinstance(emb, dict):
            floats = emb.get("float")
            if floats is None and len(emb) == 1:
                floats = next(iter(emb.values()))
            if isinstance(floats, list) and floats and isinstance(floats[0], list):
                return [_as_float_list(row) for row in floats]
            if isinstance(floats, list) and floats and isinstance(floats[0], (int, float)):
                return [_as_float_list(floats)]
            raise RuntimeError(f"Formato embeddings (dict) inesperado: {repr(emb)[:200]}")

    if len(result) == 1:
        key = next(iter(result))
        raw = result[key]
        if isinstance(raw, list) and raw and isinstance(raw[0], list):
            return [_as_float_list(row) for row in raw]
        if isinstance(raw, list) and raw and isinstance(raw[0], (int, float)):
            return [_as_float_list(raw)]

    raise RuntimeError(f"No se encontraron vectores de embedding en: {list(result.keys())}")


def parse_embedding_vector(result: dict, index: int = 0) -> List[float]:
    """Un solo texto embebido → primer vector (o índice dado)."""
    vectors = parse_embedding_vectors(result)
    if index < 0 or index >= len(vectors):
        raise RuntimeError(f"Índice embedding {index} fuera de rango (len={len(vectors)})")
    return vectors[index]


def _as_float_list(row: Union[List[Any], Any]) -> List[float]:
    if isinstance(row, (list, tuple)):
        return [float(x) for x in row]
    raise RuntimeError(f"Fila de embedding no es lista: {type(row)}")

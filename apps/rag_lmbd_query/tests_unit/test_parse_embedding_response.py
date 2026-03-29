"""Tests del parser de respuestas Bedrock / Cohere (lib.bedrock_embeddings)."""
import pytest

from lib.bedrock_embeddings import parse_embedding_vector, parse_embedding_vectors


def test_cohere_embeddings_floats_single_row():
    result = {
        "response_type": "embeddings_floats",
        "embeddings": [[0.1, 0.2, 0.3]],
        "id": "x",
    }
    assert parse_embedding_vector(result, 0) == [0.1, 0.2, 0.3]
    assert len(parse_embedding_vectors(result)) == 1


def test_cohere_embeddings_floats_batch():
    result = {
        "embeddings": [[1.0, 2.0], [3.0, 4.0]],
    }
    vecs = parse_embedding_vectors(result)
    assert vecs == [[1.0, 2.0], [3.0, 4.0]]
    assert parse_embedding_vector(result, 1) == [3.0, 4.0]


def test_cohere_embeddings_by_type_float_key():
    result = {
        "response_type": "embeddings_by_type",
        "embeddings": {"float": [[0.5, -0.5]]},
    }
    assert parse_embedding_vector(result, 0) == [0.5, -0.5]


def test_legacy_single_top_level_key():
    result = {"float": [[0.0, 1.0, 2.0]]}
    assert parse_embedding_vector(result, 0) == [0.0, 1.0, 2.0]


def test_flat_single_vector_under_embeddings_list():
    """Un solo vector plano bajo 'embeddings' (algunas respuestas edge)."""
    result = {"embeddings": [0.1, 0.2]}
    assert parse_embedding_vector(result, 0) == [0.1, 0.2]


def test_invalid_raises():
    with pytest.raises(RuntimeError):
        parse_embedding_vector({"foo": "bar"})

"""
Fixtures y configuración compartida para tests
"""
import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO
import json

# Agregar el directorio padre al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# FIXTURES DE CONFIGURACIÓN
# =============================================================================

@pytest.fixture
def test_tenant_id():
    """Tenant ID para tests."""
    return "test_tenant"


@pytest.fixture
def test_agent_id():
    """Agent ID para tests."""
    return "test-agent-uuid-1234"


@pytest.fixture
def test_document_id():
    """Document ID para tests."""
    return "test-doc-uuid-5678"


@pytest.fixture
def sample_query():
    """Query de ejemplo para tests."""
    return "¿Cuáles son los lineamientos de arquitectura?"


# =============================================================================
# MOCKS DE RESPUESTAS LAMBDA
# =============================================================================

@pytest.fixture
def mock_lambda_success_response():
    """Respuesta exitosa de Lambda query."""
    def _create_response(body_content):
        payload = BytesIO(json.dumps({
            "statusCode": 200,
            "body": body_content
        }).encode())
        return {"Payload": payload}
    return _create_response


@pytest.fixture
def mock_lambda_error_response():
    """Respuesta de error de Lambda."""
    def _create_response(error_message):
        payload = BytesIO(json.dumps({
            "errorMessage": error_message
        }).encode())
        return {"Payload": payload}
    return _create_response


@pytest.fixture
def mock_lambda_empty_response():
    """Respuesta vacía de Lambda."""
    payload = BytesIO(json.dumps({
        "statusCode": 200,
        "body": ""
    }).encode())
    return {"Payload": payload}


@pytest.fixture
def mock_embeddings_response():
    """Respuesta de Lambda embeddings."""
    embedding = [0.1] * 1536  # Vector de 1536 dimensiones
    payload = BytesIO(json.dumps({
        "statusCode": 200,
        "body": json.dumps({"embedding": embedding})
    }).encode())
    return {"Payload": payload}


# =============================================================================
# MOCKS DE CLIENTES AWS
# =============================================================================

@pytest.fixture
def mock_lambda_client():
    """Mock del cliente Lambda de boto3."""
    with patch("tools.lambda_client.lambda_client") as mock:
        yield mock


@pytest.fixture
def mock_bedrock_agent_client():
    """Mock del cliente Bedrock Agent Runtime."""
    with patch("tools.web_search.bedrock_agent") as mock:
        yield mock


# =============================================================================
# FIXTURES DE RESPUESTAS WEB SEARCH
# =============================================================================

@pytest.fixture
def mock_web_search_results():
    """Resultados simulados de búsqueda web."""
    return {
        "retrievalResults": [
            {
                "content": {"text": "Contenido del resultado 1"},
                "location": {"webLocation": {"url": "https://example.com/1"}}
            },
            {
                "content": {"text": "Contenido del resultado 2"},
                "location": {"webLocation": {"url": "https://example.com/2"}}
            },
        ]
    }


@pytest.fixture
def mock_web_search_empty():
    """Resultados vacíos de búsqueda web."""
    return {"retrievalResults": []}


# =============================================================================
# FIXTURES PARA TESTS DE INTEGRACIÓN
# =============================================================================

@pytest.fixture
def mock_full_agent_dependencies():
    """Mock de todas las dependencias externas para tests de integración."""
    with patch("tools.lambda_client.lambda_client") as mock_lambda, \
         patch("tools.web_search.bedrock_agent") as mock_bedrock:
        yield {
            "lambda_client": mock_lambda,
            "bedrock_agent": mock_bedrock
        }


@pytest.fixture
def sample_kb_response():
    """Respuesta típica de la base de conocimiento."""
    return """Según los documentos de la base de conocimiento:

Los lineamientos de arquitectura incluyen:
1. Uso de arquitectura hexagonal
2. Principios DDD (Domain-Driven Design)
3. Separación de responsabilidades

Esta información proviene de los documentos internos del tenant."""


@pytest.fixture
def sample_no_info_response():
    """Respuesta cuando no hay información disponible."""
    return "No se encontró información relevante en la base de conocimiento para esta consulta."


# =============================================================================
# HELPERS
# =============================================================================

def create_lambda_payload_response(body, status_code=200):
    """Helper para crear respuestas de Lambda."""
    payload = BytesIO(json.dumps({
        "statusCode": status_code,
        "body": body
    }).encode())
    return {"Payload": payload}


def create_lambda_error_payload(error_message):
    """Helper para crear respuestas de error de Lambda."""
    payload = BytesIO(json.dumps({
        "errorMessage": error_message
    }).encode())
    return {"Payload": payload}

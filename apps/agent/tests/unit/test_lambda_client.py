"""
Tests unitarios para lambda_client.py
"""
import pytest
import json
from io import BytesIO
from unittest.mock import patch, MagicMock


class TestInvokeQueryLambda:
    """Tests para invoke_query_lambda."""

    def test_successful_query_returns_response(self, mock_lambda_client, test_tenant_id, test_agent_id, sample_query):
        """Verifica que una query exitosa retorna la respuesta del LLM."""
        from tools.lambda_client import invoke_query_lambda
        
        expected_response = "Esta es la respuesta del LLM basada en el contexto."
        payload = BytesIO(json.dumps({
            "statusCode": 200,
            "body": expected_response
        }).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_query_lambda(
            query=sample_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == expected_response
        mock_lambda_client.invoke.assert_called_once()

    def test_query_with_document_id_includes_it_in_payload(self, mock_lambda_client, test_tenant_id, test_agent_id, test_document_id):
        """Verifica que document_id se incluye en el payload cuando se proporciona."""
        from tools.lambda_client import invoke_query_lambda
        
        payload = BytesIO(json.dumps({"body": "response"}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        invoke_query_lambda(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id,
            document_id=test_document_id
        )
        
        call_args = mock_lambda_client.invoke.call_args
        sent_payload = json.loads(call_args.kwargs["Payload"])
        assert sent_payload["document_id"] == test_document_id

    def test_query_without_document_id_excludes_it(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica que document_id no se incluye cuando es None."""
        from tools.lambda_client import invoke_query_lambda
        
        payload = BytesIO(json.dumps({"body": "response"}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        invoke_query_lambda(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        call_args = mock_lambda_client.invoke.call_args
        sent_payload = json.loads(call_args.kwargs["Payload"])
        assert "document_id" not in sent_payload

    def test_lambda_error_raises_runtime_error(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica que errores de Lambda lanzan RuntimeError."""
        from tools.lambda_client import invoke_query_lambda
        
        error_msg = "Lambda execution failed"
        payload = BytesIO(json.dumps({"errorMessage": error_msg}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        with pytest.raises(RuntimeError) as exc_info:
            invoke_query_lambda(
                query="test",
                tenant_id=test_tenant_id,
                agent_id=test_agent_id
            )
        
        assert error_msg in str(exc_info.value)

    def test_json_body_is_parsed_correctly(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica que body JSON string se parsea correctamente."""
        from tools.lambda_client import invoke_query_lambda
        
        inner_response = "Respuesta parseada"
        payload = BytesIO(json.dumps({
            "body": json.dumps(inner_response)  # JSON string dentro de body
        }).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_query_lambda(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == inner_response

    def test_non_json_body_returned_as_is(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica que body no-JSON se retorna como está."""
        from tools.lambda_client import invoke_query_lambda
        
        plain_response = "Respuesta de texto plano"
        payload = BytesIO(json.dumps({
            "body": plain_response
        }).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_query_lambda(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == plain_response

    def test_empty_body_returns_empty_string(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica manejo de respuesta vacía."""
        from tools.lambda_client import invoke_query_lambda
        
        payload = BytesIO(json.dumps({"body": ""}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_query_lambda(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == ""

    def test_response_without_body_key(self, mock_lambda_client, test_tenant_id, test_agent_id):
        """Verifica manejo cuando no hay key 'body' en la respuesta."""
        from tools.lambda_client import invoke_query_lambda
        
        response_data = {"other_key": "value", "another": 123}
        payload = BytesIO(json.dumps(response_data).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_query_lambda(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == str(response_data)


class TestInvokeEmbeddingsLambda:
    """Tests para invoke_embeddings_lambda."""

    def test_successful_embedding_returns_vector(self, mock_lambda_client):
        """Verifica que embeddings exitosos retornan el vector."""
        from tools.lambda_client import invoke_embeddings_lambda
        
        expected_embedding = [0.1, 0.2, 0.3, 0.4]
        payload = BytesIO(json.dumps({
            "body": json.dumps({"embedding": expected_embedding})
        }).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_embeddings_lambda("texto de prueba")
        
        assert result == expected_embedding

    def test_embedding_error_raises_runtime_error(self, mock_lambda_client):
        """Verifica que errores de Lambda embeddings lanzan RuntimeError."""
        from tools.lambda_client import invoke_embeddings_lambda
        
        error_msg = "Embedding generation failed"
        payload = BytesIO(json.dumps({"errorMessage": error_msg}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        with pytest.raises(RuntimeError) as exc_info:
            invoke_embeddings_lambda("texto")
        
        assert error_msg in str(exc_info.value)

    def test_empty_text_is_sent(self, mock_lambda_client):
        """Verifica que texto vacío se envía correctamente."""
        from tools.lambda_client import invoke_embeddings_lambda
        
        payload = BytesIO(json.dumps({"body": {"embedding": []}}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        invoke_embeddings_lambda("")
        
        call_args = mock_lambda_client.invoke.call_args
        sent_payload = json.loads(call_args.kwargs["Payload"])
        assert sent_payload["text"] == ""

    def test_embedding_from_direct_response(self, mock_lambda_client):
        """Verifica extracción de embedding sin key 'body'."""
        from tools.lambda_client import invoke_embeddings_lambda
        
        expected_embedding = [0.5, 0.6, 0.7]
        payload = BytesIO(json.dumps({"embedding": expected_embedding}).encode())
        mock_lambda_client.invoke.return_value = {"Payload": payload}
        
        result = invoke_embeddings_lambda("texto")
        
        assert result == expected_embedding

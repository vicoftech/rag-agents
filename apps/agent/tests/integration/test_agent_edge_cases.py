"""
Tests de edge cases para el flujo de integración del agente
"""
import pytest
import json
from io import BytesIO
from unittest.mock import patch, MagicMock


class TestAgentEdgeCasesNoInformation:
    """Tests cuando no hay información disponible."""

    @patch("tools.lambda_client.lambda_client")
    def test_kb_returns_no_info_message(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica respuesta cuando KB no tiene información."""
        from tools import knowledge_base_search
        
        # Lambda retorna respuesta indicando que no hay info
        no_info_response = "No se encontró información relacionada con tu consulta en la base de conocimiento."
        payload = BytesIO(json.dumps({"body": no_info_response}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="algo que no existe",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "No se encontró información" in result

    @patch("tools.web_search.bedrock_agent")
    def test_web_search_no_results(self, mock_bedrock):
        """Verifica respuesta cuando web search no encuentra nada."""
        from tools import web_search
        
        mock_bedrock.retrieve.return_value = {"retrievalResults": []}
        
        result = web_search(query="xyznonexistent12345")
        
        assert "No se encontraron resultados" in result

    @patch("tools.web_search.bedrock_agent")
    @patch("tools.lambda_client.lambda_client")
    def test_both_sources_return_no_info(self, mock_lambda, mock_bedrock, test_tenant_id, test_agent_id):
        """Verifica cuando ambas fuentes no tienen información."""
        from tools import knowledge_base_search, web_search
        
        # KB sin info
        payload = BytesIO(json.dumps({"body": ""}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        # Web sin resultados
        mock_bedrock.retrieve.return_value = {"retrievalResults": []}
        
        kb_result = knowledge_base_search(
            query="nonexistent",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        web_result = web_search(query="nonexistent")
        
        assert "No se encontró información" in kb_result
        assert "No se encontraron resultados" in web_result


class TestAgentEdgeCasesErrors:
    """Tests de manejo de errores."""

    @patch("tools.lambda_client.lambda_client")
    def test_lambda_timeout_handled_gracefully(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de timeout de Lambda."""
        from tools import knowledge_base_search
        
        mock_lambda.invoke.side_effect = Exception("Task timed out after 30 seconds")
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error al consultar" in result
        assert "timed out" in result

    @patch("tools.lambda_client.lambda_client")
    def test_lambda_throttling_handled(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de throttling de Lambda."""
        from tools import knowledge_base_search
        
        mock_lambda.invoke.side_effect = Exception("Rate exceeded")
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error al consultar" in result

    @patch("tools.web_search.bedrock_agent")
    def test_bedrock_service_unavailable(self, mock_bedrock):
        """Verifica manejo de servicio Bedrock no disponible."""
        from tools import web_search
        
        mock_bedrock.retrieve.side_effect = Exception("Service unavailable")
        
        result = web_search(query="test")
        
        assert "Error al buscar en internet" in result

    @patch("tools.lambda_client.lambda_client")
    def test_malformed_lambda_response_handled(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de respuesta malformada de Lambda."""
        from tools import knowledge_base_search
        
        # Respuesta no JSON
        payload = BytesIO(b"not valid json")
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error" in result

    @patch("tools.lambda_client.lambda_client")
    def test_lambda_internal_error(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de error interno de Lambda."""
        from tools import knowledge_base_search
        
        error_payload = BytesIO(json.dumps({
            "errorMessage": "Internal server error",
            "errorType": "InternalError"
        }).encode())
        mock_lambda.invoke.return_value = {"Payload": error_payload}
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error" in result


class TestAgentEdgeCasesInputValidation:
    """Tests de validación de entrada."""

    @patch("tools.lambda_client.lambda_client")
    def test_empty_query_handled(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de query vacío."""
        from tools import knowledge_base_search
        
        payload = BytesIO(json.dumps({"body": ""}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        # Debe manejar graciosamente
        assert result is not None

    @patch("tools.lambda_client.lambda_client")
    def test_very_long_query(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de query extremadamente largo."""
        from tools import knowledge_base_search
        
        payload = BytesIO(json.dumps({"body": "response"}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        long_query = "a" * 100000  # 100k caracteres
        
        result = knowledge_base_search(
            query=long_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        # Debe funcionar o manejar el error
        assert result is not None

    @patch("tools.lambda_client.lambda_client")
    def test_injection_attempt_in_query(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica que intentos de inyección se manejan."""
        from tools import knowledge_base_search
        
        payload = BytesIO(json.dumps({"body": "safe response"}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        # Intento de inyección SQL-like
        malicious_query = "'; DROP TABLE documents; --"
        
        result = knowledge_base_search(
            query=malicious_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        # La query debe pasar como texto normal
        assert result is not None

    @patch("tools.lambda_client.lambda_client")
    def test_special_tenant_id(self, mock_lambda, test_agent_id):
        """Verifica manejo de tenant_id con caracteres especiales."""
        from tools import knowledge_base_search
        
        payload = BytesIO(json.dumps({"body": "response"}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="test",
            tenant_id="tenant_with-special.chars_123",
            agent_id=test_agent_id
        )
        
        assert result is not None


class TestAgentEdgeCasesLargeResponses:
    """Tests con respuestas grandes."""

    @patch("tools.lambda_client.lambda_client")
    def test_very_large_kb_response(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica manejo de respuestas muy grandes de KB."""
        from tools import knowledge_base_search
        
        # Respuesta de 1MB
        large_response = "x" * (1024 * 1024)
        payload = BytesIO(json.dumps({"body": large_response}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == large_response

    @patch("tools.web_search.bedrock_agent")
    def test_many_web_results(self, mock_bedrock):
        """Verifica manejo de muchos resultados web."""
        from tools import web_search
        
        # 100 resultados
        results = [
            {
                "content": {"text": f"Result {i}"},
                "location": {"webLocation": {"url": f"https://example{i}.com"}}
            }
            for i in range(100)
        ]
        mock_bedrock.retrieve.return_value = {"retrievalResults": results}
        
        result = web_search(query="test", max_results=100)
        
        assert "[1]" in result
        assert "[100]" in result


class TestAgentEdgeCasesConcurrency:
    """Tests de escenarios de concurrencia."""

    @patch("tools.lambda_client.lambda_client")
    def test_multiple_sequential_calls(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica múltiples llamadas secuenciales."""
        from tools import knowledge_base_search
        
        responses = ["response1", "response2", "response3"]
        payloads = [
            BytesIO(json.dumps({"body": r}).encode())
            for r in responses
        ]
        mock_lambda.invoke.side_effect = [{"Payload": p} for p in payloads]
        
        results = []
        for i in range(3):
            result = knowledge_base_search(
                query=f"query{i}",
                tenant_id=test_tenant_id,
                agent_id=test_agent_id
            )
            results.append(result)
        
        assert results == responses

    @patch("tools.web_search.bedrock_agent")
    @patch("tools.lambda_client.lambda_client")
    def test_alternating_tool_calls(self, mock_lambda, mock_bedrock, test_tenant_id, test_agent_id):
        """Verifica llamadas alternadas a diferentes tools."""
        from tools import knowledge_base_search, web_search
        
        # Setup KB mock - usar side_effect para generar nuevo BytesIO cada vez
        def create_kb_response(*args, **kwargs):
            return {"Payload": BytesIO(json.dumps({"body": "kb"}).encode())}
        
        mock_lambda.invoke.side_effect = create_kb_response
        
        # Setup web mock
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": "web"}, "location": {"webLocation": {"url": "https://x.com"}}}
            ]
        }
        
        # Llamadas alternadas
        r1 = knowledge_base_search(query="q1", tenant_id=test_tenant_id, agent_id=test_agent_id)
        r2 = web_search(query="q2")
        r3 = knowledge_base_search(query="q3", tenant_id=test_tenant_id, agent_id=test_agent_id)
        r4 = web_search(query="q4")
        
        assert r1 == "kb"
        assert "web" in r2
        assert r3 == "kb"
        assert "web" in r4

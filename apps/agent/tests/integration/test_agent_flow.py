"""
Tests de integración para el flujo completo del agente
"""
import pytest
import json
from io import BytesIO
from unittest.mock import patch, MagicMock


class TestAgentFullFlow:
    """Tests del flujo completo del agente."""

    @pytest.fixture
    def mock_all_external_services(self):
        """Mock de todos los servicios externos."""
        with patch("tools.lambda_client.lambda_client") as mock_lambda, \
             patch("tools.web_search.bedrock_agent") as mock_bedrock, \
             patch("strands.Agent") as mock_agent_class:
            yield {
                "lambda": mock_lambda,
                "bedrock": mock_bedrock,
                "agent_class": mock_agent_class
            }

    @pytest.fixture
    def mock_strands_agent(self):
        """Mock del agente Strands."""
        with patch("agent.Agent") as mock_agent_class:
            mock_agent_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.message = "Respuesta del agente"
            mock_agent_instance.return_value = mock_response
            mock_agent_class.return_value = mock_agent_instance
            yield mock_agent_class, mock_agent_instance

    def test_create_agent_returns_agent_instance(self):
        """Verifica que create_agent retorna una instancia de agente."""
        with patch("agent.Agent") as mock_agent_class:
            from agent import create_agent
            
            mock_agent_class.return_value = MagicMock()
            
            agent = create_agent()
            
            mock_agent_class.assert_called_once()
            assert agent is not None

    def test_create_agent_has_correct_tools(self):
        """Verifica que el agente se crea con las tools correctas."""
        with patch("agent.Agent") as mock_agent_class:
            from agent import create_agent
            from tools import knowledge_base_search, web_search
            
            create_agent()
            
            call_kwargs = mock_agent_class.call_args.kwargs
            tools = call_kwargs.get("tools", [])
            
            # Verificar que las tools están incluidas
            assert knowledge_base_search in tools
            assert web_search in tools

    def test_run_agent_builds_correct_context(self):
        """Verifica que run_agent construye el contexto correctamente."""
        with patch("agent.Agent") as mock_agent_class:
            from agent import run_agent
            
            mock_agent_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.message = "response"
            mock_agent_instance.return_value = mock_response
            mock_agent_class.return_value = mock_agent_instance
            
            run_agent(
                query="test query",
                tenant_id="my_tenant",
                agent_id="my_agent"
            )
            
            # Verificar el prompt enviado al agente
            call_args = mock_agent_instance.call_args[0][0]
            assert "tenant_id: my_tenant" in call_args
            assert "agent_id: my_agent" in call_args
            assert "test query" in call_args

    def test_run_agent_returns_message(self):
        """Verifica que run_agent retorna el mensaje del agente."""
        with patch("agent.Agent") as mock_agent_class:
            from agent import run_agent
            
            expected_message = "Esta es la respuesta del agente"
            mock_agent_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.message = expected_message
            mock_agent_instance.return_value = mock_response
            mock_agent_class.return_value = mock_agent_instance
            
            result = run_agent(
                query="test",
                tenant_id="tenant",
                agent_id="agent"
            )
            
            assert result == expected_message


class TestAgentWithKnowledgeBase:
    """Tests de integración del agente con búsqueda en KB."""

    @patch("tools.lambda_client.lambda_client")
    def test_knowledge_base_tool_invoked_correctly(self, mock_lambda, test_tenant_id, test_agent_id):
        """Verifica que la tool de KB invoca la lambda correctamente."""
        from tools import knowledge_base_search
        
        # Configurar respuesta de lambda
        response_body = "Información de la base de conocimiento"
        payload = BytesIO(json.dumps({"body": response_body}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == response_body
        mock_lambda.invoke.assert_called_once()

    @patch("tools.lambda_client.lambda_client")
    def test_knowledge_base_with_document_filter(self, mock_lambda, test_tenant_id, test_agent_id, test_document_id):
        """Verifica búsqueda filtrada por documento."""
        from tools import knowledge_base_search
        
        payload = BytesIO(json.dumps({"body": "response"}).encode())
        mock_lambda.invoke.return_value = {"Payload": payload}
        
        knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id,
            document_id=test_document_id
        )
        
        # Verificar que document_id se envió en el payload
        call_args = mock_lambda.invoke.call_args
        sent_payload = json.loads(call_args.kwargs["Payload"])
        assert sent_payload["document_id"] == test_document_id


class TestAgentWithWebSearch:
    """Tests de integración del agente con búsqueda web."""

    @patch("tools.web_search.bedrock_agent")
    def test_web_search_tool_formats_results(self, mock_bedrock):
        """Verifica que web search formatea los resultados correctamente."""
        from tools import web_search
        
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "AWS Lambda es un servicio serverless"},
                    "location": {"webLocation": {"url": "https://aws.amazon.com/lambda"}}
                }
            ]
        }
        
        result = web_search(query="AWS Lambda")
        
        assert "AWS Lambda es un servicio serverless" in result
        assert "https://aws.amazon.com/lambda" in result
        assert "[1]" in result


class TestAgentToolsCombination:
    """Tests de combinación de tools."""

    @patch("tools.web_search.bedrock_agent")
    @patch("tools.lambda_client.lambda_client")
    def test_both_tools_can_be_called_sequentially(self, mock_lambda, mock_bedrock, test_tenant_id, test_agent_id):
        """Verifica que ambas tools pueden llamarse secuencialmente."""
        from tools import knowledge_base_search, web_search
        
        # Configurar KB response
        kb_payload = BytesIO(json.dumps({"body": "KB response"}).encode())
        mock_lambda.invoke.return_value = {"Payload": kb_payload}
        
        # Configurar web search response
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": "Web result"}, "location": {"webLocation": {"url": "https://test.com"}}}
            ]
        }
        
        # Llamar ambas tools
        kb_result = knowledge_base_search(
            query="arquitectura",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        web_result = web_search(query="best practices arquitectura")
        
        assert kb_result == "KB response"
        assert "Web result" in web_result
        assert mock_lambda.invoke.called
        assert mock_bedrock.retrieve.called

    @patch("tools.web_search.bedrock_agent")
    @patch("tools.lambda_client.lambda_client")
    def test_kb_failure_does_not_affect_web_search(self, mock_lambda, mock_bedrock):
        """Verifica que fallo en KB no afecta web search."""
        from tools import knowledge_base_search, web_search
        
        # KB falla
        mock_lambda.invoke.side_effect = Exception("Lambda timeout")
        
        # Web search funciona
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": "Web works"}, "location": {"webLocation": {"url": "https://ok.com"}}}
            ]
        }
        
        kb_result = knowledge_base_search(
            query="test",
            tenant_id="t",
            agent_id="a"
        )
        web_result = web_search(query="test")
        
        assert "Error" in kb_result
        assert "Web works" in web_result

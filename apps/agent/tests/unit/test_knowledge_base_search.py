"""
Tests unitarios para la tool knowledge_base_search (rag_search.py)
"""
import pytest
from unittest.mock import patch, MagicMock


class TestKnowledgeBaseSearch:
    """Tests para knowledge_base_search tool."""

    @patch("tools.rag_search.invoke_query_lambda")
    def test_successful_search_returns_response(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica que una búsqueda exitosa retorna la respuesta."""
        from tools.rag_search import knowledge_base_search
        
        expected_response = "Información encontrada en la base de conocimiento."
        mock_invoke.return_value = expected_response
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == expected_response

    @patch("tools.rag_search.invoke_query_lambda")
    def test_empty_response_returns_not_found_message(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica mensaje cuando la respuesta está vacía."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = ""
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "No se encontró información relevante" in result

    @patch("tools.rag_search.invoke_query_lambda")
    def test_none_response_returns_not_found_message(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica mensaje cuando la respuesta es None."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = None
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "No se encontró información relevante" in result

    @patch("tools.rag_search.invoke_query_lambda")
    def test_exception_returns_error_message(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica que excepciones retornan mensaje de error."""
        from tools.rag_search import knowledge_base_search
        
        error_msg = "Connection timeout"
        mock_invoke.side_effect = Exception(error_msg)
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error al consultar la base de conocimiento" in result
        assert error_msg in result

    @patch("tools.rag_search.invoke_query_lambda")
    def test_runtime_error_returns_error_message(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica que RuntimeError de lambda se maneja correctamente."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.side_effect = RuntimeError("Lambda invocation failed")
        
        result = knowledge_base_search(
            query="test query",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "Error al consultar" in result
        assert "Lambda invocation failed" in result

    @patch("tools.rag_search.invoke_query_lambda")
    def test_document_id_passed_to_lambda(self, mock_invoke, test_tenant_id, test_agent_id, test_document_id):
        """Verifica que document_id se pasa a la lambda."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = "response"
        
        knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id,
            document_id=test_document_id
        )
        
        mock_invoke.assert_called_once_with(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id,
            document_id=test_document_id
        )

    @patch("tools.rag_search.invoke_query_lambda")
    def test_document_id_none_passed_to_lambda(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica que document_id=None se pasa correctamente."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = "response"
        
        knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        mock_invoke.assert_called_once_with(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id,
            document_id=None
        )


class TestKnowledgeBaseSearchEdgeCases:
    """Tests de edge cases para knowledge_base_search."""

    @patch("tools.rag_search.invoke_query_lambda")
    def test_very_long_query(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica manejo de queries muy largos."""
        from tools.rag_search import knowledge_base_search
        
        long_query = "palabra " * 10000  # Query muy largo
        mock_invoke.return_value = "response"
        
        result = knowledge_base_search(
            query=long_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == "response"
        mock_invoke.assert_called_once()

    @patch("tools.rag_search.invoke_query_lambda")
    def test_special_characters_in_query(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica manejo de caracteres especiales en query."""
        from tools.rag_search import knowledge_base_search
        
        special_query = "¿Qué pasa con 'comillas' y \"dobles\" y símbolos @#$%?"
        mock_invoke.return_value = "response"
        
        result = knowledge_base_search(
            query=special_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == "response"

    @patch("tools.rag_search.invoke_query_lambda")
    def test_unicode_in_query(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica manejo de unicode en query."""
        from tools.rag_search import knowledge_base_search
        
        unicode_query = "¿Cómo funciona 日本語 y émojis 🚀?"
        mock_invoke.return_value = "response"
        
        result = knowledge_base_search(
            query=unicode_query,
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == "response"

    @patch("tools.rag_search.invoke_query_lambda")
    def test_whitespace_only_query(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica manejo de query solo con espacios."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = ""
        
        result = knowledge_base_search(
            query="   ",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert "No se encontró información" in result

    @patch("tools.rag_search.invoke_query_lambda")
    def test_newlines_in_response(self, mock_invoke, test_tenant_id, test_agent_id):
        """Verifica que respuestas con saltos de línea se manejan bien."""
        from tools.rag_search import knowledge_base_search
        
        multi_line_response = """Línea 1
        Línea 2
        Línea 3"""
        mock_invoke.return_value = multi_line_response
        
        result = knowledge_base_search(
            query="test",
            tenant_id=test_tenant_id,
            agent_id=test_agent_id
        )
        
        assert result == multi_line_response

    @patch("tools.rag_search.invoke_query_lambda")
    def test_special_tenant_id_characters(self, mock_invoke, test_agent_id):
        """Verifica tenant_id con caracteres especiales."""
        from tools.rag_search import knowledge_base_search
        
        mock_invoke.return_value = "response"
        
        # Tenant con guiones y números
        result = knowledge_base_search(
            query="test",
            tenant_id="tenant-123-test",
            agent_id=test_agent_id
        )
        
        assert result == "response"

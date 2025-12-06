"""
Tests unitarios para la tool web_search
"""
import pytest
from unittest.mock import patch, MagicMock


class TestWebSearch:
    """Tests para web_search tool."""

    @patch("tools.web_search.bedrock_agent")
    def test_successful_search_returns_formatted_results(self, mock_bedrock, mock_web_search_results):
        """Verifica que búsqueda exitosa retorna resultados formateados."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        result = web_search(query="test query")
        
        assert "[1]" in result
        assert "[2]" in result
        assert "Contenido del resultado 1" in result
        assert "https://example.com/1" in result

    @patch("tools.web_search.bedrock_agent")
    def test_empty_results_returns_not_found_message(self, mock_bedrock, mock_web_search_empty):
        """Verifica mensaje cuando no hay resultados."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_empty
        
        result = web_search(query="test query")
        
        assert "No se encontraron resultados" in result
        assert "test query" in result

    @patch("tools.web_search.bedrock_agent")
    def test_max_results_parameter_passed(self, mock_bedrock, mock_web_search_results):
        """Verifica que max_results se pasa correctamente."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        web_search(query="test", max_results=10)
        
        call_args = mock_bedrock.retrieve.call_args
        config = call_args.kwargs["retrievalConfiguration"]
        assert config["vectorSearchConfiguration"]["numberOfResults"] == 10

    @patch("tools.web_search.bedrock_agent")
    def test_default_max_results_is_5(self, mock_bedrock, mock_web_search_results):
        """Verifica que max_results por defecto es 5."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        web_search(query="test")
        
        call_args = mock_bedrock.retrieve.call_args
        config = call_args.kwargs["retrievalConfiguration"]
        assert config["vectorSearchConfiguration"]["numberOfResults"] == 5

    @patch("tools.web_search.bedrock_agent")
    def test_websearch_not_configured_error(self, mock_bedrock):
        """Verifica mensaje cuando web search no está configurado."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.side_effect = Exception("knowledgeBaseId WEBSEARCH not found")
        
        result = web_search(query="test")
        
        assert "búsqueda web no está configurada" in result

    @patch("tools.web_search.bedrock_agent")
    def test_generic_error_returns_error_message(self, mock_bedrock):
        """Verifica manejo de errores genéricos."""
        from tools.web_search import web_search
        
        error_msg = "Network connection failed"
        mock_bedrock.retrieve.side_effect = Exception(error_msg)
        
        result = web_search(query="test")
        
        assert "Error al buscar en internet" in result
        assert error_msg in result

    @patch("tools.web_search.bedrock_agent")
    def test_missing_url_shows_unknown_source(self, mock_bedrock):
        """Verifica manejo cuando URL no está disponible."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Contenido sin URL"},
                    "location": {}
                }
            ]
        }
        
        result = web_search(query="test")
        
        assert "Fuente desconocida" in result

    @patch("tools.web_search.bedrock_agent")
    def test_missing_content_handled(self, mock_bedrock):
        """Verifica manejo cuando content está vacío."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {},
                    "location": {"webLocation": {"url": "https://example.com"}}
                }
            ]
        }
        
        result = web_search(query="test")
        
        assert "https://example.com" in result


class TestWebSearchEdgeCases:
    """Tests de edge cases para web_search."""

    @patch("tools.web_search.bedrock_agent")
    def test_very_long_query(self, mock_bedrock, mock_web_search_results):
        """Verifica manejo de queries muy largos."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        long_query = "búsqueda " * 1000
        
        result = web_search(query=long_query)
        
        assert "[1]" in result  # Debe funcionar normalmente

    @patch("tools.web_search.bedrock_agent")
    def test_special_characters_in_query(self, mock_bedrock, mock_web_search_results):
        """Verifica manejo de caracteres especiales."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        result = web_search(query="¿Qué es @#$%^&*() en Python?")
        
        assert "[1]" in result

    @patch("tools.web_search.bedrock_agent")
    def test_unicode_query(self, mock_bedrock, mock_web_search_results):
        """Verifica manejo de unicode en query."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        result = web_search(query="日本語 검색 🔍")
        
        assert "[1]" in result

    @patch("tools.web_search.bedrock_agent")
    def test_max_results_zero(self, mock_bedrock):
        """Verifica comportamiento con max_results=0."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = {"retrievalResults": []}
        
        result = web_search(query="test", max_results=0)
        
        assert "No se encontraron resultados" in result

    @patch("tools.web_search.bedrock_agent")
    def test_max_results_large_number(self, mock_bedrock, mock_web_search_results):
        """Verifica manejo de max_results muy grande."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = mock_web_search_results
        
        web_search(query="test", max_results=1000)
        
        call_args = mock_bedrock.retrieve.call_args
        config = call_args.kwargs["retrievalConfiguration"]
        assert config["vectorSearchConfiguration"]["numberOfResults"] == 1000

    @patch("tools.web_search.bedrock_agent")
    def test_results_separator_format(self, mock_bedrock):
        """Verifica el formato de separación entre resultados."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Resultado 1"},
                    "location": {"webLocation": {"url": "https://a.com"}}
                },
                {
                    "content": {"text": "Resultado 2"},
                    "location": {"webLocation": {"url": "https://b.com"}}
                }
            ]
        }
        
        result = web_search(query="test")
        
        assert "\n\n---\n\n" in result

    @patch("tools.web_search.bedrock_agent")
    def test_single_result_no_separator(self, mock_bedrock):
        """Verifica que un solo resultado no tiene separador."""
        from tools.web_search import web_search
        
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Único resultado"},
                    "location": {"webLocation": {"url": "https://solo.com"}}
                }
            ]
        }
        
        result = web_search(query="test")
        
        assert "---" not in result
        assert "Único resultado" in result

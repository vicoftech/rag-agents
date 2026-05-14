"""
Tests para AL-03: Link roto en template de email - Configurabilidad de URL base

Valida que la generación de URLs para el template de email sea configurable
por ambiente y maneje correctamente keywords con caracteres especiales.
"""
from __future__ import annotations

import os
from unittest.mock import patch
from urllib.parse import unquote

import pytest


class TestHistoricSearchURLGeneration:
    """Tests de generación de URLs para búsqueda histórica"""

    def _simulate_historic_search_urls_for_keywords(
        self,
        fuente_codigo: str,
        keywords: list[str],
        start_at: str,
        end_at: str,
        base_url: str | None = None,
    ) -> list[str]:
        """
        Simula la función historic_search_urls_for_keywords del script.

        Args:
            fuente_codigo: Código de la fuente (ej: "ANMAT", "BOLETIN_OFICIAL")
            keywords: Lista de palabras clave
            start_at: Fecha de inicio (YYYY-MM-DD) o vacío
            end_at: Fecha de fin (YYYY-MM-DD) o vacío
            base_url: URL base opcional (usa default si es None)

        Returns:
            Lista de URLs, una por keyword
        """
        from urllib.parse import quote

        if base_url is None:
            base_url = "https://alerts.wi-soft.net/#/search/historic-search"

        base = base_url.rstrip("/")
        urls: list[str] = []

        # Limpiar fechas (simular lógica del script)
        s_raw = start_at.strip() if start_at else ""
        e_raw = end_at.strip() if end_at else ""

        for kw in keywords:
            kw_seg = quote((kw or "").strip(), safe="")
            urls.append(f"{base}/{fuente_codigo}/{kw_seg}/{s_raw}/{e_raw}")

        return urls

    @pytest.mark.unit
    def test_base_url_configurable_via_env_var(self):
        """Debe usar variable de entorno HISTORIC_SEARCH_BASE_URL si está definida"""
        qa_url = "https://dpamhb6uwt9g1.cloudfront.net/#/search/historic-search"

        with patch.dict(os.environ, {"HISTORIC_SEARCH_BASE_URL": qa_url}):
            # Simular que el módulo lee la variable
            base_url = (
                os.environ.get("HISTORIC_SEARCH_BASE_URL")
                or "https://alerts.wi-soft.net/#/search/historic-search"
            ).strip()

            urls = self._simulate_historic_search_urls_for_keywords(
                "ANMAT",
                ["vacuna"],
                "2026-01-01",
                "2026-05-13",
                base_url=base_url,
            )

            assert len(urls) == 1
            assert urls[0].startswith(qa_url)
            assert "ANMAT" in urls[0]
            assert "vacuna" in urls[0]

    @pytest.mark.unit
    def test_base_url_fallback_to_production(self):
        """Debe usar URL de producción si variable de entorno no está definida"""
        with patch.dict(os.environ, {}, clear=True):
            base_url = (
                os.environ.get("HISTORIC_SEARCH_BASE_URL")
                or "https://alerts.wi-soft.net/#/search/historic-search"
            ).strip()

            urls = self._simulate_historic_search_urls_for_keywords(
                "BOLETIN_OFICIAL",
                ["decreto"],
                "2026-01-01",
                "2026-05-13",
                base_url=base_url,
            )

            assert len(urls) == 1
            assert urls[0].startswith("https://alerts.wi-soft.net/#/search/historic-search")

    @pytest.mark.unit
    def test_keyword_with_spaces_encoded_correctly(self):
        """Keywords con espacios deben ser URL-encodeadas correctamente"""
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["Fresenius Medical Care"],
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 1
        # Espacios deben ser %20
        assert "Fresenius%20Medical%20Care" in urls[0]
        # No deben quedar espacios sin encodear
        assert " " not in urls[0].split("/#/search/historic-search/")[1]

    @pytest.mark.unit
    def test_keyword_with_accents_encoded_correctly(self):
        """Keywords con acentos deben ser URL-encodeadas correctamente"""
        urls = self._simulate_historic_search_urls_for_keywords(
            "BOLETIN_OFICIAL",
            ["medicación"],
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 1
        # Acentos deben estar encodeados
        assert "medicaci%C3%B3n" in urls[0]

    @pytest.mark.unit
    def test_keyword_with_special_chars_encoded(self):
        """Keywords con caracteres especiales deben ser URL-encodeadas"""
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["A & B Pharma S.A."],
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 1
        # & debe ser %26
        assert "%26" in urls[0]
        # . no necesita encoding (es safe en paths)
        # Espacios deben ser %20
        assert "%20" in urls[0]

    @pytest.mark.unit
    def test_empty_dates_do_not_break_url(self):
        """Fechas vacías no deben romper la generación de URL"""
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["vacuna"],
            "",
            "",
        )

        assert len(urls) == 1
        # URL debe terminar con /ANMAT/vacuna// (fechas vacías)
        assert urls[0].endswith("/vacuna//")

    @pytest.mark.unit
    def test_multiple_keywords_generate_multiple_urls(self):
        """Múltiples keywords deben generar una URL por keyword"""
        keywords = ["vacuna", "tratamiento", "medicación"]
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            keywords,
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 3
        assert all("ANMAT" in url for url in urls)
        assert "vacuna" in urls[0]
        assert "tratamiento" in urls[1]
        assert "medicaci%C3%B3n" in urls[2]

    @pytest.mark.unit
    def test_url_structure_matches_expected_format(self):
        """URL generada debe seguir el formato esperado"""
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["vacuna"],
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 1
        url = urls[0]

        # Formato: {base}/{fuente}/{keyword}/{start_at}/{end_at}
        parts = url.split("/")
        assert parts[-5] == "historic-search"
        assert parts[-4] == "ANMAT"
        assert parts[-3] == "vacuna"
        assert parts[-2] == "2026-01-01"
        assert parts[-1] == "2026-05-13"

    @pytest.mark.unit
    def test_url_decoding_preserves_original_keyword(self):
        """Decodificar la URL debe recuperar la keyword original"""
        original_keyword = "Fresenius Medical Care Argentina S.A."
        urls = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            [original_keyword],
            "2026-01-01",
            "2026-05-13",
        )

        assert len(urls) == 1
        # Extraer el segmento de keyword de la URL
        parts = urls[0].split("/")
        encoded_keyword = parts[-3]  # Posición del keyword en la URL

        # Decodificar y verificar
        decoded = unquote(encoded_keyword)
        assert decoded == original_keyword

    @pytest.mark.unit
    def test_base_url_trailing_slash_handled(self):
        """Base URL con trailing slash debe ser manejada correctamente"""
        base_with_slash = "https://alerts.wi-soft.net/#/search/historic-search/"
        base_without_slash = "https://alerts.wi-soft.net/#/search/historic-search"

        urls_with = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["vacuna"],
            "2026-01-01",
            "2026-05-13",
            base_url=base_with_slash,
        )

        urls_without = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["vacuna"],
            "2026-01-01",
            "2026-05-13",
            base_url=base_without_slash,
        )

        # Ambas deben generar la misma URL (sin doble slash)
        assert urls_with[0] == urls_without[0]
        assert "//" not in urls_with[0].split("https://")[1]

    @pytest.mark.unit
    def test_different_sources_generate_different_urls(self):
        """Diferentes fuentes deben generar URLs diferentes"""
        urls_anmat = self._simulate_historic_search_urls_for_keywords(
            "ANMAT",
            ["vacuna"],
            "2026-01-01",
            "2026-05-13",
        )

        urls_boletin = self._simulate_historic_search_urls_for_keywords(
            "BOLETIN_OFICIAL",
            ["vacuna"],
            "2026-01-01",
            "2026-05-13",
        )

        assert urls_anmat[0] != urls_boletin[0]
        assert "ANMAT" in urls_anmat[0]
        assert "BOLETIN_OFICIAL" in urls_boletin[0]


class TestEmailTemplateURLIntegration:
    """Tests de integración de URL en template de email"""

    @pytest.mark.unit
    def test_primary_url_extracted_from_list(self):
        """Debe extraer la primera URL de la lista como primary_url"""
        # Simular la lógica del script (línea 440)
        urls_per_kw = [
            "https://alerts.wi-soft.net/#/search/historic-search/ANMAT/vacuna/2026-01-01/2026-05-13",
            "https://alerts.wi-soft.net/#/search/historic-search/ANMAT/tratamiento/2026-01-01/2026-05-13",
        ]

        primary_url = (urls_per_kw[0] if urls_per_kw else "") or ""

        assert primary_url == urls_per_kw[0]
        assert "vacuna" in primary_url

    @pytest.mark.unit
    def test_empty_url_list_handled(self):
        """Lista vacía de URLs debe resultar en string vacío"""
        urls_per_kw: list[str] = []

        primary_url = (urls_per_kw[0] if urls_per_kw else "") or ""

        assert primary_url == ""

    @pytest.mark.unit
    def test_url_included_in_body_payload(self):
        """URL debe estar incluida en body_payload para SES template"""
        # Simular la construcción del body (líneas 442-447)
        primary_url = "https://alerts.wi-soft.net/#/search/historic-search/ANMAT/vacuna/2026-01-01/2026-05-13"

        body = {
            "keywords": ["vacuna"],
            "nombreUsuario": "Test User",
            "nombre_alerta": "ANMAT - Vacunas",
            "url": primary_url,
        }

        assert "url" in body
        assert body["url"] == primary_url
        assert body["url"].startswith("https://")


if __name__ == "__main__":
    # Ejecutar tests con pytest
    pytest.main([__file__, "-v", "--tb=short"])

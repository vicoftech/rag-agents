from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from datetime import date


def _install_stubs():
    """Instala stubs para dependencias no disponibles en tests."""
    if "boto3" not in sys.modules:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.client = lambda *args, **kwargs: object()
        boto3_stub.resource = lambda *args, **kwargs: types.SimpleNamespace(Table=lambda *_: object())
        sys.modules["boto3"] = boto3_stub

    if "botocore" not in sys.modules:
        sys.modules["botocore"] = types.ModuleType("botocore")
    if "botocore.exceptions" not in sys.modules:
        exceptions_stub = types.ModuleType("botocore.exceptions")
        exceptions_stub.ClientError = Exception
        sys.modules["botocore.exceptions"] = exceptions_stub

    if "psycopg2" not in sys.modules:
        psycopg2_stub = types.ModuleType("psycopg2")
        psycopg2_stub.connect = lambda *args, **kwargs: object()
        sys.modules["psycopg2"] = psycopg2_stub

    if "pgvector" not in sys.modules:
        sys.modules["pgvector"] = types.ModuleType("pgvector")
    if "pgvector.psycopg2" not in sys.modules:
        pgvector_psycopg2_stub = types.ModuleType("pgvector.psycopg2")
        pgvector_psycopg2_stub.register_vector = lambda *_args, **_kwargs: None
        sys.modules["pgvector.psycopg2"] = pgvector_psycopg2_stub


def _load_query_module():
    """Carga el módulo rag_lmbd_query con stubs."""
    _install_stubs()
    root = Path(__file__).resolve().parents[1]
    app_dir = root / "apps" / "rag_lmbd_query"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    module_path = app_dir / "index.py"
    spec = importlib.util.spec_from_file_location("rag_lmbd_query_bu04", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# --- Tests de extract_document_date() ---

def test_extract_document_date_anmat_aviso():
    """Extrae fecha de patrón ANMAT aviso: aviso_YYYY_YYYYMMDD_default_NNNNNN.pdf"""
    module = _load_query_module()

    assert module.extract_document_date("aviso_2010_20100601_default_035149.pdf") == date(2010, 6, 1)
    assert module.extract_document_date("aviso_2026_20260201_default_190914.pdf") == date(2026, 2, 1)
    assert module.extract_document_date("aviso_2011_20110315_default_123456.pdf") == date(2011, 3, 15)


def test_extract_document_date_boletin_oficial_with_path():
    """Extrae fecha de Boletín Oficial con path: YYYYMMDD/seccion/aviso_...pdf"""
    module = _load_query_module()

    assert module.extract_document_date("20260512/segunda/aviso_segunda_20260512_segunda_120233.pdf") == date(2026, 5, 12)
    assert module.extract_document_date("20260511/primera/aviso_primera_20260511_primera_120318.pdf") == date(2026, 5, 11)
    assert module.extract_document_date("20260310/tercera/aviso_tercera_20260310_tercera_999999.pdf") == date(2026, 3, 10)


def test_extract_document_date_boletin_oficial_without_path():
    """Extrae fecha de Boletín Oficial sin path: aviso_seccion_YYYYMMDD_...pdf"""
    module = _load_query_module()

    assert module.extract_document_date("aviso_primera_20260310_primera_131956.pdf") == date(2026, 3, 10)
    assert module.extract_document_date("reupload_aviso_primera_20260407.pdf") == date(2026, 4, 7)


def test_extract_document_date_dispo_anmat():
    """Extrae año de Dispo_NNNN-YY.pdf (solo año, menos preciso)"""
    module = _load_query_module()

    assert module.extract_document_date("Dispo_3618-24.pdf") == date(2024, 1, 1)
    assert module.extract_document_date("Dispo_3918-11.pdf") == date(2011, 1, 1)
    assert module.extract_document_date("Dispo_5875-23.pdf") == date(2023, 1, 1)
    # Case insensitive
    assert module.extract_document_date("dispo_3618-24.pdf") == date(2024, 1, 1)
    assert module.extract_document_date("DISPO_3918-11.PDF") == date(2011, 1, 1)


def test_extract_document_date_yyyy_mm_dd():
    """Extrae fecha de patrón YYYY-MM-DD con guiones"""
    module = _load_query_module()

    assert module.extract_document_date("informe_2026-05-15.pdf") == date(2026, 5, 15)
    assert module.extract_document_date("documento_2024-12-31.pdf") == date(2024, 12, 31)
    assert module.extract_document_date("reporte_2025-01-01_final.pdf") == date(2025, 1, 1)


def test_extract_document_date_with_query_string():
    """Limpia query strings antes de parsear"""
    module = _load_query_module()

    assert module.extract_document_date("20260511?anexos=1/primera/aviso_primera_20260511_primera_120318.pdf") == date(2026, 5, 11)
    assert module.extract_document_date("aviso_2026_20260515_default_123456.pdf?download=true") == date(2026, 5, 15)


def test_extract_document_date_invalid_date_returns_none():
    """Retorna None cuando la fecha es inválida (ej: mes 13, día 32)"""
    module = _load_query_module()

    # Mes 13, día 32
    assert module.extract_document_date("aviso_2026_20261332_default_123456.pdf") is None
    # Febrero 30
    assert module.extract_document_date("documento_20260230.pdf") is None
    # Año 9999 mes 99
    assert module.extract_document_date("archivo_99999999.pdf") is None


def test_extract_document_date_no_date_returns_none():
    """Retorna None cuando no hay fecha en el filename"""
    module = _load_query_module()

    assert module.extract_document_date("documento_sin_fecha.pdf") is None
    assert module.extract_document_date("informe_general.pdf") is None
    assert module.extract_document_date("readme.txt") is None
    assert module.extract_document_date("") is None
    assert module.extract_document_date(None) is None


def test_extract_document_date_edge_cases():
    """Casos edge: None, strings vacíos, tipos inválidos"""
    module = _load_query_module()

    assert module.extract_document_date(None) is None
    assert module.extract_document_date("") is None
    assert module.extract_document_date("   ") is None
    # Tipo inválido (número)
    assert module.extract_document_date(12345678) is None


def test_extract_document_date_priority_order():
    """Verifica que los patrones se aplican en orden de prioridad"""
    module = _load_query_module()

    # Patrón ANMAT aviso tiene prioridad sobre YYYYMMDD genérico
    # Si el filename tiene ambos, debe usar el del patrón aviso (segundo YYYYMMDD)
    result = module.extract_document_date("aviso_2010_20100601_default_035149.pdf")
    assert result == date(2010, 6, 1)  # Usa el segundo YYYYMMDD (20100601)

    # YYYYMMDD genérico tiene prioridad sobre YYYY-MM-DD
    result = module.extract_document_date("20260512_informe_2026-05-15.pdf")
    assert result == date(2026, 5, 12)  # Usa YYYYMMDD (20260512), no YYYY-MM-DD


def test_extract_document_date_real_world_samples():
    """Dataset de casos reales del sistema"""
    module = _load_query_module()

    # Casos reales de ANMAT
    assert module.extract_document_date("aviso_2010_20100601_default_035149.pdf") == date(2010, 6, 1)
    assert module.extract_document_date("aviso_2026_20260201_default_190914.pdf") == date(2026, 2, 1)

    # Casos reales de Boletín Oficial
    assert module.extract_document_date("20260512/segunda/aviso_segunda_20260512_segunda_120233.pdf") == date(2026, 5, 12)
    assert module.extract_document_date("20260512/primera/aviso_primera_20260512_primera_120149.pdf") == date(2026, 5, 12)
    assert module.extract_document_date("20260512/tercera/aviso_tercera_20260512_tercera_120148.pdf") == date(2026, 5, 12)

    # Casos reales de Disposiciones
    assert module.extract_document_date("Dispo_3618-24.pdf") == date(2024, 1, 1)
    assert module.extract_document_date("Dispo_3724-24.pdf") == date(2024, 1, 1)
    assert module.extract_document_date("Dispo_3304-24.pdf") == date(2024, 1, 1)

    # Caso real con query string
    assert module.extract_document_date("20260511?anexos=1/primera/aviso_primera_20260511?anexos=1_primera_120318.pdf") == date(2026, 5, 11)


# --- Tests de cobertura y estadísticas ---

def test_extraction_coverage_on_real_dataset():
    """Verifica que la cobertura de extracción sea >= 85% en dataset real"""
    module = _load_query_module()

    # Dataset de prueba basado en casos reales
    test_filenames = [
        # ANMAT Avisos
        "aviso_2010_20100601_default_035149.pdf",
        "aviso_2026_20260201_default_190914.pdf",
        # ANMAT Disposiciones
        "Dispo_3618-24.pdf",
        "Dispo_3918-11.pdf",
        "Dispo_5875-23.pdf",
        # Boletín Oficial con path
        "20260512/segunda/aviso_segunda_20260512_segunda_120233.pdf",
        "20260511/primera/aviso_primera_20260511_primera_120318.pdf",
        # Boletín Oficial sin path
        "aviso_primera_20260310_primera_131956.pdf",
        "reupload_aviso_primera_20260407.pdf",
        # Edge cases
        "20260511?anexos=1/primera/aviso_primera_20260511_primera_120318.pdf",
        "informe_2026-05-15.pdf",
        # Sin fecha (esperado None)
        "documento_sin_fecha.pdf",
    ]

    extracted = 0
    for filename in test_filenames:
        if module.extract_document_date(filename) is not None:
            extracted += 1

    coverage = (extracted / len(test_filenames)) * 100
    # 11 de 12 tienen fecha extraíble = 91.6%
    assert coverage >= 85, f"Cobertura {coverage:.1f}% es menor a 85% esperado"
    assert coverage >= 90, f"Cobertura {coverage:.1f}% debería ser >= 90%"


# --- Tests de validación de rangos ---

def test_date_range_validation():
    """Valida que las fechas estén en rangos razonables"""
    module = _load_query_module()

    # Fechas válidas en rango razonable (1990-2099)
    assert module.extract_document_date("aviso_2010_20100601_default_035149.pdf") == date(2010, 6, 1)
    assert module.extract_document_date("20260512/aviso_segunda_20260512.pdf") == date(2026, 5, 12)

    # Dispo con año fuera de rango siglo 21 (2000-2099)
    # Año 99 → 2099 (válido)
    assert module.extract_document_date("Dispo_1234-99.pdf") == date(2099, 1, 1)
    # Año 00 → 2000 (válido)
    assert module.extract_document_date("Dispo_1234-00.pdf") == date(2000, 1, 1)


def test_case_insensitive_matching():
    """Verifica que los patrones sean case-insensitive"""
    module = _load_query_module()

    # ANMAT aviso
    assert module.extract_document_date("AVISO_2010_20100601_DEFAULT_035149.PDF") == date(2010, 6, 1)
    assert module.extract_document_date("Aviso_2026_20260201_Default_190914.Pdf") == date(2026, 2, 1)

    # Dispo
    assert module.extract_document_date("DISPO_3618-24.PDF") == date(2024, 1, 1)
    assert module.extract_document_date("dispo_3918-11.pdf") == date(2011, 1, 1)


# --- Tests de integración (simulación de filtrado completo) ---

def test_date_filtering_logic_simulation():
    """
    Simula la lógica de filtrado BU-04 sin conectar a BD.
    Verifica que documentos fuera de rango se excluyan correctamente.
    """
    module = _load_query_module()

    # Simular matched_rows con (chunk_id, chunk_text, document_name, ...)
    mock_rows = [
        (1, "chunk 1", "aviso_2026_20260115_default_001.pdf", 0.1, 0.9, "doc-1", None),
        (2, "chunk 2", "aviso_2010_20100601_default_002.pdf", 0.2, 0.8, "doc-2", None),  # Fuera de rango
        (3, "chunk 3", "20260512/primera/aviso_primera_20260512.pdf", 0.15, 0.85, "doc-3", None),
        (4, "chunk 4", "Dispo_3618-24.pdf", 0.25, 0.75, "doc-4", None),  # 2024-01-01, fuera de rango
        (5, "chunk 5", "documento_sin_fecha.pdf", 0.3, 0.7, "doc-5", None),  # Sin fecha
    ]

    # Filtro: 2026-01-01 a 2026-06-01 (exclusivo)
    date_lo = date(2026, 1, 1)
    date_hi = date(2026, 6, 1)

    filtered_rows = []
    skipped_out_of_range = 0
    skipped_no_date = 0

    for row in mock_rows:
        doc_name = row[2]
        doc_date = module.extract_document_date(doc_name)

        if doc_date is None:
            filtered_rows.append(row)
            skipped_no_date += 1
        elif date_lo <= doc_date < date_hi:
            filtered_rows.append(row)
        else:
            skipped_out_of_range += 1

    # Verificar resultados
    assert len(filtered_rows) == 3  # Docs 1, 3 y 5 (dentro de rango + sin fecha)
    assert skipped_out_of_range == 2  # Docs 2 (2010) y 4 (2024)
    assert skipped_no_date == 1  # Doc 5 (sin fecha)

    # Verificar que los documentos correctos fueron incluidos
    included_names = [row[2] for row in filtered_rows]
    assert "aviso_2026_20260115_default_001.pdf" in included_names  # Dentro de rango
    assert "20260512/primera/aviso_primera_20260512.pdf" in included_names  # Dentro de rango
    assert "documento_sin_fecha.pdf" in included_names  # Sin fecha (incluido)
    assert "aviso_2010_20100601_default_002.pdf" not in included_names  # Fuera de rango
    assert "Dispo_3618-24.pdf" not in included_names  # Fuera de rango


def test_filtering_boundary_cases():
    """Verifica casos límite del filtrado (fechas en el borde del rango)"""
    module = _load_query_module()

    # Rango: 2026-01-01 a 2026-06-01 (exclusivo)
    date_lo = date(2026, 1, 1)
    date_hi = date(2026, 6, 1)

    # Fecha exactamente en el límite inferior (incluido)
    doc_date = module.extract_document_date("aviso_2026_20260101_default_001.pdf")
    assert doc_date == date(2026, 1, 1)
    assert date_lo <= doc_date < date_hi  # True (incluido)

    # Fecha exactamente en el límite superior (excluido)
    doc_date = module.extract_document_date("aviso_2026_20260601_default_002.pdf")
    assert doc_date == date(2026, 6, 1)
    assert not (date_lo <= doc_date < date_hi)  # False (excluido)

    # Fecha un día antes del límite inferior (excluido)
    doc_date = module.extract_document_date("aviso_2025_20251231_default_003.pdf")
    assert doc_date == date(2025, 12, 31)
    assert not (date_lo <= doc_date < date_hi)  # False (excluido)

    # Fecha un día antes del límite superior (incluido)
    doc_date = module.extract_document_date("aviso_2026_20260531_default_004.pdf")
    assert doc_date == date(2026, 5, 31)
    assert date_lo <= doc_date < date_hi  # True (incluido)


# --- Tests de regresión ---

def test_no_regression_on_existing_functionality():
    """Verifica que la función no rompa casos previamente funcionando"""
    module = _load_query_module()

    # Casos que ya funcionaban antes de BU-04
    assert module.extract_document_date("aviso_2010_20100601_default_035149.pdf") == date(2010, 6, 1)
    assert module.extract_document_date("20260512/segunda/aviso_segunda_20260512.pdf") == date(2026, 5, 12)

    # Casos None (no debe romper si se pasa None)
    assert module.extract_document_date(None) is None
    assert module.extract_document_date("") is None


if __name__ == "__main__":
    # Ejecutar tests manualmente
    print("Ejecutando tests de BU-04...")

    test_extract_document_date_anmat_aviso()
    print("✓ Test ANMAT aviso")

    test_extract_document_date_boletin_oficial_with_path()
    print("✓ Test Boletín Oficial con path")

    test_extract_document_date_boletin_oficial_without_path()
    print("✓ Test Boletín Oficial sin path")

    test_extract_document_date_dispo_anmat()
    print("✓ Test Dispo ANMAT")

    test_extract_document_date_yyyy_mm_dd()
    print("✓ Test YYYY-MM-DD")

    test_extract_document_date_with_query_string()
    print("✓ Test query strings")

    test_extract_document_date_invalid_date_returns_none()
    print("✓ Test fechas inválidas")

    test_extract_document_date_no_date_returns_none()
    print("✓ Test sin fecha")

    test_extract_document_date_edge_cases()
    print("✓ Test edge cases")

    test_extract_document_date_priority_order()
    print("✓ Test orden de prioridad")

    test_extract_document_date_real_world_samples()
    print("✓ Test casos reales")

    test_extraction_coverage_on_real_dataset()
    print("✓ Test cobertura >= 85%")

    test_date_range_validation()
    print("✓ Test validación de rangos")

    test_case_insensitive_matching()
    print("✓ Test case-insensitive")

    test_date_filtering_logic_simulation()
    print("✓ Test lógica de filtrado")

    test_filtering_boundary_cases()
    print("✓ Test casos límite")

    test_no_regression_on_existing_functionality()
    print("✓ Test no regresión")

    print("\n✅ Todos los tests pasaron exitosamente!")

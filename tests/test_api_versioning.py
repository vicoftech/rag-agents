from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


def _install_stubs():
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
    _install_stubs()
    root = Path(__file__).resolve().parents[1]
    app_dir = root / "apps" / "rag_lmbd_query"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    module_path = app_dir / "index.py"
    spec = importlib.util.spec_from_file_location("rag_lmbd_query_ver", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# =============================================================================
# _extract_version_from_path()
# =============================================================================

def test_extract_version_query_path_defaults_to_v1():
    module = _load_query_module()
    event = {
        "requestContext": {"http": {"path": "/query", "method": "POST"}},
        "httpMethod": "POST",
    }
    assert module._extract_version_from_path(event) == "v1"


def test_extract_version_v1_query_path():
    module = _load_query_module()
    event = {
        "requestContext": {"http": {"path": "/v1/query", "method": "POST"}},
    }
    assert module._extract_version_from_path(event) == "v1"


def test_extract_version_v2_query_path():
    module = _load_query_module()
    event = {
        "requestContext": {"http": {"path": "/v2/query", "method": "POST"}},
    }
    assert module._extract_version_from_path(event) == "v2"


def test_extract_version_raw_path_fallback():
    module = _load_query_module()
    event = {"rawPath": "/v2/query", "httpMethod": "POST"}
    assert module._extract_version_from_path(event) == "v2"


def test_extract_version_path_fallback():
    module = _load_query_module()
    event = {"path": "/v2/query", "httpMethod": "POST"}
    assert module._extract_version_from_path(event) == "v2"


def test_extract_version_no_path_returns_v1():
    module = _load_query_module()
    assert module._extract_version_from_path({}) == "v1"


def test_extract_version_unknown_version():
    module = _load_query_module()
    event = {"rawPath": "/v3/query"}
    assert module._extract_version_from_path(event) == "v3"


# =============================================================================
# _normalize_v2_body()
# =============================================================================

def test_normalize_v2_default_params():
    """TASK-399: retrieval_limit siempre es 100 (fetch completo)."""
    module = _load_query_module()
    body = {"query": "ibuprofeno"}
    result = module._normalize_v2_body(body)
    assert result["retrieval_limit"] == 100
    assert result["_page"] == 1
    assert result["_page_size"] == 10
    assert "sort_by" not in result


def test_normalize_v2_custom_page_and_page_size():
    """TASK-399: retrieval_limit siempre 100, pageSize se guarda en _page_size."""
    module = _load_query_module()
    body = {"query": "ibuprofeno", "page": 3, "pageSize": 25}
    result = module._normalize_v2_body(body)
    assert result["retrieval_limit"] == 100
    assert result["_page"] == 3
    assert result["_page_size"] == 25


def test_normalize_v2_sort_maps_to_sort_by():
    module = _load_query_module()
    body = {"query": "test", "sort": "date_desc"}
    result = module._normalize_v2_body(body)
    assert result["sort_by"] == "date_desc"


def test_normalize_v2_page_size_exceeds_max():
    module = _load_query_module()
    body = {"query": "test", "pageSize": 100}
    try:
        module._normalize_v2_body(body)
        assert False, "Debio lanzar ValueError"
    except ValueError as e:
        assert "50" in str(e)


def test_normalize_v2_page_size_below_one():
    module = _load_query_module()
    body = {"query": "test", "pageSize": 0}
    try:
        module._normalize_v2_body(body)
        assert False, "Debio lanzar ValueError"
    except ValueError as e:
        assert "1 y 50" in str(e) or "0" in str(e)


def test_normalize_v2_page_below_one():
    module = _load_query_module()
    body = {"query": "test", "page": 0}
    try:
        module._normalize_v2_body(body)
        assert False, "Debio lanzar ValueError"
    except ValueError as e:
        assert "page" in str(e)


def test_normalize_v2_invalid_page_size_type():
    module = _load_query_module()
    body = {"query": "test", "pageSize": "abc"}
    try:
        module._normalize_v2_body(body)
        assert False, "Debio lanzar ValueError"
    except ValueError as e:
        assert "entero" in str(e)


def test_normalize_v2_invalid_page_type():
    module = _load_query_module()
    body = {"query": "test", "page": "abc"}
    try:
        module._normalize_v2_body(body)
        assert False, "Debio lanzar ValueError"
    except ValueError as e:
        assert "entero" in str(e)


def test_normalize_v2_retrieval_limit_always_100():
    """TASK-399: retrieval_limit siempre es 100 independiente del pageSize."""
    module = _load_query_module()
    body = {"query": "ibuprofeno", "pageSize": 5}
    result = module._normalize_v2_body(body)
    assert result["retrieval_limit"] == 100
    assert result["_page_size"] == 5


def test_normalize_v2_preserves_original_params():
    module = _load_query_module()
    body = {"query": "ibuprofeno", "page": 2, "pageSize": 15, "sort": "hybrid"}
    result = module._normalize_v2_body(body)
    assert result["page"] == 2
    assert result["pageSize"] == 15
    assert result["sort"] == "hybrid"


# =============================================================================
# _build_v2_response()
# =============================================================================

def test_build_v2_response_has_data_pagination_metadata():
    """TASK-399: Verifica estructura básica del response v2 simplificado."""
    module = _load_query_module()
    v1 = {
        "response": "El ibuprofeno es...",
        "contexts": ["ctx1", "ctx2"],
        "context_items": [{"rank": 0, "chunk_text": "ctx1"}, {"rank": 1, "chunk_text": "ctx2"}],
        "documents": ["doc1.pdf"],
        "retrieval_config": {"max_semantic_distance": 0.45},
    }
    result = module._build_v2_response(v1, 1, 10)
    assert "data" in result
    assert "pagination" in result
    assert "metadata" in result
    # data es array de context_items (no objeto)
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 2
    # metadata contiene response y retrieval_config
    assert result["metadata"]["response"] == "El ibuprofeno es..."
    assert result["metadata"]["retrieval_config"]["max_semantic_distance"] == 0.45


def test_build_v2_response_has_next_on_full_page():
    """TASK-399: hasNext cuando hay más items después de la página actual."""
    module = _load_query_module()
    # 15 items totales, página 1 con pageSize 10 → hay página 2
    v1 = {
        "response": "test",
        "contexts": [f"ctx{i}" for i in range(15)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(15)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 1, 10)
    # data debe tener solo 10 items (página 1)
    assert len(result["data"]) == 10
    assert result["pagination"]["hasNext"] is True
    assert result["pagination"]["hasPrevious"] is False


def test_build_v2_response_no_has_next_on_last_page():
    """TASK-399: hasNext=false cuando estamos en la última página."""
    module = _load_query_module()
    # 15 items, página 2 con pageSize 10 → items 10-14 (5 items)
    v1 = {
        "response": "test",
        "contexts": [f"ctx{i}" for i in range(15)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(15)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 2, 10)
    assert len(result["data"]) == 5  # Última página con 5 items
    assert result["pagination"]["hasNext"] is False
    assert result["pagination"]["hasPrevious"] is True


def test_build_v2_response_empty_page_beyond_data():
    """TASK-399: Página vacía cuando se solicita más allá de los datos."""
    module = _load_query_module()
    # 5 items totales, página 3 con pageSize 10 → vacía (0 items)
    v1 = {
        "response": "test",
        "contexts": [f"ctx{i}" for i in range(5)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(5)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 3, 10)
    assert len(result["data"]) == 0  # Página vacía
    assert result["pagination"]["hasNext"] is False
    assert result["pagination"]["hasPrevious"] is True
    assert result["pagination"]["page"] == 3
    assert result["pagination"]["pageSize"] == 10


# =============================================================================
# TASK-399: Tests para formato simplificado v2 (sin documents)
# =============================================================================

def test_build_v2_response_data_is_array_of_contexts():
    """TASK-399: data debe ser array de context_items, no objeto."""
    module = _load_query_module()
    v1 = {
        "response": "Test response",
        "contexts": ["ctx1", "ctx2", "ctx3"],
        "context_items": [
            {"rank": 0, "chunk_text": "ctx1", "distance": 0.1},
            {"rank": 1, "chunk_text": "ctx2", "distance": 0.2},
            {"rank": 2, "chunk_text": "ctx3", "distance": 0.3},
        ],
        "documents": ["doc1.pdf", "doc2.pdf"],
        "retrieval_config": {"max_semantic_distance": 0.45},
    }
    result = module._build_v2_response(v1, 1, 10)
    # data es array, NO objeto
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 3
    assert result["data"][0]["rank"] == 0
    assert result["data"][1]["rank"] == 1


def test_build_v2_response_metadata_has_response_and_config():
    """TASK-399: metadata debe contener response y retrieval_config."""
    module = _load_query_module()
    v1 = {
        "response": "El ibuprofeno es un AINE...",
        "contexts": ["ctx1"],
        "context_items": [{"rank": 0, "chunk_text": "ctx1"}],
        "documents": ["doc1.pdf"],
        "retrieval_config": {
            "max_semantic_distance": 0.45,
            "retrieval_limit": 100,
            "sort_by": "relevance",
        },
    }
    result = module._build_v2_response(v1, 1, 10)
    assert "metadata" in result
    assert result["metadata"]["response"] == "El ibuprofeno es un AINE..."
    assert "retrieval_config" in result["metadata"]
    assert result["metadata"]["retrieval_config"]["max_semantic_distance"] == 0.45
    assert result["metadata"]["retrieval_config"]["retrieval_limit"] == 100


def test_build_v2_response_metadata_no_documents_field():
    """TASK-399: metadata NO debe incluir campo documents (decisión aprobada)."""
    module = _load_query_module()
    v1 = {
        "response": "Test",
        "contexts": ["ctx1"],
        "context_items": [{"rank": 0, "chunk_text": "ctx1"}],
        "documents": ["doc1.pdf", "doc2.pdf"],  # Viene del v1 pero se omite
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 1, 10)
    # metadata NO debe tener documents
    assert "documents" not in result["metadata"]
    # data tampoco debe tener documents
    assert "documents" not in result


def test_build_v2_response_pagination_logic_first_page():
    """TASK-399: Primera página (page=1) → hasPrevious=false, hasNext depende de datos."""
    module = _load_query_module()
    # 25 items, página 1, pageSize 10 → items 0-9, hay página 2
    v1 = {
        "response": "Test",
        "contexts": [f"ctx{i}" for i in range(25)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(25)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 1, 10)
    assert result["pagination"]["page"] == 1
    assert result["pagination"]["pageSize"] == 10
    assert result["pagination"]["hasPrevious"] is False
    assert result["pagination"]["hasNext"] is True
    assert len(result["data"]) == 10
    assert result["data"][0]["rank"] == 0
    assert result["data"][9]["rank"] == 9


def test_build_v2_response_pagination_logic_middle_page():
    """TASK-399: Página intermedia → hasPrevious=true, hasNext=true."""
    module = _load_query_module()
    # 30 items, página 2, pageSize 10 → items 10-19
    v1 = {
        "response": "Test",
        "contexts": [f"ctx{i}" for i in range(30)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(30)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 2, 10)
    assert result["pagination"]["page"] == 2
    assert result["pagination"]["pageSize"] == 10
    assert result["pagination"]["hasPrevious"] is True
    assert result["pagination"]["hasNext"] is True
    assert len(result["data"]) == 10
    assert result["data"][0]["rank"] == 10
    assert result["data"][9]["rank"] == 19


def test_build_v2_response_pagination_logic_last_page():
    """TASK-399: Última página → hasPrevious=true, hasNext=false."""
    module = _load_query_module()
    # 23 items, página 3, pageSize 10 → items 20-22 (3 items)
    v1 = {
        "response": "Test",
        "contexts": [f"ctx{i}" for i in range(23)],
        "context_items": [{"rank": i, "chunk_text": f"ctx{i}"} for i in range(23)],
        "documents": [],
        "retrieval_config": {},
    }
    result = module._build_v2_response(v1, 3, 10)
    assert result["pagination"]["page"] == 3
    assert result["pagination"]["pageSize"] == 10
    assert result["pagination"]["hasPrevious"] is True
    assert result["pagination"]["hasNext"] is False
    assert len(result["data"]) == 3
    assert result["data"][0]["rank"] == 20
    assert result["data"][2]["rank"] == 22

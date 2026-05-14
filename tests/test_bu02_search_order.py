from __future__ import annotations

import importlib.util
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
    spec = importlib.util.spec_from_file_location("rag_lmbd_query_bu02", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_normalize_search_sort_by_defaults_to_relevance():
    module = _load_query_module()

    assert module.normalize_search_sort_by(None) == "relevance"
    assert module.normalize_search_sort_by("") == "relevance"
    assert module.normalize_search_sort_by(" HYBRID ") == "hybrid"


def test_normalize_search_sort_by_rejects_unknown_values():
    module = _load_query_module()

    try:
        module.normalize_search_sort_by("created_at desc; drop table documents")
    except ValueError as exc:
        assert "sort_by inválido" in str(exc)
        assert "date_desc" in str(exc)
        assert "hybrid" in str(exc)
        assert "relevance" in str(exc)
    else:
        raise AssertionError("sort_by inválido no fue rechazado")


def test_search_order_clause_uses_safe_hardcoded_clauses():
    module = _load_query_module()

    relevance = module.search_order_clause("relevance")
    hybrid = module.search_order_clause("hybrid")
    date_desc = module.search_order_clause("date_desc")

    assert relevance.startswith("vector_distance ASC NULLS LAST")
    assert "rrf_score DESC" in relevance
    assert hybrid.startswith("rrf_score DESC")
    assert "vector_distance ASC NULLS LAST" in hybrid
    assert date_desc.startswith("created_at DESC NULLS LAST")
    assert "vector_distance ASC NULLS LAST" in date_desc


def test_ordered_unique_documents_preserves_final_result_order():
    module = _load_query_module()
    rows = [
        (10, "chunk x", "x.pdf", 0.10, 0.80, "doc-x"),
        (11, "chunk y", "y.pdf", 0.11, 0.79, "doc-y"),
        (12, "chunk x 2", "x.pdf", 0.12, 0.78, "doc-x"),
        (13, "chunk z", "z.pdf", 0.13, 0.77, "doc-z"),
    ]

    assert module.ordered_unique_documents(rows) == ["x.pdf", "y.pdf", "z.pdf"]


def test_handler_rejects_invalid_sort_by_with_http_400():
    module = _load_query_module()
    event = {
        "tenant_id": "tenant_gp",
        "agent_id": "agent-1",
        "query": "consulta",
        "sort_by": "rrf_score desc; drop table documents",
    }

    response = module.handler(event, context=None)

    assert response["statusCode"] == 400
    import json

    body = json.loads(response["body"])
    assert "sort_by inválido" in body["error"]

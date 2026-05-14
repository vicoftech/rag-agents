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
    spec = importlib.util.spec_from_file_location("rag_lmbd_query_bu01", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_dedupe_rows_by_document_keeps_best_chunk_per_document_name():
    module = _load_query_module()
    rows = [
        (1, "best doc A", "a.pdf", 0.10, 0.90, "doc-a"),
        (2, "worse doc A", "a.pdf", 0.12, 0.80, "doc-a"),
        (3, "best doc B", "b.pdf", 0.20, 0.70, "doc-b"),
    ]

    deduped = module.dedupe_rows_by_document(rows)

    assert [row[0] for row in deduped] == [1, 3]


def test_dedupe_rows_by_document_uses_document_id_when_name_is_missing():
    module = _load_query_module()
    rows = [
        (1, "best doc A", "", 0.10, 0.90, "doc-a"),
        (2, "worse doc A", "", 0.12, 0.80, "doc-a"),
        (3, "doc without id", "", 0.20, 0.70, "doc-b"),
    ]

    deduped = module.dedupe_rows_by_document(rows)

    assert [row[0] for row in deduped] == [1, 3]


def test_dedupe_rows_by_document_does_not_collapse_distinct_documents():
    module = _load_query_module()
    rows = [
        (1, "doc A", "a.pdf", 0.10, 0.90, "doc-a"),
        (2, "doc B", "b.pdf", 0.12, 0.80, "doc-b"),
        (3, "doc C", "c.pdf", 0.20, 0.70, "doc-c"),
    ]

    deduped = module.dedupe_rows_by_document(rows)

    assert [row[0] for row in deduped] == [1, 2, 3]


def test_dedupe_rows_by_document_applies_result_limit_after_dedupe():
    module = _load_query_module()
    rows = [
        (1, "best doc A", "a.pdf", 0.10, 0.90, "doc-a"),
        (2, "worse doc A", "a.pdf", 0.12, 0.80, "doc-a"),
        (3, "best doc B", "b.pdf", 0.20, 0.70, "doc-b"),
        (4, "best doc C", "c.pdf", 0.25, 0.60, "doc-c"),
    ]

    deduped = module.dedupe_rows_by_document(rows, limit=2)

    assert [row[0] for row in deduped] == [1, 3]

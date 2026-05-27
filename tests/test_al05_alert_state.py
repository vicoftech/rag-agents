from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

PERMANENTE_ACTIVO_CASE_SQL = (
    "activo = CASE WHEN COALESCE(permanente, false) THEN activo ELSE false END"
)


def _install_aws_stubs():
    if "boto3" not in sys.modules:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.Session = object
        boto3_stub.client = lambda *args, **kwargs: object()
        sys.modules["boto3"] = boto3_stub

    if "botocore" not in sys.modules:
        sys.modules["botocore"] = types.ModuleType("botocore")

    if "botocore.config" not in sys.modules:
        config_stub = types.ModuleType("botocore.config")
        config_stub.Config = object
        sys.modules["botocore.config"] = config_stub

    if "botocore.exceptions" not in sys.modules:
        exceptions_stub = types.ModuleType("botocore.exceptions")
        exceptions_stub.ClientError = Exception
        sys.modules["botocore.exceptions"] = exceptions_stub


def _install_alert_creation_stubs():
    _install_aws_stubs()

    if "psycopg2" not in sys.modules:
        psycopg2_stub = types.ModuleType("psycopg2")
        psycopg2_stub.connect = lambda *args, **kwargs: object()
        sys.modules["psycopg2"] = psycopg2_stub
    else:
        psycopg2_stub = sys.modules["psycopg2"]

    if "psycopg2.errors" not in sys.modules:
        errors_stub = types.ModuleType("psycopg2.errors")
        errors_stub.UniqueViolation = type("UniqueViolation", (Exception,), {})
        sys.modules["psycopg2.errors"] = errors_stub
    else:
        errors_stub = sys.modules["psycopg2.errors"]
    setattr(psycopg2_stub, "errors", errors_stub)

    if "psycopg2.extensions" not in sys.modules:
        extensions_stub = types.ModuleType("psycopg2.extensions")
        extensions_stub.connection = object
        sys.modules["psycopg2.extensions"] = extensions_stub


def _load_alerts_semantic_matches():
    _install_aws_stubs()
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "alerts_semantic_matches.py"
    spec = importlib.util.spec_from_file_location("alerts_semantic_matches", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_alert_creation_handler():
    _install_alert_creation_stubs()
    root = Path(__file__).resolve().parents[1]
    module_path = root / "apps" / "rag_lmbd_alert_creation" / "handler.py"
    spec = importlib.util.spec_from_file_location("rag_lmbd_alert_creation_handler", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_mark_alert_creation_messages_as_fired_marks_matching_busqueda_ids():
    module = _load_alerts_semantic_matches()

    messages = [
        {"busqueda_id": 10, "matched_chunk_ids": [1]},
        {"busqueda_id": 20, "matched_chunk_ids": [2]},
    ]
    notifications = [
        {"alerta_id": 10, "message": {"to": "user@example.com"}},
    ]

    marked = module.mark_alert_creation_messages_as_fired(
        messages,
        notifications,
        fired_at="2026-05-13T10:00:00+00:00",
    )

    assert marked[0]["enviada"] is True
    assert marked[0]["last_fired_at"] == "2026-05-13T10:00:00+00:00"
    assert marked[0]["estado_envio_alerta"] == "published_to_email_queue"
    assert "enviada" not in marked[1]


def test_mark_alert_creation_messages_as_fired_does_not_mutate_original_messages():
    module = _load_alerts_semantic_matches()

    messages = [{"busqueda_id": 10, "matched_chunk_ids": [1]}]
    notifications = [{"alerta_id": 10, "message": {"to": "user@example.com"}}]

    marked = module.mark_alert_creation_messages_as_fired(messages, notifications)

    assert marked is not messages
    assert marked[0] is not messages[0]
    assert "enviada" not in messages[0]
    assert marked[0]["enviada"] is True


def test_mark_alert_creation_messages_as_fired_ignores_invalid_ids():
    module = _load_alerts_semantic_matches()

    messages = [
        {"busqueda_id": "not-int", "matched_chunk_ids": [1]},
        {"busqueda_id": 20, "matched_chunk_ids": [2]},
    ]
    notifications = [
        {"alerta_id": "invalid", "message": {"to": "user@example.com"}},
    ]

    marked = module.mark_alert_creation_messages_as_fired(messages, notifications)

    assert all("enviada" not in msg for msg in marked)


def test_busqueda_fired_set_clause_includes_last_fired_and_estado_alerta():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)
    col = {"last_fired_at": "timestamp with time zone", "estado_alerta": "integer"}
    out = module.busqueda_fired_set_clause_and_params(col, ts)
    assert out is not None
    set_sql, params = out
    assert "last_fired_at" in set_sql
    assert "estado_alerta" in set_sql
    assert params[0] is ts
    assert params[1] == 2


def test_busqueda_fired_set_clause_none_when_no_supported_columns():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert module.busqueda_fired_set_clause_and_params({"foo": "text"}, ts) is None


def test_busqueda_fired_set_clause_activo_false_when_boolean():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)
    out = module.busqueda_fired_set_clause_and_params({"activo": "boolean"}, ts)
    assert out is not None
    set_sql, params = out
    assert "activo = false" in set_sql
    assert params == []


def test_busqueda_fired_set_clause_preserves_activo_for_permanente_boolean():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module.busqueda_fired_set_clause_and_params(
        {"activo": "boolean", "permanente": "boolean"},
        ts,
    )

    assert out is not None
    set_sql, params = out
    assert PERMANENTE_ACTIVO_CASE_SQL in set_sql
    assert "activo = false" not in set_sql
    assert params == []


def test_busqueda_fired_set_clause_preserves_activo_for_permanente_with_state_updates():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module.busqueda_fired_set_clause_and_params(
        {
            "activo": "boolean",
            "permanente": "boolean",
            "last_fired_at": "timestamp with time zone",
            "estado_alerta": "integer",
        },
        ts,
    )

    assert out is not None
    set_sql, params = out
    assert "last_fired_at = %s" in set_sql
    assert "estado_alerta = %s" in set_sql
    assert PERMANENTE_ACTIVO_CASE_SQL in set_sql
    assert params == [ts, 2]


def test_busqueda_fired_set_clause_deactivates_when_permanente_is_not_boolean():
    module = _load_alerts_semantic_matches()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module.busqueda_fired_set_clause_and_params(
        {"activo": "boolean", "permanente": "text"},
        ts,
    )

    assert out is not None
    set_sql, params = out
    assert "activo = false" in set_sql
    assert PERMANENTE_ACTIVO_CASE_SQL not in set_sql
    assert params == []


def test_alert_creation_handler_preserves_activo_for_permanente_boolean():
    module = _load_alert_creation_handler()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module._busqueda_fired_set_clause_and_params(
        {"activo": "boolean", "permanente": "boolean"},
        ts,
    )

    assert out is not None
    set_sql, params = out
    assert PERMANENTE_ACTIVO_CASE_SQL in set_sql
    assert "activo = false" not in set_sql
    assert params == []


def test_alert_creation_handler_deactivates_when_no_permanente_column():
    module = _load_alert_creation_handler()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module._busqueda_fired_set_clause_and_params({"activo": "boolean"}, ts)

    assert out is not None
    set_sql, params = out
    assert "activo = false" in set_sql
    assert PERMANENTE_ACTIVO_CASE_SQL not in set_sql
    assert params == []


def test_alert_creation_handler_preserves_activo_for_permanente_with_state_updates():
    module = _load_alert_creation_handler()
    ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    out = module._busqueda_fired_set_clause_and_params(
        {
            "activo": "boolean",
            "permanente": "boolean",
            "last_fired_at": "timestamp with time zone",
            "estado_alerta": "integer",
        },
        ts,
    )

    assert out is not None
    set_sql, params = out
    assert "last_fired_at = %s" in set_sql
    assert "estado_alerta = %s" in set_sql
    assert PERMANENTE_ACTIVO_CASE_SQL in set_sql
    assert params == [ts, 2]

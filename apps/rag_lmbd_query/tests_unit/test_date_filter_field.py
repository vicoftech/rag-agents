import sys
import os
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
import json

import pytest


# Agregar apps/ al path para importar rag_lmbd_query_dispatcher
_APPS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _APPS_DIR not in sys.path:
    sys.path.insert(0, _APPS_DIR)


@pytest.fixture
def mock_deps():
    """Mockear dependencias pesadas de index (boto3, DB, LLM, prompts)."""
    with (
        patch("index.semantic_search") as mock_sem,
        patch("index.lexical_search") as mock_lex,
        patch("index.get_connection"),
        patch("index.get_prompt_template", return_value="template {context} {query}"),
        patch("index.embed", return_value=[0.1] * 1536),
        patch("index.LLMClient") as mock_llm,
        patch("index.resolve_schema_name", return_value="tenant_anmat"),
        patch("index.bedrock"),
        patch("index.secretsmanager"),
        patch("index.s3"),
    ):
        mock_llm_instance = MagicMock()
        mock_llm_instance.generate.return_value = "respuesta"
        mock_llm.return_value = mock_llm_instance

        mock_sem.return_value = (
            ["chunk1"],
            ["doc1"],
            [{"rank": 0, "chunk_id": 1, "chunk_text": "chunk1", "document_name": "doc1"}],
            {"searchMode": "hybrid", "date_filter_field": "created_at"},
        )
        mock_lex.return_value = (
            ["chunk1"],
            ["doc1"],
            [{"rank": 0, "chunk_id": 1, "chunk_text": "chunk1", "document_name": "doc1"}],
            {"searchMode": "lexical", "date_filter_field": "created_at"},
        )

        yield {
            "semantic_search": mock_sem,
            "lexical_search": mock_lex,
            "llm_generate": mock_llm_instance.generate,
        }


def make_event(body: dict) -> dict:
    return {
        "requestContext": {"http": {"method": "POST", "path": "/query"}},
        "body": json.dumps(body),
        "httpMethod": "POST",
    }


def _make_hybrid_event(body: dict) -> dict:
    """Igual que make_event pero agrega searchMode=hybrid."""
    b = dict(body)
    b.setdefault("searchMode", "hybrid")
    return make_event(b)


_MOCK_DDB_TABLE = MagicMock()
_MOCK_SQS_CLIENT = MagicMock()


@pytest.fixture(autouse=True)
def _reset_mocks():
    _MOCK_DDB_TABLE.reset_mock()
    _MOCK_SQS_CLIENT.reset_mock()
    yield


def _dispatcher_patches():
    """Context managers para parchear el dispatcher."""
    mock_tbl = _MOCK_DDB_TABLE
    mock_tbl.get_item.return_value = {"Item": {"id": "fixed-job-id"}}
    mock_sqs = _MOCK_SQS_CLIENT
    stack = ExitStack()
    stack.enter_context(patch("rag_lmbd_query_dispatcher.index._env_table_name", return_value="test-table"))
    stack.enter_context(patch("rag_lmbd_query_dispatcher.index._env_queue_url", return_value="https://sqs.test"))
    stack.enter_context(patch("rag_lmbd_query_dispatcher.index._ddb_table", return_value=mock_tbl))
    stack.enter_context(patch("rag_lmbd_query_dispatcher.index._sqs_client_fn", return_value=mock_sqs))
    stack.enter_context(patch("rag_lmbd_query_dispatcher.index._find_cached_job_id", return_value=None))
    stack.enter_context(patch("uuid.uuid4", return_value="fixed-job-id"))
    return stack



class TestDateFilterFieldHandler:
    """TASK-411: Verificar que handler extrae y propaga date_filter_field."""

    def test_default_created_at_when_omitted(self, mock_deps):
        event = _make_hybrid_event({
            "tenant_id": "anmat",
            "agent_id": "agent-123",
            "query": "GRIP",
            "created_at_start": "2021-02-01",
            "created_at_end": "2026-05-31",
        })
        from index import handler
        handler(event, None)

        mock_sem = mock_deps["semantic_search"]
        mock_sem.assert_called_once()
        _check_date_filter_field(mock_sem, "created_at")

    def test_explicit_created_at(self, mock_deps):
        event = _make_hybrid_event({
            "tenant_id": "anmat",
            "agent_id": "agent-123",
            "query": "GRIP",
            "created_at_start": "2021-02-01",
            "created_at_end": "2026-05-31",
            "date_filter_field": "created_at",
        })
        from index import handler
        handler(event, None)

        mock_sem = mock_deps["semantic_search"]
        mock_sem.assert_called_once()
        _check_date_filter_field(mock_sem, "created_at")

    def test_publication_date_passed_through(self, mock_deps):
        event = _make_hybrid_event({
            "tenant_id": "anmat",
            "agent_id": "agent-123",
            "query": "GRIP",
            "created_at_start": "2021-02-01",
            "created_at_end": "2026-05-31",
            "date_filter_field": "publication_date",
        })
        from index import handler
        handler(event, None)

        mock_sem = mock_deps["semantic_search"]
        mock_sem.assert_called_once()
        _check_date_filter_field(mock_sem, "publication_date")

    def test_invalid_value_defaults_to_created_at(self, mock_deps):
        event = _make_hybrid_event({
            "tenant_id": "anmat",
            "agent_id": "agent-123",
            "query": "GRIP",
            "created_at_start": "2021-02-01",
            "created_at_end": "2026-05-31",
            "date_filter_field": "invalid_value",
        })
        from index import handler
        handler(event, None)

        mock_sem = mock_deps["semantic_search"]
        mock_sem.assert_called_once()
        _check_date_filter_field(mock_sem, "created_at")

    def test_lexical_search_receives_date_filter_field(self, mock_deps):
        event = make_event({
            "tenant_id": "anmat",
            "agent_id": "agent-123",
            "query": "GRIP",
            "created_at_start": "2021-02-01",
            "created_at_end": "2026-05-31",
            "date_filter_field": "publication_date",
            "searchMode": "lexical",
        })
        from index import handler
        handler(event, None)

        mock_lex = mock_deps["lexical_search"]
        mock_lex.assert_called_once()
        _check_date_filter_field(mock_lex, "publication_date")


def _check_date_filter_field(mock_func, expected: str):
    _call_kwargs = mock_func.call_args.kwargs
    assert "date_filter_field" in _call_kwargs, (
        f"date_filter_field no está en kwargs de {mock_func._extract_mock_name()}. "
        f"kwargs={list(_call_kwargs.keys())}"
    )
    actual = _call_kwargs["date_filter_field"]
    assert actual == expected, (
        f"Esperado date_filter_field={expected!r}, obtenido={actual!r}"
    )


class TestDateFilterFieldDispatcher:
    """TASK-411: Verificar que el dispatcher propaga date_filter_field."""

    def test_dispatcher_pasa_date_filter_field_en_msg(self):
        with _dispatcher_patches():
            from rag_lmbd_query_dispatcher.index import handler

            event = {
                "routeKey": "POST /query",
                "requestContext": {"http": {"method": "POST", "path": "/query"}},
                "body": json.dumps({
                    "tenant_id": "anmat",
                    "agent_id": "agent-123",
                    "query": "GRIP",
                    "created_at_start": "2021-02-01",
                    "created_at_end": "2026-05-31",
                    "date_filter_field": "publication_date",
                }),
                "httpMethod": "POST",
            }

            response = handler(event, None)
            assert response["statusCode"] == 202, f"Expected 202, got {response['statusCode']}: {response['body']}"

            item = _MOCK_DDB_TABLE.put_item.call_args.kwargs["Item"]
            assert item.get("date_filter_field") == "publication_date"

            msg_body = json.loads(
                _MOCK_SQS_CLIENT.send_message.call_args.kwargs["MessageBody"]
            )
            assert msg_body.get("date_filter_field") == "publication_date"

    def test_dispatcher_default_created_at(self):
        with _dispatcher_patches():
            from rag_lmbd_query_dispatcher.index import handler

            event = {
                "routeKey": "POST /query",
                "requestContext": {"http": {"method": "POST", "path": "/query"}},
                "body": json.dumps({
                    "tenant_id": "anmat",
                    "agent_id": "agent-123",
                    "query": "GRIP",
                    "created_at_start": "2021-02-01",
                    "created_at_end": "2026-05-31",
                }),
                "httpMethod": "POST",
            }

            response = handler(event, None)
            assert response["statusCode"] == 202, f"Expected 202, got {response['statusCode']}: {response['body']}"

            item = _MOCK_DDB_TABLE.put_item.call_args.kwargs["Item"]
            assert item.get("date_filter_field") == "created_at"

            msg_body = json.loads(
                _MOCK_SQS_CLIENT.send_message.call_args.kwargs["MessageBody"]
            )
            assert msg_body.get("date_filter_field") == "created_at"

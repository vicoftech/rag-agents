from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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


def _load_alerts_semantic_matches():
    _install_aws_stubs()
    root = Path(__file__).resolve().parents[1]
    module_path = root / "scripts" / "alerts_semantic_matches.py"
    spec = importlib.util.spec_from_file_location("alerts_semantic_matches_al06", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_normalize_document_url_accepts_valid_s3_uri():
    module = _load_alerts_semantic_matches()

    assert module.normalize_document_url_for_alert(
        "s3://rag-documents-prod-123/tenant_anmat/agent/documents/file.pdf"
    ) == "s3://rag-documents-prod-123/tenant_anmat/agent/documents/file.pdf"


def test_normalize_document_url_rejects_local_and_dev_urls():
    module = _load_alerts_semantic_matches()

    assert module.normalize_document_url_for_alert("http://localhost:4200/file.pdf") is None
    assert module.normalize_document_url_for_alert("http://192.168.1.10/file.pdf") is None
    assert module.normalize_document_url_for_alert("file:///tmp/file.pdf") is None
    assert module.normalize_document_url_for_alert("/tmp/file.pdf") is None


def test_compute_alert_creation_messages_does_not_emit_fake_s3_url_when_missing():
    module = _load_alerts_semantic_matches()
    blob = {
        "resultados": [
            {
                "alerta_id": 123,
                "estado_alerta": 1,
                "documents_unique": ["doc.pdf"],
                "matched_chunk_ids_por_documento": {"doc.pdf": [10]},
                "chunks_count": 1,
                "tiene_fuente_documental_recuperada": True,
                "s3_uri_por_documento": {},
                "url_disposicion_default": "http://localhost:4200/doc.pdf",
            }
        ]
    }

    messages = module.compute_alert_creation_messages(blob)

    assert len(messages) == 1
    assert messages[0]["disposicion"]["url"] is None


def test_compute_alert_creation_messages_uses_valid_s3_uri():
    module = _load_alerts_semantic_matches()
    s3_uri = "s3://rag-documents-prod-123/tenant_anmat/agent/documents/doc.pdf"
    blob = {
        "resultados": [
            {
                "alerta_id": 123,
                "estado_alerta": 1,
                "documents_unique": ["doc.pdf"],
                "matched_chunk_ids_por_documento": {"doc.pdf": [10]},
                "chunks_count": 1,
                "tiene_fuente_documental_recuperada": True,
                "s3_uri_por_documento": {"doc.pdf": s3_uri},
            }
        ]
    }

    messages = module.compute_alert_creation_messages(blob)

    assert messages[0]["disposicion"]["url"] == s3_uri

"""Tests de parse_s3_rag_key (fecha de partición → created_at)."""

import os
import sys
from datetime import datetime
from pathlib import Path

_EMB_ROOT = Path(__file__).resolve().parents[1]
if str(_EMB_ROOT) not in sys.path:
    sys.path.insert(0, str(_EMB_ROOT))

os.environ.setdefault(
    "RAG_S3_DEFAULT_AGENT_ID",
    "aaaaaaaa-bbbb-4ccc-dddd-eeeeeeeeeeee",
)

from s3_rag_key import parse_s3_rag_key  # noqa: E402


def test_canonical_with_date_partition():
    key = (
        "anmat/7c9aa113-ecf2-4449-a955-d91c76e7ee27/"
        "documents/20250101/default/aviso.pdf"
    )
    schema, agent, doc, created = parse_s3_rag_key(key)
    assert schema == "tenant_anmat"
    assert agent == "7c9aa113-ecf2-4449-a955-d91c76e7ee27"
    assert doc == "20250101/default/aviso.pdf"
    assert created == datetime(2025, 1, 1, 0, 0, 0)


def test_canonical_tenant_prefix_with_date():
    key = (
        "tenant_boletin/7c9aa113-ecf2-4449-a955-d91c76e7ee27/"
        "documents/20100801/x.pdf"
    )
    schema, agent, doc, created = parse_s3_rag_key(key)
    assert schema == "tenant_boletin"
    assert doc == "20100801/x.pdf"
    assert created == datetime(2010, 8, 1, 0, 0, 0)


def test_canonical_no_date_uses_none_for_default_now():
    key = (
        "anmat/7c9aa113-ecf2-4449-a955-d91c76e7ee27/documents/informe.pdf"
    )
    schema, agent, doc, created = parse_s3_rag_key(key)
    assert doc == "informe.pdf"
    assert created is None


def test_legacy_key_uses_second_segment_as_partition():
    key = "tenant_boletin/20111201/sub/carta.pdf"
    schema, agent, doc, created = parse_s3_rag_key(key)
    assert schema == "tenant_boletin"
    assert agent == "aaaaaaaa-bbbb-4ccc-dddd-eeeeeeeeeeee"
    assert doc == "sub/carta.pdf"
    assert created == datetime(2011, 12, 1, 0, 0, 0)


def test_invalid_date8_not_used_as_filename_that_looks_like_date():
    # Primer segmento bajo documents/ no es exactamente 8 dígitos → sin partición fecha
    key = "anmat/7c9aa113-ecf2-4449-a955-d91c76e7ee27/documents/2025010/x.pdf"
    _, _, doc, created = parse_s3_rag_key(key)
    assert doc == "2025010/x.pdf"
    assert created is None

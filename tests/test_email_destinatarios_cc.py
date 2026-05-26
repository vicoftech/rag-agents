"""Destinatarios múltiples → to + cc en alerts_semantic_matches."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from alerts_semantic_matches import (  # noqa: E402
    build_plain_alert_message,
    normalize_destinatarios_busqueda,
)


@pytest.mark.unit
def test_multiple_addresses_in_to_field_split_to_cc():
    d = normalize_destinatarios_busqueda({"to": "prim@x.com, sec@x.com; terc@x.com"})
    assert d["to"] == "prim@x.com"
    assert d["cc"] == ["sec@x.com", "terc@x.com"]


@pytest.mark.unit
def test_para_key_supported():
    d = normalize_destinatarios_busqueda({"para": "a@a.com,b@b.com"})
    assert d["to"] == "a@a.com"
    assert d["cc"] == ["b@b.com"]


@pytest.mark.unit
def test_explicit_cc_and_bcc_merged():
    d = normalize_destinatarios_busqueda(
        {"to": "p@p.com, x@x.com", "cc": "y@y.com", "cco": "blind@x.com"}
    )
    assert d["to"] == "p@p.com"
    assert "x@x.com" in d["cc"]
    assert "y@y.com" in d["cc"]
    assert d["bcc"] == ["blind@x.com"]


@pytest.mark.unit
def test_build_plain_alert_message_includes_cc_list():
    msg = build_plain_alert_message(
        {
            "destinatarios": '{"to": "a@a.com, b@b.com"}',
            "palabras_de_busqueda": "kw",
            "nombre_busqueda": "Alerta",
        },
        fuente_informacion="ANMAT",
        busqueda_desde="2026-01-01",
        busqueda_hasta="2026-01-31",
        fallback_from="from@x.com",
    )
    assert msg["to"] == "a@a.com"
    assert msg["cc"] == ["b@b.com"]
    assert "bcc" not in msg

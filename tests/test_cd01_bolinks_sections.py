from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime as RealDatetime
from pathlib import Path


def _install_stubs():
    if "boto3" not in sys.modules:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.client = lambda *args, **kwargs: object()
        boto3_stub.resource = lambda *args, **kwargs: object()
        sys.modules["boto3"] = boto3_stub

    if "requests" not in sys.modules:
        requests_stub = types.ModuleType("requests")
        requests_stub.head = lambda *args, **kwargs: types.SimpleNamespace(headers={})
        requests_stub.Session = lambda: types.SimpleNamespace(
            headers={},
            get=lambda *args, **kwargs: types.SimpleNamespace(status_code=200, text=""),
        )
        requests_stub.RequestException = Exception
        sys.modules["requests"] = requests_stub

    if "bs4" not in sys.modules:
        bs4_stub = types.ModuleType("bs4")
        bs4_stub.BeautifulSoup = lambda *_args, **_kwargs: types.SimpleNamespace(find_all=lambda *a, **k: [])
        sys.modules["bs4"] = bs4_stub


def _load_bolinks_module():
    _install_stubs()
    root = Path(__file__).resolve().parents[1]
    module_path = root / "apps" / "rag_lmbd_bolinks" / "index.py"
    spec = importlib.util.spec_from_file_location("rag_lmbd_bolinks_cd01", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _body(response):
    return json.loads(response["body"])


def test_empty_payload_uses_today_and_default_primera(monkeypatch):
    module = _load_bolinks_module()

    class FixedDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 5, 14, 9, 30)  # jueves

    calls = []

    def fake_get_pdf_links(date_str, section):
        calls.append((date_str, section))
        return [{"url": f"https://example.test/{section}/1.pdf", "section": section, "date": date_str}]

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(module, "get_pdf_links", fake_get_pdf_links)

    response = module.handler({}, None)
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["date"] == "20260514"
    assert body["sections_processed"] == ["primera"]
    assert body["totals"] == {"primera": 1, "total": 1}
    assert calls == [("20260514", "primera")]


def test_section_all_processes_all_sections(monkeypatch):
    module = _load_bolinks_module()
    calls = []

    def fake_get_pdf_links(date_str, section):
        calls.append((date_str, section))
        return [{"url": f"https://example.test/{section}/1.pdf", "section": section, "date": date_str}]

    monkeypatch.setattr(module, "get_pdf_links", fake_get_pdf_links)

    response = module.handler({"date": "2026-05-14", "section": "all"}, None)
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["sections_processed"] == ["primera", "segunda", "tercera"]
    assert set(body["pdf_links"].keys()) == {"primera", "segunda", "tercera"}
    assert body["totals"]["total"] == 3
    assert calls == [("20260514", "primera"), ("20260514", "segunda"), ("20260514", "tercera")]


def test_section_list_processes_subset(monkeypatch):
    module = _load_bolinks_module()
    calls = []

    def fake_get_pdf_links(date_str, section):
        calls.append((date_str, section))
        return []

    monkeypatch.setattr(module, "get_pdf_links", fake_get_pdf_links)

    response = module.handler({"date": "20260514", "section": ["primera", "tercera"]}, None)
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["sections_processed"] == ["primera", "tercera"]
    assert body["pdf_links"] == {"primera": [], "tercera": []}
    assert body["totals"] == {"primera": 0, "tercera": 0, "total": 0}
    assert calls == [("20260514", "primera"), ("20260514", "tercera")]


def test_weekend_returns_without_scraping(monkeypatch):
    module = _load_bolinks_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("get_pdf_links no debe ejecutarse fines de semana")

    monkeypatch.setattr(module, "get_pdf_links", fail_if_called)

    response = module.handler({"date": "2026-05-16", "section": "all"}, None)  # sábado
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["is_weekend"] is True
    assert body["sections_processed"] == []
    assert body["pdf_links"] == {}
    assert body["totals"] == {"total": 0}


def test_invalid_section_returns_400():
    module = _load_bolinks_module()

    response = module.handler({"date": "20260514", "section": "cuarta"}, None)
    body = _body(response)

    assert response["statusCode"] == 400
    assert body["success"] is False
    assert "Sección inválida" in body["message"]


def test_section_failure_is_reported_and_other_sections_continue(monkeypatch):
    module = _load_bolinks_module()

    def fake_get_pdf_links(date_str, section):
        if section == "segunda":
            raise RuntimeError("falló scraping")
        return [{"url": f"https://example.test/{section}/1.pdf", "section": section, "date": date_str}]

    monkeypatch.setattr(module, "get_pdf_links", fake_get_pdf_links)

    response = module.handler({"date": "20260514", "section": "all"}, None)
    body = _body(response)

    assert response["statusCode"] == 200
    assert body["success"] is False
    assert body["sections_processed"] == ["primera", "tercera"]
    assert body["sections_failed"] == {"segunda": "falló scraping"}
    assert body["totals"] == {"primera": 1, "tercera": 1, "total": 2}

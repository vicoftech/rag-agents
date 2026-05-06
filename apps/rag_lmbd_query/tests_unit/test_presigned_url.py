"""Tests for GET /presigned-url (presigned S3 download URL)."""
import json

import pytest

import index as mod


class TestNormalizeS3Key:
    def test_decodes_url_encoded_key(self):
        assert mod._normalize_s3_key("prefix%2Fdocumento.pdf") == "prefix/documento.pdf"

    def test_strips_whitespace(self):
        assert mod._normalize_s3_key("  doc.pdf  ") == "doc.pdf"

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="requerido"):
            mod._normalize_s3_key(None)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="requerido"):
            mod._normalize_s3_key("   ")

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError, match="inválido"):
            mod._normalize_s3_key("/abs/path.pdf")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="inválido"):
            mod._normalize_s3_key("a/../b.pdf")

    def test_invalid_percent_raises_clear_error(self):
        # strict unquote rejects truncated % sequences → must not propagate UnicodeDecodeError
        with pytest.raises(ValueError, match="codificación"):
            mod._normalize_s3_key("bad%EE.pdf")


class TestPresignedQueryParams:
    def test_fallback_raw_query_string_when_qp_null(self):
        ev = {
            "queryStringParameters": None,
            "rawQueryString": "key=x%2Fy.pdf&foo=bar",
        }
        p = mod._presigned_query_params(ev)
        # parse_qs decodes %-encoding
        assert p["key"] == "x/y.pdf"


class TestIsPresignedUrlRoute:
    def test_route_key_match(self):
        assert mod._is_presigned_url_route(
            {"routeKey": "GET /presigned-url"}, "GET"
        )

    def test_path_suffix_match(self):
        assert mod._is_presigned_url_route(
            {
                "requestContext": {"http": {"path": "/dev/presigned-url"}},
            },
            "GET",
        )

    def test_post_query_not_match(self):
        assert not mod._is_presigned_url_route(
            {"routeKey": "POST /query"}, "POST"
        )


class TestHandlePresignedDownload:
    def test_missing_bucket_config(self, monkeypatch):
        monkeypatch.setattr(mod, "DOCUMENTS_S3_BUCKET", "")
        event = {
            "routeKey": "GET /presigned-url",
            "queryStringParameters": {"key": "ok.pdf"},
        }
        r = mod.handle_presigned_download(event)
        assert r["statusCode"] == 500
        body = json.loads(r["body"])
        assert "error" in body

    def test_missing_key_param(self, monkeypatch):
        monkeypatch.setattr(mod, "DOCUMENTS_S3_BUCKET", "my-bucket")
        event = {
            "routeKey": "GET /presigned-url",
            "queryStringParameters": {},
        }
        r = mod.handle_presigned_download(event)
        assert r["statusCode"] == 400
        assert "error" in json.loads(r["body"])

    def test_success_returns_url(self, monkeypatch):
        monkeypatch.setattr(mod, "DOCUMENTS_S3_BUCKET", "my-bucket")
        monkeypatch.setattr(mod, "PRESIGNED_URL_EXPIRES_SECONDS", 900)

        def fake_presign(ClientMethod, Params, ExpiresIn):
            assert ClientMethod == "get_object"
            assert Params["Bucket"] == "my-bucket"
            assert Params["Key"] == "folder/file.pdf"
            assert ExpiresIn == 900
            return "https://s3.example.com/presigned"

        monkeypatch.setattr(mod.s3, "generate_presigned_url", fake_presign)

        event = {
            "routeKey": "GET /presigned-url",
            "queryStringParameters": {"key": "folder%2Ffile.pdf"},
        }
        r = mod.handle_presigned_download(event)
        assert r["statusCode"] == 200
        body = json.loads(r["body"])
        assert body["url"] == "https://s3.example.com/presigned"
        assert body["expires_in"] == 900
        assert body["bucket"] == "my-bucket"
        assert body["key"] == "folder/file.pdf"


class TestHandlerRoutesToPresigned:
    def test_get_presigned_route_short_circuits(self, monkeypatch):
        monkeypatch.setattr(mod, "DOCUMENTS_S3_BUCKET", "b")
        monkeypatch.setattr(mod, "PRESIGNED_URL_EXPIRES_SECONDS", 60)

        def fake_presign(ClientMethod, Params, ExpiresIn):
            return "https://signed"

        monkeypatch.setattr(mod.s3, "generate_presigned_url", fake_presign)

        event = {
            "requestContext": {"http": {"method": "GET"}},
            "routeKey": "GET /presigned-url",
            "queryStringParameters": {"key": "x.pdf"},
        }
        r = mod.handler(event, None)
        assert r["statusCode"] == 200
        assert "url" in json.loads(r["body"])

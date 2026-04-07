import pytest

from lib.tenant_schema import assert_valid_schema_name, resolve_schema_name


def test_resolve_prefix_short_slug():
    assert resolve_schema_name("gp") == "tenant_gp"


def test_resolve_full_schema_unchanged():
    assert resolve_schema_name("tenant_gp") == "tenant_gp"


def test_resolve_strips_whitespace():
    assert resolve_schema_name("  gp  ") == "tenant_gp"


def test_resolve_empty_raises():
    with pytest.raises(ValueError):
        resolve_schema_name("")


def test_invalid_characters():
    with pytest.raises(ValueError):
        assert_valid_schema_name("tenant-bad")


def test_avoids_double_prefix_convention():
    """gp → tenant_gp, no tenant_tenant_gp."""
    assert resolve_schema_name("gp") == "tenant_gp"

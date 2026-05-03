from datetime import date, datetime

import pytest

from index import parse_created_at_day, pagination_meta, resolve_created_at_bounds


def test_parse_none_and_empty():
    assert parse_created_at_day(None) is None
    assert parse_created_at_day("") is None
    assert parse_created_at_day("   ") is None
    assert parse_created_at_day("null") is None
    assert parse_created_at_day("NULL") is None
    assert parse_created_at_day("none") is None


def test_parse_date_only():
    assert parse_created_at_day("2026-03-15") == date(2026, 3, 15)


def test_parse_iso_datetime_utc_z():
    assert parse_created_at_day("2026-03-15T23:00:00Z") == date(2026, 3, 15)


def test_parse_iso_datetime_offset_changes_day():
    # 2026-03-16 01:00 in +02 → 2026-03-15 23:00 UTC
    assert parse_created_at_day("2026-03-16T01:00:00+02:00") == date(2026, 3, 15)


def test_parse_invalid_raises():
    with pytest.raises(ValueError, match="created_at"):
        parse_created_at_day("not-a-date")


def test_resolve_created_at_range():
    start, end = resolve_created_at_bounds(None, "2026-01-10", "2026-01-12")
    assert start == datetime(2026, 1, 10, 0, 0, 0)
    assert end == datetime(2026, 1, 13, 0, 0, 0)


def test_resolve_single_created_at_still_works():
    start, end = resolve_created_at_bounds("2026-03-01", None, None)
    assert start == datetime(2026, 3, 1, 0, 0, 0)
    assert end == datetime(2026, 3, 2, 0, 0, 0)


def test_resolve_range_takes_priority_over_single_day():
    start, end = resolve_created_at_bounds("2026-01-01", "2026-02-01", "2026-02-28")
    assert start == datetime(2026, 2, 1, 0, 0, 0)
    assert end == datetime(2026, 3, 1, 0, 0, 0)


def test_resolve_from_after_to_raises():
    with pytest.raises(ValueError, match="created_at_start"):
        resolve_created_at_bounds(None, "2026-05-01", "2026-04-01")


def test_pagination_meta_total_pages():
    m = pagination_meta(1800, 1, 20)
    assert m["total_count"] == 1800
    assert m["total_pages"] == 90
    assert m["has_next"] is True
    m2 = pagination_meta(1800, 90, 20)
    assert m2["has_next"] is False

from datetime import date

import pytest

from index import parse_created_at_day


def test_parse_none_and_empty():
    assert parse_created_at_day(None) is None
    assert parse_created_at_day("") is None
    assert parse_created_at_day("   ") is None


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

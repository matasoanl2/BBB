import pytest

from scripts.common.offline_support import parse_time_filter


def test_parse_time_filter_supports_legacy_hours() -> None:
    assert parse_time_filter("3") == (True, "3 hours")


def test_parse_time_filter_supports_all() -> None:
    assert parse_time_filter("all") == (False, None)


def test_parse_time_filter_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        parse_time_filter("yesterday")
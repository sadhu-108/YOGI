"""Unit tests for neutral market calendar and date boundary utilities."""

from datetime import date, datetime
import sys
import pytest

from yogi.market.calendar import (
    INDIAN_TRADING_HOLIDAYS,
    parse_date_boundary,
    validate_and_format_date_range,
)


def test_calendar_import_independence():
    """Verify that yogi.market.calendar can be imported without loading yfinance provider."""
    # Ensure yfinance provider is not imported as a prerequisite
    assert "yogi.market.calendar" in sys.modules
    assert isinstance(INDIAN_TRADING_HOLIDAYS, dict)
    assert 2024 in INDIAN_TRADING_HOLIDAYS
    assert 2025 in INDIAN_TRADING_HOLIDAYS
    assert 2026 in INDIAN_TRADING_HOLIDAYS
    assert "2024-01-26" in INDIAN_TRADING_HOLIDAYS[2024]
    assert "2025-08-15" in INDIAN_TRADING_HOLIDAYS[2025]
    assert "2026-10-02" in INDIAN_TRADING_HOLIDAYS[2026]


def test_parse_date_boundary_valid():
    """Verify parse_date_boundary for datetime, date, and valid string representations."""
    # Datetime input
    dt = datetime(2025, 4, 15, 10, 30)
    res_dt, res_str = parse_date_boundary(dt, "test_dt")
    assert res_dt == dt
    assert res_str == "2025-04-15"

    # Date input
    d = date(2025, 4, 15)
    res_dt, res_str = parse_date_boundary(d, "test_d")
    assert res_dt == datetime(2025, 4, 15)
    assert res_str == "2025-04-15"

    # String ISO input
    s = "2025-04-15"
    res_dt, res_str = parse_date_boundary(s, "test_s")
    assert res_dt == datetime(2025, 4, 15)
    assert res_str == "2025-04-15"


def test_parse_date_boundary_invalid():
    """Verify parse_date_boundary error conditions."""
    with pytest.raises(ValueError, match="Empty date string"):
        parse_date_boundary("   ", "empty_date")

    with pytest.raises(ValueError, match="Invalid date string"):
        parse_date_boundary("not-a-date", "bad_date")

    with pytest.raises(ValueError, match="Unsupported type"):
        parse_date_boundary(12345, "numeric_date")  # type: ignore


def test_validate_and_format_date_range():
    """Verify start_date and end_date range validation and formatting."""
    # None, None -> None, None
    assert validate_and_format_date_range(None, None) == (None, None)

    # Only start_date
    assert validate_and_format_date_range("2025-01-01", None) == ("2025-01-01", None)

    # Only end_date -> raises ValueError
    with pytest.raises(ValueError, match="Cannot specify end_date without start_date"):
        validate_and_format_date_range(None, "2025-01-01")

    # start_date >= end_date -> raises ValueError
    with pytest.raises(ValueError, match="strictly earlier than end_date"):
        validate_and_format_date_range("2025-01-02", "2025-01-01")

    with pytest.raises(ValueError, match="strictly earlier than end_date"):
        validate_and_format_date_range("2025-01-01", "2025-01-01")

    # Valid range
    assert validate_and_format_date_range("2025-01-01", "2025-01-10") == (
        "2025-01-01",
        "2025-01-10",
    )


def test_legacy_reexports_backward_compatibility():
    """Verify that legacy imports from yfinance and data package remain functional."""
    from yogi.data.providers.yfinance import (
        INDIAN_TRADING_HOLIDAYS as YF_HOLIDAYS,
        _parse_date_boundary as yf_parse,
        _validate_and_format_date_range as yf_validate,
    )
    from yogi.data.providers import INDIAN_TRADING_HOLIDAYS as PROV_HOLIDAYS
    from yogi.data import INDIAN_TRADING_HOLIDAYS as DATA_HOLIDAYS

    assert YF_HOLIDAYS is INDIAN_TRADING_HOLIDAYS
    assert PROV_HOLIDAYS is INDIAN_TRADING_HOLIDAYS
    assert DATA_HOLIDAYS is INDIAN_TRADING_HOLIDAYS

    # Call aliases
    dt, s = yf_parse("2025-05-01", "date")
    assert s == "2025-05-01"
    start, end = yf_validate("2025-05-01", "2025-05-10")
    assert start == "2025-05-01"
    assert end == "2025-05-10"

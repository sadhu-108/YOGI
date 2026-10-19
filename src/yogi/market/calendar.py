"""Exchange Trading Calendars and Date Utilities for Indian Equity Markets (NSE/BSE).

Provides canonical trading holiday datasets and date boundary parsing
independent of specific external market-data vendor adapters.
"""

from datetime import date, datetime
from typing import Mapping, Optional, Sequence, Union

import pandas as pd

# Standard Indian Stock Market Trading Holidays (NSE/BSE)
INDIAN_TRADING_HOLIDAYS: Mapping[int, Sequence[str]] = {
    2024: (
        "2024-01-22",
        "2024-01-26",
        "2024-03-08",
        "2024-03-25",
        "2024-03-29",
        "2024-04-11",
        "2024-04-17",
        "2024-05-01",
        "2024-05-20",
        "2024-06-17",
        "2024-07-17",
        "2024-08-15",
        "2024-10-02",
        "2024-11-01",
        "2024-11-15",
        "2024-12-25",
    ),
    2025: (
        "2025-02-26",
        "2025-03-14",
        "2025-03-31",
        "2025-04-10",
        "2025-04-14",
        "2025-04-18",
        "2025-05-01",
        "2025-08-15",
        "2025-08-27",
        "2025-10-02",
        "2025-10-21",
        "2025-10-22",
        "2025-11-05",
        "2025-12-25",
    ),
    2026: (
        "2026-01-26",
        "2026-03-03",
        "2026-03-20",
        "2026-03-31",
        "2026-04-03",
        "2026-04-14",
        "2026-05-01",
        "2026-05-28",
        "2026-08-15",
        "2026-08-26",
        "2026-10-02",
        "2026-10-20",
        "2026-11-10",
        "2026-12-25",
    ),
}


def parse_date_boundary(val: Union[datetime, date, str], name: str) -> tuple[datetime, str]:
    """Parse a date boundary into a (datetime, str) tuple.

    Preserves exact string representation when valid, or formats date/datetime as YYYY-MM-DD.
    Raises ValueError on invalid input or unsupported type.
    """
    if isinstance(val, datetime):
        return val, val.strftime("%Y-%m-%d")
    elif isinstance(val, date):
        return datetime(val.year, val.month, val.day), val.strftime("%Y-%m-%d")
    elif isinstance(val, str):
        s = val.strip()
        if not s:
            raise ValueError(f"Empty date string provided for '{name}'")
        try:
            dt = datetime.fromisoformat(s)
            return dt, s
        except ValueError:
            try:
                dt = pd.to_datetime(s).to_pydatetime()
                return dt, s
            except Exception as e:
                raise ValueError(f"Invalid date string for '{name}': '{val}'") from e
    else:
        raise ValueError(
            f"Unsupported type for '{name}': expected datetime, date, or str, got {type(val).__name__}"
        )


def validate_and_format_date_range(
    start_date: Optional[Union[datetime, date, str]],
    end_date: Optional[Union[datetime, date, str]],
) -> tuple[Optional[str], Optional[str]]:
    """Validate date range boundaries and return (start_str, end_str) for provider download.

    Semantics:
    - If neither is provided: returns (None, None) for legacy period-based download.
    - If only start_date is provided: returns (start_str, None) for start-to-present download.
    - If only end_date is provided: raises ValueError (prevents accidental full-history fallback).
    - If both are provided: verifies start_date < end_date, raising ValueError if start >= end
      or if mixing timezone-aware and timezone-naive datetimes.
    """
    if start_date is None and end_date is None:
        return None, None

    if start_date is None and end_date is not None:
        raise ValueError("Cannot specify end_date without start_date; start_date is required")

    dt_start, start_str = parse_date_boundary(start_date, "start_date")

    end_str: Optional[str] = None
    if end_date is not None:
        dt_end, end_str = parse_date_boundary(end_date, "end_date")

        # Guard against mixing timezone-aware and timezone-naive datetimes
        if (dt_start.tzinfo is None) != (dt_end.tzinfo is None):
            raise ValueError("Cannot compare timezone-aware and timezone-naive date boundaries")

        if dt_start >= dt_end:
            raise ValueError(
                f"Invalid date range: start_date ({start_date}) must be strictly earlier than end_date ({end_date})"
            )

    return start_str, end_str

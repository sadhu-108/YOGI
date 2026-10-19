"""Engine pipeline configuration specifying runtime scope and capability keys."""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class EngineConfig:
    """System-level configuration specifying pipeline scope and capability choices.

    Holds declarative intent and stable Registry capability keys.
    Does NOT resolve keys, instantiate implementations, or execute pipelines.
    """
    provider: str = "yfinance"
    bands_repository: str = "excel"
    calculation_modules: Sequence[str] = ("bands", "velocity", "impulse", "trend")
    exchange: str = "NSE"
    timeframes: Sequence[str] = ("D", "W", "M", "Q", "H", "Y")
    historical_years: int = 10
    symbol_limit: Optional[int] = None
    symbols: Optional[Sequence[str]] = None
    provider_options: Mapping[str, Any] = field(default_factory=dict)
    half_year_policy: str = "prototype"

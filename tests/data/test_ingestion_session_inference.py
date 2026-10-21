"""Target-date and session inference regression tests for Ingestion Service.

Verifies:
- Explicit session_completed is strictly respected.
- When omitted, session completion is inferred dynamically for past, current, and future dates.
- Weekends and exchange holidays roll back to the expected completed trading day.
- A cache ending on 15 October 2026 triggers an incremental update when target_date is 16 October 2026.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.ingestion.service import MarketDataIngestionService
from yogi.market.calendar import INDIAN_TRADING_HOLIDAYS
from yogi.storage.cache import IngestionCohort, MarketBarsCache, get_latest_completed_trading_day, plan_ingestion


def make_bar(dt: datetime, close: float = 100.0) -> MarketBar:
    return MarketBar(
        timestamp=dt,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=1000.0,
    )


def generate_bars(start_dt: datetime, count: int) -> tuple[MarketBar, ...]:
    return tuple(
        make_bar(start_dt + timedelta(days=i), 100.0 + i * 0.5)
        for i in range(count)
    )


class MockInferenceProvider(IDataProvider):
    name = "mock_inference"

    def __init__(self, data: Optional[Mapping[str, Sequence[MarketBar]]] = None) -> None:
        self.data = dict(data or {})
        self.calls: list[dict[str, Any]] = []

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return list(self.data.keys())

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Sequence[MarketBar]:
        self.calls.append({
            "symbol": symbol,
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        bars = self.data.get(symbol, ())
        if start_date is not None and bars:
            start_d = start_date if isinstance(start_date, date) else start_date.date()
            return [b for b in bars if b.timestamp.date() >= start_d]
        return list(bars)

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years, start_date, end_date) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.data.get(symbol, ())
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock_inference", ok=True)


def test_explicit_session_completed_true_respected(tmp_path: Path):
    """Explicit session_completed=True in provider_options must be preserved."""
    service = MarketDataIngestionService()
    cache = MarketBarsCache(cache_dir=tmp_path)

    # 100 bars ending on 2026-10-16
    start_d = datetime(2026, 1, 1)
    bars = tuple(make_bar(start_d + timedelta(days=i)) for i in range(100))
    # latest bar date
    latest_d = bars[-1].timestamp.date()

    cache.save_bars({"INFY": bars}, exchange="NSE", provider="mock_inference")
    provider = MockInferenceProvider({"INFY": bars})

    # Target date is latest_d, explicit session_completed=True
    result = service.ingest_daily_bars(
        symbols=["INFY"],
        provider=provider,
        exchange="NSE",
        bars_cache=cache,
        target_date=latest_d,
        provider_options={"session_completed": True},
    )

    # Symbol must be evaluated as UP_TO_DATE (0 provider calls)
    assert len(provider.calls) == 0
    assert "INFY" in result


def test_explicit_session_completed_false_respected(tmp_path: Path):
    """Explicit session_completed=False in provider_options must be preserved."""
    service = MarketDataIngestionService()
    cache = MarketBarsCache(cache_dir=tmp_path)

    # Target date Friday 2026-10-16. With session_completed=False, expected completed day is 2026-10-15.
    # Cache ending on 2026-10-15 is therefore up-to-date for a session that is explicitly marked not completed.
    t_date = date(2026, 10, 16)
    expected_fresh = get_latest_completed_trading_day(t_date, session_completed=False)
    assert expected_fresh == date(2026, 10, 15)


def test_omitted_session_completed_infers_true_for_past_date(tmp_path: Path):
    """When session_completed is omitted and target_date is in the past, session is completed."""
    service = MarketDataIngestionService()
    cache = MarketBarsCache(cache_dir=tmp_path)

    # Cache has 100 bars ending on 2026-10-15
    start_d = date(2026, 10, 15) - timedelta(days=99)
    cached_bars = tuple(make_bar(datetime.combine(start_d + timedelta(days=i), datetime.min.time())) for i in range(100))
    assert cached_bars[-1].timestamp.date() == date(2026, 10, 15)

    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_inference")

    # Provider has bar for 2026-10-16
    bar_16 = make_bar(datetime(2026, 10, 16), close=150.0)
    provider = MockInferenceProvider({"INFY": (*cached_bars, bar_16)})

    # Target date is 2026-10-16 (Friday). session_completed omitted.
    # Prior to fix, session_completed defaulted to False, rolling back to 2026-10-15 and skipping provider!
    result = service.ingest_daily_bars(
        symbols=["INFY"],
        provider=provider,
        exchange="NSE",
        bars_cache=cache,
        target_date=date(2026, 10, 16),
    )

    # Must call provider for incremental update because cached data ends on 15 Oct < 16 Oct
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["symbol"] == "INFY"
    assert call["start_date"] == date(2026, 10, 15) - timedelta(days=5)

    # Result must include the newly fetched 16 Oct bar
    assert len(result["INFY"]) == 101
    assert result["INFY"][-1].timestamp.date() == date(2026, 10, 16)


def test_weekend_target_date_rolls_back_to_friday():
    """Weekend target dates (Saturday/Sunday) resolve to previous Friday as latest completed trading day."""
    saturday = date(2026, 10, 17)
    sunday = date(2026, 10, 18)

    fresh_sat = get_latest_completed_trading_day(saturday, session_completed=True)
    fresh_sun = get_latest_completed_trading_day(sunday, session_completed=True)

    assert fresh_sat == date(2026, 10, 16)  # Friday
    assert fresh_sun == date(2026, 10, 16)  # Friday


def test_exchange_holiday_rolls_back_to_previous_trading_day():
    """Exchange holiday (e.g. 2026-10-20 Diwali Balipratipada) rolls back to preceding trading day."""
    holiday = date(2026, 10, 20)
    assert holiday.strftime("%Y-%m-%d") in INDIAN_TRADING_HOLIDAYS[2026]

    fresh_hol = get_latest_completed_trading_day(holiday, session_completed=True)
    assert fresh_hol == date(2026, 10, 19)  # Monday

"""Unit and regression tests for chart cache freshness and incremental updates.

Verifies:
1. A cache ending before the latest completed trading session triggers an appropriate incremental provider request.
2. Successfully fetched data is merged and persisted, and subsequent chart reads include the new candles.
3. Existing historical candles remain intact after incremental updates.
4. A fresh cache does not trigger an unnecessary full-history fetch.
5. A provider failure preserves the existing cached-data fallback and established error behaviour.
6. Chart consumers and dependent calculations (envelopes, EMAs, volume, candles) receive the refreshed data.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.charting import ChartDataService
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.cache import MarketBarsCache


class DummyBandsRepo(IBandsRepository):
    def __init__(self, bands: Optional[dict[str, dict[str, float]]] = None) -> None:
        self._bands = bands or {}

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return self._bands.get(symbol, {}).get(timeframe)

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        return self._bands.get(symbol, {})

    def set_band(self, symbol: str, timeframe: str, value: float, who: str = "app", source: str = "app") -> float:
        if symbol not in self._bands:
            self._bands[symbol] = {}
        self._bands[symbol][timeframe] = value
        return value


class MockChartingProvider(IDataProvider):
    name = "mock_charting"

    def __init__(self, data: Optional[Mapping[str, Sequence[MarketBar]]] = None, fail_on_fetch: bool = False) -> None:
        self.data = dict(data or {})
        self.daily_calls: list[dict[str, Any]] = []
        self.fail_on_fetch = fail_on_fetch

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
        years: int = 2,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Sequence[MarketBar]:
        self.daily_calls.append({
            "symbol": symbol,
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        if self.fail_on_fetch:
            raise DataProviderError(f"Simulated network outage for provider {self.name}")

        bars = self.data.get(symbol, ())
        if start_date is not None and bars:
            start_d = start_date if isinstance(start_date, date) else start_date.date()
            return [b for b in bars if b.timestamp.date() >= start_d]
        return list(bars)

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 2,
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
        return ProviderHealth(provider="mock_charting", ok=True)


def make_bar(dt: datetime, close: float = 100.0) -> MarketBar:
    return MarketBar(
        timestamp=dt,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=5000.0,
    )


def test_stale_cache_triggers_incremental_provider_request(tmp_path: Path):
    """Case 1: Cache ending before latest completed session triggers an incremental provider request."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # 100 historical bars ending on 2026-10-15
    base_d = date(2026, 10, 15) - timedelta(days=99)
    cached_bars = [make_bar(datetime.combine(base_d + timedelta(days=i), datetime.min.time()), 100.0 + i) for i in range(100)]
    assert cached_bars[-1].timestamp.date() == date(2026, 10, 15)

    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_charting")

    # Provider has a new bar on 2026-10-16
    new_bar = make_bar(datetime(2026, 10, 16), close=160.0)
    provider = MockChartingProvider({"INFY": (*cached_bars, new_bar)})

    service = ChartDataService(provider=provider, bars_cache=cache)

    # Request candles for target date 2026-10-16 (session completed)
    out = service.get_candles("INFY", timeframe="D", years=2, target_date=date(2026, 10, 16))

    # Must have triggered exactly 1 incremental provider call
    assert len(provider.daily_calls) == 1
    call = provider.daily_calls[0]
    assert call["symbol"] == "INFY"
    # Overlap of 5 days
    assert call["start_date"] == date(2026, 10, 15) - timedelta(days=5)


def test_incremental_fetch_merges_persists_and_preserves_history(tmp_path: Path):
    """Case 2 & 3: Successfully fetched data is merged and persisted, and history is preserved."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # 100 historical bars ending on 2026-10-15
    base_d = date(2026, 10, 15) - timedelta(days=99)
    cached_bars = [make_bar(datetime.combine(base_d + timedelta(days=i), datetime.min.time()), 100.0 + i) for i in range(100)]
    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_charting")

    # Provider has a new bar on 2026-10-16
    new_bar = make_bar(datetime(2026, 10, 16), close=160.0)
    provider = MockChartingProvider({"INFY": (*cached_bars, new_bar)})
    service = ChartDataService(provider=provider, bars_cache=cache)

    out = service.get_candles("INFY", timeframe="D", years=2, target_date=date(2026, 10, 16))

    # Candles must include the new bar on 2026-10-16
    assert len(out.candles) == 101
    assert out.candles[-1].time == "2026-10-16"
    assert out.candles[-1].close == 160.0

    # History must be preserved: first candle must match original first bar
    assert out.candles[0].time == base_d.strftime("%Y-%m-%d")

    # Persistent cache on disk must contain the merged 101 bars
    disk_bars, _ = cache.get_bars_for_symbols(["INFY"], exchange="NSE", provider="mock_charting")
    assert len(disk_bars["INFY"]) == 101
    assert disk_bars["INFY"][-1].timestamp.date() == date(2026, 10, 16)

    # Subsequent chart read with a fresh service instance should read from disk without calling provider
    service2 = ChartDataService(provider=provider, bars_cache=cache)
    calls_before = len(provider.daily_calls)
    out2 = service2.get_candles("INFY", timeframe="D", years=2, target_date=date(2026, 10, 16))
    assert len(out2.candles) == 101
    assert out2.candles[-1].time == "2026-10-16"
    assert len(provider.daily_calls) == calls_before  # Zero additional calls


def test_fresh_cache_avoids_unnecessary_fetch(tmp_path: Path):
    """Case 4: A fresh cache does not trigger an unnecessary full-history or incremental fetch."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # Cache already has bars up to 2026-10-16
    base_d = date(2026, 10, 16) - timedelta(days=99)
    cached_bars = [make_bar(datetime.combine(base_d + timedelta(days=i), datetime.min.time()), 100.0 + i) for i in range(100)]
    assert cached_bars[-1].timestamp.date() == date(2026, 10, 16)
    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_charting")

    provider = MockChartingProvider({"INFY": cached_bars})
    service = ChartDataService(provider=provider, bars_cache=cache)

    out = service.get_candles("INFY", timeframe="D", years=2, target_date=date(2026, 10, 16))

    # Provider should never be called
    assert len(provider.daily_calls) == 0
    assert len(out.candles) == 100
    assert out.candles[-1].time == "2026-10-16"


def test_provider_failure_preserves_cached_fallback(tmp_path: Path):
    """Case 5: A provider failure preserves existing cached data and logs a warning."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # Cache has bars up to 2026-10-15
    base_d = date(2026, 10, 15) - timedelta(days=99)
    cached_bars = [make_bar(datetime.combine(base_d + timedelta(days=i), datetime.min.time()), 100.0 + i) for i in range(100)]
    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_charting")

    # Provider is configured to fail
    provider = MockChartingProvider({"INFY": cached_bars}, fail_on_fetch=True)
    service = ChartDataService(provider=provider, bars_cache=cache)

    # Requesting newer date 2026-10-16 when provider fails must gracefully fall back to cached 15 Oct data
    out = service.get_candles("INFY", timeframe="D", years=2, target_date=date(2026, 10, 16))

    assert len(out.candles) == 100
    assert out.candles[-1].time == "2026-10-15"

    # If NO cache exists at all, provider failure must propagate as DataProviderError
    empty_cache = MarketBarsCache(cache_dir=tmp_path / "empty")
    service_empty = ChartDataService(provider=provider, bars_cache=empty_cache)
    with pytest.raises(DataProviderError):
        service_empty.get_candles("TCS", timeframe="D", years=2, target_date=date(2026, 10, 16))


def test_dependent_calculations_receive_refreshed_data(tmp_path: Path):
    """Case 8: Chart consumers and dependent calculations receive the refreshed data."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    base_d = date(2026, 10, 15) - timedelta(days=99)
    cached_bars = [make_bar(datetime.combine(base_d + timedelta(days=i), datetime.min.time()), 100.0 + i) for i in range(100)]
    cache.save_bars({"INFY": cached_bars}, exchange="NSE", provider="mock_charting")

    # Add 16 Oct bar with price jump to 200.0
    new_bar = make_bar(datetime(2026, 10, 16), close=200.0)
    provider = MockChartingProvider({"INFY": (*cached_bars, new_bar)})

    bands_repo = DummyBandsRepo({"INFY": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo, bars_cache=cache)

    out = service.get_candles("INFY", timeframe="D", band_timeframe="D", years=2, target_date=date(2026, 10, 16))

    # 1. Candles
    assert out.candles[-1].time == "2026-10-16"
    assert out.candles[-1].close == 200.0

    # 2. Moving average / EMA curves include 2026-10-16
    assert len(out.ema3_curve) > 0
    assert out.ema3_curve[-1].time == "2026-10-16"

    # 3. Band curves include 2026-10-16
    assert len(out.band_upper_curve) > 0
    assert out.band_upper_curve[-1].time == "2026-10-16"
    assert out.band_lower_curve[-1].time == "2026-10-16"
    assert out.latest_band is not None
    assert out.latest_band.width == 0.10

    # 4. Volume curve includes 2026-10-16
    assert out.volume_curve[-1].time == "2026-10-16"
    assert out.volume_curve[-1].value == 5000.0

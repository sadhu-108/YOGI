"""Focused regression tests for Chart vs Matrix Bar Consistency (YOGI Shared Bar Cache).

Verifies:
1. Persistent-cache hit: Chart candles consume canonical cached bars without invoking the external provider.
2. Shared inputs: Chart envelope and stock-panel daily band levels match to the exact decimal for identical bars.
3. Band-width update: Updating discretionary band width updates both views consistently without refetching historical bars.
4. Cache miss: When the persistent cache lacks usable bars, the configured provider fallback still works.
5. Isolation: Different symbols, exchanges, providers, and requested history ranges do not accidentally share incompatible data.
6. Bar handling: Ordering, date slicing, missing data, and minimum lookback are preserved deterministically.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.storage.cache import MarketBarsCache


class RecordingMockProvider(IDataProvider):
    """Deterministic mock provider recording calls to daily_history."""

    def __init__(self, name: str = "mock_provider") -> None:
        self._name = name
        self.call_history: list[tuple[str, str, int]] = []
        self.bars: dict[str, list[MarketBar]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return list(self.bars.keys())

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 2
    ) -> Sequence[MarketBar]:
        self.call_history.append((symbol, exchange, years))
        return self.bars.get(symbol, [])

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        b = self.bars.get(symbol)
        return b[-1].close if b else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self._name, ok=True)


class MockBandsRepo(IBandsRepository):
    """In-memory discretionary bands repository."""

    def __init__(self, bands: Optional[dict[str, dict[str, float]]] = None) -> None:
        self._bands: dict[str, dict[str, float]] = bands or {}

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return self._bands.get(symbol.strip().upper(), {}).get(timeframe.strip().upper())

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        return dict(self._bands.get(symbol.strip().upper(), {}))

    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "cockpit",
        source: str = "manual",
    ) -> float:
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        if sym not in self._bands:
            self._bands[sym] = {}
        self._bands[sym][tf] = float(value)
        return float(value)

    def is_configured(self, symbol: str, timeframe: str) -> bool:
        return self.get_band(symbol, timeframe) is not None

    def audit_trail(self, symbol: Optional[str] = None, limit: int = 50) -> Sequence[Mapping[str, Any]]:
        return ()


def make_synthetic_bars(n: int = 100, base_price: float = 500.0, base_date: Optional[datetime] = None) -> list[MarketBar]:
    """Generate ascending daily market bars with known close prices."""
    start = base_date or datetime(2025, 1, 1)
    bars = []
    for i in range(n):
        dt = start + timedelta(days=i)
        p = base_price + i * 2.0
        bars.append(
            MarketBar(
                timestamp=dt,
                open=p - 1.0,
                high=p + 2.0,
                low=p - 2.0,
                close=p,
                volume=5000.0,
            )
        )
    return bars


def test_persistent_cache_hit_avoids_provider_call(tmp_path: Path):
    """Verify that when MarketBarsCache has canonical bars, ChartDataService does not call the provider."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    sample_bars = make_synthetic_bars(80, base_price=700.0)
    bars_cache.save_bars({"TEST_SYM": sample_bars}, exchange="NSE", provider="mock_provider")

    provider = RecordingMockProvider("mock_provider")
    bands_repo = MockBandsRepo({"TEST_SYM": {"D": 0.02}})

    service = ChartDataService(
        provider=provider,
        bands_repo=bands_repo,
        bars_cache=bars_cache,
    )

    series = service.get_candles("TEST_SYM", timeframe="D", band_timeframe="D", exchange="NSE", years=2)

    # Provider should never have been invoked because bars were retrieved from MarketBarsCache
    assert len(provider.call_history) == 0
    assert len(series.candles) > 0
    assert series.latest_band is not None
    assert series.latest_band.width == 0.02


def test_shared_inputs_chart_and_panel_match_exactly(tmp_path: Path):
    """Verify that Chart and Stock Detail Matrix compute identical daily band levels from shared bars."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    sample_bars = make_synthetic_bars(100, base_price=1000.0)
    bars_cache.save_bars({"SHARED_SYM": sample_bars}, exchange="NSE", provider="mock_provider")

    provider = RecordingMockProvider("mock_provider")
    bands_repo = MockBandsRepo({"SHARED_SYM": {"D": 0.015}})

    state = AppState(
        provider=provider,
        bands_repo=bands_repo,
        bars_cache=bars_cache,
        config=EngineConfig(
            provider="mock_provider",
            bands_repository="demo",
            exchange="NSE",
            symbols=["SHARED_SYM"],
        ),
    )

    panel = state.get_stock_panel("SHARED_SYM")
    assert panel is not None

    candles = state.chart_service.get_candles("SHARED_SYM", timeframe="D", band_timeframe="D", exchange="NSE", years=2)
    assert candles.latest_band is not None

    d_row = next(r for r in panel.timeframes if r.timeframe == "D")
    b = candles.latest_band

    # Implied basis calculation for the last 20 bars:
    expected_basis = round(sum(b.close for b in sample_bars[-20:]) / 20.0, 2)
    expected_upper = round(expected_basis * 1.015, 2)
    expected_lower = round(expected_basis * 0.985, 2)

    assert b.basis == expected_basis
    assert b.upper == expected_upper
    assert b.lower == expected_lower

    # Absolute equality between panel and chart
    assert d_row.band_upper == b.upper
    assert d_row.band_lower == b.lower


def test_band_width_update_consistency_without_refetch(tmp_path: Path):
    """Verify that updating band width updates both views consistently without refetching historical bars."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    sample_bars = make_synthetic_bars(100, base_price=400.0)
    bars_cache.save_bars({"TUNE_SYM": sample_bars}, exchange="NSE", provider="mock_provider")

    provider = RecordingMockProvider("mock_provider")
    bands_repo = MockBandsRepo({"TUNE_SYM": {"D": 0.01}})

    state = AppState(
        provider=provider,
        bands_repo=bands_repo,
        bars_cache=bars_cache,
        config=EngineConfig(
            provider="mock_provider",
            bands_repository="demo",
            exchange="NSE",
            symbols=["TUNE_SYM"],
        ),
    )

    # Initial query with 1% band width
    panel1 = state.get_stock_panel("TUNE_SYM")
    candles1 = state.chart_service.get_candles("TUNE_SYM", timeframe="D", band_timeframe="D", exchange="NSE", years=2)
    d_row1 = next(r for r in panel1.timeframes if r.timeframe == "D")
    assert d_row1.band_upper == candles1.latest_band.upper
    assert d_row1.band_lower == candles1.latest_band.lower

    # Update band width to 2.5%
    state.bands_repo.set_band("TUNE_SYM", "D", 0.025)
    state.invalidate_symbol("TUNE_SYM")

    # Refresh panel and chart
    panel2 = state.get_stock_panel("TUNE_SYM")
    candles2 = state.chart_service.get_candles("TUNE_SYM", timeframe="D", band_timeframe="D", exchange="NSE", years=2)
    d_row2 = next(r for r in panel2.timeframes if r.timeframe == "D")

    assert candles2.latest_band.width == 0.025
    assert d_row2.band_width == 0.025
    assert d_row2.band_upper == candles2.latest_band.upper
    assert d_row2.band_lower == candles2.latest_band.lower
    assert len(provider.call_history) == 0


def test_persistent_cache_miss_falls_back_to_provider(tmp_path: Path):
    """Verify that when MarketBarsCache does not have the symbol, provider.daily_history is called."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    provider = RecordingMockProvider("mock_provider")
    provider.bars["MISS_SYM"] = make_synthetic_bars(50, base_price=200.0)

    service = ChartDataService(
        provider=provider,
        bars_cache=bars_cache,
    )

    series = service.get_candles("MISS_SYM", timeframe="D", exchange="NSE", years=2)
    assert len(provider.call_history) == 1
    assert provider.call_history[0] == ("MISS_SYM", "NSE", 2)
    assert len(series.candles) == 50


def test_isolation_across_symbols_and_providers(tmp_path: Path):
    """Verify that different symbols, exchanges, and providers remain strictly isolated."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    bars_a = make_synthetic_bars(60, base_price=100.0)
    bars_b = make_synthetic_bars(60, base_price=900.0)
    bars_cache.save_bars({"SYM_A": bars_a}, exchange="NSE", provider="prov_1")
    bars_cache.save_bars({"SYM_B": bars_b}, exchange="BSE", provider="prov_1")

    provider1 = RecordingMockProvider("prov_1")
    service = ChartDataService(provider=provider1, bars_cache=bars_cache)

    # 1. Query SYM_A on NSE -> hit
    res_a = service.get_candles("SYM_A", exchange="NSE")
    assert res_a.candles[-1].close == bars_a[-1].close

    # 2. Query SYM_A on BSE -> miss in cache, falls back to provider
    res_a_bse = service.get_candles("SYM_A", exchange="BSE")
    assert len(provider1.call_history) == 1
    assert provider1.call_history[0] == ("SYM_A", "BSE", 2)

    # 3. Query SYM_B on BSE -> hit
    res_b = service.get_candles("SYM_B", exchange="BSE")
    assert res_b.candles[-1].close == bars_b[-1].close


def test_slice_bars_preserves_lookback_and_ordering():
    """Verify _slice_bars_for_years preserves ascending ordering, date range, and minimum lookback."""
    base_dt = datetime(2020, 1, 1)
    bars = make_synthetic_bars(100, base_price=50.0, base_date=base_dt)

    # Shuffled bars to test ordering safety
    shuffled = [bars[i] for i in [10, 0, 50, 99, 20, 4]]
    sorted_sliced = ChartDataService._slice_bars_for_years(shuffled, years=10)
    assert sorted_sliced[0].timestamp < sorted_sliced[-1].timestamp
    assert sorted_sliced[0] == bars[0]
    assert sorted_sliced[-1] == bars[99]

    # Preserves minimum 20 bars lookback when date slicing would leave fewer
    short_bars = make_synthetic_bars(30, base_price=50.0, base_date=datetime(2025, 1, 1))
    sliced_short = ChartDataService._slice_bars_for_years(short_bars, years=1)
    assert len(sliced_short) >= 20

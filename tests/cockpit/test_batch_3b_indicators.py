"""Integration tests for Batch 3B: Price / Volatility Technical Indicators in ChartDataService & API.

Verifies:
1. Bollinger Bands (20, 2) curve and summary exposure in CandleSeriesOut.
2. Donchian Channels (20) curve and summary exposure in CandleSeriesOut.
3. ATR Volatility Bands (14, 2.0) curve and summary exposure in CandleSeriesOut.
4. Cumulative VWAP curve exposure matching visible chart window.
5. Average Price Line exposure matching average_price().
6. Short history handling (< 20 bars, < 14 bars, 0 bars) returning safe defaults without crash.
7. Missing volume bars handled cleanly without fabrication.
8. Seamless coexistence with Batch 2 cross-timeframe band envelope (band_tf).
9. Cockpit Router (/api/candles/{symbol}) serialization and status code parity.
10. Screening engine isolation: zero side effects or changes to screening metrics.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence
import numpy as np
import pandas as pd
import pytest

from yogi.calculation.bands.calculator import (
    calculate_atr_bands,
    calculate_bollinger_bands,
    calculate_donchian_channels,
)
from yogi.calculation.trend.calculator import (
    average_price,
    calculate_vwap,
)
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.router import get_candles
from yogi.cockpit.schemas import (
    ATRBandsSeriesOut,
    BollingerSeriesOut,
    CandleSeriesOut,
    DonchianSeriesOut,
)
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.configuration.query import ScreeningQuery



class DummyProvider(IDataProvider):
    name = "dummy_batch3b"

    def __init__(self, bars: Sequence[MarketBar]) -> None:
        self._bars = list(bars)

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["TEST_SYM"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        if symbol == "TEST_SYM":
            return self._bars
        return []

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2):
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return self._bars[-1].close if self._bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5):
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick, exchange: str = "NSE"):
        return None

    def trading_holidays(self, year: Optional[int] = None):
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="dummy_batch3b", ok=True)


class DummyBandsRepo(IBandsRepository):
    def __init__(self, bands: Optional[dict[str, dict[str, float]]] = None) -> None:
        self._bands = bands or {}

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return self._bands.get(symbol, {}).get(timeframe)

    def get_all_bands(self, symbol: str):
        return self._bands.get(symbol, {})

    def set_band(self, symbol: str, timeframe: str, value: float, who: str = "app", source: str = "app") -> float:
        if symbol not in self._bands:
            self._bands[symbol] = {}
        self._bands[symbol][timeframe] = value
        return value


def generate_bars(
    n: int = 30,
    base_price: float = 100.0,
    with_volume: bool = True,
    vol_value: float = 1000.0,
) -> list[MarketBar]:
    base_date = datetime(2026, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
        # Add realistic variability
        o = base_price + i * 0.5
        h = o + 2.0
        l = o - 2.0
        c = o + 1.0
        vol = (vol_value + i * 50) if with_volume else None
        bars.append(MarketBar(timestamp=dt, open=o, high=h, low=l, close=c, volume=vol))
    return bars


# =============================================================================
# 1. Full Series Integration & Numerical Parity Tests
# =============================================================================

def test_chart_data_service_bollinger_bands_parity():
    """Verify ChartDataService exposes Bollinger Bands matching calculate_bollinger_bands()."""
    bars = generate_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.bollinger is not None
    assert isinstance(res.bollinger, BollingerSeriesOut)

    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    bb_expected = calculate_bollinger_bands(closes, window=20, num_std=2.0)

    # 30 bars, window=20 -> 11 valid rolling points (indices 19 to 29)
    assert len(res.bollinger.upper) == 11
    assert len(res.bollinger.lower) == 11
    assert len(res.bollinger.basis) == 11

    # Check last values
    assert res.bollinger.last_basis == round(bb_expected.last_basis, 2)
    assert res.bollinger.last_upper == round(bb_expected.last_upper, 2)
    assert res.bollinger.last_lower == round(bb_expected.last_lower, 2)

    # Verify time alignment
    assert res.bollinger.upper[-1].time == bars[-1].timestamp.strftime("%Y-%m-%d")
    assert res.bollinger.upper[-1].value == round(bb_expected.last_upper, 2)


def test_chart_data_service_donchian_channels_parity():
    """Verify ChartDataService exposes Donchian Channels matching calculate_donchian_channels()."""
    bars = generate_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.donchian is not None
    assert isinstance(res.donchian, DonchianSeriesOut)

    highs = pd.Series([b.high for b in bars], index=[b.timestamp for b in bars])
    lows = pd.Series([b.low for b in bars], index=[b.timestamp for b in bars])
    dc_expected = calculate_donchian_channels(highs, lows, window=20)

    assert len(res.donchian.upper) == 11
    assert len(res.donchian.lower) == 11
    assert len(res.donchian.middle) == 11

    assert res.donchian.last_upper == round(dc_expected.last_upper, 2)
    assert res.donchian.last_lower == round(dc_expected.last_lower, 2)
    assert res.donchian.last_middle == round(dc_expected.last_middle, 2)


def test_chart_data_service_atr_bands_parity():
    """Verify ChartDataService exposes ATR Volatility Bands matching calculate_atr_bands()."""
    bars = generate_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.atr_bands is not None
    assert isinstance(res.atr_bands, ATRBandsSeriesOut)

    highs = pd.Series([b.high for b in bars], index=[b.timestamp for b in bars])
    lows = pd.Series([b.low for b in bars], index=[b.timestamp for b in bars])
    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    atr_expected = calculate_atr_bands(highs, lows, closes, period=14, multiplier=2.0)

    # 30 bars, period=14 -> 17 valid rolling points (indices 13 to 29)
    assert len(res.atr_bands.upper) == 17
    assert len(res.atr_bands.lower) == 17
    assert len(res.atr_bands.atr) == 17

    assert res.atr_bands.last_upper == round(atr_expected.last_upper, 2)
    assert res.atr_bands.last_lower == round(atr_expected.last_lower, 2)
    assert res.atr_bands.last_atr == round(atr_expected.last_atr, 2)


def test_chart_data_service_vwap_and_avg_price():
    """Verify VWAP curve and Average Price match formulas."""
    bars = generate_bars(n=30, base_price=100.0, with_volume=True)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    # VWAP
    highs = pd.Series([b.high for b in bars], index=[b.timestamp for b in bars])
    lows = pd.Series([b.low for b in bars], index=[b.timestamp for b in bars])
    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    vols = pd.Series([b.volume for b in bars], index=[b.timestamp for b in bars])
    vwap_expected = calculate_vwap(highs, lows, closes, vols)

    assert len(res.vwap_curve) == 30
    assert res.vwap_curve[-1].value == round(float(vwap_expected.iloc[-1]), 2)

    # Average price
    avg_expected = average_price(closes)
    assert res.avg_price == round(avg_expected, 2)


# =============================================================================
# 2. Edge Case & Missing Data Tests
# =============================================================================

def test_short_series_graceful_fallbacks():
    """Verify that series with fewer than window bars return None without crashing."""
    # 10 bars: less than 14 (ATR) and less than 20 (BB, Donchian)
    bars = generate_bars(n=10, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.bollinger is None
    assert res.donchian is None
    assert res.atr_bands is None
    # But VWAP and avg_price are still valid
    assert len(res.vwap_curve) == 10
    assert res.avg_price is not None


def test_missing_volume_handling():
    """Verify missing volume (None) does not crash VWAP and is preserved in volume_curve."""
    bars = generate_bars(n=25, base_price=100.0, with_volume=False)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    # Volume curve should have value=None points
    assert len(res.volume_curve) == 25
    assert all(pt.value is None for pt in res.volume_curve)

    # VWAP should be empty since all volume is missing/None
    assert len(res.vwap_curve) == 0

    # Bollinger and Donchian remain unaffected
    assert res.bollinger is not None
    assert res.donchian is not None


def test_empty_bars_service_response():
    """Verify empty provider history returns clean empty CandleSeriesOut."""
    provider = DummyProvider([])
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.candles == []
    assert res.bollinger is None
    assert res.donchian is None
    assert res.atr_bands is None
    assert res.vwap_curve == []
    assert res.avg_price is None


# =============================================================================
# 3. Cross-Timeframe Band Coexistence (Batch 2 Compatibility)
# =============================================================================

def test_coexistence_with_batch2_cross_timeframe_bands():
    """Verify that using band_timeframe != timeframe works seamlessly alongside Batch 3B indicators."""
    bars = generate_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.25}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D", band_timeframe="M")

    # Batch 2 envelope check
    assert res.latest_band is not None
    assert res.latest_band.timeframe == "D"
    assert res.latest_band.band_timeframe == "M"
    assert res.latest_band.width == 0.25

    # Batch 3B indicators are fully populated on candle timeframe D
    assert res.bollinger is not None
    assert res.donchian is not None
    assert res.atr_bands is not None
    assert len(res.vwap_curve) == 30
    assert res.avg_price is not None


# =============================================================================
# 4. Router API Endpoint Test
# =============================================================================

def test_cockpit_router_endpoint_serialization():
    """Verify /api/candles/{symbol} returns CandleSeriesOut with Batch 3B indicators."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    class MockAppState:
        chart_service = service

    res = get_candles(symbol="TEST_SYM", tf="D", band_tf="D", app_state=MockAppState())
    assert isinstance(res, CandleSeriesOut)
    assert res.bollinger is not None
    assert res.donchian is not None
    assert res.atr_bands is not None
    assert len(res.vwap_curve) == 25
    assert res.avg_price is not None


# =============================================================================
# 5. Screening Pipeline Isolation Test
# =============================================================================

def test_screening_pipeline_isolation():
    """Verify that adding Batch 3B indicators causes zero side-effects to the screening pipeline."""
    from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
    from yogi.core.contracts.ranking import RankingOrder
    from yogi.core.orchestration.pipeline import PipelineOrchestrator
    from yogi.core.registry.hub import RegistryHub
    from yogi.filter.engine import FilterEngine
    from yogi.ranking.engine import RankingEngine
    from yogi.results.assembler import ResultAssembler
    from yogi.selection.engine import SelectionEngine

    dataset = {
        "S1": {"symbol": "S1", "M_CUR": 20.0, "EMA_W": "upcut", "price": 100.0},
        "S2": {"symbol": "S2", "M_CUR": 10.0, "EMA_W": "no", "price": 50.0},
        "S3": {"symbol": "S3", "M_CUR": 30.0, "EMA_W": "upcut", "price": 200.0},
    }

    pipeline = PipelineOrchestrator(
        registry=RegistryHub(),
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        result_assembler=ResultAssembler(),
    )

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="upcut")]
        ),
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        limit=2,
    )

    result = pipeline.execute_screen(query=query, records=dataset)

    assert len(result.rows) == 2
    assert result.rows[0]["symbol"] == "S3"
    assert result.rows[1]["symbol"] == "S1"
    assert result.qualified_count == 2

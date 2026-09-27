"""Integration tests for Batch 3C: Oscillators (RSI, MACD, OBV, MFI) in ChartDataService & API.

Verifies:
1. Relative Strength Index (RSI 14) exposure in CandleSeriesOut.
2. Moving Average Convergence Divergence (MACD 12, 26, 9) curves and scalars in CandleSeriesOut.
3. On-Balance Volume (OBV) exposure in CandleSeriesOut.
4. Money Flow Index (MFI 14) exposure in CandleSeriesOut.
5. Short history handling (< 15 bars, < 2 bars, 0 bars) returning safe defaults without exceptions.
6. Missing volume bars handled cleanly without fabrication.
7. Seamless coexistence with Batch 2 cross-timeframe bands, Batch 3A series, and Batch 3B indicators.
8. Cockpit Router (/api/candles/{symbol}) serialization and status code parity.
9. Screening engine isolation: zero side effects or changes to screening metrics.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence
import numpy as np
import pandas as pd
import pytest

from yogi.calculation.trend.calculator import (
    calculate_macd,
    calculate_mfi,
    calculate_obv,
    calculate_rsi,
)
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.router import get_candles
from yogi.cockpit.schemas import (
    CandleSeriesOut,
    MACDSeriesOut,
    MFISeriesOut,
    OBVSeriesOut,
    RSISeriesOut,
)
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth


class DummyProvider(IDataProvider):
    name = "dummy_batch3c"

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
        return ProviderHealth(provider="dummy_batch3c", ok=True)


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
    n: int = 35,
    base_price: float = 100.0,
    with_volume: bool = True,
    vol_value: float = 1000.0,
) -> list[MarketBar]:
    base_date = datetime(2026, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
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

def test_chart_data_service_rsi_parity():
    """Verify ChartDataService exposes RSI matching calculate_rsi()."""
    bars = generate_bars(n=35, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.rsi is not None
    assert isinstance(res.rsi, RSISeriesOut)
    assert len(res.rsi_curve) > 0

    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    rsi_expected = calculate_rsi(closes, period=14)

    # 35 bars, period 14 -> 35 - 14 = 21 valid points
    assert len(res.rsi.points) == 21
    assert len(res.rsi_curve) == 21
    assert res.rsi.last_rsi == round(rsi_expected.last_rsi, 2)
    assert res.rsi.points[-1].value == round(rsi_expected.last_rsi, 2)
    assert res.rsi.points[-1].time == bars[-1].timestamp.strftime("%Y-%m-%d")


def test_chart_data_service_macd_parity():
    """Verify ChartDataService exposes MACD matching calculate_macd()."""
    bars = generate_bars(n=35, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.macd is not None
    assert isinstance(res.macd, MACDSeriesOut)
    assert len(res.macd.macd) == 35
    assert len(res.macd.signal) == 35
    assert len(res.macd.histogram) == 35

    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    macd_expected = calculate_macd(closes, fast_period=12, slow_period=26, signal_period=9)

    assert res.macd.last_macd == round(macd_expected.last_macd, 2)
    assert res.macd.last_signal == round(macd_expected.last_signal, 2)
    assert res.macd.last_histogram == round(macd_expected.last_histogram, 2)


def test_chart_data_service_obv_parity():
    """Verify ChartDataService exposes OBV matching calculate_obv()."""
    bars = generate_bars(n=35, base_price=100.0, with_volume=True)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.obv is not None
    assert isinstance(res.obv, OBVSeriesOut)
    assert len(res.obv_curve) == 35

    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    volumes = pd.Series([b.volume for b in bars], index=[b.timestamp for b in bars])
    obv_expected = calculate_obv(closes, volumes)

    assert res.obv.last_obv == round(obv_expected.last_obv, 2)
    assert res.obv.points[-1].value == round(obv_expected.last_obv, 2)


def test_chart_data_service_mfi_parity():
    """Verify ChartDataService exposes MFI matching calculate_mfi()."""
    bars = generate_bars(n=35, base_price=100.0, with_volume=True)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.mfi is not None
    assert isinstance(res.mfi, MFISeriesOut)
    assert len(res.mfi_curve) > 0

    highs = pd.Series([b.high for b in bars], index=[b.timestamp for b in bars])
    lows = pd.Series([b.low for b in bars], index=[b.timestamp for b in bars])
    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    volumes = pd.Series([b.volume for b in bars], index=[b.timestamp for b in bars])
    mfi_expected = calculate_mfi(highs, lows, closes, volumes, period=14)

    # 35 bars, period 14 -> 35 - 13 = 22 valid points
    assert len(res.mfi.points) == 22
    assert len(res.mfi_curve) == 22
    assert res.mfi.last_mfi == round(mfi_expected.last_mfi, 2)
    assert res.mfi.points[-1].value == round(mfi_expected.last_mfi, 2)


# =============================================================================
# 2. Edge Case & Missing Data Tests
# =============================================================================

def test_short_series_graceful_fallbacks():
    """Verify that series with fewer than window bars return None without crashing."""
    # 10 bars: less than 15 (RSI, MFI) but >= 2 (MACD)
    bars = generate_bars(n=10, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.rsi is None
    assert res.rsi_curve == []
    assert res.mfi is None
    assert res.mfi_curve == []
    # MACD computes for >= 2 bars
    assert res.macd is not None
    assert len(res.macd.macd) == 10
    # OBV computes for > 0 bars with volume
    assert res.obv is not None
    assert len(res.obv.points) == 10


def test_missing_volume_handling():
    """Verify missing volume (None) does not crash OBV/MFI and returns None/empty."""
    bars = generate_bars(n=35, base_price=100.0, with_volume=False)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    # OBV and MFI should be None when all volume is missing
    assert res.obv is None
    assert res.obv_curve == []
    assert res.mfi is None
    assert res.mfi_curve == []

    # RSI and MACD are price-only and remain fully populated
    assert res.rsi is not None
    assert res.macd is not None


def test_empty_bars_service_response():
    """Verify empty provider history returns clean empty CandleSeriesOut."""
    provider = DummyProvider([])
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert res.candles == []
    assert res.rsi is None
    assert res.macd is None
    assert res.obv is None
    assert res.mfi is None
    assert res.rsi_curve == []
    assert res.obv_curve == []
    assert res.mfi_curve == []


# =============================================================================
# 3. Coexistence with Prior Batches (Batch 2, 3A, 3B Compatibility)
# =============================================================================

def test_coexistence_with_all_prior_batches():
    """Verify that Batch 2 cross-timeframe bands, Batch 3A, and Batch 3B coexist seamlessly."""
    bars = generate_bars(n=35, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.25}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D", band_timeframe="M")

    # Batch 2: cross-timeframe band
    assert res.latest_band is not None
    assert res.latest_band.timeframe == "D"
    assert res.latest_band.band_timeframe == "M"
    assert res.latest_band.width == 0.25

    # Batch 3A: EMA, DMI, Volume, ATH
    assert len(res.ema3_curve) == 35
    assert len(res.ema5_curve) == 35
    assert res.dmi_series is not None
    assert res.ath_diff is not None

    # Batch 3B: Bollinger, Donchian, ATR, VWAP, avgPrice
    assert res.bollinger is not None
    assert res.donchian is not None
    assert res.atr_bands is not None
    assert len(res.vwap_curve) == 35
    assert res.avg_price is not None

    # Batch 3C: RSI, MACD, OBV, MFI
    assert res.rsi is not None
    assert res.macd is not None
    assert res.obv is not None
    assert res.mfi is not None


# =============================================================================
# 4. Router API Endpoint Test
# =============================================================================

def test_cockpit_router_endpoint_serialization():
    """Verify /api/candles/{symbol} returns CandleSeriesOut with Batch 3C oscillators."""
    bars = generate_bars(n=35, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    class MockAppState:
        chart_service = service

    res = get_candles(symbol="TEST_SYM", tf="D", band_tf="D", app_state=MockAppState())
    assert isinstance(res, CandleSeriesOut)
    assert res.rsi is not None
    assert res.macd is not None
    assert res.obv is not None
    assert res.mfi is not None
    assert len(res.rsi_curve) > 0
    assert len(res.obv_curve) > 0
    assert len(res.mfi_curve) > 0


# =============================================================================
# 5. Screening Pipeline Isolation Test
# =============================================================================

def test_screening_pipeline_isolation():
    """Verify that adding Batch 3C oscillators causes zero side-effects to the screening pipeline."""
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

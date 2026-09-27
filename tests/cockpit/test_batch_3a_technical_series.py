"""Unit and integration tests for Batch 3A: Existing Technical-Series Exposure.

Verifies:
1. EMA3 & EMA5 curve exposure matching TrendCalculator.ema() with zero numerical drift.
2. SMA20 / Basis curve exposure matching BandsCalculator.calculate_band_envelope().
3. DMI / ADX chronological time-series and summary matching TrendCalculator.dmi().
4. Volume curve preservation, handling None, zero, and standard values without fabrication.
5. ATH drawdown percentage matching TrendCalculator.ath_diff().
6. API endpoint /api/candles/{symbol} backward compatibility and Batch 2 band_tf preservation.
7. Screening isolation: technical-series chart exposure causes zero regression in screening pipeline.
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence
import pandas as pd
import pytest

from yogi.calculation.bands.calculator import (
    band_state,
    calculate_band_envelope,
)
from yogi.calculation.trend.calculator import (
    ath_diff,
    dmi,
    dmi_state,
    ema,
)
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.router import get_candles
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth


class DummyProvider(IDataProvider):
    name = "dummy_batch3a"

    def __init__(self, bars: Sequence[MarketBar]) -> None:
        self._bars = list(bars)

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["TEST_STOCK"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        if symbol == "TEST_STOCK":
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
        return ProviderHealth(provider="dummy_batch3a", ok=True)


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


def generate_ohlcv_bars(
    n: int = 40,
    base_price: float = 100.0,
    with_volume: bool = True,
    volume_pattern: Optional[str] = "standard",
) -> list[MarketBar]:
    """Generate realistic synthetic OHLCV daily bars."""
    base_date = datetime(2025, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
        # Add slight non-linear variation
        c = base_price + i * 1.5 + (2.0 if i % 2 == 0 else -1.0)
        h = c + 3.0 + (i % 3)
        l = c - 2.5 - (i % 2)
        o = (c + l) / 2.0

        vol: Optional[float] = None
        if with_volume:
            if volume_pattern == "with_zeros" and i % 5 == 0:
                vol = 0.0
            elif volume_pattern == "with_nones" and i % 7 == 0:
                vol = None
            else:
                vol = 1000.0 + i * 50.0

        bars.append(
            MarketBar(
                timestamp=dt,
                open=round(o, 2),
                high=round(h, 2),
                low=round(l, 2),
                close=round(c, 2),
                volume=vol,
            )
        )
    return bars


# =============================================================================
# 1. EMA3 & EMA5 Tests + Numerical Parity
# =============================================================================

def test_ema3_and_ema5_exposure_and_numerical_parity():
    """Verify EMA3 and EMA5 curves match authoritative TrendCalculator.ema with zero drift."""
    bars = generate_ohlcv_bars(n=30)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")

    assert len(res.ema3_curve) == 30
    assert len(res.ema5_curve) == 30

    # Authoritative reference calculation directly from TrendCalculator
    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    expected_ema3 = ema(closes, span=3)
    expected_ema5 = ema(closes, span=5)

    for i in range(30):
        t_str = bars[i].timestamp.strftime("%Y-%m-%d")
        assert res.ema3_curve[i].time == t_str
        assert res.ema5_curve[i].time == t_str

        # Numerical parity verification: no drift beyond 2-decimal rounding
        assert res.ema3_curve[i].value == round(float(expected_ema3.iloc[i]), 2)
        assert res.ema5_curve[i].value == round(float(expected_ema5.iloc[i]), 2)


# =============================================================================
# 2. SMA20 / Basis Curve & Band Level Tests
# =============================================================================

def test_basis_curve_and_band_level_exposure():
    """Verify basis_curve (SMA20) matches BandsCalculator.calculate_band_envelope."""
    bars = generate_ohlcv_bars(n=35)
    bands_repo = DummyBandsRepo({"TEST_STOCK": {"D": 0.15}})
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    closes = [float(b.close) for b in bars]
    envelope = calculate_band_envelope(closes=closes, band_frac=0.15, basis_window=20)
    expected_bs = band_state(bars=closes, band_frac=0.15, basis_window=20)
    valid_basis = envelope.basis.dropna()

    res = service.get_candles("TEST_STOCK", timeframe="D")

    assert len(res.basis_curve) == len(valid_basis)
    assert len(res.band_upper_curve) == len(valid_basis)
    assert len(res.band_lower_curve) == len(valid_basis)

    for i, (idx, val) in enumerate(valid_basis.items()):
        assert res.basis_curve[i].time == bars[idx].timestamp.strftime("%Y-%m-%d")
        assert res.basis_curve[i].value == round(float(val), 2)

    assert res.latest_band is not None
    assert res.latest_band.basis == round(envelope.last_basis, 2)
    assert res.latest_band.band_distance == expected_bs.get("bd")
    assert res.latest_band.band_state == expected_bs.get("state")


# =============================================================================
# 3. DMI / ADX Time Series & Summary Tests
# =============================================================================

def test_dmi_adx_series_and_summary_exposure():
    """Verify +DI, -DI, ADX series and summary match TrendCalculator.dmi."""
    bars = generate_ohlcv_bars(n=40)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")

    assert res.dmi_series is not None
    assert res.dmi_summary is not None

    # Reference calculation directly from TrendCalculator.dmi
    df = pd.DataFrame(
        {
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
        },
        index=[b.timestamp for b in bars],
    )
    expected_dmi = dmi(df, period=14, adx_period=14)
    expected_state = dmi_state(
        expected_dmi.get("plus_di"),
        expected_dmi.get("minus_di"),
        expected_dmi.get("adx"),
    )

    # Check summary metrics
    assert res.dmi_summary.plus_di == expected_dmi["plus_di"]
    assert res.dmi_summary.minus_di == expected_dmi["minus_di"]
    assert res.dmi_summary.adx == expected_dmi["adx"]
    assert res.dmi_summary.adxr == expected_dmi["adxr"]
    assert res.dmi_summary.state == expected_state
    assert res.dmi_summary.period == 14
    assert res.dmi_summary.adx_period == 14

    # Check series points and numerical parity
    p_s = expected_dmi["series"]["plus"]
    m_s = expected_dmi["series"]["minus"]
    a_s = expected_dmi["series"]["adx"]

    assert len(res.dmi_series.plus) == len(p_s)
    assert len(res.dmi_series.minus) == len(m_s)
    assert len(res.dmi_series.adx) == len(a_s)

    for i in range(len(res.dmi_series.plus)):
        assert res.dmi_series.plus[i].value == round(float(p_s.iloc[i]), 2)
        assert res.dmi_series.minus[i].value == round(float(m_s.iloc[i]), 2)


def test_dmi_adx_short_or_flat_history_handled_safely():
    """Verify DMI returns None gracefully when history is < 6 bars or high == low."""
    # 1. Very short history (< 6 bars)
    short_bars = generate_ohlcv_bars(n=4)
    provider = DummyProvider(short_bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")
    assert res.dmi_series is None
    assert res.dmi_summary is None

    # 2. Flat bars where high == low (no true range variation)
    base_date = datetime(2025, 1, 1)
    flat_bars = [
        MarketBar(timestamp=base_date + timedelta(days=i), open=100.0, high=100.0, low=100.0, close=100.0, volume=10.0)
        for i in range(10)
    ]
    flat_provider = DummyProvider(flat_bars)
    flat_service = ChartDataService(provider=flat_provider)
    flat_res = flat_service.get_candles("TEST_STOCK", timeframe="D")
    assert flat_res.dmi_series is None
    assert flat_res.dmi_summary is None


# =============================================================================
# 4. Volume Curve Tests (Preservation & No Fabrication)
# =============================================================================

def test_volume_preservation_and_zero_handling():
    """Verify volume points preserve exact values, zero volume, and None without fabrication."""
    bars = generate_ohlcv_bars(n=20, volume_pattern="with_zeros")
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")
    assert len(res.volume_curve) == 20

    for i in range(20):
        t_str = bars[i].timestamp.strftime("%Y-%m-%d")
        assert res.volume_curve[i].time == t_str
        assert res.volume_curve[i].value == bars[i].volume
        # Check zeros are preserved as 0.0, not converted to None or dropped
        if i % 5 == 0:
            assert res.volume_curve[i].value == 0.0


def test_missing_volume_handled_safely():
    """Verify missing volume (None) is preserved cleanly."""
    bars = generate_ohlcv_bars(n=20, with_volume=False)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")
    assert len(res.volume_curve) == 20
    for pt in res.volume_curve:
        assert pt.value is None


# =============================================================================
# 5. ATH Drawdown Exposure Tests
# =============================================================================

def test_ath_diff_exposure_and_parity():
    """Verify ath_diff matches TrendCalculator.ath_diff."""
    bars = generate_ohlcv_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="D")

    closes = pd.Series([b.close for b in bars], index=[b.timestamp for b in bars])
    expected_ath_diff = ath_diff(closes)

    assert res.ath_diff is not None
    assert res.ath_diff == round(float(expected_ath_diff), 2)


# =============================================================================
# 6. Backward Compatibility & Cross-Timeframe Preservation
# =============================================================================

def test_batch_2_band_tf_and_empty_candles_preserved():
    """Verify Batch 2 cross-timeframe band behavior remains 100% intact."""
    bars = generate_ohlcv_bars(n=30)
    bands_repo = DummyBandsRepo({"TEST_STOCK": {"D": 0.10, "M": 0.25}})
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    # Cross-timeframe band: Daily candles + Monthly band
    res = service.get_candles("TEST_STOCK", timeframe="D", band_timeframe="M")
    assert res.latest_band is not None
    assert res.latest_band.timeframe == "D"
    assert res.latest_band.band_timeframe == "M"
    assert res.latest_band.width == 0.25
    assert len(res.basis_curve) == 21  # 30 bars - 9 warm-up bars for 20-bar SMA (min_periods=10)
    assert len(res.ema3_curve) == 30
    assert len(res.ema5_curve) == 30

    # Band suppression: band_timeframe="NONE"
    res_none = service.get_candles("TEST_STOCK", timeframe="D", band_timeframe="NONE")
    assert res_none.band_upper_curve == []
    assert res_none.band_lower_curve == []
    assert len(res_none.basis_curve) == 21  # Basis SMA20 is still present!
    assert len(res_none.ema3_curve) == 30

    # Empty stock
    empty_res = service.get_candles("NON_EXISTENT", timeframe="D")
    assert empty_res.candles == []
    assert empty_res.basis_curve == []
    assert empty_res.ema3_curve == []
    assert empty_res.ema5_curve == []
    assert empty_res.volume_curve == []
    assert empty_res.dmi_series is None
    assert empty_res.dmi_summary is None
    assert empty_res.ath_diff is None


# =============================================================================
# 7. FastAPI Route Integration Test
# =============================================================================

def test_route_candles_technical_series_integration():
    """Verify route handler get_candles() returns all new technical series."""
    from yogi.cockpit.state import AppState

    bars = generate_ohlcv_bars(n=30)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_STOCK": {"D": 0.12}})
    chart_service = ChartDataService(provider=provider, bands_repo=bands_repo)

    state = AppState(
        chart_service=chart_service,
        bands_repo=bands_repo,
    )

    out = get_candles(
        symbol="TEST_STOCK",
        tf="D",
        band_tf="D",
        exchange="NSE",
        years=2,
        app_state=state,
    )

    assert out.symbol == "TEST_STOCK"
    assert len(out.candles) == 30
    assert len(out.basis_curve) == 21
    assert len(out.ema3_curve) == 30
    assert len(out.ema5_curve) == 30
    assert len(out.volume_curve) == 30
    assert out.dmi_series is not None
    assert len(out.dmi_series.plus) > 0
    assert out.dmi_summary is not None
    assert out.dmi_summary.plus_di is not None
    assert out.ath_diff is not None
    assert out.latest_band is not None
    assert out.latest_band.band_distance is not None
    assert out.latest_band.band_state is not None


# =============================================================================
# 8. Timeframe Resampling Test (Weekly Candles)
# =============================================================================

def test_weekly_resampled_technical_series():
    """Verify indicators calculate directly on resampled weekly candle series."""
    # 70 daily bars (~14 weeks)
    bars = generate_ohlcv_bars(n=70)
    provider = DummyProvider(bars)
    service = ChartDataService(provider=provider)

    res = service.get_candles("TEST_STOCK", timeframe="W")

    assert res.timeframe == "W"
    n_weeks = len(res.candles)
    assert n_weeks > 5

    # EMA3 and EMA5 curves match the number of weekly candles
    assert len(res.ema3_curve) == n_weeks
    assert len(res.ema5_curve) == n_weeks
    assert len(res.volume_curve) == n_weeks

    # DMI/ADX calculated on weekly bars
    if n_weeks >= 6:
        assert res.dmi_series is not None
        assert res.dmi_summary is not None
        assert res.dmi_summary.plus_di is not None


# =============================================================================
# 9. Screening Pipeline Isolation Test
# =============================================================================

def test_screening_pipeline_isolation():
    """Verify chart technical series exposure does not alter screening results or pipeline."""
    from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
    from yogi.core.contracts.ranking import RankingOrder
    from yogi.core.configuration.query import ScreeningQuery
    from yogi.core.orchestration.pipeline import PipelineOrchestrator
    from yogi.filter.engine import FilterEngine
    from yogi.ranking.engine import RankingEngine
    from yogi.selection.engine import SelectionEngine
    from yogi.results.assembler import ResultAssembler

    dataset = {
        "S1": {"symbol": "S1", "M_CUR": 20.0, "EMA_W": "upcut", "price": 100.0},
        "S2": {"symbol": "S2", "M_CUR": 10.0, "EMA_W": "no", "price": 50.0},
        "S3": {"symbol": "S3", "M_CUR": 30.0, "EMA_W": "upcut", "price": 200.0},
    }

    from yogi.core.registry.hub import RegistryHub

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

    # Output strictly follows QUALIFY -> ORDER -> SHOW -> LIMIT -> RESULTS
    assert len(result.rows) == 2
    assert result.rows[0]["symbol"] == "S3"  # 30.0
    assert result.rows[1]["symbol"] == "S1"  # 20.0
    assert result.qualified_count == 2

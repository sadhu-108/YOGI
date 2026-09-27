"""Integration and API tests for Batch 3D YOGI Custom Curves in Cockpit layer.

Verifies:
- ChartDataService integration for y_sprint, y_accel, y_band, y_roc
- Batch 2 cross-timeframe band distance synthesis and suppression
- Router endpoint get_candles serialization
- Graceful degradation for short history and flat series
- Seamless coexistence with Batches 1, 2, 3A, 3B, and 3C
- Backward compatibility of CandleSeriesOut schema
"""

from datetime import datetime, timedelta
from typing import Optional, Sequence
import pytest

from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.router import get_candles
from yogi.cockpit.schemas import (
    BandCurvePointOut,
    CandleSeriesOut,
    YAccelSeriesOut,
    YBandSeriesOut,
    YRocSeriesOut,
    YSprintSeriesOut,
)
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth


class DummyProvider(IDataProvider):
    name = "dummy_batch3d"

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
        return ProviderHealth(provider="dummy_batch3d", ok=True)


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
    n: int = 300,
    base_price: float = 100.0,
    price_step: float = 0.5,
    with_volume: bool = True,
) -> list[MarketBar]:
    base_date = datetime(2025, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
        o = base_price + i * price_step
        h = o + 2.0
        l = o - 2.0
        c = o + 1.0
        vol = (1000.0 + i * 50) if with_volume else None
        bars.append(MarketBar(timestamp=dt, open=o, high=h, low=l, close=c, volume=vol))
    return bars


class MockAppState:
    def __init__(self, chart_service):
        self.chart_service = chart_service


class TestBatch3DCustomCurves:
    """Test suite for Batch 3D custom curves in ChartDataService and HTTP Router."""

    def test_chart_data_service_includes_custom_curves(self):
        bars = generate_bars(n=300, base_price=100.0)
        provider = DummyProvider(bars)
        bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.15, "M": 0.20}})
        service = ChartDataService(provider=provider, bands_repo=bands_repo)

        res = service.get_candles(symbol="TEST_SYM", timeframe="D", exchange="NSE", years=2, band_timeframe="M")
        assert isinstance(res, CandleSeriesOut)

        # 1. YOGI Sprint Speed
        assert res.y_sprint is not None
        assert isinstance(res.y_sprint, YSprintSeriesOut)
        assert res.y_sprint.weeks == 4
        assert len(res.y_sprint.points) > 0
        assert len(res.y_sprint_curve) == len(res.y_sprint.points)

        # 2. YOGI Acceleration (4w vs 52w)
        assert res.y_accel is not None
        assert isinstance(res.y_accel, YAccelSeriesOut)
        assert res.y_accel.short_weeks == 4
        assert res.y_accel.long_weeks == 52
        assert len(res.y_accel.points) > 0
        assert len(res.y_accel_curve) == len(res.y_accel.points)

        # 3. YOGI Band Distance
        assert res.y_band is not None
        assert isinstance(res.y_band, YBandSeriesOut)
        assert res.y_band.basis_window == 20
        assert res.y_band.band_frac == 0.20
        assert len(res.y_band.points) > 0
        assert len(res.y_band_curve) == len(res.y_band.points)

        # 4. YOGI ROC (21 days)
        assert res.y_roc is not None
        assert isinstance(res.y_roc, YRocSeriesOut)
        assert res.y_roc.days == 21
        assert len(res.y_roc.points) > 0
        assert len(res.y_roc_curve) == len(res.y_roc.points)

    def test_chart_data_service_short_history_custom_curves(self):
        # 10 bars: insufficient for sprint speed (>20), accel (>260), or roc (>21)
        bars = generate_bars(n=10)
        provider = DummyProvider(bars)
        service = ChartDataService(provider=provider)

        res = service.get_candles(symbol="TEST_SYM", timeframe="D", exchange="NSE", years=1)
        assert res.y_sprint is None
        assert res.y_sprint_curve == []
        assert res.y_accel is None
        assert res.y_accel_curve == []
        assert res.y_roc is None
        assert res.y_roc_curve == []

    def test_cockpit_router_get_candles_custom_curves(self):
        bars = generate_bars(n=300, base_price=100.0)
        provider = DummyProvider(bars)
        bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.20}})
        service = ChartDataService(provider=provider, bands_repo=bands_repo)
        app_state = MockAppState(chart_service=service)

        res = get_candles(symbol="TEST_SYM", tf="D", exchange="NSE", years=2, app_state=app_state)
        assert isinstance(res, CandleSeriesOut)

        assert res.y_sprint is not None
        assert len(res.y_sprint.points) > 0
        assert res.y_accel is not None
        assert len(res.y_accel.points) > 0
        assert res.y_band is not None
        assert len(res.y_band.points) > 0
        assert res.y_roc is not None
        assert len(res.y_roc.points) > 0

        assert len(res.y_sprint_curve) > 0
        assert len(res.y_accel_curve) > 0
        assert len(res.y_band_curve) > 0
        assert len(res.y_roc_curve) > 0

    def test_cockpit_router_band_distance_cross_timeframe(self):
        bars = generate_bars(n=300, base_price=100.0)
        provider = DummyProvider(bars)
        bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.25}})
        service = ChartDataService(provider=provider, bands_repo=bands_repo)
        app_state = MockAppState(chart_service=service)

        # 1. With Monthly band timeframe
        res_m = get_candles(symbol="TEST_SYM", tf="D", band_tf="M", years=2, app_state=app_state)
        assert res_m.y_band is not None
        assert len(res_m.y_band.points) > 0
        assert res_m.y_band.band_frac == 0.25

        # 2. Suppressed with band_tf=NONE
        res_none = get_candles(symbol="TEST_SYM", tf="D", band_tf="NONE", years=2, app_state=app_state)
        assert res_none.y_band is None
        assert res_none.y_band_curve == []

    def test_cockpit_flat_series(self):
        base_date = datetime(2025, 1, 1)
        bars = [
            MarketBar(timestamp=base_date + timedelta(days=i), open=100.0, high=100.0, low=100.0, close=100.0, volume=1000.0)
            for i in range(300)
        ]
        provider = DummyProvider(bars)
        bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
        service = ChartDataService(provider=provider, bands_repo=bands_repo)

        res = service.get_candles(symbol="TEST_SYM", timeframe="D", exchange="NSE", years=2, band_timeframe="D")

        # All curves must evaluate to 0.0 without division by zero or errors
        assert res.y_sprint is not None
        assert res.y_sprint.last_speed == pytest.approx(0.0)
        assert res.y_accel is not None
        assert res.y_accel.last_accel == pytest.approx(0.0)
        assert res.y_band is not None
        assert res.y_band.last_distance == pytest.approx(0.0)
        assert res.y_roc is not None
        assert res.y_roc.last_roc == pytest.approx(0.0)

    def test_coexistence_with_batches_1_to_3c(self):
        bars = generate_bars(n=300, base_price=100.0)
        provider = DummyProvider(bars)
        bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.20}})
        service = ChartDataService(provider=provider, bands_repo=bands_repo)

        res = service.get_candles(symbol="TEST_SYM", timeframe="D", exchange="NSE", years=2, band_timeframe="M")

        # Batch 2: cross-timeframe band
        assert res.latest_band is not None
        assert res.latest_band.band_timeframe == "M"

        # Batch 3A: EMA, DMI, Volume, ATH
        assert len(res.ema3_curve) == 300
        assert len(res.ema5_curve) == 300
        assert res.dmi_series is not None
        assert res.ath_diff is not None

        # Batch 3B: Bollinger, Donchian, ATR, VWAP, avg_price
        assert res.bollinger is not None
        assert res.donchian is not None
        assert res.atr_bands is not None
        assert len(res.vwap_curve) == 300
        assert res.avg_price is not None

        # Batch 3C: RSI, MACD, OBV, MFI
        assert res.rsi is not None
        assert res.macd is not None
        assert res.obv is not None
        assert res.mfi is not None

        # Batch 3D: y_sprint, y_accel, y_band, y_roc
        assert res.y_sprint is not None
        assert res.y_accel is not None
        assert res.y_band is not None
        assert res.y_roc is not None

    def test_schema_serialization_custom_curves(self):
        pt = BandCurvePointOut(time="2026-03-01", value=4.5)

        sprint_model = YSprintSeriesOut(points=[pt], weeks=4, last_speed=4.5)
        accel_model = YAccelSeriesOut(points=[pt], short_weeks=4, long_weeks=52, last_accel=1.2)
        band_model = YBandSeriesOut(points=[pt], basis_window=20, band_frac=0.15, last_distance=0.0)
        roc_model = YRocSeriesOut(points=[pt], days=21, last_roc=5.2)

        assert sprint_model.model_dump()["last_speed"] == 4.5
        assert accel_model.model_dump()["short_weeks"] == 4
        assert band_model.model_dump()["band_frac"] == 0.15
        assert roc_model.model_dump()["days"] == 21

    def test_backward_compatibility_candle_series_out(self):
        payload = {
            "symbol": "INFY",
            "exchange": "NSE",
            "timeframe": "D",
            "candles": [],
            "band_upper_curve": [],
            "band_lower_curve": [],
        }
        res = CandleSeriesOut(**payload)
        assert res.y_sprint is None
        assert res.y_accel is None
        assert res.y_band is None
        assert res.y_roc is None
        assert res.y_sprint_curve == []
        assert res.y_accel_curve == []
        assert res.y_band_curve == []
        assert res.y_roc_curve == []

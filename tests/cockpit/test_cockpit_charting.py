"""Unit tests for ChartDataService and verified financial band semantics."""

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.charting import ChartDataService
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider
from yogi.timeframe.engine import TimeframeEngine


class DummyProvider(IDataProvider):
    name = "dummy"

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

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return self._bars[-1].close if self._bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self):
        from yogi.core.contracts.provider import ProviderHealth
        return ProviderHealth(provider="dummy", ok=True)


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


def generate_bars(n: int = 30, base_price: float = 100.0) -> list[MarketBar]:
    base_date = datetime(2025, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
        p = base_price + i * 2.0  # steadily climbing from 100 to 158
        bars.append(
            MarketBar(
                timestamp=dt,
                open=p - 1.0,
                high=p + 2.0,
                low=p - 2.0,
                close=p,
                volume=1000.0,
            )
        )
    return bars


def test_chart_data_service_empty():
    provider = DummyProvider([])
    service = ChartDataService(provider=provider)

    res = service.get_candles("UNKNOWN", timeframe="D")
    assert res.candles == []
    assert res.band_upper_curve == []
    assert res.band_lower_curve == []
    assert res.latest_band is None


def test_chart_data_service_verified_band_semantics():
    """Verify that Upper/Lower bands are strictly centered on Basis = SMA(Close, bw), NOT Close."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})  # 10% band
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert len(res.candles) == 25
    # First 9 bars are NaN due to min_periods = max(2, bw // 2) = 10, leaving 16 points
    assert len(res.band_upper_curve) == 16
    assert len(res.band_lower_curve) == 16
    assert res.latest_band is not None

    latest_close = bars[-1].close  # 100 + 24*2 = 148.0
    latest_band = res.latest_band
    assert latest_band.width == 0.10

    # Calculate expected 20-period SMA basis of the last 20 closes
    last_20_closes = [b.close for b in bars[-20:]]
    expected_basis = sum(last_20_closes) / 20.0
    expected_upper = expected_basis * 1.10
    expected_lower = expected_basis * 0.90

    assert latest_band.basis == round(expected_basis, 2)
    assert latest_band.upper == round(expected_upper, 2)
    assert latest_band.lower == round(expected_lower, 2)

    # CRITICAL: Verify Upper is NOT Close * (1 + w)
    flawed_upper = latest_close * 1.10
    assert latest_band.upper != round(flawed_upper, 2)
    # Because prices are climbing, SMA(20) < Close, so expected_upper < flawed_upper
    assert latest_band.upper < flawed_upper

    # Direct parity proof: ChartDataService semantics strictly match Core band_state for N >= 20
    from yogi.calculation.bands.calculator import band_state
    all_closes = [b.close for b in bars]
    core_calc = band_state(all_closes, band_frac=0.10, basis_window=20)
    assert latest_band.basis == round(core_calc["basis"], 2)
    assert latest_band.upper == round(core_calc["up"], 2)
    assert latest_band.lower == round(core_calc["lo"], 2)


def test_chart_data_service_weekly_resampling():
    """Verify multi-timeframe resampling in ChartDataService for weekly bars."""
    bars = generate_bars(n=35, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"W": 0.15}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="W")
    # 35 daily bars should resample into ~5-6 weekly bars
    assert 4 <= len(res.candles) <= 7
    assert res.timeframe == "W"
    assert res.latest_band is not None
    assert res.latest_band.width == 0.15


def test_chart_data_service_short_history_5_bars():
    """Verify short-history (5 bars) behavior adheres strictly to authoritative calculator.py math."""
    from yogi.calculation.bands.calculator import band_state

    bars = generate_bars(n=5, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert len(res.candles) == 5
    assert res.latest_band is not None

    # N = 5 -> bw = max(3, 5 // 2) = 3, min_periods = max(2, 3 // 2) = 2
    # Basis is the 3-period SMA of the last 3 bars: [104, 106, 108] -> 106.0
    expected_basis = (bars[2].close + bars[3].close + bars[4].close) / 3.0
    expected_upper = expected_basis * 1.10
    expected_lower = expected_basis * 0.90

    assert res.latest_band.basis == round(expected_basis, 2)
    assert res.latest_band.upper == round(expected_upper, 2)
    assert res.latest_band.lower == round(expected_lower, 2)

    # Compare directly with Core band_state output
    closes = [b.close for b in bars]
    core_calc = band_state(closes, band_frac=0.10, basis_window=20)
    assert res.latest_band.basis == round(core_calc["basis"], 2)
    assert res.latest_band.upper == round(core_calc["up"], 2)
    assert res.latest_band.lower == round(core_calc["lo"], 2)


def test_chart_data_service_insufficient_history_under_3_bars():
    """Verify history with < 3 bars produces no band curves, matching calculator.py len(bars) < 3."""
    # 2 bars
    bars_2 = generate_bars(n=2, base_price=100.0)
    provider_2 = DummyProvider(bars_2)
    bands_repo_2 = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service_2 = ChartDataService(provider=provider_2, bands_repo=bands_repo_2)

    res_2 = service_2.get_candles("TEST_SYM", timeframe="D")
    assert len(res_2.candles) == 2
    assert res_2.band_upper_curve == []
    assert res_2.band_lower_curve == []
    assert res_2.latest_band is None

    # 1 bar
    bars_1 = generate_bars(n=1, base_price=100.0)
    provider_1 = DummyProvider(bars_1)
    service_1 = ChartDataService(provider=provider_1, bands_repo=bands_repo_2)

    res_1 = service_1.get_candles("TEST_SYM", timeframe="D")
    assert len(res_1.candles) == 1
    assert res_1.band_upper_curve == []
    assert res_1.band_lower_curve == []
    assert res_1.latest_band is None


def test_chart_data_service_does_not_mutate_input_bars():
    """Verify get_candles leaves original MarketBar sequences untouched."""
    bars = generate_bars(n=10, base_price=100.0)
    original_closes = [b.close for b in bars]
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D")
    assert len(res.candles) == 10

    # Ensure provider bars remain identical in length and values
    assert [b.close for b in provider._bars] == original_closes


def test_chart_data_service_no_band_width_produces_basis_only():
    """Verify that when no band width is configured, basis is calculated but upper/lower curves are empty."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({})  # No width configured for TEST_SYM
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D")

    assert len(res.candles) == 25
    assert res.band_upper_curve == []
    assert res.band_lower_curve == []
    assert res.latest_band is not None
    assert res.latest_band.basis is not None
    assert res.latest_band.upper is None
    assert res.latest_band.lower is None
    assert res.latest_band.width is None


def test_chart_data_service_delegation_to_authoritative_band_calculator(monkeypatch):
    """Verify ChartDataService explicitly calls calculate_band_envelope from Core."""
    import yogi.cockpit.charting as charting_module

    call_count = 0
    orig_calc = charting_module.calculate_band_envelope

    def spy_calc(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return orig_calc(*args, **kwargs)

    monkeypatch.setattr(charting_module, "calculate_band_envelope", spy_calc)

    bars = generate_bars(n=10, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    res = service.get_candles("TEST_SYM", timeframe="D")
    assert call_count == 1
    assert res.latest_band is not None


# =============================================================================
# Batch 2: Cross-Timeframe Band Envelope Synthesis Tests
# =============================================================================

def test_chart_data_service_cross_timeframe_synthesis_d_candles_m_band():
    """Verify Daily candles + Monthly band combines Daily 20-bar basis with Monthly band width.
    
    Guarantees no accidental basis projection:
    - Basis is SMA(Daily Close, 20), NOT Monthly SMA.
    - Width is stored Monthly width (0.25).
    - Upper = Daily Basis * (1 + 0.25).
    - Lower = Daily Basis * (1 - 0.25).
    """
    bars = generate_bars(n=30, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({
        "TEST_SYM": {
            "D": 0.10,
            "W": 0.18,
            "M": 0.25,
            "Q": 0.35,
        }
    })
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    # Request Daily candles with Monthly band envelope
    res = service.get_candles("TEST_SYM", timeframe="D", band_timeframe="M")

    # 1. Candles are Daily
    assert len(res.candles) == 30
    assert res.timeframe == "D"

    # 2. Envelope curves are present and time-aligned with daily bars
    assert len(res.band_upper_curve) == 21  # 30 bars - (bw//2 - 1) = 21 valid rolling points
    assert len(res.band_lower_curve) == 21

    # 3. BandLevelOut reflects both candle timeframe and band timeframe
    assert res.latest_band is not None
    assert res.latest_band.timeframe == "D"
    assert res.latest_band.band_timeframe == "M"
    assert res.latest_band.width == 0.25

    # 4. Mathematical verification:
    # Expected basis = SMA of last 20 daily closes
    last_20_daily_closes = [b.close for b in bars[-20:]]
    expected_daily_basis = sum(last_20_daily_closes) / 20.0
    expected_upper = expected_daily_basis * 1.25
    expected_lower = expected_daily_basis * 0.75

    assert res.latest_band.basis == round(expected_daily_basis, 2)
    assert res.latest_band.upper == round(expected_upper, 2)
    assert res.latest_band.lower == round(expected_lower, 2)

    # 5. Proof: Upper curve values match daily basis * (1 + 0.25)
    last_upper_curve_pt = res.band_upper_curve[-1]
    assert last_upper_curve_pt.value == round(expected_upper, 2)
    assert last_upper_curve_pt.time == bars[-1].timestamp.strftime("%Y-%m-%d")


def test_chart_data_service_cross_timeframe_multiple_standard_combinations():
    """Verify representative standard cross-timeframe combinations (D+W, D+Q, D+H, D+Y, W+M, W+Q)."""
    bars = generate_bars(n=60, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({
        "TEST_SYM": {
            "D": 0.08,
            "W": 0.14,
            "M": 0.22,
            "Q": 0.30,
            "H": 0.40,
            "Y": 0.50,
        }
    })
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    test_combos = [
        ("D", "W", 0.14),
        ("D", "Q", 0.30),
        ("D", "H", 0.40),
        ("D", "Y", 0.50),
        ("W", "M", 0.22),
        ("W", "Q", 0.30),
    ]

    for ctf, btf, expected_width in test_combos:
        res = service.get_candles("TEST_SYM", timeframe=ctf, band_timeframe=btf)
        assert res.timeframe == ctf
        assert res.latest_band is not None
        assert res.latest_band.timeframe == ctf
        assert res.latest_band.band_timeframe == btf
        assert res.latest_band.width == expected_width

        # Numerical verification
        basis = res.latest_band.basis
        assert basis is not None
        assert res.latest_band.upper == round(basis * (1.0 + expected_width), 2)
        assert res.latest_band.lower == round(basis * (1.0 - expected_width), 2)


def test_chart_data_service_band_suppression():
    """Verify band_timeframe in ('', 'NONE', 'OFF', 'none', 'off') suppresses envelope curves."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.20}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    suppression_values = ["", "NONE", "OFF", "none", "off"]

    for supp in suppression_values:
        res = service.get_candles("TEST_SYM", timeframe="D", band_timeframe=supp)
        assert len(res.candles) == 25
        assert res.band_upper_curve == []
        assert res.band_lower_curve == []
        assert res.latest_band is not None
        # Basis is STILL calculated: basis math is never altered merely because bands are off
        assert res.latest_band.basis is not None
        assert res.latest_band.band_timeframe is None
        assert res.latest_band.width is None
        assert res.latest_band.upper is None
        assert res.latest_band.lower is None


def test_chart_data_service_backward_compatibility_omitted_band_timeframe():
    """Verify that omitting band_timeframe preserves existing behavior exactly (defaults to candle tf)."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10, "M": 0.25}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    # Call with omitted band_timeframe
    res_default = service.get_candles("TEST_SYM", timeframe="D")

    # Call with explicit band_timeframe="D"
    res_explicit = service.get_candles("TEST_SYM", timeframe="D", band_timeframe="D")

    assert res_default.latest_band is not None
    assert res_explicit.latest_band is not None
    assert res_default.latest_band.width == 0.10
    assert res_explicit.latest_band.width == 0.10
    assert res_default.latest_band.basis == res_explicit.latest_band.basis
    assert res_default.latest_band.upper == res_explicit.latest_band.upper
    assert res_default.latest_band.lower == res_explicit.latest_band.lower
    assert len(res_default.band_upper_curve) == len(res_explicit.band_upper_curve)


def test_chart_data_service_invalid_band_timeframe_raises_value_error():
    """Verify unsupported band timeframe raises ValueError adhering to standard YOGI conventions."""
    bars = generate_bars(n=25, base_price=100.0)
    provider = DummyProvider(bars)
    bands_repo = DummyBandsRepo({"TEST_SYM": {"D": 0.10}})
    service = ChartDataService(provider=provider, bands_repo=bands_repo)

    with pytest.raises(ValueError, match="Unsupported band timeframe '2W'"):
        service.get_candles("TEST_SYM", timeframe="D", band_timeframe="2W")

    with pytest.raises(ValueError, match="Unsupported band timeframe 'INVALID'"):
        service.get_candles("TEST_SYM", timeframe="D", band_timeframe="INVALID")




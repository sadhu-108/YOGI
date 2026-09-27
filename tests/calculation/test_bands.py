"""Unit tests for BandsCalculator and envelope mathematics."""

from datetime import datetime, timedelta
import pandas as pd
import pytest

from yogi.calculation.bands import (
    BandEnvelopeResult,
    BandsCalculator,
    band_state,
    calculate_band_envelope,
)
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext


def test_band_inside_is_in():
    bars = [100.0] * 40
    r = band_state(bars, 0.10)
    assert r["state"] == "IN"
    assert r["bd"] == 0.0
    assert r["pos"] == 0.5
    assert r["basis"] == 100.0
    assert r["up"] == 110.0
    assert r["lo"] == 90.0


def test_band_above_is_positive_bd():
    bars = [100.0] * 39 + [200.0]
    r = band_state(bars, 0.10)
    assert r["state"] == "ABOVE"
    assert r["bd"] > 0
    assert r["pos"] > 1.0


def test_band_below_is_negative_bd():
    bars = [100.0] * 39 + [50.0]
    r = band_state(bars, 0.10)
    assert r["state"] == "BELOW"
    assert r["bd"] < 0
    assert r["pos"] < 0.0


def test_no_band_means_na():
    bars = [100.0] * 40
    r = band_state(bars, None)
    assert r["state"] == "na"
    assert r["bd"] is None
    assert r["pos"] is None
    assert r["up"] is None
    assert r["lo"] is None
    assert r["basis"] is None


def test_zero_band_means_na():
    bars = [100.0] * 40
    r = band_state(bars, 0.0)
    assert r["state"] == "na"
    assert r["bd"] is None


def test_insufficient_bars_returns_na():
    bars = [100.0, 105.0]  # only 2 bars, need >= 3
    r = band_state(bars, 0.10)
    assert r["state"] == "na"
    assert r["bd"] is None


def test_short_history_scales_down_window():
    # 5 bars: bw = max(3, 5 // 2) = 3
    bars = [100.0, 102.0, 104.0, 106.0, 108.0]
    r = band_state(bars, 0.10)
    assert r["state"] in ("IN", "ABOVE", "BELOW")
    assert r["basis"] is not None
    assert r["pos"] is not None


def test_band_levels_move_with_width():
    bars = [100.0] * 40
    narrow = band_state(bars, 0.05)
    wide = band_state(bars, 0.25)
    assert narrow["up"] == 105.0 and narrow["lo"] == 95.0
    assert wide["up"] == 125.0 and wide["lo"] == 75.0


def test_bands_calculator_contract_and_calculation():
    calc = BandsCalculator()
    assert isinstance(calc, ICalcModule)
    assert calc.name == "bands"
    assert calc.required_timeframes == ("D", "W", "M", "Q", "H", "Y")

    # Construct dummy market context with 40 daily bars
    daily_bars = [
        MarketBar(
            timestamp=datetime(2026, 1, 1) + pd.Timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0,
            volume=1000.0,
        )
        for i in range(40)
    ]
    # Make last bar break above
    daily_bars[-1] = MarketBar(
        timestamp=datetime(2026, 2, 10),
        open=100.0,
        high=160.0,
        low=100.0,
        close=150.0,
        volume=1000.0,
    )

    market_ctx = MarketContext(
        symbol="TEST",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(
        market_context=market_ctx,
        bands_lookup={"D": 0.10, "M": 0.20},
    )

    res = calc.calculate("TEST", calc_ctx)
    assert isinstance(res, CalculationResult)
    assert res.symbol == "TEST"
    assert res.module_name == "bands"

    m = res.metrics
    assert m["BAND_D"] == 0.10
    assert m["BANDST_D"] == "ABOVE"
    assert m["BD_D"] > 0
    assert m["BAND_M"] == 0.20
    assert m["BANDST_M"] == "na"  # no M bars provided
    assert "D" in m["OUT_ABOVE"]
    assert m["N_ABOVE"] >= 1
    assert m["N_BELOW"] == 0


def test_bands_calculator_empty_context():
    calc = BandsCalculator()
    market_ctx = MarketContext(symbol="EMPTY", exchange="NSE", bars_by_timeframe={})
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("EMPTY", calc_ctx)
    m = res.metrics
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        assert m[f"BAND_{tf}"] is None
        assert m[f"BANDST_{tf}"] == "na"
        assert m[f"BD_{tf}"] is None
    assert m["OUT_ABOVE"] == ""
    assert m["OUT_BELOW"] == ""
    assert m["N_ABOVE"] == 0
    assert m["N_BELOW"] == 0


def test_calculate_band_envelope_insufficient_bars():
    """Verify history with < 3 bars returns empty series and None levels."""
    for n in (0, 1, 2):
        res = calculate_band_envelope([100.0] * n, band_frac=0.10)
        assert isinstance(res, BandEnvelopeResult)
        assert len(res.basis) == 0
        assert res.upper is None
        assert res.lower is None
        assert res.last_basis is None
        assert res.last_upper is None
        assert res.last_lower is None


def test_calculate_band_envelope_normal_history():
    """Verify normal history (>= 20 bars) computes 20-period rolling envelope."""
    closes = [100.0 + i for i in range(25)]
    res = calculate_band_envelope(closes, band_frac=0.10, basis_window=20)

    assert isinstance(res, BandEnvelopeResult)
    assert len(res.basis) == 25
    assert res.upper is not None and len(res.upper) == 25
    assert res.lower is not None and len(res.lower) == 25

    # min_periods = max(2, 20 // 2) = 10, so first 9 values are NaN
    for i in range(9):
        assert pd.isna(res.basis.iloc[i])
        assert pd.isna(res.upper.iloc[i])
        assert pd.isna(res.lower.iloc[i])

    # Bar index 9 onwards has rolling mean
    assert not pd.isna(res.basis.iloc[9])

    # Verify last value
    expected_last_basis = sum(closes[-20:]) / 20.0
    expected_last_upper = expected_last_basis * 1.10
    expected_last_lower = expected_last_basis * 0.90

    assert res.last_basis == pytest.approx(expected_last_basis)
    assert res.last_upper == pytest.approx(expected_last_upper)
    assert res.last_lower == pytest.approx(expected_last_lower)
    assert res.basis.iloc[-1] == pytest.approx(expected_last_basis)
    assert res.upper.iloc[-1] == pytest.approx(expected_last_upper)
    assert res.lower.iloc[-1] == pytest.approx(expected_last_lower)


def test_calculate_band_envelope_short_history():
    """Verify short history scales down basis window and min_periods."""
    # 3 bars: bw = max(3, 3 // 2) = 3, min_periods = max(2, 3 // 2) = 2
    res_3 = calculate_band_envelope([100.0, 102.0, 104.0], band_frac=0.10)
    assert res_3.last_basis == pytest.approx(102.0)
    assert res_3.last_upper == pytest.approx(102.0 * 1.10)
    assert res_3.last_lower == pytest.approx(102.0 * 0.90)

    # 5 bars: bw = max(3, 5 // 2) = 3, min_periods = 2
    # Last 3 bars of [10, 20, 30, 40, 50] -> 40.0
    res_5 = calculate_band_envelope([10.0, 20.0, 30.0, 40.0, 50.0], band_frac=0.05)
    assert res_5.last_basis == pytest.approx(40.0)
    assert res_5.last_upper == pytest.approx(40.0 * 1.05)
    assert res_5.last_lower == pytest.approx(40.0 * 0.95)

    # 10 bars: bw = max(3, 10 // 2) = 5, min_periods = max(2, 5 // 2) = 2
    bars_10 = [float(x) for x in range(1, 11)]  # 1..10, last 5: 6,7,8,9,10 -> mean = 8.0
    res_10 = calculate_band_envelope(bars_10, band_frac=0.20)
    assert res_10.last_basis == pytest.approx(8.0)
    assert res_10.last_upper == pytest.approx(8.0 * 1.20)
    assert res_10.last_lower == pytest.approx(8.0 * 0.80)


def test_calculate_band_envelope_no_band_or_zero():
    """Verify band_frac=None or <= 0 calculates basis but leaves upper/lower as None."""
    closes = [100.0] * 20

    res_none = calculate_band_envelope(closes, band_frac=None)
    assert res_none.last_basis == pytest.approx(100.0)
    assert res_none.upper is None
    assert res_none.lower is None
    assert res_none.last_upper is None
    assert res_none.last_lower is None

    res_zero = calculate_band_envelope(closes, band_frac=0.0)
    assert res_zero.last_basis == pytest.approx(100.0)
    assert res_zero.upper is None
    assert res_zero.lower is None
    assert res_zero.last_upper is None
    assert res_zero.last_lower is None


def test_calculate_band_envelope_parity_with_band_state():
    """Verify calculate_band_envelope numerical outputs match band_state levels exactly."""
    closes = [100.0 + (i * 1.5) for i in range(30)]
    w = 0.12

    envelope = calculate_band_envelope(closes, band_frac=w, basis_window=20)
    state = band_state(closes, band_frac=w, basis_window=20)

    assert round(envelope.last_basis, 2) == state["basis"]
    assert round(envelope.last_upper, 2) == state["up"]
    assert round(envelope.last_lower, 2) == state["lo"]


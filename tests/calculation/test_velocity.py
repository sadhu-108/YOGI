"""Unit tests for VelocityCalculator and sprint mathematics."""

from datetime import datetime
import pandas as pd
import pytest

from yogi.calculation.velocity import (
    VelocityCalculator,
    anchored_block,
    anchored_curve,
    anchored_sprint,
    calculate_anchored_curve,
    rolling_speed,
    sprint,
    sprint_block,
    sprint_v2,
)
from yogi.calculation.velocity.calculator import faster
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext


def test_rolling_speed():
    idx = pd.bdate_range(end="2026-08-13", periods=22)
    s = pd.Series([100.0] * 21 + [120.0], index=idx)
    # +20% over 20 days (4 weeks) = 5.0 %/week
    sp = rolling_speed(s, 20)
    assert sp is not None
    assert abs(sp - 5.0) < 0.3


def test_rolling_speed_insufficient_bars():
    idx = pd.bdate_range(end="2026-08-13", periods=10)
    s = pd.Series([100.0] * 10, index=idx)
    assert rolling_speed(s, 20) is None


def test_faster_differential():
    assert faster(5.0, 3.0) == 2.0
    assert faster(3.0, 5.0) == -2.0
    assert faster(None, 3.0) is None
    assert faster(5.0, None) is None


def test_anchored_sprint_exact():
    idx = pd.date_range("2025-12-30", "2026-08-13", freq="D")
    s = pd.Series([200.0] * 3 + [250.0] * (len(idx) - 3), index=idx)
    assert round(anchored_sprint(s, "2026-01-01"), 4) == 25.0


def test_anchored_sprint_blank_if_listed_after_anchor():
    idx = pd.date_range("2026-03-01", "2026-08-13", freq="D")
    s = pd.Series(100.0, index=idx)
    assert anchored_sprint(s, "2021-01-01") is None


def test_anchored_curve_exact():
    idx = pd.date_range("2025-12-25", "2026-02-15", freq="D")
    s = pd.Series([200.0 if t < pd.Timestamp("2026-01-01") else 250.0 for t in idx], index=idx)
    curve = calculate_anchored_curve(s, "2026-01-01", weekly=True)
    assert len(curve) > 0
    for pt in curve:
        assert pt["value"] == 25.0
        assert "time" in pt


def test_anchored_curve_blank_if_listed_after_anchor():
    idx = pd.date_range("2026-03-01", "2026-08-13", freq="D")
    s = pd.Series(100.0, index=idx)
    assert calculate_anchored_curve(s, "2021-01-01") == []


def test_sprint_block():
    idx = pd.bdate_range("2025-01-01", "2026-08-13")
    s = pd.Series(100.0, index=idx)
    sb = sprint_block(s)
    for tf in ("W", "M", "Q", "H", "Y"):
        assert f"SPR_{tf}" in sb
        assert f"SPD_{tf}" in sb


def test_sprint_faster_gain_higher_speed():
    slow = pd.Series([100.0] * 81 + [130.0], index=pd.date_range("2026-01-01", periods=82, freq="D"))
    fast = pd.Series([100.0] * 21 + [130.0], index=pd.date_range("2026-01-01", periods=22, freq="D"))
    assert sprint(fast, "Y")["speed"] > sprint(slow, "Y")["speed"]


def test_sprint_v2_consistency():
    idx = pd.date_range("2025-01-01", periods=20, freq="W")
    w = pd.Series([100.0 * (1.02 ** i) for i in range(20)], index=idx)
    # daily series that resamples to w
    daily_idx = pd.date_range("2025-01-01", periods=140, freq="D")
    c = pd.Series(100.0, index=daily_idx)
    v2 = sprint_v2(c, weekly_closes=w)
    assert v2["SPR_CONSIST"] == 100.0


def test_velocity_calculator_contract_and_calculation():
    calc = VelocityCalculator()
    assert isinstance(calc, ICalcModule)
    assert calc.name == "velocity"
    assert calc.required_timeframes == ("D", "W")

    # Construct dummy market context with 300 daily bars
    daily_bars = [
        MarketBar(
            timestamp=datetime(2025, 1, 1) + pd.Timedelta(days=i),
            open=100.0 + i * 0.1,
            high=102.0 + i * 0.1,
            low=99.0 + i * 0.1,
            close=100.0 + i * 0.1,
            volume=1000.0,
        )
        for i in range(300)
    ]
    market_ctx = MarketContext(
        symbol="VEL",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("VEL", calc_ctx)
    assert isinstance(res, CalculationResult)
    assert res.symbol == "VEL"
    assert res.module_name == "velocity"

    m = res.metrics
    assert "S4" in m
    assert "S13" in m
    assert "ACCEL_S" in m
    assert "ACCEL_L" in m
    assert "SPR_M" in m
    assert "SPD_M" in m


def test_velocity_calculator_empty_context():
    calc = VelocityCalculator()
    market_ctx = MarketContext(symbol="EMPTY", exchange="NSE", bars_by_timeframe={})
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("EMPTY", calc_ctx)
    m = res.metrics
    assert m["S4"] is None
    assert m["ACCEL_L"] is None
    assert m["SPR_M"] is None


def test_calculate_anchored_curve_all_timeframes():
    """Verify calculate_anchored_curve produces correct monotonic point counts across all 6 timeframes."""
    idx = pd.date_range("2020-01-01", "2022-12-31", freq="D")
    s = pd.Series([100.0 * (1.001 ** i) for i in range(len(idx))], index=idx)

    pts_d = calculate_anchored_curve(s, "2021-01-01", timeframe="D")
    pts_w = calculate_anchored_curve(s, "2021-01-01", timeframe="W")
    pts_m = calculate_anchored_curve(s, "2021-01-01", timeframe="M")
    pts_q = calculate_anchored_curve(s, "2021-01-01", timeframe="Q")
    pts_h = calculate_anchored_curve(s, "2021-01-01", timeframe="H")
    pts_y = calculate_anchored_curve(s, "2021-01-01", timeframe="Y")

    assert len(pts_d) > len(pts_w) > len(pts_m) > len(pts_q) > len(pts_h) > len(pts_y) > 0
    assert pts_d[0]["time"] == "2021-01-01"
    assert pts_y[-1]["time"] == "2022-12-31"


def test_calculate_anchored_curve_unsupported_timeframe():
    """Verify calculate_anchored_curve raises ValueError on unsupported timeframe code."""
    idx = pd.date_range("2020-01-01", "2023-01-01", freq="D")
    s = pd.Series(100.0, index=idx)
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        calculate_anchored_curve(s, "2021-01-01", timeframe="INVALID")

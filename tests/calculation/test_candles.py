"""Unit tests for Candlestick Theory / Pattern Engine and CandleCalculator."""

from datetime import datetime
import pandas as pd
import pytest

from yogi.calculation.candles import (
    CandleCalculator,
    calculate_candle_fields,
    DEFAULT_CANDLE_RULES,
)
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext


def _make_bar(ts_str: str, o: float, h: float, l: float, c: float, v: float = 1000.0) -> MarketBar:
    return MarketBar(
        timestamp=pd.to_datetime(ts_str).to_pydatetime(),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_insufficient_bars_returns_empty():
    """Fewer than 3 valid bars must return an empty dictionary."""
    bars = [
        _make_bar("2026-01-01", 100, 105, 95, 102),
        _make_bar("2026-01-02", 102, 108, 100, 105),
    ]
    assert calculate_candle_fields(bars) == {}
    assert calculate_candle_fields(None) == {}
    assert calculate_candle_fields([]) == {}


def test_basic_shape_metrics():
    """Verify exact formula values for O, H, L, C, body, wicks, range, close pos, gap."""
    bars = [
        _make_bar("2026-01-01", 100.0, 105.0, 95.0, 100.0, 1000.0),
        _make_bar("2026-01-02", 100.0, 110.0, 90.0, 105.0, 1000.0),
        _make_bar("2026-01-03", 108.0, 120.0, 100.0, 118.0, 2000.0),
    ]
    fields = calculate_candle_fields(bars, prefix="CD_")

    assert fields["CD_O"] == 108.0
    assert fields["CD_H"] == 120.0
    assert fields["CD_L"] == 100.0
    assert fields["CD_C"] == 118.0
    assert fields["CD_BODY"] == 10.0  # |118 - 108|
    assert fields["CD_UPWICK"] == 2.0  # 120 - max(108, 118)
    assert fields["CD_DNWICK"] == 8.0  # min(108, 118) - 100
    assert fields["CD_RANGE_PCT"] == round(20.0 / 100.0 * 100.0, 2)  # 20.0%
    assert fields["CD_BODY_PCT"] == round(10.0 / 20.0 * 100.0, 2)  # 50.0%
    assert fields["CD_UPWICK_PCT"] == round(2.0 / 20.0 * 100.0, 2)  # 10.0%
    assert fields["CD_DNWICK_PCT"] == round(8.0 / 20.0 * 100.0, 2)  # 40.0%
    assert fields["CD_GAP_PCT"] == round((108.0 / 105.0 - 1.0) * 100.0, 2)  # +2.86%
    assert fields["CD_CLOSE_POS"] == round((118.0 - 100.0) / 20.0 * 100.0, 2)  # 90.0%
    assert fields["CD_PREV_H"] == 110.0
    assert fields["CD_PREV_L"] == 90.0
    assert fields["CD_GREEN"] == "Y"
    assert fields["CD_CLOSE_STRONG"] == "Y"  # 90.0% >= 80.0%
    assert fields["CD_CLOSE_WEAK"] == "N"
    assert fields["CD_BIG_RANGE"] == "Y"  # 20.0% >= 5.0%
    assert fields["CD_BREAKOUT"] == "Y"  # 118 > 110
    assert fields["CD_BREAKDOWN"] == "N"


def test_inside_and_outside_bar():
    """Verify INSIDE and OUTSIDE flags."""
    # Inside bar: high <= prev.high and low >= prev.low
    bars_inside = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 120, 80, 100),
        _make_bar("2026-01-03", 95, 110, 85, 105),
    ]
    f_in = calculate_candle_fields(bars_inside, prefix="CD_")
    assert f_in["CD_INSIDE"] == "Y"
    assert f_in["CD_OUTSIDE"] == "N"

    # Outside bar: high > prev.high and low < prev.low
    bars_outside = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 110, 90, 100),
        _make_bar("2026-01-03", 95, 115, 85, 105),
    ]
    f_out = calculate_candle_fields(bars_outside, prefix="CD_")
    assert f_out["CD_INSIDE"] == "N"
    assert f_out["CD_OUTSIDE"] == "Y"


def test_bullish_and_bearish_engulfing():
    """Verify BULL_ENGULF and BEAR_ENGULF under full body and range modes."""
    # Bullish engulfing (full body mode):
    # cl > o, prev.cl < prev.o, cl >= prev.o, o <= prev.cl
    bars_bull = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 110, 112, 98, 100),  # Red bar: open 110, close 100
        _make_bar("2026-01-03", 99, 115, 95, 112),  # Green bar: open 99 <= 100, close 112 >= 110
    ]
    f_bull = calculate_candle_fields(bars_bull, prefix="CD_")
    assert f_bull["CD_BULL_ENGULF"] == "Y"
    assert f_bull["CD_BEAR_ENGULF"] == "N"

    # Bearish engulfing (full body mode):
    # cl < o, prev.cl > prev.o, cl <= prev.o, o >= prev.cl
    bars_bear = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 112, 98, 110),  # Green bar: open 100, close 110
        _make_bar("2026-01-03", 112, 115, 95, 99),  # Red bar: open 112 >= 110, close 99 <= 100
    ]
    f_bear = calculate_candle_fields(bars_bear, prefix="CD_")
    assert f_bear["CD_BEAR_ENGULF"] == "Y"
    assert f_bear["CD_BULL_ENGULF"] == "N"


def test_doji_and_marubozu():
    """Verify DOJI (small body) and MARUBOZU (large body)."""
    # Doji: body / range < 10%
    bars_doji = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 105, 95, 100),
        _make_bar("2026-01-03", 100.0, 110.0, 90.0, 100.5),  # range 20, body 0.5 (2.5% < 10%)
    ]
    f_doji = calculate_candle_fields(bars_doji, prefix="CD_")
    assert f_doji["CD_DOJI"] == "Y"
    assert f_doji["CD_MARUBOZU"] == "N"

    # Marubozu: body / range > 90%
    bars_maru = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 105, 95, 100),
        _make_bar("2026-01-03", 90.5, 110.0, 90.0, 109.5),  # range 20, body 19 (95% > 90%)
    ]
    f_maru = calculate_candle_fields(bars_maru, prefix="CD_")
    assert f_maru["CD_MARUBOZU"] == "Y"
    assert f_maru["CD_DOJI"] == "N"


def test_hammer_and_shooting_star():
    """Verify HAMMER and SHOOTSTAR."""
    # Hammer: dn_wick / range >= 60%, up_wick / range <= 15%
    # range 100-80=20. close=98, open=96 (dn_wick=96-80=16 -> 80%), up_wick=100-98=2 -> 10%
    bars_hammer = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 105, 95, 100),
        _make_bar("2026-01-03", 96.0, 100.0, 80.0, 98.0),
    ]
    f_hammer = calculate_candle_fields(bars_hammer, prefix="CD_")
    assert f_hammer["CD_HAMMER"] == "Y"
    assert f_hammer["CD_SHOOTSTAR"] == "N"

    # Shooting Star: up_wick / range >= 60%, dn_wick / range <= 15%
    # range 120-100=20. open=104, close=102. up_wick=120-104=16 -> 80%, dn_wick=102-100=2 -> 10%
    bars_shoot = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 105, 95, 100),
        _make_bar("2026-01-03", 104.0, 120.0, 100.0, 102.0),
    ]
    f_shoot = calculate_candle_fields(bars_shoot, prefix="CD_")
    assert f_shoot["CD_SHOOTSTAR"] == "Y"
    assert f_shoot["CD_HAMMER"] == "N"


def test_nr_wr_three_up_three_dn():
    """Verify NR, WR, THREE_UP, THREE_DN flags."""
    # Three up bars: cl > o for 3 bars in a row
    bars_three_up = [
        _make_bar("2026-01-01", 100, 105, 95, 104),  # Green
        _make_bar("2026-01-02", 104, 110, 102, 109),  # Green, range 8
        _make_bar("2026-01-03", 109, 115, 108, 114),  # Green, range 7 (< 8 -> NR)
    ]
    f_up = calculate_candle_fields(bars_three_up, prefix="CD_")
    assert f_up["CD_THREE_UP"] == "Y"
    assert f_up["CD_THREE_DN"] == "N"
    assert f_up["CD_NR"] == "Y"
    assert f_up["CD_WR"] == "N"

    # Three down bars: cl < o for 3 bars in a row
    bars_three_dn = [
        _make_bar("2026-01-01", 115, 116, 109, 110),  # Red
        _make_bar("2026-01-02", 110, 111, 105, 106),  # Red, range 6
        _make_bar("2026-01-03", 106, 108, 98, 100),  # Red, range 10 (> 6 -> WR)
    ]
    f_dn = calculate_candle_fields(bars_three_dn, prefix="CD_")
    assert f_dn["CD_THREE_UP"] == "N"
    assert f_dn["CD_THREE_DN"] == "Y"
    assert f_dn["CD_NR"] == "N"
    assert f_dn["CD_WR"] == "Y"


def test_volume_metrics_and_spike():
    """Verify VOL, VOL_X, and VOL_SPIKE with 20-bar average."""
    # 20 bars with volume 1000, last bar volume 2500 -> 2.5x -> spike Y
    bars = [
        _make_bar(f"2026-01-{i:02d}", 100, 105, 95, 102, v=1000.0)
        for i in range(1, 21)
    ]
    bars.append(_make_bar("2026-01-21", 102, 108, 100, 105, v=2500.0))
    fields = calculate_candle_fields(bars, prefix="CD_")

    assert fields["CD_VOL"] == 2500.0
    # Average of last 20 bars is (19 * 1000 + 2500) / 20 = 21500 / 20 = 1075.0
    # 2500 / 1075 = 2.33x >= 2.0x -> VOL_SPIKE == "Y"
    assert fields["CD_VOL_X"] == round(2500.0 / 1075.0, 2)
    assert fields["CD_VOL_SPIKE"] == "Y"


def test_candle_calculator_contract_and_multitimeframe():
    """Verify CandleCalculator satisfies ICalcModule and calculates all 6 standard timeframes."""
    calc = CandleCalculator()
    assert isinstance(calc, ICalcModule)
    assert calc.name == "candles"
    assert calc.required_timeframes == ("D", "W", "M", "Q", "H", "Y")

    # Generate 400 daily bars to cover all timeframes
    base_date = datetime(2025, 1, 1)
    daily_bars = [
        MarketBar(
            timestamp=base_date + pd.Timedelta(days=i),
            open=100.0 + (i % 10),
            high=105.0 + (i % 10),
            low=95.0 + (i % 10),
            close=102.0 + (i % 10),
            volume=10000.0 + i * 10,
        )
        for i in range(400)
    ]

    market_ctx = MarketContext(
        symbol="CANDLE_TEST",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("CANDLE_TEST", calc_ctx)
    assert isinstance(res, CalculationResult)
    assert res.symbol == "CANDLE_TEST"
    assert res.module_name == "candles"

    m = res.metrics
    # Verify daily and weekly fields are populated
    for tf_p in ("CD_", "CW_", "CM_", "CQ_"):
        assert f"{tf_p}O" in m
        assert f"{tf_p}H" in m
        assert f"{tf_p}L" in m
        assert f"{tf_p}C" in m
        assert f"{tf_p}BODY" in m
        assert f"{tf_p}GREEN" in m
        assert f"{tf_p}BULL_ENGULF" in m
        assert f"{tf_p}DOJI" in m
        assert f"{tf_p}HAMMER" in m
        assert f"{tf_p}VOL" in m
        assert f"{tf_p}VOL_SPIKE" in m


def test_custom_rule_overrides():
    """Verify rules passed via CalculationContext.parameters dynamically alter threshold behavior."""
    bars_doji = [
        _make_bar("2026-01-01", 100, 105, 95, 100),
        _make_bar("2026-01-02", 100, 105, 95, 100),
        _make_bar("2026-01-03", 100.0, 110.0, 90.0, 101.5),  # range 20, body 1.5 (7.5%)
    ]
    # Default threshold is 10.0%: 7.5% < 10% -> DOJI == "Y"
    f_default = calculate_candle_fields(bars_doji, prefix="CD_")
    assert f_default["CD_DOJI"] == "Y"

    # Strict threshold 5.0%: 7.5% > 5.0% -> DOJI == "N"
    strict_rules = {"DOJI_body_pct_max": 5.0}
    f_strict = calculate_candle_fields(bars_doji, prefix="CD_", rules=strict_rules)
    assert f_strict["CD_DOJI"] == "N"

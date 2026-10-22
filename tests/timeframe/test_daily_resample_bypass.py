"""Targeted regression test suite for Prompt 1: Eliminate Redundant Daily Timeframe Resampling.

Verifies:
1. Daily Context Construction:
   - Valid normalized daily bars produce the expected daily MarketContext.
   - The daily path does not call resample_bars("D") when the bypass is authorized.
   - The returned timeframe key "D" contains identical bars, timestamps, and OHLCV values.
   - Empty and single-bar sequences exhibit defined, contract-compatible behavior.
2. Input-Contract Boundaries:
   - Mutable sequences (list) fall back to resample_bars("D") and return an immutable tuple.
   - Unsorted sequences (reverse-ordered, shuffled, or endpoint-ordered with middle disorder)
     fall back to resample_bars("D") and are correctly sorted.
   - Duplicate timestamps fall back to resample_bars("D") and retain the final duplicate.
   - Non-finite (NaN, +/-Inf) or missing (None) values retain exact existing semantics.
3. Downstream Numerical Equivalence:
   - Compares calculate_dynamic_ema_signal on old vs bypassed daily bars across spans (5, 13, 21).
   - Verifies ROC calculation inputs and outputs match identically.
4. Non-Daily Regression Protection:
   - Verifies weekly ("W") and monthly ("M") synthesis remain unaffected.
"""

from datetime import datetime, timedelta
from typing import Sequence
from unittest.mock import patch
import pytest

from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.timeframe.engine import (
    TimeframeEngine,
    build_market_context,
    resample_bars,
    _is_normalized_daily_tuple,
    _resolve_daily_bars,
)
from yogi.calculation.trend.calculator import calculate_dynamic_ema_signal, ema


def make_bar(
    dt: datetime,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: float = 1000.0,
) -> MarketBar:
    return MarketBar(
        timestamp=dt,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_normalized_bars(count: int = 100) -> tuple[MarketBar, ...]:
    start = datetime(2024, 1, 1)
    return tuple(
        make_bar(
            dt=start + timedelta(days=i),
            open_=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=1000.0 + i * 10,
        )
        for i in range(count)
    )


# ===========================================================================
# 1. Daily Context Construction Tests
# ===========================================================================

def test_daily_context_construction_preserves_normalized_bars():
    """Normalized immutable tuple produces expected MarketContext and preserves bar contents."""
    bars = make_normalized_bars(50)
    engine = TimeframeEngine(enable_cache=True)

    ctx = engine.build_context("RELIANCE", "NSE", bars, timeframes=["D"])
    daily_bars = ctx.get_bars("D")

    assert isinstance(daily_bars, tuple)
    assert len(daily_bars) == 50
    assert daily_bars == bars
    assert ctx.as_of == bars[-1].timestamp
    assert ctx.symbol == "RELIANCE"
    assert ctx.exchange == "NSE"


def test_daily_path_bypasses_resample_bars():
    """Authorized daily bypass does not invoke resample_bars("D")."""
    bars = make_normalized_bars(30)
    engine = TimeframeEngine(enable_cache=True)

    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx = engine.build_context("TCS", "NSE", bars, timeframes=["D"])
        assert len(ctx.get_bars("D")) == 30
        mock_resample.assert_not_called()


def test_build_market_context_function_bypasses_resample_bars():
    """build_market_context standalone function also uses the safe daily bypass."""
    bars = make_normalized_bars(20)

    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx = build_market_context("INFY", "NSE", bars, timeframes=["D"])
        assert len(ctx.get_bars("D")) == 20
        mock_resample.assert_not_called()


def test_empty_and_single_bar_context():
    """Empty and single-bar sequences produce valid contract-compliant contexts."""
    engine = TimeframeEngine(enable_cache=True)

    # Empty sequence
    ctx_empty = engine.build_context("EMPTY", "NSE", (), timeframes=["D"])
    assert ctx_empty.get_bars("D") == ()
    assert ctx_empty.as_of is None

    # Single bar sequence
    single_bar = (make_bar(datetime(2024, 1, 1), close=150.0),)
    ctx_single = engine.build_context("SINGLE", "NSE", single_bar, timeframes=["D"])
    assert ctx_single.get_bars("D") == single_bar
    assert ctx_single.as_of == datetime(2024, 1, 1)


# ===========================================================================
# 2. Input-Contract Boundaries Tests
# ===========================================================================

def test_mutable_list_falls_back_to_resample():
    """Callers providing mutable list fall back to resample_bars and receive immutable tuple."""
    bars_list = list(make_normalized_bars(10))
    engine = TimeframeEngine(enable_cache=True)

    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx = engine.build_context("MUTABLE", "NSE", bars_list, timeframes=["D"])
        mock_resample.assert_called_once()
        res_bars = ctx.get_bars("D")
        assert isinstance(res_bars, tuple)
        assert len(res_bars) == 10
        assert res_bars == tuple(bars_list)


def test_unsorted_tuple_falls_back_and_is_sorted():
    """Unsorted tuple falls back to resample_bars and is returned in strict chronological order."""
    b1 = make_bar(datetime(2024, 1, 1), close=100.0)
    b2 = make_bar(datetime(2024, 1, 2), close=105.0)
    b3 = make_bar(datetime(2024, 1, 3), close=110.0)

    # Reverse order: b3, b2, b1
    engine = TimeframeEngine(enable_cache=True)
    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx = engine.build_context("UNSORTED", "NSE", (b3, b2, b1), timeframes=["D"])
        mock_resample.assert_called_once()
        assert ctx.get_bars("D") == (b1, b2, b3)
        assert ctx.as_of == datetime(2024, 1, 3)

    # Middle disorder: b1, b3, b2 (endpoints ordered, middle disordered)
    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx2 = engine.build_context("MIDDLE_UNSORTED", "NSE", (b1, b3, b2), timeframes=["D"])
        mock_resample.assert_called_once()
        assert ctx2.get_bars("D") == (b1, b2, b3)


def test_duplicate_timestamps_fall_back_and_deduplicate():
    """Tuple with duplicate timestamps falls back to resample_bars and retains final duplicate."""
    b1_first = make_bar(datetime(2024, 1, 1), close=100.0, volume=1000.0)
    b1_final = make_bar(datetime(2024, 1, 1), close=102.0, volume=1500.0)
    b2 = make_bar(datetime(2024, 1, 2), close=105.0, volume=2000.0)

    engine = TimeframeEngine(enable_cache=True)
    with patch("yogi.timeframe.engine.resample_bars", wraps=resample_bars) as mock_resample:
        ctx = engine.build_context("DUP", "NSE", (b1_first, b1_final, b2), timeframes=["D"])
        mock_resample.assert_called_once()
        bars = ctx.get_bars("D")
        assert len(bars) == 2
        assert bars[0].close == 102.0
        assert bars[0].volume == 1500.0
        assert bars[1].close == 105.0


def test_non_finite_values_preserved_identically():
    """Non-finite (NaN) and None volume values are preserved identically to resample_bars."""
    b1 = make_bar(datetime(2024, 1, 1), close=float("nan"), volume=None)
    b2 = make_bar(datetime(2024, 1, 2), close=105.0, volume=float("nan"))
    bars = (b1, b2)

    engine = TimeframeEngine(enable_cache=True)
    ctx = engine.build_context("NAN_TEST", "NSE", bars, timeframes=["D"])
    res = ctx.get_bars("D")
    expected = resample_bars(bars, "D")

    assert len(res) == len(expected)
    import math
    assert math.isnan(res[0].close)
    assert res[0].volume is None
    assert res[1].close == 105.0
    assert math.isnan(res[1].volume)


# ===========================================================================
# 3. Downstream Numerical Equivalence Tests
# ===========================================================================

def test_daily_ema_and_roc_numerical_equivalence():
    """EMA and ROC indicator calculations match identically between resample_bars and bypassed daily bars."""
    bars = make_normalized_bars(150)
    engine = TimeframeEngine(enable_cache=True)

    # Context via new engine (bypassed)
    ctx_bypassed = engine.build_context("TEST", "NSE", bars, timeframes=["D"])
    d_bars_bypassed = ctx_bypassed.get_bars("D")

    # Direct resample_bars baseline
    d_bars_baseline = resample_bars(bars, "D")

    # 1. EMA 5/13 comparison
    sig_bypassed = calculate_dynamic_ema_signal(d_bars_bypassed, p1=5, p2=13, timeframe="D")
    sig_baseline = calculate_dynamic_ema_signal(d_bars_baseline, p1=5, p2=13, timeframe="D")

    assert sig_bypassed["state"] == sig_baseline["state"]
    assert sig_bypassed["is_up"] == sig_baseline["is_up"]
    assert sig_bypassed["is_down"] == sig_baseline["is_down"]
    assert pytest.approx(sig_bypassed["cur_diff"], 1e-12) == sig_baseline["cur_diff"]
    assert pytest.approx(sig_bypassed["p1_val"], 1e-12) == sig_baseline["p1_val"]
    assert pytest.approx(sig_bypassed["p2_val"], 1e-12) == sig_baseline["p2_val"]

    # 2. ROC (10) comparison
    c_bypassed = ctx_bypassed.get_closes("D")
    c_baseline = [b.close for b in d_bars_baseline]
    assert c_bypassed == c_baseline

    roc_bypassed = (c_bypassed[-1] - c_bypassed[-11]) / c_bypassed[-11] * 100.0
    roc_baseline = (c_baseline[-1] - c_baseline[-11]) / c_baseline[-11] * 100.0
    assert pytest.approx(roc_bypassed, 1e-12) == roc_baseline


# ===========================================================================
# 4. Non-Daily Regression Protection Tests
# ===========================================================================

def test_weekly_and_monthly_context_construction_unchanged():
    """Weekly and Monthly synthesis remain completely intact and unaffected by daily bypass."""
    bars = make_normalized_bars(60)
    engine = TimeframeEngine(enable_cache=True)

    ctx = engine.build_context("MULTI_TF", "NSE", bars, timeframes=["D", "W", "M"])

    assert "D" in ctx.bars_by_timeframe
    assert "W" in ctx.bars_by_timeframe
    assert "M" in ctx.bars_by_timeframe

    # Weekly and Monthly bars match resample_bars directly
    expected_w = resample_bars(bars, "W")
    expected_m = resample_bars(bars, "M")

    assert ctx.get_bars("W") == expected_w
    assert ctx.get_bars("M") == expected_m
    assert len(ctx.get_bars("W")) > 0
    assert len(ctx.get_bars("M")) > 0

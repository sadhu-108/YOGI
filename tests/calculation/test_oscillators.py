"""Pure calculation unit tests for Batch 3C: Oscillators (RSI, MACD, OBV, MFI).

Verifies mathematical precision, edge case handling, and prototype formula parity for:
1. Relative Strength Index (RSI 14)
2. Moving Average Convergence Divergence (MACD 12, 26, 9)
3. On-Balance Volume (OBV)
4. Money Flow Index (MFI 14)
"""

import numpy as np
import pandas as pd
import pytest

from yogi.calculation.trend.calculator import (
    MACDResult,
    MFIResult,
    OBVResult,
    RSIResult,
    calculate_macd,
    calculate_mfi,
    calculate_obv,
    calculate_rsi,
    ema,
)


# =============================================================================
# 1. Relative Strength Index (RSI) Tests
# =============================================================================

def test_rsi_formula_and_parity():
    """Verify RSI matches prototype rolling mean convention (routes.py:125-128)."""
    np.random.seed(42)
    closes = [100.0 + float(v) for v in np.random.normal(0, 1, 40).cumsum()]
    s = pd.Series(closes)

    res = calculate_rsi(s, period=14)

    assert isinstance(res, RSIResult)
    assert len(res.rsi) == 40
    # First 14 points (indices 0..13) are NaN
    assert res.rsi.iloc[:14].isna().all()
    # Index 14 onwards is non-NaN
    assert not res.rsi.iloc[14:].isna().any()

    # Prototype reference calculation
    d = s.diff()
    g = d.clip(lower=0.0).rolling(14).mean()
    l = (-d.clip(upper=0.0)).rolling(14).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        expected_rsi = 100.0 - (100.0 / (1.0 + (g / l)))

    pd.testing.assert_series_equal(res.rsi, expected_rsi, check_names=False)
    assert res.last_rsi == pytest.approx(float(expected_rsi.iloc[-1]))


def test_rsi_strictly_increasing_and_decreasing():
    """Verify RSI produces 100.0 for pure uptrend and 0.0 for pure downtrend."""
    up = [100.0 + i * 2.0 for i in range(25)]
    res_up = calculate_rsi(up, period=14)
    assert res_up.last_rsi == pytest.approx(100.0)

    dn = [100.0 - i * 2.0 for i in range(25)]
    res_dn = calculate_rsi(dn, period=14)
    assert res_dn.last_rsi == pytest.approx(0.0)


def test_rsi_flat_price_and_short_series():
    """Verify RSI handles flat price (zero variance) and short histories gracefully."""
    # Flat price: gains and losses are zero -> NaN
    flat = [50.0] * 20
    res_flat = calculate_rsi(flat, period=14)
    assert res_flat.last_rsi is None
    assert res_flat.rsi.iloc[14:].isna().all()

    # Short history (< 15 bars)
    short = [10.0, 11.0, 12.0]
    res_short = calculate_rsi(short, period=14)
    assert res_short.rsi.empty
    assert res_short.last_rsi is None


# =============================================================================
# 2. Moving Average Convergence Divergence (MACD) Tests
# =============================================================================

def test_macd_formula_and_parity():
    """Verify MACD matches prototype convention (routes.py:129-130) reusing authoritative ema()."""
    np.random.seed(42)
    closes = [100.0 + float(v) for v in np.random.normal(0, 1, 50).cumsum()]
    s = pd.Series(closes)

    res = calculate_macd(s, fast_period=12, slow_period=26, signal_period=9)

    assert isinstance(res, MACDResult)
    assert len(res.macd) == 50
    assert len(res.signal) == 50
    assert len(res.histogram) == 50

    # Prototype reference calculation
    expected_fast = s.ewm(span=12, adjust=False).mean()
    expected_slow = s.ewm(span=26, adjust=False).mean()
    expected_macd = expected_fast - expected_slow
    expected_signal = expected_macd.ewm(span=9, adjust=False).mean()
    expected_hist = expected_macd - expected_signal

    pd.testing.assert_series_equal(res.macd, expected_macd, check_names=False)
    pd.testing.assert_series_equal(res.signal, expected_signal, check_names=False)
    pd.testing.assert_series_equal(res.histogram, expected_hist, check_names=False)

    assert res.last_macd == pytest.approx(float(expected_macd.iloc[-1]))
    assert res.last_signal == pytest.approx(float(expected_signal.iloc[-1]))
    assert res.last_histogram == pytest.approx(float(expected_hist.iloc[-1]))


def test_macd_short_series_and_edge_cases():
    """Verify MACD handles very short histories (< 2 bars) and invalid periods cleanly."""
    res_empty = calculate_macd([])
    assert res_empty.macd.empty
    assert res_empty.last_macd is None

    res_single = calculate_macd([100.0])
    assert res_single.macd.empty
    assert res_single.last_macd is None

    # Invalid periods
    res_inv = calculate_macd([100.0, 101.0], fast_period=0)
    assert res_inv.macd.empty


# =============================================================================
# 3. On-Balance Volume (OBV) Tests
# =============================================================================

def test_obv_formula_and_parity():
    """Verify OBV matches prototype cumsum convention (routes.py:145-146)."""
    closes = [100.0, 105.0, 105.0, 102.0, 108.0]
    volumes = [1000.0, 1500.0, 2000.0, 1200.0, 1800.0]

    res = calculate_obv(closes, volumes)

    assert isinstance(res, OBVResult)
    # Day 0: 0.0
    # Day 1: +1500 -> 1500.0
    # Day 2: flat -> 1500.0
    # Day 3: -1200 -> 300.0
    # Day 4: +1800 -> 2100.0
    expected_values = [0.0, 1500.0, 1500.0, 300.0, 2100.0]
    assert res.obv.tolist() == pytest.approx(expected_values)
    assert res.last_obv == pytest.approx(2100.0)


def test_obv_missing_and_zero_volume():
    """Verify OBV handles None volume, all-zero volume, and empty inputs cleanly."""
    # None volume
    res_none = calculate_obv([100.0, 105.0], None)
    assert res_none.obv.empty
    assert res_none.last_obv is None

    # Empty inputs
    assert calculate_obv([], []).obv.empty

    # All-NaN volume
    res_nan = calculate_obv([100.0, 105.0], [np.nan, np.nan])
    assert res_nan.last_obv is None

    # Partial zero volume: unchanged on zero-volume days
    res_zero = calculate_obv([100.0, 105.0, 110.0], [1000.0, 500.0, 0.0])
    assert res_zero.obv.tolist() == pytest.approx([0.0, 500.0, 500.0])


# =============================================================================
# 4. Money Flow Index (MFI) Tests
# =============================================================================

def test_mfi_formula_and_parity():
    """Verify MFI matches prototype convention (formulas.py:597-606)."""
    np.random.seed(42)
    closes = [100.0 + float(v) for v in np.random.normal(0, 1, 40).cumsum()]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    volumes = [1000.0 + float(v) for v in np.random.uniform(0, 500, 40)]

    res = calculate_mfi(highs, lows, closes, volumes, period=14)

    assert isinstance(res, MFIResult)
    assert len(res.mfi) == 40
    # First 13 points (indices 0..12) are NaN
    assert res.mfi.iloc[:13].isna().all()
    assert not res.mfi.iloc[13:].isna().any()

    # Prototype reference calculation
    tp = (pd.Series(highs) + pd.Series(lows) + pd.Series(closes)) / 3.0
    mf = tp * pd.Series(volumes)
    up = mf.where(tp > tp.shift(), 0.0).rolling(14).sum()
    dn = mf.where(tp < tp.shift(), 0.0).rolling(14).sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = up / dn
        expected_mfi = 100.0 - (100.0 / (1.0 + ratio))

    pd.testing.assert_series_equal(res.mfi, expected_mfi, check_names=False)
    assert res.last_mfi == pytest.approx(float(expected_mfi.iloc[-1]))


def test_mfi_edge_cases():
    """Verify MFI handles missing volume, short history, and division by zero cleanly."""
    # Missing volume
    assert calculate_mfi([10.0], [8.0], [9.0], None).mfi.empty

    # Short history (< 15 bars)
    res_short = calculate_mfi([10.0]*5, [8.0]*5, [9.0]*5, [100.0]*5, period=14)
    assert res_short.mfi.empty
    assert res_short.last_mfi is None

    # Zero volume series
    res_zero = calculate_mfi([10.0]*20, [8.0]*20, [9.0]*20, [0.0]*20, period=14)
    assert res_zero.last_mfi is None

    # Pure uptrend: dn is 0 -> MFI is 100.0
    c_up = [100.0 + i * 2.0 for i in range(25)]
    h_up = [c + 1.0 for c in c_up]
    l_up = [c - 1.0 for c in c_up]
    v_up = [1000.0] * 25
    res_up = calculate_mfi(h_up, l_up, c_up, v_up, period=14)
    assert res_up.last_mfi == pytest.approx(100.0)

"""Pure calculation unit tests for Batch 3B: Price / Volatility Technical Indicators.

Verifies mathematical precision, edge case handling, and prototype formula parity for:
1. Bollinger Bands (20, 2)
2. Donchian Channels (20)
3. True Range and ATR (14)
4. ATR Volatility Bands (14, 2.0)
5. Cumulative VWAP
6. Average Price Line
"""

import numpy as np
import pandas as pd
import pytest

from yogi.calculation.bands.calculator import (
    ATRBandsResult,
    BollingerBandsResult,
    DonchianChannelsResult,
    calculate_atr,
    calculate_atr_bands,
    calculate_bollinger_bands,
    calculate_donchian_channels,
    calculate_true_range,
)
from yogi.calculation.trend.calculator import (
    average_price,
    calculate_vwap,
)


# =============================================================================
# 1. Bollinger Bands
# =============================================================================

def test_bollinger_bands_formula_and_parity():
    """Verify Bollinger Bands matches prototype: basis=rolling_mean(20), sd=rolling_std(20), basis +/- 2*sd."""
    np.random.seed(42)
    closes = [100.0 + i * 0.5 + float(np.random.normal(0, 1.0)) for i in range(30)]
    s = pd.Series(closes)

    result = calculate_bollinger_bands(s, window=20, num_std=2.0)

    assert isinstance(result, BollingerBandsResult)
    assert len(result.basis) == 30
    assert len(result.upper) == 30
    assert len(result.lower) == 30

    # First 19 points must be NaN
    assert result.basis.iloc[:19].isna().all()
    assert result.upper.iloc[:19].isna().all()
    assert result.lower.iloc[:19].isna().all()

    # Point 20 (index 19) onwards must match rolling(20)
    expected_basis = s.rolling(20).mean()
    expected_std = s.rolling(20).std()
    expected_upper = expected_basis + 2.0 * expected_std
    expected_lower = expected_basis - 2.0 * expected_std

    pd.testing.assert_series_equal(result.basis, expected_basis)
    pd.testing.assert_series_equal(result.upper, expected_upper)
    pd.testing.assert_series_equal(result.lower, expected_lower)

    # Last scalar values
    assert result.last_basis == pytest.approx(float(expected_basis.iloc[-1]))
    assert result.last_upper == pytest.approx(float(expected_upper.iloc[-1]))
    assert result.last_lower == pytest.approx(float(expected_lower.iloc[-1]))


def test_bollinger_bands_short_series_and_edge_cases():
    """Verify Bollinger Bands returns clean empty/None results for series shorter than window."""
    short_closes = [100.0, 102.0, 101.0]
    res = calculate_bollinger_bands(short_closes, window=20)

    assert res.basis.empty
    assert res.upper.empty
    assert res.lower.empty
    assert res.last_basis is None
    assert res.last_upper is None
    assert res.last_lower is None


def test_bollinger_bands_flat_price():
    """Verify Bollinger Bands on flat series has std=0, so upper == lower == basis."""
    flat = [50.0] * 25
    res = calculate_bollinger_bands(flat, window=20, num_std=2.0)

    assert res.last_basis == pytest.approx(50.0)
    assert res.last_upper == pytest.approx(50.0)
    assert res.last_lower == pytest.approx(50.0)


# =============================================================================
# 2. Donchian Channels
# =============================================================================

def test_donchian_channels_formula_and_parity():
    """Verify Donchian Channels matches prototype: upper=max(20), lower=min(20), mid=(up+lo)/2."""
    highs = [100.0 + i for i in range(25)]
    lows = [90.0 + i for i in range(25)]

    res = calculate_donchian_channels(highs, lows, window=20)

    assert isinstance(res, DonchianChannelsResult)
    assert len(res.upper) == 25
    assert len(res.lower) == 25
    assert len(res.middle) == 25

    # Rolling window 20
    assert res.upper.iloc[:19].isna().all()
    assert res.upper.iloc[19] == 119.0  # max of 100..119
    assert res.lower.iloc[19] == 90.0   # min of 90..109
    assert res.middle.iloc[19] == (119.0 + 90.0) / 2.0

    assert res.last_upper == 124.0
    assert res.last_lower == 95.0
    assert res.last_middle == (124.0 + 95.0) / 2.0


def test_donchian_channels_short_series():
    """Verify Donchian Channels returns empty/None for insufficient history."""
    res = calculate_donchian_channels([10.0, 11.0], [8.0, 9.0], window=20)

    assert res.upper.empty
    assert res.lower.empty
    assert res.middle.empty
    assert res.last_upper is None
    assert res.last_lower is None
    assert res.last_middle is None


# =============================================================================
# 3. True Range and ATR
# =============================================================================

def test_true_range_calculation():
    """Verify True Range correctly accounts for high-low, gap up, and gap down."""
    # Day 0: H=105, L=95, C=100 -> TR = 10
    # Day 1 (gap up): H=120, L=110, C=115 -> H-L=10, |H-PC|=20, |L-PC|=10 -> TR = 20
    # Day 2 (gap down): H=90, L=80, C=85 -> H-L=10, |H-PC|=25, |L-PC|=35 -> TR = 35
    highs = [105.0, 120.0, 90.0]
    lows = [95.0, 110.0, 80.0]
    closes = [100.0, 115.0, 85.0]

    tr = calculate_true_range(highs, lows, closes)
    assert tr.iloc[0] == 10.0
    assert tr.iloc[1] == 20.0
    assert tr.iloc[2] == 35.0


def test_atr_simple_rolling_mean():
    """Verify ATR is simple rolling mean of TR over period (routes.py:137)."""
    # 15 bars of constant range 10
    highs = [100.0 + i for i in range(20)]
    lows = [90.0 + i for i in range(20)]
    closes = [95.0 + i for i in range(20)]

    atr = calculate_atr(highs, lows, closes, period=14)
    assert len(atr) == 20
    assert atr.iloc[:13].isna().all()
    # High - Low is 10. High - prev_close is (100+i) - (95+i-1) = 6. Low - prev_close is 4. Max = 10.
    assert atr.iloc[13] == pytest.approx(10.0)
    assert atr.iloc[-1] == pytest.approx(10.0)


# =============================================================================
# 4. ATR Volatility Bands
# =============================================================================

def test_atr_bands_formula_and_parity():
    """Verify ATR Bands: upper = close + 2*atr, lower = close - 2*atr."""
    highs = [105.0] * 20
    lows = [95.0] * 20
    closes = [100.0] * 20

    res = calculate_atr_bands(highs, lows, closes, period=14, multiplier=2.0)

    assert isinstance(res, ATRBandsResult)
    # TR is 10.0, ATR is 10.0. Multiplier 2.0 -> band offset = 20.0
    assert res.last_atr == pytest.approx(10.0)
    assert res.last_upper == pytest.approx(120.0)
    assert res.last_lower == pytest.approx(80.0)


def test_atr_bands_short_series():
    """Verify ATR Bands handles series shorter than period cleanly."""
    res = calculate_atr_bands([10.0] * 5, [8.0] * 5, [9.0] * 5, period=14)
    assert res.upper.empty
    assert res.lower.empty
    assert res.atr.empty
    assert res.last_upper is None
    assert res.last_lower is None
    assert res.last_atr is None


# =============================================================================
# 5. Cumulative VWAP
# =============================================================================

def test_vwap_formula_and_parity():
    """Verify cumulative VWAP: cumsum(tp * vol) / cumsum(vol) where tp=(h+l+c)/3."""
    # Bar 1: H=10, L=8, C=9 -> tp=9, vol=100 -> tp*vol=900, cum_vol=100 -> vwap=9
    # Bar 2: H=12, L=10, C=11 -> tp=11, vol=200 -> tp*vol=2200, cum_vol=300 -> cum_tp_vol=3100 -> vwap = 3100/300 = 10.333
    highs = [10.0, 12.0]
    lows = [8.0, 10.0]
    closes = [9.0, 11.0]
    volumes = [100.0, 200.0]

    vwap = calculate_vwap(highs, lows, closes, volumes)
    assert len(vwap) == 2
    assert vwap.iloc[0] == pytest.approx(9.0)
    assert vwap.iloc[1] == pytest.approx(3100.0 / 300.0)


def test_vwap_edge_cases():
    """Verify VWAP edge cases: None volume, zero volume, empty data."""
    # None volume
    assert calculate_vwap([10.0], [8.0], [9.0], None).empty

    # Empty
    assert calculate_vwap([], [], [], []).empty

    # Zero volume
    vwap_zero = calculate_vwap([10.0, 12.0], [8.0, 10.0], [9.0, 11.0], [0.0, 0.0])
    assert vwap_zero.isna().all()

    # Partial zero volume
    vwap_part = calculate_vwap([10.0, 12.0], [8.0, 10.0], [9.0, 11.0], [100.0, 0.0])
    assert vwap_part.iloc[0] == pytest.approx(9.0)
    assert vwap_part.iloc[1] == pytest.approx(9.0)  # volume did not increase


# =============================================================================
# 6. Average Price
# =============================================================================

def test_average_price():
    """Verify average_price matches prototype routes.py:232 (float(close.mean()))."""
    assert average_price([10.0, 20.0, 30.0]) == pytest.approx(20.0)
    assert average_price([]) is None
    assert average_price([np.nan, np.nan]) is None
    assert average_price([15.5]) == pytest.approx(15.5)

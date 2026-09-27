"""Tests for YOGI custom analytical curves: Sprint Speed, Acceleration, Band Distance, and YOGI ROC.

Verifies pure calculation correctness, edge cases, numerical parity against prototype equations,
and index preservation.
"""

import sys
import numpy as np
import pandas as pd
import pytest

from yogi.calculation.bands.calculator import (
    BandDistanceResult,
    calculate_band_distance_curve,
    band_distance_series,
)
from yogi.calculation.velocity.calculator import (
    AccelerationResult,
    SprintSpeedResult,
    calculate_acceleration_curve,
    calculate_sprint_speed_curve,
    accel_series,
    sprint_series,
)
from yogi.calculation.trend.calculator import (
    ROCResult,
    calculate_roc_curve,
    roc_series,
)

# Reference prototype imports if available
import importlib.util
proto_path = r"D:\Yogi Investing\yogi_engine\yogi_engine"
if proto_path not in sys.path:
    sys.path.insert(0, proto_path)
try:
    spec = importlib.util.spec_from_file_location(
        "proto_formulas",
        r"D:\Yogi Investing\yogi_engine\yogi_engine\yogi\core_math\formulas.py",
    )
    proto_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proto_mod)
    proto_sprint_series = proto_mod.sprint_series
    proto_accel_series = proto_mod.accel_series
    proto_band_distance_series = proto_mod.band_distance_series
    proto_roc_series = proto_mod.roc_series
    HAS_PROTOTYPE = True
except Exception:
    HAS_PROTOTYPE = False


class TestSprintSpeedCurve:
    """Test suite for YOGI Sprint Speed curve (%/week over weeks*5 bars)."""

    def test_sprint_speed_pure_calculation(self):
        # 30 bars of constant price 100.0 -> 0.0% speed
        s = pd.Series([100.0] * 30, index=pd.date_range("2026-01-01", periods=30))
        res = calculate_sprint_speed_curve(s, weeks=4)
        assert isinstance(res, SprintSpeedResult)
        assert res.weeks == 4
        assert res.last_speed == pytest.approx(0.0)
        # First 20 bars are NaN
        assert res.speed.iloc[:20].isna().all()
        # Bars 20..29 are 0.0
        assert (res.speed.iloc[20:] == 0.0).all()

    def test_sprint_speed_exact_gain(self):
        # Price increases 20% over 20 trading bars (4 weeks) -> 5.0% / week
        vals = [100.0] * 20 + [120.0] * 10
        s = pd.Series(vals, index=pd.date_range("2026-01-01", periods=30))
        res = calculate_sprint_speed_curve(s, weeks=4)
        # At index 20: 120 / 100 - 1 = 20% -> 20 / 4 = 5.0%/week
        assert res.speed.iloc[20] == pytest.approx(5.0)
        assert res.last_speed == pytest.approx(5.0)

    @pytest.mark.skipif(not HAS_PROTOTYPE, reason="Requires prototype yogi_engine")
    def test_sprint_speed_prototype_parity(self):
        # Compare with prototype sprint_series on dynamic series
        np.random.seed(42)
        prices = 100.0 + np.cumsum(np.random.randn(80) * 2.0)
        s = pd.Series(prices, index=pd.date_range("2026-01-01", periods=80))

        yogi_res = calculate_sprint_speed_curve(s, weeks=4)
        proto_res = proto_sprint_series(s, weeks=4)

        # Drop NaNs to compare valid values
        yogi_valid = yogi_res.speed.dropna()
        proto_valid = proto_res.dropna()

        assert len(yogi_valid) == len(proto_valid)
        np.testing.assert_allclose(yogi_valid.values, proto_valid.values, rtol=1e-12, atol=1e-12)
        assert sprint_series(s, 4).dropna().equals(proto_valid)

    def test_sprint_speed_edge_cases(self):
        # Empty input
        empty_s = pd.Series([], dtype=float)
        assert calculate_sprint_speed_curve(empty_s, 4).speed.empty
        assert calculate_sprint_speed_curve(empty_s, 4).last_speed is None

        # Insufficient history (<= 20 bars for 4 weeks)
        short_s = pd.Series([100.0] * 20)
        res_short = calculate_sprint_speed_curve(short_s, 4)
        assert res_short.speed.empty
        assert res_short.last_speed is None

        # Exactly 21 bars (first valid value at index 20)
        exact_s = pd.Series([100.0] * 21)
        res_exact = calculate_sprint_speed_curve(exact_s, 4)
        assert len(res_exact.speed) == 21
        assert res_exact.last_speed == pytest.approx(0.0)

        # Invalid weeks <= 0
        assert calculate_sprint_speed_curve(exact_s, 0).speed.empty


class TestAccelerationCurve:
    """Test suite for YOGI Acceleration curve (short_weeks speed - long_weeks speed)."""

    def test_acceleration_pure_calculation(self):
        # Constant price across 300 bars -> 0.0 accel
        s = pd.Series([100.0] * 300, index=pd.date_range("2025-01-01", periods=300))
        res = calculate_acceleration_curve(s, short_weeks=4, long_weeks=52)
        assert isinstance(res, AccelerationResult)
        assert res.short_weeks == 4
        assert res.long_weeks == 52
        assert res.last_accel == pytest.approx(0.0)
        # First 260 bars (52*5) are NaN
        assert res.accel.iloc[:260].isna().all()
        # Bars 260..299 are 0.0
        assert (res.accel.iloc[260:] == 0.0).all()

    @pytest.mark.skipif(not HAS_PROTOTYPE, reason="Requires prototype yogi_engine")
    def test_acceleration_prototype_parity(self):
        np.random.seed(123)
        prices = 100.0 + np.cumsum(np.random.randn(320) * 1.5)
        s = pd.Series(prices, index=pd.date_range("2025-01-01", periods=320))

        yogi_res = calculate_acceleration_curve(s, short_weeks=4, long_weeks=52)
        proto_res = proto_accel_series(s, short_w=4, long_w=52)

        yogi_valid = yogi_res.accel.dropna()
        assert len(yogi_valid) == len(proto_res)
        np.testing.assert_allclose(yogi_valid.values, proto_res.values, rtol=1e-12, atol=1e-12)
        assert accel_series(s, 4, 52).equals(proto_res)

    def test_acceleration_edge_cases(self):
        # Insufficient bars (< 260 bars)
        s = pd.Series([100.0] * 200)
        res = calculate_acceleration_curve(s, short_weeks=4, long_weeks=52)
        assert res.accel.empty
        assert res.last_accel is None
        assert accel_series(s).empty


class TestBandDistanceCurve:
    """Test suite for YOGI Band Distance curve (% beyond edge: + above, - below, 0 inside)."""

    def test_band_distance_pure_calculation(self):
        # Price: 10 bars
        s = pd.Series([100, 102, 104, 103, 105, 108, 112, 115, 120, 130], dtype=float)
        res = calculate_band_distance_curve(s, band_frac=0.05, basis_window=20)
        assert isinstance(res, BandDistanceResult)
        assert res.band_frac == 0.05
        assert res.basis_window == 20
        # Inside the band at the beginning
        assert res.distance.iloc[0] == 0.0
        # Price spikes at the end, breaking above the upper band
        assert res.distance.iloc[-1] > 0.0
        assert res.last_distance == pytest.approx(res.distance.iloc[-1])

    @pytest.mark.skipif(not HAS_PROTOTYPE, reason="Requires prototype yogi_engine")
    def test_band_distance_prototype_parity(self):
        s = pd.Series([100, 102, 104, 103, 105, 108, 112, 115, 120, 130], dtype=float)
        yogi_res = calculate_band_distance_curve(s, band_frac=0.05, basis_window=20)
        proto_res = proto_band_distance_series(s, band_frac=0.05, basis_window=20)

        np.testing.assert_allclose(yogi_res.distance.values, proto_res.values, rtol=1e-12, atol=1e-12)
        assert band_distance_series(s, 0.05).equals(proto_res)

    def test_band_distance_below_band(self):
        # Price collapses below lower band
        s = pd.Series([100, 100, 100, 100, 100, 50, 40], dtype=float)
        res = calculate_band_distance_curve(s, band_frac=0.10, basis_window=5)
        # Last values must be negative (% below lower band)
        assert res.distance.iloc[-1] < 0.0
        assert res.last_distance < 0.0

    def test_band_distance_edge_cases(self):
        s = pd.Series([100.0, 105.0])
        # Fewer than 3 bars
        assert calculate_band_distance_curve(s, 0.10).distance.empty
        assert calculate_band_distance_curve(s, 0.10).last_distance is None

        # Missing or zero band_frac
        s_long = pd.Series([100.0] * 10)
        assert calculate_band_distance_curve(s_long, None).distance.empty
        assert calculate_band_distance_curve(s_long, 0.0).distance.empty


class TestROCCurve:
    """Test suite for YOGI Rate of Change (21d) curve."""

    def test_roc_curve_pure_calculation(self):
        # 30 bars constant price -> 0.0 ROC
        s = pd.Series([100.0] * 30, index=pd.date_range("2026-01-01", periods=30))
        res = calculate_roc_curve(s, days=21)
        assert isinstance(res, ROCResult)
        assert res.days == 21
        assert res.last_roc == pytest.approx(0.0)
        # First 21 bars are NaN
        assert res.roc.iloc[:21].isna().all()
        # Bars 21..29 are 0.0
        assert (res.roc.iloc[21:] == 0.0).all()

    @pytest.mark.skipif(not HAS_PROTOTYPE, reason="Requires prototype yogi_engine")
    def test_roc_curve_prototype_parity(self):
        np.random.seed(99)
        prices = 50.0 + np.cumsum(np.random.randn(50) * 1.2)
        s = pd.Series(prices, index=pd.date_range("2026-01-01", periods=50))

        yogi_res = calculate_roc_curve(s, days=21)
        proto_res = proto_roc_series(s, days=21)

        yogi_valid = yogi_res.roc.dropna()
        assert len(yogi_valid) == len(proto_res)
        np.testing.assert_allclose(yogi_valid.values, proto_res.values, rtol=1e-12, atol=1e-12)
        assert roc_series(s, 21).equals(proto_res)

    def test_roc_curve_edge_cases(self):
        # Empty input
        empty_s = pd.Series([], dtype=float)
        assert calculate_roc_curve(empty_s, 21).roc.empty
        assert calculate_roc_curve(empty_s, 21).last_roc is None

        # Insufficient history (<= 21 bars)
        short_s = pd.Series([100.0] * 21)
        assert calculate_roc_curve(short_s, 21).roc.empty
        assert calculate_roc_curve(short_s, 21).last_roc is None

        # Exactly 22 bars (first valid value at index 21)
        exact_s = pd.Series([100.0] * 22)
        res = calculate_roc_curve(exact_s, 21)
        assert len(res.roc) == 22
        assert res.last_roc == pytest.approx(0.0)


class TestInputImmutabilityAndAlignment:
    """Verify input series immutability and index preservation."""

    def test_immutability(self):
        dates = pd.date_range("2025-01-01", periods=300)
        original_vals = [100.0 + i for i in range(300)]
        s = pd.Series(original_vals, index=dates)
        s_copy = s.copy()

        _ = calculate_sprint_speed_curve(s, 4)
        _ = calculate_acceleration_curve(s, 4, 52)
        _ = calculate_band_distance_curve(s, 0.15)
        _ = calculate_roc_curve(s, 21)

        assert s.equals(s_copy)

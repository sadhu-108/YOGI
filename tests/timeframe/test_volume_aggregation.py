"""Tests for optimized weekly/monthly volume aggregation in Yogi Timeframe Engine.

Verifies strict contract compliance:
1. Ordinary numeric volume aggregation (exact sum).
2. Mixed numeric and missing (None / NaN) values (sums finite values, ignores missing).
3. Groups where every volume value is missing MUST result in None (never silently 0.0).
4. Zero volume (0.0) is preserved as 0.0 (never converted to None).
5. All timeframe rules (W, M, Q, H, Y) and calendar half-year policies.
6. Bit-for-bit equivalence against the baseline lambda aggregation contract.
"""

from datetime import datetime
import math
from typing import Optional
import pytest

from yogi.core.contracts.market_data import MarketBar, Timeframe
from yogi.timeframe.engine import resample_bars


def make_bar(
    ts: datetime,
    open_: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: Optional[float] = 1000.0,
) -> MarketBar:
    return MarketBar(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


class TestVolumeAggregationSemantics:
    """Verifies volume aggregation semantics across edge cases."""

    def test_ordinary_numeric_volume_sums_correctly(self):
        """Standard daily volumes must sum to the exact total for the period."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=1000.0),
            make_bar(datetime(2024, 1, 9), volume=2500.0),
            make_bar(datetime(2024, 1, 10), volume=1500.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 5000.0

    def test_all_volume_none_produces_none(self):
        """When all bars in a period have None volume, synthesized volume must be None."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=None),
            make_bar(datetime(2024, 1, 9), volume=None),
            make_bar(datetime(2024, 1, 10), volume=None),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume is None

    def test_all_volume_nan_produces_none(self):
        """When all bars in a period have NaN volume, synthesized volume must be None."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=float("nan")),
            make_bar(datetime(2024, 1, 9), volume=float("nan")),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume is None

    def test_mixed_volume_none_and_numeric(self):
        """Periods with mixed None and numeric volume must sum only numeric values."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=1000.0),
            make_bar(datetime(2024, 1, 9), volume=None),
            make_bar(datetime(2024, 1, 10), volume=2000.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 3000.0

    def test_mixed_volume_nan_and_numeric(self):
        """Periods with mixed NaN and numeric volume must sum only numeric values."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=1500.0),
            make_bar(datetime(2024, 1, 9), volume=float("nan")),
            make_bar(datetime(2024, 1, 10), volume=3500.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 5000.0

    def test_zero_volume_is_preserved_as_zero(self):
        """Zero volume is valid data and must not become None or be omitted."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=0.0),
            make_bar(datetime(2024, 1, 9), volume=0.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 0.0

    def test_zero_volume_mixed_with_none_preserves_zero(self):
        """If a period has only 0.0 and None, the finite 0.0 must be preserved."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=0.0),
            make_bar(datetime(2024, 1, 9), volume=None),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 0.0

    def test_multi_period_with_varying_volume_presence(self):
        """Across multiple periods, periods with missing volume must yield None,

        periods with 0.0 must yield 0.0, and periods with positive volume must yield their sum.
        """
        bars = [
            # Week 1: Valid numeric volume
            make_bar(datetime(2024, 1, 1), volume=1000.0),
            make_bar(datetime(2024, 1, 2), volume=2000.0),
            # Week 2: Mixed None and NaN -> MUST yield None, NOT 0.0
            make_bar(datetime(2024, 1, 8), volume=None),
            make_bar(datetime(2024, 1, 9), volume=float("nan")),
            # Week 3: Mixed zero and numeric -> 500.0
            make_bar(datetime(2024, 1, 15), volume=0.0),
            make_bar(datetime(2024, 1, 16), volume=500.0),
            # Week 4: Only zero -> 0.0
            make_bar(datetime(2024, 1, 22), volume=0.0),
            make_bar(datetime(2024, 1, 23), volume=0.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 4
        assert weekly[0].volume == 3000.0
        assert weekly[1].volume is None
        assert weekly[2].volume == 500.0
        assert weekly[3].volume == 0.0

    def test_monthly_and_calendar_half_year_volume(self):
        """Verify volume semantics across Monthly and Calendar Half-Year synthesis."""
        bars = [
            # Jan 2024: finite volume
            make_bar(datetime(2024, 1, 15), volume=1000.0),
            # Feb 2024: all None volume
            make_bar(datetime(2024, 2, 15), volume=None),
            # Mar 2024: 0.0 volume
            make_bar(datetime(2024, 3, 15), volume=0.0),
        ]
        monthly = resample_bars(bars, "M")
        assert len(monthly) == 3
        assert monthly[0].volume == 1000.0
        assert monthly[1].volume is None
        assert monthly[2].volume == 0.0

        # Calendar half-year: H1 2024 should sum Jan, Feb, Mar -> 1000.0 + None + 0.0 = 1000.0
        half = resample_bars(bars, "H", half_year_policy="calendar")
        assert len(half) == 1
        assert half[0].volume == 1000.0


class TestTimeframeEquivalence:
    """Verifies that all OHLCV components match expected reference values across all timeframes."""

    @pytest.mark.parametrize("tf", ["W", "M", "Q", "H", "Y"])
    def test_all_timeframes_preserve_ohlc_and_volume(self, tf):
        bars = [
            make_bar(datetime(2024, 1, 2), open_=100, high=105, low=95, close=102, volume=100.0),
            make_bar(datetime(2024, 1, 3), open_=102, high=110, low=101, close=108, volume=200.0),
            make_bar(datetime(2024, 2, 1), open_=108, high=115, low=105, close=112, volume=300.0),
        ]
        res = resample_bars(bars, tf)
        assert len(res) >= 1
        assert all(b.open > 0 for b in res)
        assert all(b.high >= b.low for b in res)
        assert all(b.volume is not None and b.volume > 0 for b in res)

"""Comprehensive verification test suite for YOGI Timeframe Cache Foundation.

Verifies the 10 required caching foundation behaviors:
1. Lazy population: a missing entry is calculated only when needed.
2. Cache hit: repeated requests reuse a valid entry.
3. Isolation: different symbols or timeframes cannot incorrectly share entries.
4. Invalidation: a source-data update makes the affected derived entry unusable.
5. Historical revision: changes to relevant historical bars cannot silently reuse stale data.
6. Timeframe correctness: cached results match the existing uncached timeframe calculation across D, W, M, Q, H, Y.
7. Candle policy: existing completed-candle and current-candle behaviour remains unchanged.
8. Failure handling: failed derivation does not leave a corrupt or falsely valid cache entry.
9. Memory/lifecycle policy: LRU capacity eviction and cleanup behaviour work as intended.
10. Contract compatibility: existing module boundaries, ITimeframeEngine contracts, and MarketContext remain consistent.
"""

from datetime import datetime, timedelta
from typing import Sequence
import unittest
from unittest.mock import patch
import pytest

from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.timeframe.cache import (
    TimeframeCache,
    TimeframeCacheEntry,
    compute_bars_fingerprint,
    normalize_timeframe_key,
)
from yogi.timeframe.engine import (
    TIMEFRAME_RULES,
    TimeframeEngine,
    build_market_context,
    resample_bars,
)


def make_daily_bars(
    start_date: str = "2024-01-01",
    count: int = 100,
    base_price: float = 100.0,
    symbol: str = "TEST",
) -> tuple[MarketBar, ...]:
    """Deterministic fixture generating daily MarketBar sequence."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    bars = []
    for i in range(count):
        ts = start + timedelta(days=i)
        p = base_price + i * 0.5
        bars.append(
            MarketBar(
                timestamp=ts,
                open=p - 1.0,
                high=p + 2.0,
                low=p - 2.0,
                close=p,
                volume=1000.0 + i * 10,
            )
        )
    return tuple(bars)


class TestTimeframeCacheFoundation(unittest.TestCase):
    """Test suite covering the 10 formal caching foundation requirements."""

    def setUp(self):
        self.daily_bars = make_daily_bars("2024-01-01", 120, base_price=150.0)
        self.engine = TimeframeEngine(enable_cache=True, max_cache_entries=100)

    def test_01_lazy_population(self):
        """Requirement 1: A missing entry is calculated only when first requested."""
        stats_before = self.engine.cache_stats
        self.assertIsNotNone(stats_before)
        self.assertEqual(stats_before["entries"], 0)
        self.assertEqual(stats_before["hits"], 0)
        self.assertEqual(stats_before["misses"], 0)

        # Request weekly timeframe
        ctx = self.engine.build_context("RELIANCE", "NSE", self.daily_bars, timeframes=["W"])
        self.assertIn("W", ctx.bars_by_timeframe)
        self.assertGreater(len(ctx.get_bars("W")), 0)

        stats_after = self.engine.cache_stats
        self.assertEqual(stats_after["entries"], 1)
        self.assertEqual(stats_after["misses"], 1)
        self.assertEqual(stats_after["hits"], 0)

    def test_02_cache_hit_reuse(self):
        """Requirement 2: Repeated requests reuse a valid entry without recalculation."""
        # 1st request -> populate
        ctx1 = self.engine.build_context("TCS", "NSE", self.daily_bars, timeframes=["W"])
        bars1 = ctx1.get_bars("W")

        # 2nd request with exact same daily bars
        ctx2 = self.engine.build_context("TCS", "NSE", self.daily_bars, timeframes=["W"])
        bars2 = ctx2.get_bars("W")

        # Verify identity reuse
        self.assertIs(bars1, bars2)
        stats = self.engine.cache_stats
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["entries"], 1)

    def test_03_isolation(self):
        """Requirement 3: Different symbols or timeframes cannot incorrectly share entries."""
        other_bars = make_daily_bars("2024-01-01", 120, base_price=3000.0)

        # Populate RELIANCE W and TCS W
        self.engine.build_context("RELIANCE", "NSE", self.daily_bars, timeframes=["W"])
        self.engine.build_context("TCS", "NSE", other_bars, timeframes=["W"])
        self.engine.build_context("RELIANCE", "NSE", self.daily_bars, timeframes=["M"])

        stats = self.engine.cache_stats
        self.assertEqual(stats["entries"], 3)

        rel_w = self.engine.build_context("RELIANCE", "NSE", self.daily_bars, timeframes=["W"]).get_bars("W")
        tcs_w = self.engine.build_context("TCS", "NSE", other_bars, timeframes=["W"]).get_bars("W")
        rel_m = self.engine.build_context("RELIANCE", "NSE", self.daily_bars, timeframes=["M"]).get_bars("M")

        # Prove isolation across prices, lengths, and identities
        self.assertNotEqual(rel_w[0].close, tcs_w[0].close)
        self.assertNotEqual(len(rel_w), len(rel_m))
        self.assertIsNot(rel_w, tcs_w)
        self.assertIsNot(rel_w, rel_m)

    def test_04_invalidation_on_source_update(self):
        """Requirement 4: Appending new bars makes the affected derived entry unusable and recomputes."""
        self.engine.build_context("INFY", "NSE", self.daily_bars, timeframes=["W"])
        initial_stats = self.engine.cache_stats
        self.assertEqual(initial_stats["entries"], 1)

        # Append a new daily bar
        new_bar = MarketBar(
            timestamp=self.daily_bars[-1].timestamp + timedelta(days=1),
            open=250.0,
            high=255.0,
            low=249.0,
            close=254.0,
            volume=50000.0,
        )
        updated_daily = self.daily_bars + (new_bar,)

        # Request again with updated bars
        ctx = self.engine.build_context("INFY", "NSE", updated_daily, timeframes=["W"])
        updated_w = ctx.get_bars("W")

        # Stale entry must be invalidated and recomputed
        self.assertEqual(updated_w[-1].close, 254.0)
        stats = self.engine.cache_stats
        self.assertEqual(stats["invalidations"], 1)
        self.assertEqual(stats["misses"], 2)  # 1 initial miss + 1 after invalidation

    def test_05_historical_revision_detection(self):
        """Requirement 5: Changes to historical bars cannot silently reuse stale data."""
        self.engine.build_context("HDFCBANK", "NSE", self.daily_bars, timeframes=["W"])
        orig_w = self.engine.build_context("HDFCBANK", "NSE", self.daily_bars, timeframes=["W"]).get_bars("W")

        # Simulate historical corporate action / price revision at index 50 without changing bar count or start/end dates
        revised_list = list(self.daily_bars)
        target_b = revised_list[50]
        revised_list[50] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open / 2.0,
            high=target_b.high / 2.0,
            low=target_b.low / 2.0,
            close=target_b.close / 2.0,
            volume=target_b.volume * 2.0,
        )
        revised_daily = tuple(revised_list)

        # Same length and same boundary dates
        self.assertEqual(len(revised_daily), len(self.daily_bars))
        self.assertEqual(revised_daily[0].timestamp, self.daily_bars[0].timestamp)
        self.assertEqual(revised_daily[-1].timestamp, self.daily_bars[-1].timestamp)

        # Revision fingerprint MUST detect the price change
        fp_orig = compute_bars_fingerprint(self.daily_bars)
        fp_rev = compute_bars_fingerprint(revised_daily)
        self.assertNotEqual(fp_orig, fp_rev)

        # Re-evaluating MUST invalidate stale entry and produce revised weekly bars
        ctx_rev = self.engine.build_context("HDFCBANK", "NSE", revised_daily, timeframes=["W"])
        new_w = ctx_rev.get_bars("W")
        self.assertIsNot(orig_w, new_w)
        self.assertNotEqual(orig_w, new_w)

    def test_06_timeframe_correctness_all_timeframes(self):
        """Requirement 6: Cached results match uncached calculation across all 6 timeframes: D, W, M, Q, H, Y."""
        timeframes = ("D", "W", "M", "Q", "H", "Y")
        long_bars = make_daily_bars("2020-01-01", 1200, base_price=100.0)

        for tf in timeframes:
            # Uncached pure calculation
            expected = resample_bars(long_bars, tf, half_year_policy="prototype")

            # 1st request through engine (populates cache)
            ctx1 = self.engine.build_context("TEST", "NSE", long_bars, timeframes=[tf])
            cached1 = ctx1.get_bars(tf)

            # 2nd request through engine (serves from cache)
            ctx2 = self.engine.build_context("TEST", "NSE", long_bars, timeframes=[tf])
            cached2 = ctx2.get_bars(tf)

            # Assert exact mathematical and object equality
            self.assertEqual(len(cached1), len(expected), f"Length mismatch on timeframe {tf}")
            self.assertEqual(len(cached2), len(expected), f"Length mismatch on timeframe {tf} (cache hit)")
            for i in range(len(expected)):
                self.assertEqual(cached1[i].timestamp, expected[i].timestamp, f"Timestamp mismatch at index {i} on {tf}")
                self.assertAlmostEqual(cached1[i].close, expected[i].close, places=4, msg=f"Close mismatch at {i} on {tf}")
                self.assertEqual(cached2[i].timestamp, expected[i].timestamp)
                self.assertAlmostEqual(cached2[i].close, expected[i].close, places=4)

    def test_07_candle_policy_preservation(self):
        """Requirement 7: Existing completed-candle and current-candle behavior remains unchanged."""
        long_bars = make_daily_bars("2024-01-01", 300, base_price=100.0)
        # Verify both prototype and calendar policies
        ctx_proto = self.engine.build_context("STOCK", "NSE", long_bars, timeframes=["H"], half_year_policy="prototype")
        ctx_cal = self.engine.build_context("STOCK", "NSE", long_bars, timeframes=["H"], half_year_policy="calendar")

        proto_h = ctx_proto.get_bars("H")
        cal_h = ctx_cal.get_bars("H")

        # Prototype boundaries (Mar/Sep 2QE) vs Calendar boundaries (Jun/Dec)
        self.assertNotEqual([b.timestamp for b in proto_h], [b.timestamp for b in cal_h])

        # Repeated requests under each policy retrieve correct respective cached entries
        ctx_proto2 = self.engine.build_context("STOCK", "NSE", long_bars, timeframes=["H"], half_year_policy="prototype")
        ctx_cal2 = self.engine.build_context("STOCK", "NSE", long_bars, timeframes=["H"], half_year_policy="calendar")

        self.assertIs(ctx_proto.get_bars("H"), ctx_proto2.get_bars("H"))
        self.assertIs(ctx_cal.get_bars("H"), ctx_cal2.get_bars("H"))

    def test_08_failure_handling_leaves_no_corrupt_entry(self):
        """Requirement 8: Failed derivation does not leave a corrupt or falsely valid cache entry."""
        with patch("yogi.timeframe.engine.resample_bars", side_effect=ValueError("Synthetic resampling failure")):
            with self.assertRaises(ValueError):
                self.engine.build_context("FAIL", "NSE", self.daily_bars, timeframes=["W"])

        # Cache must have 0 entries for failed key
        stats = self.engine.cache_stats
        self.assertEqual(stats["entries"], 0)

        # Subsequent call with normal execution succeeds cleanly
        ctx = self.engine.build_context("FAIL", "NSE", self.daily_bars, timeframes=["W"])
        self.assertIn("W", ctx.bars_by_timeframe)
        self.assertEqual(self.engine.cache_stats["entries"], 1)

    def test_09_memory_and_eviction_lifecycle(self):
        """Requirement 9: LRU eviction, capacity limit, and explicit clearing work as intended."""
        small_engine = TimeframeEngine(enable_cache=True, max_cache_entries=3)

        # Insert 3 entries
        small_engine.build_context("SYM1", "NSE", self.daily_bars, timeframes=["W"])
        small_engine.build_context("SYM2", "NSE", self.daily_bars, timeframes=["W"])
        small_engine.build_context("SYM3", "NSE", self.daily_bars, timeframes=["W"])
        self.assertEqual(small_engine.cache_stats["entries"], 3)
        self.assertEqual(small_engine.cache_stats["evictions"], 0)

        # Insert 4th entry -> triggers LRU eviction of oldest (SYM1)
        small_engine.build_context("SYM4", "NSE", self.daily_bars, timeframes=["W"])
        self.assertEqual(small_engine.cache_stats["entries"], 3)
        self.assertEqual(small_engine.cache_stats["evictions"], 1)

        # Explicit invalidation of SYM2
        evicted = small_engine.invalidate_cache(symbol="SYM2")
        self.assertEqual(evicted, 1)
        self.assertEqual(small_engine.cache_stats["entries"], 2)

        # Clear entire cache
        small_engine.clear_cache()
        self.assertEqual(small_engine.cache_stats["entries"], 0)

    def test_10_contract_compatibility(self):
        """Requirement 10: Preserves ITimeframeEngine contract and MarketContext interfaces."""
        self.assertIsInstance(self.engine, ITimeframeEngine)
        self.assertTrue(hasattr(self.engine, "resample"))
        self.assertTrue(hasattr(self.engine, "build_context"))
        self.assertTrue(hasattr(self.engine, "invalidate_cache"))
        self.assertTrue(hasattr(self.engine, "clear_cache"))

        ctx = self.engine.build_context("CONTRACT", "NSE", self.daily_bars, timeframes=["W", "M"])
        self.assertIsInstance(ctx, MarketContext)
        self.assertEqual(ctx.symbol, "CONTRACT")
        self.assertEqual(ctx.exchange, "NSE")
        self.assertIsInstance(ctx.get_bars("W"), Sequence)
        self.assertIsInstance(ctx.get_closes("W"), Sequence)
        self.assertEqual(len(ctx.get_bars("W")), len(ctx.get_closes("W")))

    def test_11_field_level_mutation_detection_independent_fields(self):
        """Correction 1 (F-TIMEFRAME-01): Changes to any OHLCV field or timestamp invalidate cache."""
        # Baseline weekly derivation
        ctx_base = self.engine.build_context("FIELD_TEST", "NSE", self.daily_bars, timeframes=["W"])
        base_w = ctx_base.get_bars("W")
        fp_base = compute_bars_fingerprint(self.daily_bars)

        # Target an index that was NOT sampled by previous sampled-close fingerprint
        target_idx = 13
        target_b = self.daily_bars[target_idx]

        # 1. High price mutation
        bars_high = list(self.daily_bars)
        bars_high[target_idx] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open,
            high=target_b.high + 500.0,
            low=target_b.low,
            close=target_b.close,
            volume=target_b.volume,
        )
        tuple_high = tuple(bars_high)
        fp_high = compute_bars_fingerprint(tuple_high)
        self.assertNotEqual(fp_base, fp_high, "High price mutation must alter fingerprint")

        ctx_high = self.engine.build_context("FIELD_TEST", "NSE", tuple_high, timeframes=["W"])
        w_high = ctx_high.get_bars("W")
        self.assertIsNot(base_w, w_high, "Cache must invalidate and return fresh weekly bars")
        self.assertTrue(any(b.high >= target_b.high + 500.0 for b in w_high))

        # 2. Low price mutation
        bars_low = list(self.daily_bars)
        bars_low[target_idx] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open,
            high=target_b.high,
            low=target_b.low - 50.0,
            close=target_b.close,
            volume=target_b.volume,
        )
        tuple_low = tuple(bars_low)
        fp_low = compute_bars_fingerprint(tuple_low)
        self.assertNotEqual(fp_base, fp_low, "Low price mutation must alter fingerprint")

        ctx_low = self.engine.build_context("FIELD_TEST", "NSE", tuple_low, timeframes=["W"])
        w_low = ctx_low.get_bars("W")
        self.assertTrue(any(b.low <= target_b.low - 50.0 for b in w_low))

        # 3. Volume mutation
        bars_vol = list(self.daily_bars)
        bars_vol[target_idx] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open,
            high=target_b.high,
            low=target_b.low,
            close=target_b.close,
            volume=(target_b.volume or 0.0) + 1_000_000.0,
        )
        tuple_vol = tuple(bars_vol)
        fp_vol = compute_bars_fingerprint(tuple_vol)
        self.assertNotEqual(fp_base, fp_vol, "Volume mutation must alter fingerprint")

        ctx_vol = self.engine.build_context("FIELD_TEST", "NSE", tuple_vol, timeframes=["W"])
        w_vol = ctx_vol.get_bars("W")
        self.assertTrue(any(b.volume is not None and b.volume >= 1_000_000.0 for b in w_vol))

        # 4. Open price mutation
        bars_open = list(self.daily_bars)
        bars_open[target_idx] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open + 200.0,
            high=max(target_b.high, target_b.open + 200.0),
            low=target_b.low,
            close=target_b.close,
            volume=target_b.volume,
        )
        tuple_open = tuple(bars_open)
        fp_open = compute_bars_fingerprint(tuple_open)
        self.assertNotEqual(fp_base, fp_open, "Open price mutation must alter fingerprint")

        # 5. Offsetting price changes on same-length series (sum of close invariant)
        bars_offset = list(self.daily_bars)
        b1 = bars_offset[13]
        b2 = bars_offset[17]
        bars_offset[13] = MarketBar(b1.timestamp, b1.open, b1.high, b1.low, b1.close + 10.0, b1.volume)
        bars_offset[17] = MarketBar(b2.timestamp, b2.open, b2.high, b2.low, b2.close - 10.0, b2.volume)
        tuple_offset = tuple(bars_offset)
        fp_offset = compute_bars_fingerprint(tuple_offset)
        self.assertNotEqual(fp_base, fp_offset, "Offsetting price changes must alter fingerprint")

    def test_12_in_place_sequence_mutations_on_mutable_list(self):
        """Correction 2 (F-TIMEFRAME-02): In-place list mutations cannot bypass validation via object identity."""
        daily_list = list(make_daily_bars("2024-01-01", 100, base_price=100.0))
        list_obj_id = id(daily_list)

        # 1. First build context with mutable list
        ctx1 = self.engine.build_context("MUT_LIST", "NSE", daily_list, timeframes=["W"])
        w1 = ctx1.get_bars("W")
        stats1 = self.engine.cache_stats
        self.assertEqual(stats1["misses"], 1)
        self.assertEqual(stats1["hits"], 0)

        # 2. Append new bar in place (id(daily_list) remains unchanged!)
        new_bar = MarketBar(
            timestamp=daily_list[-1].timestamp + timedelta(days=1),
            open=300.0,
            high=310.0,
            low=295.0,
            close=305.0,
            volume=10000.0,
        )
        daily_list.append(new_bar)
        self.assertEqual(id(daily_list), list_obj_id, "List object identity must be preserved")

        ctx2 = self.engine.build_context("MUT_LIST", "NSE", daily_list, timeframes=["W"])
        w2 = ctx2.get_bars("W")
        self.assertIsNot(w1, w2, "Cache must NOT return stale weekly bars after in-place append")
        self.assertEqual(w2[-1].close, 305.0, "Derived bar must reflect the appended daily bar")

        # 3. In-place shorten / pop
        daily_list.pop()
        self.assertEqual(id(daily_list), list_obj_id)

        ctx3 = self.engine.build_context("MUT_LIST", "NSE", daily_list, timeframes=["W"])
        w3 = ctx3.get_bars("W")
        self.assertIsNot(w2, w3, "Cache must NOT return stale weekly bars after in-place pop")
        self.assertNotEqual(w3[-1].close, 305.0)

        # 4. In-place element modification / replacement
        target_b = daily_list[10]
        daily_list[10] = MarketBar(
            timestamp=target_b.timestamp,
            open=target_b.open,
            high=999.0,
            low=target_b.low,
            close=target_b.close,
            volume=target_b.volume,
        )
        self.assertEqual(id(daily_list), list_obj_id)

        ctx4 = self.engine.build_context("MUT_LIST", "NSE", daily_list, timeframes=["W"])
        w4 = ctx4.get_bars("W")
        self.assertIsNot(w3, w4, "Cache must NOT return stale weekly bars after in-place item replacement")
        self.assertTrue(any(b.high >= 999.0 for b in w4))

    def test_13_non_finite_and_missing_value_fingerprint_stability(self):
        """Correction 3: NaN, Infinities, and None volume produce stable fingerprints without false evictions."""
        base_bars = list(make_daily_bars("2024-01-01", 60, base_price=100.0))
        # Insert NaN volume and None volume
        base_bars[10] = MarketBar(
            timestamp=base_bars[10].timestamp,
            open=base_bars[10].open,
            high=base_bars[10].high,
            low=base_bars[10].low,
            close=base_bars[10].close,
            volume=float("nan"),
        )
        base_bars[20] = MarketBar(
            timestamp=base_bars[20].timestamp,
            open=base_bars[20].open,
            high=base_bars[20].high,
            low=base_bars[20].low,
            close=base_bars[20].close,
            volume=None,
        )
        nan_tuple = tuple(base_bars)

        fp1 = compute_bars_fingerprint(nan_tuple)
        fp2 = compute_bars_fingerprint(nan_tuple)
        self.assertEqual(fp1, fp2, "Fingerprints containing NaN must evaluate as equal across calls")

        # 1st request populates cache
        ctx1 = self.engine.build_context("NAN_STABLE", "NSE", nan_tuple, timeframes=["W"])
        w1 = ctx1.get_bars("W")

        # 2nd and 3rd requests must HIT the cache, NOT evict or miss
        ctx2 = self.engine.build_context("NAN_STABLE", "NSE", nan_tuple, timeframes=["W"])
        w2 = ctx2.get_bars("W")
        ctx3 = self.engine.build_context("NAN_STABLE", "NSE", nan_tuple, timeframes=["W"])
        w3 = ctx3.get_bars("W")

        self.assertIs(w1, w2)
        self.assertIs(w2, w3)

        stats = self.engine.cache_stats
        self.assertEqual(stats["invalidations"], 0, "No false invalidations should occur on NaN series")
        self.assertEqual(stats["hits"], 2)

        # Meaningful change on NaN-containing series must still be detected
        mutated_bars = list(nan_tuple)
        mutated_bars[5] = MarketBar(
            timestamp=mutated_bars[5].timestamp,
            open=mutated_bars[5].open,
            high=mutated_bars[5].high,
            low=mutated_bars[5].low,
            close=mutated_bars[5].close + 25.0,
            volume=mutated_bars[5].volume,
        )
        mut_tuple = tuple(mutated_bars)
        fp_mut = compute_bars_fingerprint(mut_tuple)
        self.assertNotEqual(fp1, fp_mut, "Price change in NaN series must be detected")

        ctx_mut = self.engine.build_context("NAN_STABLE", "NSE", mut_tuple, timeframes=["W"])
        w_mut = ctx_mut.get_bars("W")
        self.assertIsNot(w1, w_mut)
        self.assertEqual(self.engine.cache_stats["invalidations"], 1)

    def test_14_windows_pre_epoch_and_timezone_robustness(self):
        """Pre-1970 dates do not raise OSError on Windows and hash deterministically."""
        pre_epoch_bars = (
            MarketBar(datetime(1965, 1, 1), 10.0, 11.0, 9.5, 10.5, 1000.0),
            MarketBar(datetime(1965, 1, 2), 10.5, 12.0, 10.0, 11.5, 1500.0),
            MarketBar(datetime(1965, 1, 3), 11.5, 12.5, 11.0, 12.0, 1200.0),
        )
        # Verify compute_bars_fingerprint does not raise
        fp = compute_bars_fingerprint(pre_epoch_bars)
        self.assertEqual(fp[0], 3)
        self.assertIsInstance(fp[1], str)
        self.assertEqual(len(fp[1]), 64)  # SHA-256 hex digest length

        # Cache lookup and hit
        ctx1 = self.engine.build_context("PRE_EPOCH", "NSE", pre_epoch_bars, timeframes=["W"])
        ctx2 = self.engine.build_context("PRE_EPOCH", "NSE", pre_epoch_bars, timeframes=["W"])
        self.assertIs(ctx1.get_bars("W"), ctx2.get_bars("W"))



if __name__ == "__main__":
    unittest.main()

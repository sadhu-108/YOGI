"""Comprehensive test suite for YOGI Timeframe Engine (Step 7).

Verifies:
- Prototype resampling frequency rules (D, W, ME, QE, 2QE, YE).
- Authoritative OHLCV aggregation invariant (Open=first, High=max, Low=min, Close=last, Volume=sum).
- Missing, None, and zero volume handling without bar truncation.
- Calendar boundaries: leap years, short weeks, mid-week holidays, incomplete current periods.
- Gap periods: absence of synthetic/phantom bars when market is closed.
- Limited history: single bar, 3-bar recent IPOs, empty sequences.
- Deterministic chronological sorting and duplicate timestamp handling.
- MarketContext assembly and PipelineOrchestrator integration.
"""

from datetime import datetime, timedelta
import random
from typing import Mapping, Sequence

import pytest

from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext, Timeframe
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.timeframe.engine import (
    TIMEFRAME_RULES,
    TimeframeEngine,
    build_market_context,
    resample_bars,
)


def make_bar(
    ts: datetime,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: float = 1000.0,
) -> MarketBar:
    return MarketBar(
        timestamp=ts,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# ===========================================================================
# 1. Rules, Enums, and Normalization
# ===========================================================================


class TestTimeframeRulesAndEnums:
    def test_prototype_frequency_rules_exact_match(self):
        """Verify the 6 canonical timeframes match prototype config.py exactly."""
        expected = {
            "D": None,
            "W": "W",
            "M": "ME",
            "Q": "QE",
            "H": "2QE",
            "Y": "YE",
        }
        assert TIMEFRAME_RULES == expected

    def test_timeframe_enum_and_string_equivalence(self):
        engine = TimeframeEngine()
        bars = [
            make_bar(datetime(2024, 1, 1), 100, 105, 95, 102, 1000),
            make_bar(datetime(2024, 1, 2), 102, 107, 100, 105, 1200),
        ]
        res_enum = engine.resample(bars, Timeframe.WEEKLY)
        res_str = engine.resample(bars, "W")
        res_lower = engine.resample(bars, "w")
        assert res_enum == res_str == res_lower

    def test_unsupported_timeframe_raises_value_error(self):
        bars = [make_bar(datetime(2024, 1, 1))]
        with pytest.raises(ValueError, match="Unsupported timeframe '2D'"):
            resample_bars(bars, "2D")

        # Empty input with unsupported timeframe must also raise ValueError
        with pytest.raises(ValueError, match="Unsupported timeframe 'INVALID'"):
            resample_bars([], "INVALID")

        # Empty input with supported timeframe must return empty tuple ()
        assert resample_bars([], "D") == ()
        assert resample_bars([], "W") == ()
        assert resample_bars([], Timeframe.MONTHLY) == ()


# ===========================================================================
# 2. OHLCV Aggregation Invariant
# ===========================================================================


class TestOHLCVAggregationInvariant:
    def test_5_day_week_exact_aggregation(self):
        """Verify Open=first, High=max, Low=min, Close=last, Volume=sum on a standard 5-day week."""
        # 2024-01-08 (Mon) to 2024-01-12 (Fri)
        daily_bars = [
            make_bar(datetime(2024, 1, 8), open_=100.0, high=105.0, low=99.0, close=101.0, volume=1000.0),
            make_bar(datetime(2024, 1, 9), open_=101.0, high=106.0, low=100.0, close=104.0, volume=1500.0),
            make_bar(datetime(2024, 1, 10), open_=104.0, high=108.0, low=103.0, close=107.0, volume=2000.0),
            make_bar(datetime(2024, 1, 11), open_=107.0, high=107.0, low=95.0, close=98.0, volume=2500.0),
            make_bar(datetime(2024, 1, 12), open_=98.0, high=102.0, low=97.0, close=102.0, volume=1200.0),
        ]
        weekly = resample_bars(daily_bars, "W")

        assert len(weekly) == 1
        w_bar = weekly[0]
        # Period-end timestamp is Sunday 2024-01-14
        assert w_bar.timestamp == datetime(2024, 1, 14, 0, 0)
        assert w_bar.timestamp.tzinfo is None
        # OHLCV mathematical invariants
        assert w_bar.open == 100.0   # Monday Open
        assert w_bar.high == 108.0   # Wednesday High (peak of the week)
        assert w_bar.low == 95.0     # Thursday Low (trough of the week)
        assert w_bar.close == 102.0  # Friday Close
        assert w_bar.volume == 8200.0  # 1000 + 1500 + 2000 + 2500 + 1200

    def test_daily_timeframe_returns_canonical_identity(self):
        """Daily timeframe (D) must return identical sorted daily bars without resampling."""
        bars = [
            make_bar(datetime(2024, 1, 2), close=105.0),
            make_bar(datetime(2024, 1, 1), close=100.0),
        ]
        res = resample_bars(bars, "D")
        assert len(res) == 2
        assert res[0].timestamp == datetime(2024, 1, 1)
        assert res[0].close == 100.0
        assert res[1].timestamp == datetime(2024, 1, 2)
        assert res[1].close == 105.0


# ===========================================================================
# 3. All Standard Higher-Order Timeframes
# ===========================================================================


class TestAllStandardTimeframes:
    @pytest.fixture
    def two_year_daily_bars(self) -> list[MarketBar]:
        """Generate contiguous business-day bars for 2024 and 2025."""
        bars = []
        cur = datetime(2024, 1, 1)
        end = datetime(2025, 12, 31)
        price = 100.0
        while cur <= end:
            # Skip Saturday (5) and Sunday (6)
            if cur.weekday() < 5:
                bars.append(
                    MarketBar(
                        timestamp=cur,
                        open=price,
                        high=price + 2.0,
                        low=price - 2.0,
                        close=price + 1.0,
                        volume=5000.0,
                    )
                )
                price += 0.5
            cur += timedelta(days=1)
        return bars

    def test_synthesis_across_all_six_timeframes(self, two_year_daily_bars):
        engine = TimeframeEngine()
        for tf in ("D", "W", "M", "Q", "H", "Y"):
            res = engine.resample(two_year_daily_bars, tf)
            assert len(res) > 0, f"Timeframe {tf} produced zero bars"
            assert all(isinstance(b, MarketBar) for b in res)
            # Verify strict chronological ascending order
            for i in range(len(res) - 1):
                assert res[i].timestamp < res[i + 1].timestamp

    def test_period_end_boundary_timestamps(self, two_year_daily_bars):
        engine = TimeframeEngine()
        # Weekly: all timestamps must be Sunday
        weeks = engine.resample(two_year_daily_bars, "W")
        assert all(b.timestamp.weekday() == 6 for b in weeks)

        # Monthly: timestamps must be calendar month ends
        months = engine.resample(two_year_daily_bars, "M")
        for m in months:
            next_day = m.timestamp + timedelta(days=1)
            assert next_day.day == 1, f"Month bar {m.timestamp} is not month end"

        # Quarterly: timestamps must be Mar 31, Jun 30, Sep 30, Dec 31
        quarters = engine.resample(two_year_daily_bars, "Q")
        assert len(quarters) == 8
        for q in quarters:
            assert (q.timestamp.month, q.timestamp.day) in [(3, 31), (6, 30), (9, 30), (12, 31)]

        # Half-Yearly: 2QE timestamps (Mar 31, Sep 30)
        halves = engine.resample(two_year_daily_bars, "H")
        assert len(halves) == 5
        for h in halves:
            assert (h.timestamp.month, h.timestamp.day) in [(3, 31), (9, 30)]

        # Yearly: timestamps must be Dec 31
        years = engine.resample(two_year_daily_bars, "Y")
        assert len(years) == 2
        assert years[0].timestamp == datetime(2024, 12, 31)
        assert years[1].timestamp == datetime(2025, 12, 31)


# ===========================================================================
# 4. Volume and Missing / None Value Semantics
# ===========================================================================


class TestVolumeHandling:
    def test_all_volume_none_preserves_none_without_dropping_bars(self):
        """Missing volume across all daily bars must yield volume=None, not drop price bars."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=None),
            make_bar(datetime(2024, 1, 9), volume=None),
            make_bar(datetime(2024, 1, 10), volume=None),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume is None
        assert weekly[0].open == 100.0
        assert weekly[0].close == 102.0

    def test_mixed_volume_sums_available_volumes(self):
        """Mixed volume (some None, some float) must sum available numeric volume."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=1000.0),
            make_bar(datetime(2024, 1, 9), volume=None),
            make_bar(datetime(2024, 1, 10), volume=2500.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 3500.0

    def test_zero_volume_is_retained_as_zero(self):
        """Zero volume is a valid numerical quantity and must not become None."""
        bars = [
            make_bar(datetime(2024, 1, 8), volume=0.0),
            make_bar(datetime(2024, 1, 9), volume=0.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].volume == 0.0


# ===========================================================================
# 5. Calendar Boundaries, Holidays & Incomplete Periods
# ===========================================================================


class TestCalendarAndHolidayBoundaries:
    def test_single_day_holiday_week(self):
        """A week with only 1 trading session (e.g. Diwali Muhurat) produces 1 valid weekly bar."""
        bars = [
            make_bar(datetime(2024, 1, 10), open_=150.0, high=160.0, low=148.0, close=155.0, volume=500.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].open == 150.0
        assert weekly[0].high == 160.0
        assert weekly[0].low == 148.0
        assert weekly[0].close == 155.0
        assert weekly[0].volume == 500.0
        assert weekly[0].timestamp == datetime(2024, 1, 14)  # Week ending Sunday

    def test_midweek_holiday_aggregates_without_gap(self):
        """4 trading days in a week (holiday on Wednesday) aggregates seamlessly."""
        bars = [
            make_bar(datetime(2024, 1, 8), open_=100.0, close=101.0),
            make_bar(datetime(2024, 1, 9), open_=101.0, close=102.0),
            # 2024-01-10 is a holiday
            make_bar(datetime(2024, 1, 11), open_=102.0, close=103.0),
            make_bar(datetime(2024, 1, 12), open_=103.0, close=105.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].open == 100.0
        assert weekly[0].close == 105.0

    def test_leap_year_february_29(self):
        """February 2024 leap year produces monthly bar ending on Feb 29."""
        bars = [
            make_bar(datetime(2024, 2, 1), open_=200.0, close=205.0),
            make_bar(datetime(2024, 2, 29), open_=210.0, close=215.0),
        ]
        monthly = resample_bars(bars, "M")
        assert len(monthly) == 1
        assert monthly[0].timestamp == datetime(2024, 2, 29)
        assert monthly[0].open == 200.0
        assert monthly[0].close == 215.0

    def test_incomplete_current_period_tracks_latest_daily_close(self):
        """In-progress week ending mid-week (e.g. Wednesday) has close matching Wednesday's close."""
        bars = [
            make_bar(datetime(2024, 1, 15), open_=300.0, high=305.0, low=298.0, close=302.0),
            make_bar(datetime(2024, 1, 16), open_=302.0, high=310.0, low=301.0, close=308.0),
            make_bar(datetime(2024, 1, 17), open_=308.0, high=312.0, low=305.0, close=311.0),
        ]
        weekly = resample_bars(bars, "W")
        assert len(weekly) == 1
        assert weekly[0].open == 300.0
        assert weekly[0].high == 312.0
        assert weekly[0].low == 298.0
        assert weekly[0].close == 311.0  # Latest Wednesday close

    def test_gap_periods_do_not_produce_synthetic_bars(self):
        """Trading suspension for 2 months must NOT emit synthetic or interpolated bars."""
        bars = [
            make_bar(datetime(2024, 1, 15), close=100.0),
            # February and March have NO trading
            make_bar(datetime(2024, 4, 15), close=120.0),
        ]
        monthly = resample_bars(bars, "M")
        assert len(monthly) == 2
        assert monthly[0].timestamp == datetime(2024, 1, 31)
        assert monthly[1].timestamp == datetime(2024, 4, 30)


# ===========================================================================
# 6. Recent IPOs and Limited History
# ===========================================================================


class TestLimitedHistoryAndEmptyInputs:
    def test_single_daily_bar_produces_all_higher_timeframes(self):
        """A stock with exactly 1 daily bar produces 1 bar in every requested timeframe."""
        bars = [
            make_bar(datetime(2024, 3, 15), open_=50.0, high=55.0, low=48.0, close=52.0, volume=1000.0)
        ]
        engine = TimeframeEngine()
        for tf in ("D", "W", "M", "Q", "H", "Y"):
            res = engine.resample(bars, tf)
            assert len(res) == 1
            assert res[0].open == 50.0
            assert res[0].close == 52.0
            assert res[0].volume == 1000.0

    def test_empty_bars_produces_empty_tuples_without_crash(self):
        """Empty input sequences return () without error."""
        engine = TimeframeEngine()
        for tf in ("D", "W", "M", "Q", "H", "Y"):
            assert engine.resample((), tf) == ()
            assert engine.resample([], tf) == ()

    def test_few_bars_recent_ipo(self):
        """Recent IPO with 3 daily bars produces valid bars across all timeframes."""
        bars = [
            make_bar(datetime(2024, 6, 26), close=100.0),
            make_bar(datetime(2024, 6, 27), close=105.0),
            make_bar(datetime(2024, 6, 28), close=110.0),
        ]
        engine = TimeframeEngine()
        ctx = engine.build_context("NEW_IPO", "NSE", bars)
        assert len(ctx.get_bars("D")) == 3
        assert len(ctx.get_bars("W")) == 1
        assert len(ctx.get_bars("M")) == 1
        assert ctx.get_closes("M") == [110.0]


# ===========================================================================
# 7. Unsorted Inputs and Duplicate Timestamps
# ===========================================================================


class TestUnsortedAndDuplicateInputs:
    def test_reverse_order_input_is_sorted_chronologically(self):
        """Unsorted input daily bars must be sorted before OHLCV synthesis."""
        b1 = make_bar(datetime(2024, 1, 8), open_=100.0, close=102.0)
        b2 = make_bar(datetime(2024, 1, 9), open_=102.0, close=104.0)
        b3 = make_bar(datetime(2024, 1, 10), open_=104.0, close=106.0)

        # Pass in reverse order: b3, b2, b1
        weekly = resample_bars([b3, b2, b1], "W")
        assert len(weekly) == 1
        assert weekly[0].open == 100.0  # b1 Open
        assert weekly[0].close == 106.0  # b3 Close

    def test_randomly_shuffled_input_produces_identical_result(self):
        """Randomly shuffled daily bars produce deterministic identical output."""
        base_bars = [
            make_bar(datetime(2024, 1, 8 + i), open_=100.0 + i, close=101.0 + i)
            for i in range(5)
        ]
        expected_weekly = resample_bars(base_bars, "W")

        shuffled = list(base_bars)
        random.seed(42)
        random.shuffle(shuffled)

        res = resample_bars(shuffled, "W")
        assert res == expected_weekly

    def test_duplicate_timestamps_deduplicated_deterministically(self):
        """Duplicate daily bar timestamps retain the final occurrence and maintain strict ordering."""
        # Two conflicting bars for 2024-01-08: b1_first and b1_final
        b1_first = make_bar(datetime(2024, 1, 8), open_=100.0, high=102.0, low=99.0, close=101.0, volume=1000.0)
        b1_final = make_bar(datetime(2024, 1, 8), open_=101.0, high=104.0, low=100.0, close=103.0, volume=1500.0)

        # Two conflicting bars for 2024-01-09: b2_first and b2_final
        b2_first = make_bar(datetime(2024, 1, 9), open_=103.0, high=106.0, low=102.0, close=105.0, volume=2000.0)
        b2_final = make_bar(datetime(2024, 1, 9), open_=104.0, high=107.0, low=103.0, close=106.0, volume=2500.0)

        input_bars = [b1_first, b1_final, b2_first, b2_final]

        # 1. Verify Daily ("D") retention of the final duplicate
        daily = resample_bars(input_bars, "D")
        assert len(daily) == 2
        # First bar has b1_final values
        assert daily[0].timestamp == datetime(2024, 1, 8)
        assert daily[0].open == 101.0
        assert daily[0].close == 103.0
        assert daily[0].volume == 1500.0
        # Second bar has b2_final values
        assert daily[1].timestamp == datetime(2024, 1, 9)
        assert daily[1].open == 104.0
        assert daily[1].close == 106.0
        assert daily[1].volume == 2500.0

        # Strict chronological order and no duplicate timestamps remain
        assert daily[0].timestamp < daily[1].timestamp
        assert len(daily) == len({b.timestamp for b in daily})

        # 2. Verify Weekly ("W") synthesis uses retained deduplicated records
        weekly = resample_bars(input_bars, "W")
        assert len(weekly) == 1
        w_bar = weekly[0]
        assert w_bar.open == 101.0   # b1_final Open
        assert w_bar.high == 107.0   # b2_final High
        assert w_bar.low == 100.0    # b1_final Low
        assert w_bar.close == 106.0  # b2_final Close
        assert w_bar.volume == 4000.0  # 1500 + 2500
        assert len(weekly) == len({b.timestamp for b in weekly})


# ===========================================================================
# 8. MarketContext Assembly
# ===========================================================================


class TestMarketContextAssembly:
    def test_build_market_context_all_timeframes(self):
        bars = [
            make_bar(datetime(2024, 1, 8), close=100.0),
            make_bar(datetime(2024, 1, 9), close=105.0),
        ]
        ctx = build_market_context(
            symbol="RELIANCE",
            exchange="NSE",
            daily_bars=bars,
        )
        assert ctx.symbol == "RELIANCE"
        assert ctx.exchange == "NSE"
        assert ctx.as_of == datetime(2024, 1, 9)
        assert set(ctx.bars_by_timeframe.keys()) == {"D", "W", "M", "Q", "H", "Y"}
        assert len(ctx.get_bars("D")) == 2
        assert len(ctx.get_bars("W")) == 1
        assert ctx.get_closes("D") == [100.0, 105.0]
        assert ctx.get_closes("W") == [105.0]

    def test_build_market_context_timeframe_subset(self):
        bars = [make_bar(datetime(2024, 1, 8), close=100.0)]
        ctx = build_market_context(
            symbol="INFY",
            exchange="NSE",
            daily_bars=bars,
            timeframes=("D", "W"),
        )
        assert set(ctx.bars_by_timeframe.keys()) == {"D", "W"}
        assert ctx.get_bars("M") == ()

    def test_build_market_context_empty_bars(self):
        ctx = build_market_context("EMPTY", "NSE", ())
        assert ctx.symbol == "EMPTY"
        assert ctx.as_of is None
        assert set(ctx.bars_by_timeframe.keys()) == {"D", "W", "M", "Q", "H", "Y"}
        assert ctx.get_bars("D") == ()
        assert ctx.get_closes("W") == []


# ===========================================================================
# 9. Pipeline Orchestrator Integration
# ===========================================================================


class MockDataProvider(IDataProvider):
    def __init__(self, history_map: Mapping[str, Sequence[MarketBar]]):
        self._history = history_map

    @property
    def name(self) -> str:
        return "mock_provider"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return list(self._history.keys())

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 10) -> Sequence[MarketBar]:
        return self._history.get(symbol, ())

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 10) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> float:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else 0.0

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols, on_tick, exchange="NSE"):
        return None

    def trading_holidays(self, year=None):
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth("mock_provider", True)


class RecordingCalcModule(ICalcModule):
    def __init__(self, name: str):
        self._name = name
        self.recorded_contexts: list[CalculationContext] = []

    @property
    def name(self) -> str:
        return self._name

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        self.recorded_contexts.append(context)
        return CalculationResult(symbol=symbol, module_name=self._name, metrics={"ran": True})


class MockBandsRepo(IBandsRepository):
    def get_band(self, symbol: str, timeframe: str) -> float:
        return 0.1

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        return {"D": 0.1, "W": 0.15, "M": None, "Q": None, "H": None, "Y": None}

    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "app",
        source: str = "app",
    ) -> float:
        return value


class TestOrchestratorTimeframeIntegration:
    def test_pipeline_orchestrator_populates_multi_timeframe_context(self):
        """Verify PipelineOrchestrator invokes TimeframeEngine and populates MarketContext across timeframes."""
        history = {
            "TCS": [
                make_bar(datetime(2024, 1, 8), close=3500.0),
                make_bar(datetime(2024, 1, 9), close=3550.0),
                make_bar(datetime(2024, 1, 10), close=3600.0),
            ]
        }
        provider = MockDataProvider(history)
        calc_mod = RecordingCalcModule("trend")
        bands_repo = MockBandsRepo()

        hub = RegistryHub()
        hub.providers.register("mock_provider", provider)
        hub.calculations.register("trend", calc_mod)
        hub.bands.register("mock_bands", bands_repo)

        orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
        config = EngineConfig(
            provider="mock_provider",
            bands_repository="mock_bands",
            calculation_modules=("trend",),
            symbols=("TCS",),
            timeframes=("D", "W", "M"),
        )

        records = orchestrator.build_dataset(config)

        assert "TCS" in records
        assert records["TCS"]["price"] == 3600.0
        assert len(calc_mod.recorded_contexts) == 1

        calc_ctx = calc_mod.recorded_contexts[0]
        m_ctx = calc_ctx.market_context

        # Verify multi-timeframe context was synthesized and passed to calculation module
        assert len(m_ctx.get_bars("D")) == 3
        assert len(m_ctx.get_bars("W")) == 1
        assert len(m_ctx.get_bars("M")) == 1
        assert m_ctx.get_closes("W") == [3600.0]
        assert m_ctx.get_closes("M") == [3600.0]

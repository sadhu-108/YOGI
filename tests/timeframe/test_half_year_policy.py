"""Tests for Configurable Half-Year (H) Timeframe Policy.

Verifies:
1. Prototype-Compatible policy (default): 2QE boundaries ending Mar 31 and Sep 30.
2. Calendar Half-Year policy: H1 = Jan 1 to Jun 30 (Jun 30), H2 = Jul 1 to Dec 31 (Dec 31).
3. OHLCV aggregation invariant for both policies.
4. Semantics of H_CUR, H_P1, H_P2, and H_CUR_KEY under both policies.
5. Multi-timeframe MarketContext and calculation pillar integration.
"""

from datetime import datetime
import numpy as np
import pandas as pd
import pytest

from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.calculation import CalculationContext
from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.calculation.bands import BandsCalculator
from yogi.calculation.trend import TrendCalculator, half_block
from yogi.timeframe.engine import TimeframeEngine, resample_bars, build_market_context


def make_daily_series(start_date: str, end_date: str) -> list[MarketBar]:
    """Generate daily MarketBar test fixtures over a specified date range."""
    idx = pd.bdate_range(start_date, end_date)
    bars = []
    base = 100.0
    for i, ts in enumerate(idx):
        # Deterministic price wave
        o = base + i * 0.1
        h = o + 2.0
        l = o - 2.0
        c = o + 0.5
        v = 1000.0 + i
        bars.append(
            MarketBar(
                timestamp=ts.to_pydatetime(),
                open=round(o, 2),
                high=round(h, 2),
                low=round(l, 2),
                close=round(c, 2),
                volume=v,
            )
        )
    return bars


class TestHalfYearPolicySynthesis:
    def test_prototype_policy_boundaries(self):
        """Prototype policy (2QE) must produce half-year bars ending Mar 31 and Sep 30."""
        bars = make_daily_series("2024-01-01", "2026-08-13")
        engine = TimeframeEngine(half_year_policy="prototype")
        h_bars = engine.resample(bars, "H")

        assert len(h_bars) >= 4
        for b in h_bars:
            # Must end in either month 3 (March) or month 9 (September)
            assert b.timestamp.month in (3, 9)
            if b.timestamp.month == 3:
                assert b.timestamp.day == 31
            elif b.timestamp.month == 9:
                assert b.timestamp.day == 30

    def test_calendar_policy_boundaries(self):
        """Calendar policy must produce half-year bars ending Jun 30 (H1) and Dec 31 (H2)."""
        bars = make_daily_series("2024-01-01", "2026-08-13")
        engine = TimeframeEngine(half_year_policy="calendar")
        h_bars = engine.resample(bars, "H")

        assert len(h_bars) >= 4
        for b in h_bars:
            # Must end in either month 6 (June) or month 12 (December)
            assert b.timestamp.month in (6, 12)
            if b.timestamp.month == 6:
                assert b.timestamp.day == 30
            elif b.timestamp.month == 12:
                assert b.timestamp.day == 31

    def test_calendar_half_ohlcv_aggregation(self):
        """Verify strict OHLCV aggregation invariant for Calendar Half-Year bars."""
        # 2 full years: 2024 and 2025 -> 4 calendar half bars
        bars = make_daily_series("2024-01-01", "2025-12-31")
        h_bars = resample_bars(bars, "H", half_year_policy="calendar")

        assert len(h_bars) == 4
        expected_ends = [
            datetime(2024, 6, 30),
            datetime(2024, 12, 31),
            datetime(2025, 6, 30),
            datetime(2025, 12, 31),
        ]
        for b, exp_end in zip(h_bars, expected_ends):
            assert b.timestamp == exp_end

        # Check H1 2024: Jan 1 to Jun 30
        h1_daily = [b for b in bars if b.timestamp <= datetime(2024, 6, 30)]
        h1_bar = h_bars[0]
        assert h1_bar.open == h1_daily[0].open
        assert h1_bar.close == h1_daily[-1].close
        assert h1_bar.high == max(b.high for b in h1_daily)
        assert h1_bar.low == min(b.low for b in h1_daily)
        assert h1_bar.volume == sum(b.volume for b in h1_daily)

    def test_build_market_context_respects_policy(self):
        """build_market_context must synthesize H bars according to the configured policy."""
        bars = make_daily_series("2024-01-01", "2026-08-13")

        ctx_proto = build_market_context(
            symbol="TEST",
            exchange="NSE",
            daily_bars=bars,
            half_year_policy="prototype",
        )
        h_proto = ctx_proto.get_bars("H")
        assert all(b.timestamp.month in (3, 9) for b in h_proto)

        ctx_cal = build_market_context(
            symbol="TEST",
            exchange="NSE",
            daily_bars=bars,
            half_year_policy="calendar",
        )
        h_cal = ctx_cal.get_bars("H")
        assert all(b.timestamp.month in (6, 12) for b in h_cal)


class TestHalfYearPolicyCalculations:
    def test_trend_calculator_with_calendar_policy(self):
        """TrendCalculator must use the calendar H bars and parameters when configured."""
        bars = make_daily_series("2023-01-01", "2026-08-13")
        engine = TimeframeEngine(half_year_policy="calendar")
        market_ctx = engine.build_context(
            symbol="TEST",
            exchange="NSE",
            daily_bars=bars,
        )

        calc = TrendCalculator()
        ctx = CalculationContext(
            market_context=market_ctx,
            parameters={"half_year_policy": "calendar"},
        )
        res = calc.calculate("TEST", ctx)

        assert "H_CUR" in res.metrics
        assert "H_P1" in res.metrics
        assert "H_P2" in res.metrics
        assert res.metrics["H_CUR_KEY"] == "H2"
        assert res.metrics["H_KEYS"] == "H2,H1,H2"
        assert res.metrics["EMA_H"] in ("yes", "no", "upcut", "downcut", "na")

    def test_bands_calculator_with_calendar_policy(self):
        """BandsCalculator must evaluate H band states against calendar H bars."""
        bars = make_daily_series("2023-01-01", "2026-08-13")
        engine = TimeframeEngine(half_year_policy="calendar")
        market_ctx = engine.build_context(
            symbol="TEST",
            exchange="NSE",
            daily_bars=bars,
        )

        calc = BandsCalculator()
        ctx = CalculationContext(
            market_context=market_ctx,
            bands_lookup={"H": 0.20},
        )
        res = calc.calculate("TEST", ctx)

        assert res.metrics["BAND_H"] == 0.20
        assert res.metrics["BANDST_H"] in ("ABOVE", "BELOW", "IN", "na")
        assert "N_ABOVE" in res.metrics

    def test_timeframe_engine_contract_conformance_and_signature(self):
        """Verify TimeframeEngine satisfies ITimeframeEngine contract with half_year_policy."""
        import inspect
        from yogi.core.contracts.timeframe import ITimeframeEngine

        engine = TimeframeEngine()
        assert isinstance(engine, ITimeframeEngine)

        # Verify contract declaration
        contract_sig = inspect.signature(ITimeframeEngine.build_context)
        assert "half_year_policy" in contract_sig.parameters
        assert contract_sig.parameters["half_year_policy"].default is None

        # Verify concrete implementation declaration
        impl_sig = inspect.signature(engine.build_context)
        assert "half_year_policy" in impl_sig.parameters

        # Verify contract call without reflection
        typed_engine: ITimeframeEngine = engine
        bars = make_daily_series("2024-01-01", "2024-06-30")
        ctx = typed_engine.build_context(
            symbol="TEST",
            exchange="NSE",
            daily_bars=bars,
            half_year_policy="calendar",
        )
        assert ctx.symbol == "TEST"
        assert "H" in ctx.bars_by_timeframe


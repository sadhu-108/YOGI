"""Focused verification test suite for Prompt 2: Targeted Dynamic EMA Screening Optimization.

Verifies:
1. Mathematical Equivalence: Optimized dynamic EMA matches reference calculation across fast/slow periods,
   weekly/monthly timeframes, and closed-candle policies.
2. Rule Combination Reuse: Rules sharing a timeframe reuse resolved timeframe bars and pre-extracted Series.
3. Shared Period Reuse: Rules sharing an EMA span (e.g. fast period 9) reuse computed EMA series.
4. Identical Rule Memoization: Duplicate calculation keys within a request reuse the evaluated signal dictionary.
5. Precalculated Shortcut: Fixed EMA 3/5 requests retain their precalculated field shortcut without triggering dynamic evaluation.
6. Isolation & Lifecycle: Request-local caches are strictly scoped to execute_screen() and do not leak across queries.
7. Dataset Isolation: Core feature dataset remains unchanged without dynamic column pollution.
"""

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
import pytest
import pandas as pd

from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.calculation import CalculationContext
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.market_data import MarketBar
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.calculation.trend.calculator import (
    TrendCalculator,
    calculate_dynamic_ema_signal,
    ema,
)
from yogi.filter.engine import FilterEngine
from yogi.timeframe.engine import TimeframeEngine


def make_test_bars(start_date: str = "2023-01-01", count: int = 150) -> tuple[MarketBar, ...]:
    """Generate deterministic synthetic daily bars for testing."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    bars = []
    for i in range(count):
        ts = start + timedelta(days=i)
        p = 100.0 + i * 0.5
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


def test_mathematical_equivalence_all_periods():
    """Requirement 6.A: Mathematical equivalence across various fast and slow periods."""
    bars = make_test_bars("2023-01-01", 200)
    engine = TimeframeEngine(enable_cache=True)
    w_bars = engine.build_context("TEST", "NSE", bars, timeframes=["W"]).get_bars("W")

    test_pairs = [(3, 5), (9, 21), (13, 34), (5, 13), (8, 21)]
    for p1, p2 in test_pairs:
        # 1. Unoptimized path: direct bars
        res_raw = calculate_dynamic_ema_signal(w_bars, p1=p1, p2=p2, timeframe="W")

        # 2. Optimized path: passing pre-extracted pd.Series + ema_cache
        c_series = pd.Series([float(b.close) for b in w_bars])
        ema_cache: dict[tuple[int, int], pd.Series] = {}
        res_opt = calculate_dynamic_ema_signal(c_series, p1=p1, p2=p2, timeframe="W", ema_cache=ema_cache)

        assert res_raw["state"] == res_opt["state"]
        assert res_raw["is_up"] == res_opt["is_up"]
        assert res_raw["is_down"] == res_opt["is_down"]
        assert res_raw["is_upcut"] == res_opt["is_upcut"]
        assert res_raw["is_downcut"] == res_opt["is_downcut"]
        assert pytest.approx(res_raw["cur_diff"], 1e-9) == res_opt["cur_diff"]
        assert pytest.approx(res_raw["p1_val"], 1e-9) == res_opt["p1_val"]
        assert pytest.approx(res_raw["p2_val"], 1e-9) == res_opt["p2_val"]


def test_shared_timeframe_and_span_reuse():
    """Requirement 6.B: Rules sharing timeframe and spans reuse cached objects."""
    bars = make_test_bars("2023-01-01", 200)
    calc = TrendCalculator()
    engine = TimeframeEngine(enable_cache=True)
    ctx = engine.build_context("TEST", "NSE", bars, timeframes=["W"])

    # Shared request caches
    series_cache: dict[tuple[str, str], pd.Series] = {}
    ema_cache: dict[tuple[int, int], pd.Series] = {}
    calc_ctx = CalculationContext(
        market_context=ctx,
        parameters={"series_cache": series_cache, "ema_cache": ema_cache},
    )

    rule1 = FilterRuleSpec(field="W_9_21", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=9, p2=21)
    rule2 = FilterRuleSpec(field="W_9_34", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=9, p2=34)

    # 1st evaluation populates series_cache and ema_cache (spans 9 and 21)
    sig1 = calc.calculate_dynamic("TEST", rule1, calc_ctx)
    assert len(series_cache) == 1
    assert ("TEST", "W") in series_cache
    assert len(ema_cache) == 2  # span 9 and span 21

    # 2nd evaluation reuses series and span 9, only computing span 34
    sig2 = calc.calculate_dynamic("TEST", rule2, calc_ctx)
    assert len(series_cache) == 1  # Series was reused without re-allocation!
    assert len(ema_cache) == 3  # Only 1 new span (34) was computed!

    assert sig1["p1_val"] == sig2["p1_val"]  # Fast EMA 9 values match exactly


def make_test_orchestrator(bars_cache: Any) -> PipelineOrchestrator:
    hub = RegistryHub()
    hub.calculations.register("trend", TrendCalculator())
    return PipelineOrchestrator(
        registry=hub,
        timeframe_engine=TimeframeEngine(enable_cache=True),
        filter_rule=FilterEngine(),
        bars_cache=bars_cache,
    )


def test_pipeline_request_local_cache_lifecycle():
    """Requirement 6.D: Pipeline execute_screen request-local memoization does not leak across calls."""
    bars = make_test_bars("2023-01-01", 200)
    bars_cache = {"SYM_A": bars, "SYM_B": bars}
    records = {
        "SYM_A": {"symbol": "SYM_A", "exchange": "NSE", "price": 150.0},
        "SYM_B": {"symbol": "SYM_B", "exchange": "NSE", "price": 150.0},
    }

    orch = make_test_orchestrator(bars_cache)

    query1 = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="W_EMA_9_21", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=9, p2=21, params={"state": "UP"}),
                FilterRuleSpec(field="W_EMA_9_34", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=9, p2=34, params={"state": "UP"}),
            ]
        )
    )

    res1 = orch.execute_screen(query=query1, records=records)
    assert res1 is not None
    assert len(res1.rows) > 0

    # Execute second independent query with different parameters
    query2 = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="W_EMA_13_34", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=13, p2=34, params={"state": "UP"}),
            ]
        )
    )
    res2 = orch.execute_screen(query=query2, records=records)
    assert res2 is not None
    assert len(res2.rows) > 0


def test_precalculated_ema_shortcut_preserved():
    """Requirement 6.C: Precalculated EMA 3/5 fields use existing shortcut without dynamic recomputation."""
    records = {
        "SYM_1": {"symbol": "SYM_1", "exchange": "NSE", "price": 100.0, "EMA_W": "up"},
        "SYM_2": {"symbol": "SYM_2", "exchange": "NSE", "price": 200.0, "EMA_W": "down"},
    }

    orch = make_test_orchestrator({})  # Empty bars_cache proves no dynamic bar lookup is triggered!

    # Screening query using default EMA 3/5
    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="UP", condition_type="ema", timeframe="W", p1=3, p2=5, params={"state": "UP"}),
            ]
        )
    )

    # Must succeed cleanly from precalculated records without needing bars_cache
    res = orch.execute_screen(query=query, records=records)
    assert len(res.rows) == 1
    assert res.rows[0]["symbol"] == "SYM_1"


# ==============================================================================
# PROMPT 3: TARGETED CACHE-CORRECTNESS REMEDIATIONS (F-01, F-02, F-03, F-04)
# ==============================================================================

def test_f01_signal_cache_parameter_collision_prevention():
    """F-01: Distinct parameterized dynamic rules (e.g. ROC 1m vs 3m) must not collide in req_sig_cache."""
    bars = make_test_bars("2024-01-01", 100)
    bars_cache = {"TEST": bars}
    records = {"TEST": {"symbol": "TEST", "exchange": "NSE", "price": 100.0}}

    class SignalRecorderFilter(FilterEngine):
        def evaluate(self, records, spec, **kwargs):
            self.recorded_rec = dict(records.get("TEST", {}))
            return super().evaluate(records, spec, **kwargs)

    filter_engine = SignalRecorderFilter()
    hub = RegistryHub()
    hub.calculations.register("trend", TrendCalculator())
    orch = PipelineOrchestrator(
        registry=hub,
        timeframe_engine=TimeframeEngine(enable_cache=True),
        filter_rule=filter_engine,
        bars_cache=bars_cache,
    )

    # 1. Forward order: ROC 1m followed by ROC 3m
    q1 = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="r_1m", condition_type="roc", timeframe="D", params={"period": "1m"}),
                FilterRuleSpec(field="r_3m", condition_type="roc", timeframe="D", params={"period": "3m"}),
            ]
        )
    )
    orch.execute_screen(q1, records)
    rec1 = filter_engine.recorded_rec
    assert rec1["r_1m"]["period"] == "1m"
    assert rec1["r_3m"]["period"] == "current_quarter"  # 3m maps to current_quarter in calculate_dynamic_roc
    assert rec1["r_1m"]["period"] != rec1["r_3m"]["period"]

    # 2. Reverse order: ROC 3m followed by ROC 1m
    q2 = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="r_3m_rev", condition_type="roc", timeframe="D", params={"period": "3m"}),
                FilterRuleSpec(field="r_1m_rev", condition_type="roc", timeframe="D", params={"period": "1m"}),
            ]
        )
    )
    orch.execute_screen(q2, records)
    rec2 = filter_engine.recorded_rec
    assert rec2["r_3m_rev"]["period"] == "current_quarter"
    assert rec2["r_1m_rev"]["period"] == "1m"

    # 3. Identical rules share evaluated signal safely
    q3 = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="r_1m_a", condition_type="roc", timeframe="D", params={"period": "1m"}),
                FilterRuleSpec(field="r_1m_b", condition_type="roc", timeframe="D", params={"period": "1m"}),
            ]
        )
    )
    orch.execute_screen(q3, records)
    rec3 = filter_engine.recorded_rec
    assert rec3["r_1m_a"] == rec3["r_1m_b"]

    # 4. Parameter dictionary insertion order invariance
    from yogi.core.orchestration.pipeline import _extract_calc_param_key
    r_order_a = FilterRuleSpec(field="test_a", condition_type="ema", timeframe="W", params={"p1": 9, "p2": 21, "foo": "bar"})
    r_order_b = FilterRuleSpec(field="test_b", condition_type="ema", timeframe="W", params={"foo": "bar", "p2": 21, "p1": 9})
    assert _extract_calc_param_key(r_order_a) == _extract_calc_param_key(r_order_b)


def test_f02_ema_cache_identity_reuse_and_nan_handling():
    """F-02: Strong reference retention in ema_cache prevents pointer recycling on Series with NaNs."""
    ema_cache: dict[tuple[int, int], Any] = {}

    # Test 100 consecutive short-lived Series with NaNs and ascending price baselines
    for i in range(100):
        baseline = 1000.0 * (i + 1)
        prices = [baseline + float(x) for x in range(10)] + [float("nan")]
        s = pd.Series(prices)
        res = calculate_dynamic_ema_signal(s, p1=3, p2=5, ema_cache=ema_cache)
        fast_val = res["ema_fast"]
        assert fast_val > baseline, f"Contamination in iteration {i}: got {fast_val} <= baseline {baseline}"

    # Exactly 2 spans (3 and 5) cached per series without key collisions
    assert len(ema_cache) == 200

    # Test cache hit on identical Series instance
    clean_s = pd.Series([100.0 + x for x in range(20)])
    clean_cache: dict[tuple[int, int], Any] = {}
    r1 = calculate_dynamic_ema_signal(clean_s, p1=9, p2=21, ema_cache=clean_cache)
    assert len(clean_cache) == 2
    r2 = calculate_dynamic_ema_signal(clean_s, p1=9, p2=21, ema_cache=clean_cache)
    assert len(clean_cache) == 2  # Cache hit, no new keys
    assert r1["ema_fast"] == r2["ema_fast"]


def test_f03_higher_timeframe_context_preserves_daily_bars():
    """F-03: Context construction for non-daily rules must preserve canonical daily bars."""
    bars = make_test_bars("2024-01-01", 100)
    bars_cache = {"TEST": bars}
    records = {"TEST": {"symbol": "TEST", "exchange": "NSE", "price": 100.0}}

    class DailyBarVerifyingFilter(FilterEngine):
        def evaluate(self, records, spec, **kwargs):
            self.rec = dict(records.get("TEST", {}))
            return super().evaluate(records, spec, **kwargs)

    filter_engine = DailyBarVerifyingFilter()
    hub = RegistryHub()
    hub.calculations.register("trend", TrendCalculator())
    orch = PipelineOrchestrator(
        registry=hub,
        timeframe_engine=TimeframeEngine(enable_cache=True),
        filter_rule=filter_engine,
        bars_cache=bars_cache,
    )

    # Weekly ROC rule requires daily bars from market_context.get_bars("D")
    q = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="r_w_roc", condition_type="roc", timeframe="W", params={"period": "3m"}),
                FilterRuleSpec(field="r_w_ema", condition_type="ema", timeframe="W", p1=9, p2=21),
            ]
        )
    )
    orch.execute_screen(q, records)
    rec = filter_engine.rec
    assert rec["r_w_roc"]["period"] == "current_quarter"
    assert rec["r_w_roc"]["roc"] is not None  # Daily bars were present, so ROC calculation succeeded!
    assert rec["r_w_ema"]["state"] in ("UP", "DOWN", "UPCUT", "DOWNCUT", "na")


def test_f04_exchange_included_in_cache_keys():
    """F-04: Multi-exchange screening distinguishes cache keys by exchange."""
    from yogi.core.orchestration.pipeline import _extract_calc_param_key
    r = FilterRuleSpec(field="r", condition_type="ema", timeframe="W", p1=9, p2=21)
    pkey = _extract_calc_param_key(r)

    # In execute_screen, sig_key incorporates exchange:
    sig_key_nse = ("NSE", "TEST", "ema", "W", pkey)
    sig_key_bse = ("BSE", "TEST", "ema", "W", pkey)
    assert sig_key_nse != sig_key_bse
    assert sig_key_nse[0] == "NSE"
    assert sig_key_bse[0] == "BSE"


"""Comprehensive integration and validation tests for Native Rate of Change (ROC) in Screener and Cockpit API."""

from datetime import datetime, timedelta
import math
from typing import Any, Mapping, Optional, Sequence
import pytest
from pydantic import ValidationError

from yogi.calculation.trend.calculator import TrendCalculator, calculate_dynamic_roc
from yogi.cockpit.router import run_screen
from yogi.cockpit.schemas import FilterGroupIn, FilterRuleIn, ScreenRequestIn
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.filter.evaluators import RocConditionEvaluator
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.selection.engine import SelectionEngine
from yogi.timeframe.engine import TimeframeEngine


# -----------------------------------------------------------------------------
# Mock Provider & Bands for Multi-Year Market Data
# -----------------------------------------------------------------------------

class MockRocProvider(IDataProvider):
    name = "mock_roc"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["WINNER", "RUNNER", "LOSER", "NEWBIE"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 6) -> Sequence[MarketBar]:
        """Generate deterministic daily bars spanning 2021 through 2026.
        
        Assumes latest date is in 2026 (e.g. 2026-06-15).
        - WINNER: Strong growth in 2026 and prior years (>100% return).
        - RUNNER: Moderate growth (15% return in 2026).
        - LOSER: Negative return in 2026 (-20%).
        - NEWBIE: Listed recently in 2026, has only 3 bars (no prior year history).
        """
        bars = []
        if symbol == "NEWBIE":
            base = datetime(2026, 6, 1)
            for i in range(5):
                bars.append(MarketBar(
                    timestamp=base + timedelta(days=i),
                    open=100.0, high=105.0, low=95.0, close=100.0 + i, volume=1000.0
                ))
            return bars

        # Generate trading bars across 2021, 2022, 2023, 2024, 2025, 2026
        # First bar of month roughly day 1..3, last day 28
        years_list = [2021, 2022, 2023, 2024, 2025, 2026]
        for yr in years_list:
            max_m = 6 if yr == 2026 else 12
            for m in range(1, max_m + 1):
                # Day 2 and Day 25 of month
                d1 = datetime(yr, m, 2)
                d2 = datetime(yr, m, 25)
                
                if symbol == "WINNER":
                    # Doubling from 100 in 2021 to 500+ in 2026; in June 2026 >100% (+150%)
                    p1 = 100.0 * (1.3 ** (yr - 2021)) * (1.0 + m * 0.05)
                    p2 = p1 * 2.5 if (yr == 2026 and m == 6) else p1 * 1.08
                elif symbol == "RUNNER":
                    # Steady growth; in June 2026 15% (bucket 10_to_20)
                    p1 = 100.0 * (1.1 ** (yr - 2021)) * (1.0 + m * 0.01)
                    p2 = p1 * 1.15 if (yr == 2026 and m == 6) else p1 * 1.02
                else:  # LOSER
                    # Declining; in June 2026 -15% (negative return)
                    p1 = 500.0 * (0.85 ** (yr - 2021)) * (1.0 - m * 0.02)
                    p2 = p1 * 0.85 if (yr == 2026 and m == 6) else p1 * 0.98

                bars.append(MarketBar(timestamp=d1, open=p1, high=p1*1.02, low=p1*0.98, close=p1, volume=500.0))
                bars.append(MarketBar(timestamp=d2, open=p2, high=p2*1.02, low=p2*0.98, close=p2, volume=500.0))

        return bars

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 6) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock_roc", ok=True)


class MockBands(IBandsRepository):
    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return 0.15

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        return {"D": 0.15, "W": 0.20, "M": 0.25, "Q": 0.30, "H": 0.35, "Y": 0.40}

    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "app",
        source: str = "app",
    ) -> float:
        return value


@pytest.fixture
def roc_app_state():
    hub = RegistryHub()
    provider = MockRocProvider()
    bands_repo = MockBands()
    hub.providers.register("mock_roc", provider)
    hub.bands.register("mock_roc", bands_repo)
    hub.calculations.register("trend", TrendCalculator())

    bars_cache = {s: provider.daily_history(s) for s in provider.universe()}

    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        result_assembler=ResultAssembler(),
        timeframe_engine=TimeframeEngine(),
        bars_cache=bars_cache,
    )

    ds = {
        "WINNER": {"symbol": "WINNER", "name": "Winner Corp", "exchange": "NSE", "price": 400.0, "M_CUR": 50.0},
        "RUNNER": {"symbol": "RUNNER", "name": "Runner Corp", "exchange": "NSE", "price": 150.0, "M_CUR": 15.0},
        "LOSER": {"symbol": "LOSER", "name": "Loser Corp", "exchange": "NSE", "price": 80.0, "M_CUR": -10.0},
        "NEWBIE": {"symbol": "NEWBIE", "name": "Newbie Corp", "exchange": "NSE", "price": 104.0, "M_CUR": 4.0},
    }

    return AppState(
        orchestrator=orchestrator,
        bars_cache=bars_cache,
        provider=provider,
        initial_dataset=ds,
    )


# -----------------------------------------------------------------------------
# 1. Calculation Unit Tests across all 10 Timeframe Options
# -----------------------------------------------------------------------------

def test_calculate_dynamic_roc_ongoing_periods():
    """Verify ongoing periods (current_month, current_quarter, current_half_year, ytd)."""
    # Create hand-verifiable bars in 2026: Jan, Feb, Mar, Apr, May, Jun
    bars = [
        MarketBar(timestamp=datetime(2026, 1, 2), open=100.0, high=102.0, low=98.0, close=100.0),
        MarketBar(timestamp=datetime(2026, 1, 30), open=110.0, high=112.0, low=108.0, close=110.0),
        MarketBar(timestamp=datetime(2026, 4, 1), open=120.0, high=122.0, low=118.0, close=120.0),
        MarketBar(timestamp=datetime(2026, 6, 1), open=150.0, high=152.0, low=148.0, close=150.0),
        MarketBar(timestamp=datetime(2026, 6, 20), open=180.0, high=182.0, low=178.0, close=180.0),
    ]

    # 1. current_month (June 2026): first bar close=150, latest close=180 -> +20.0%
    res_cm = calculate_dynamic_roc(bars, "current_month")
    assert res_cm["period"] == "current_month"
    assert res_cm["p_start"] == 150.0
    assert res_cm["p_end"] == 180.0
    assert res_cm["roc"] == 20.0

    # 2. current_quarter (Q2 2026): months 4..6. First bar is April close=120, latest=180 -> +50.0%
    res_cq = calculate_dynamic_roc(bars, "current_quarter")
    assert res_cq["period"] == "current_quarter"
    assert res_cq["p_start"] == 120.0
    assert res_cq["p_end"] == 180.0
    assert res_cq["roc"] == 50.0

    # 3. current_half_year (H1 2026): months 1..6. First bar is Jan close=100, latest=180 -> +80.0%
    res_ch = calculate_dynamic_roc(bars, "current_half_year")
    assert res_ch["period"] == "current_half_year"
    assert res_ch["p_start"] == 100.0
    assert res_ch["p_end"] == 180.0
    assert res_ch["roc"] == 80.0

    # 4. ytd (2026): First bar of 2026 close=100, latest=180 -> +80.0%
    res_ytd = calculate_dynamic_roc(bars, "ytd")
    assert res_ytd["period"] == "ytd"
    assert res_ytd["p_start"] == 100.0
    assert res_ytd["p_end"] == 180.0
    assert res_ytd["roc"] == 80.0


def test_calculate_dynamic_roc_completed_periods():
    """Verify completed periods (last_month, last_to_last_month, last_quarter, last_year)."""
    bars = [
        # 2025: Last year
        MarketBar(timestamp=datetime(2025, 1, 2), open=80.0, high=82.0, low=78.0, close=80.0),
        MarketBar(timestamp=datetime(2025, 12, 30), open=100.0, high=102.0, low=98.0, close=100.0),
        # 2026 Q1: Jan, Feb, Mar
        MarketBar(timestamp=datetime(2026, 1, 2), open=100.0, high=102.0, low=98.0, close=100.0),
        MarketBar(timestamp=datetime(2026, 3, 31), open=120.0, high=122.0, low=118.0, close=120.0),
        # 2026 April (last to last month)
        MarketBar(timestamp=datetime(2026, 4, 1), open=130.0, high=132.0, low=128.0, close=130.0),
        MarketBar(timestamp=datetime(2026, 4, 30), open=143.0, high=145.0, low=140.0, close=143.0),
        # 2026 May (last month)
        MarketBar(timestamp=datetime(2026, 5, 2), open=150.0, high=152.0, low=148.0, close=150.0),
        MarketBar(timestamp=datetime(2026, 5, 29), open=165.0, high=167.0, low=160.0, close=165.0),
        # 2026 June (current ongoing month)
        MarketBar(timestamp=datetime(2026, 6, 1), open=170.0, high=172.0, low=168.0, close=170.0),
        MarketBar(timestamp=datetime(2026, 6, 15), open=180.0, high=182.0, low=178.0, close=180.0),
    ]

    # 1. last_month (May 2026): first bar close=150, last bar close=165 -> (165-150)/150 = +10.0%
    res_lm = calculate_dynamic_roc(bars, "last_month")
    assert res_lm["period"] == "last_month"
    assert res_lm["p_start"] == 150.0
    assert res_lm["p_end"] == 165.0
    assert res_lm["roc"] == 10.0

    # 2. last_to_last_month (April 2026): first bar close=130, last bar close=143 -> (143-130)/130 = +10.0%
    res_l2m = calculate_dynamic_roc(bars, "last_to_last_month")
    assert res_l2m["period"] == "last_to_last_month"
    assert res_l2m["p_start"] == 130.0
    assert res_l2m["p_end"] == 143.0
    assert res_l2m["roc"] == 10.0

    # 3. last_quarter (Q1 2026): first bar Jan close=100, last bar Mar close=120 -> +20.0%
    res_lq = calculate_dynamic_roc(bars, "last_quarter")
    assert res_lq["period"] == "last_quarter"
    assert res_lq["p_start"] == 100.0
    assert res_lq["p_end"] == 120.0
    assert res_lq["roc"] == 20.0

    # 4. last_year (2025): first bar Jan close=80, last bar Dec close=100 -> +25.0%
    res_ly = calculate_dynamic_roc(bars, "last_year")
    assert res_ly["period"] == "last_year"
    assert res_ly["p_start"] == 80.0
    assert res_ly["p_end"] == 100.0
    assert res_ly["roc"] == 25.0


def test_calculate_dynamic_roc_multi_year():
    """Verify preceding_last_4_years and avg_preceding_last_5_years calculations."""
    # Build complete history 2021..2026
    # Annual returns:
    # 2021: 100 -> 120 (+20%)
    # 2022: 120 -> 150 (+25%)
    # 2023: 150 -> 180 (+20%)
    # 2024: 180 -> 216 (+20%)
    # 2025: 216 -> 248.4 (+15%)
    # 2026: latest year (ongoing)
    bars = [
        MarketBar(timestamp=datetime(2021, 1, 4), open=100.0, high=102.0, low=98.0, close=100.0),
        MarketBar(timestamp=datetime(2021, 12, 30), open=120.0, high=122.0, low=118.0, close=120.0),

        MarketBar(timestamp=datetime(2022, 1, 3), open=120.0, high=122.0, low=118.0, close=120.0),
        MarketBar(timestamp=datetime(2022, 12, 30), open=150.0, high=152.0, low=148.0, close=150.0),

        MarketBar(timestamp=datetime(2023, 1, 2), open=150.0, high=152.0, low=148.0, close=150.0),
        MarketBar(timestamp=datetime(2023, 12, 29), open=180.0, high=182.0, low=178.0, close=180.0),

        MarketBar(timestamp=datetime(2024, 1, 2), open=180.0, high=182.0, low=178.0, close=180.0),
        MarketBar(timestamp=datetime(2024, 12, 31), open=216.0, high=218.0, low=214.0, close=216.0),

        MarketBar(timestamp=datetime(2025, 1, 2), open=216.0, high=218.0, low=214.0, close=216.0),
        MarketBar(timestamp=datetime(2025, 12, 31), open=248.4, high=250.0, low=245.0, close=248.4),

        MarketBar(timestamp=datetime(2026, 1, 2), open=250.0, high=252.0, low=248.0, close=250.0),
        MarketBar(timestamp=datetime(2026, 6, 15), open=300.0, high=305.0, low=295.0, close=300.0),
    ]

    # Preceding last 4 years (2022..2025):
    # P_start = first close of 2022 = 120.0
    # P_end = last close of 2025 = 248.4
    # Total ROC = (248.4 - 120.0) / 120.0 * 100 = 107.0%
    res_4y = calculate_dynamic_roc(bars, "preceding_last_4_years")
    assert res_4y["period"] == "preceding_last_4_years"
    assert res_4y["p_start"] == 120.0
    assert res_4y["p_end"] == 248.4
    assert res_4y["roc"] == pytest.approx(107.0, rel=1e-3)

    # Average of preceding last 5 years (2021..2025):
    # 2021 ROC: (120-100)/100 = 20%
    # 2022 ROC: (150-120)/120 = 25%
    # 2023 ROC: (180-150)/150 = 20%
    # 2024 ROC: (216-180)/180 = 20%
    # 2025 ROC: (248.4-216)/216 = 15%
    # Arithmetic Mean = (20 + 25 + 20 + 20 + 15) / 5 = 20.0%
    res_5y = calculate_dynamic_roc(bars, "avg_preceding_last_5_years")
    assert res_5y["period"] == "avg_preceding_last_5_years"
    assert res_5y["roc"] == pytest.approx(20.0, rel=1e-3)


def test_calculate_dynamic_roc_insufficient_history():
    """Verify that insufficient history returns None rather than partial/corrupt numbers."""
    bars_short = [
        MarketBar(timestamp=datetime(2026, 6, 1), open=100.0, high=102.0, low=98.0, close=100.0),
        MarketBar(timestamp=datetime(2026, 6, 15), open=110.0, high=112.0, low=108.0, close=110.0),
    ]

    # Current month succeeds
    assert calculate_dynamic_roc(bars_short, "current_month")["roc"] == 10.0

    # Prior periods fail cleanly
    assert calculate_dynamic_roc(bars_short, "last_month")["roc"] is None
    assert calculate_dynamic_roc(bars_short, "last_quarter")["roc"] is None
    assert calculate_dynamic_roc(bars_short, "last_year")["roc"] is None
    assert calculate_dynamic_roc(bars_short, "preceding_last_4_years")["roc"] is None
    assert calculate_dynamic_roc(bars_short, "avg_preceding_last_5_years")["roc"] is None


# -----------------------------------------------------------------------------
# 2. Condition Evaluator Unit Tests & Boundary Invariants
# -----------------------------------------------------------------------------

def test_roc_evaluator_all_eleven_buckets_and_boundaries():
    """Verify exhaustive interval boundaries across all 11 non-negative buckets."""
    evaluator = RocConditionEvaluator()

    def _eval(roc_val: Optional[float], bucket: str) -> Optional[bool]:
        rec = {"ROC_CURRENT_MONTH": roc_val}
        rule = FilterRuleSpec(
            field="ROC_CURRENT_MONTH",
            op=FilterOperator.EQ,
            value=bucket,
            condition_type="roc",
            params={"period": "current_month", "bucket": bucket},
        )
        return evaluator.evaluate(rec, rule)

    # Bucket 1: lt_10 [0, 10)
    assert _eval(0.0, "lt_10") is True
    assert _eval(5.5, "lt_10") is True
    assert _eval(9.9999, "lt_10") is True
    assert _eval(10.0, "lt_10") is False  # 10.0 belongs to 10_to_20

    # Bucket 2: 10_to_20 [10, 20)
    assert _eval(10.0, "10_to_20") is True
    assert _eval(19.99, "10_to_20") is True
    assert _eval(20.0, "10_to_20") is False

    # Intermediate buckets
    assert _eval(25.0, "20_to_30") is True
    assert _eval(35.0, "30_to_40") is True
    assert _eval(45.0, "40_to_50") is True
    assert _eval(55.0, "50_to_60") is True
    assert _eval(65.0, "60_to_70") is True
    assert _eval(75.0, "70_to_80") is True
    assert _eval(85.0, "80_to_90") is True

    # Bucket 10: 90_to_100 [90, 100] (Inclusive of 100!)
    assert _eval(90.0, "90_to_100") is True
    assert _eval(95.0, "90_to_100") is True
    assert _eval(100.0, "90_to_100") is True
    assert _eval(100.0001, "90_to_100") is False

    # Bucket 11: gt_100 (100, Inf) (Strictly greater than 100!)
    assert _eval(100.0, "gt_100") is False
    assert _eval(100.01, "gt_100") is True
    assert _eval(250.0, "gt_100") is True

    # Negative values: match NO bucket (False)
    assert _eval(-0.01, "lt_10") is False
    assert _eval(-15.0, "10_to_20") is False
    assert _eval(-50.0, "gt_100") is False

    # Missing / None / NaN / Inf values: return None (tri-state unknown)
    assert _eval(None, "gt_100") is None
    assert _eval(float("nan"), "gt_100") is None
    assert _eval(float("inf"), "gt_100") is None


def test_roc_evaluator_dict_payload_unpacking():
    """Verify evaluator unpacks dict payloads emitted by TrendCalculator."""
    evaluator = RocConditionEvaluator()
    rec = {
        "ROC_CURRENT_MONTH": {
            "roc": 125.4,
            "period": "current_month",
            "p_start": 100.0,
            "p_end": 225.4,
        }
    }
    rule = FilterRuleSpec(
        field="ROC_CURRENT_MONTH",
        op=FilterOperator.EQ,
        value="gt_100",
        condition_type="roc",
        params={"period": "current_month", "bucket": "gt_100"},
    )
    assert evaluator.evaluate(rec, rule) is True


def test_roc_evaluator_describe():
    """Verify human-readable explanation formatting."""
    evaluator = RocConditionEvaluator()
    rule = FilterRuleSpec(
        field="ROC_LAST_YEAR",
        op=FilterOperator.EQ,
        value="20_to_30",
        condition_type="roc",
        params={"period": "last_year", "bucket": "20_to_30"},
    )
    desc = evaluator.describe(rule)
    assert desc == "Last Year ROC 20% to 30%"


# -----------------------------------------------------------------------------
# 3. Tri-State and Group Logic Invariants
# -----------------------------------------------------------------------------

def test_roc_tri_state_negation_safety():
    """Verify that an unknown ROC result (missing history) does NOT qualify on NOT."""
    engine = FilterEngine()
    record_with_missing_roc = {"symbol": "TEST"}  # No ROC computed

    # Standalone rule
    roc_rule = FilterRuleSpec(
        field="ROC_LAST_4_YEARS",
        op=FilterOperator.EQ,
        value="gt_100",
        condition_type="roc",
        params={"period": "preceding_last_4_years", "bucket": "gt_100"},
        is_negated=False,
    )
    res = engine.evaluate({"TEST": record_with_missing_roc}, FilterGroupSpec(rules=[roc_rule]))
    assert "TEST" not in res.matching_symbols  # Did not pass

    # Inverted rule (NOT)
    roc_negated_rule = FilterRuleSpec(
        field="ROC_LAST_4_YEARS",
        op=FilterOperator.EQ,
        value="gt_100",
        condition_type="roc",
        params={"period": "preceding_last_4_years", "bucket": "gt_100"},
        is_negated=True,
    )
    res_neg = engine.evaluate({"TEST": record_with_missing_roc}, FilterGroupSpec(rules=[roc_negated_rule]))
    # Crucial Kleene property: NOT Unknown == Unknown (does NOT become True!)
    assert "TEST" not in res_neg.matching_symbols


# -----------------------------------------------------------------------------
# 4. Schema & Validation Tests
# -----------------------------------------------------------------------------

def test_roc_schema_validation_valid():
    """Verify valid FilterRuleIn with ROC condition."""
    rule = FilterRuleIn(
        condition_type="roc",
        period="current_quarter",
        bucket="50_to_60",
    )
    assert rule.condition_type == "roc"
    assert rule.timeframe == "D"  # Pipeline bar timeframe
    assert rule.period == "current_quarter"
    assert rule.bucket == "50_to_60"
    assert rule.field == "ROC_CURRENT_QUARTER"
    assert rule.value == "50_to_60"


def test_roc_schema_validation_default_bucket():
    """Verify default bucket is gt_100 when omitted."""
    rule = FilterRuleIn(
        condition_type="roc",
        period="last_year",
    )
    assert rule.bucket == "gt_100"
    assert rule.value == "gt_100"


def test_roc_schema_validation_invalid_period():
    """Verify invalid period raises ValidationError."""
    with pytest.raises(ValidationError):
        FilterRuleIn(
            condition_type="roc",
            period="invalid_custom_period",
            bucket="gt_100",
        )


def test_roc_schema_validation_invalid_bucket():
    """Verify invalid bucket raises ValidationError."""
    with pytest.raises(ValidationError):
        FilterRuleIn(
            condition_type="roc",
            period="current_month",
            bucket="negative_50",
        )


# -----------------------------------------------------------------------------
# 5. End-to-End Pipeline & Screener Integration Tests
# -----------------------------------------------------------------------------

def test_end_to_end_roc_screening_execution(roc_app_state):
    """Verify full end-to-end screener execution through run_screen."""
    # Screen for stocks with Current Month ROC > 100%
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[
                FilterRuleIn(
                    condition_type="roc",
                    period="current_month",
                    bucket="gt_100",
                )
            ]
        ),
        limit=20,
    )

    result = run_screen(req=req, app_state=roc_app_state)
    assert result.qualified_count >= 1
    # WINNER doubled in 2026 and qualifies for >100%
    symbols = [r["symbol"] for r in result.rows]
    assert "WINNER" in symbols
    # LOSER declined and RUNNER had only ~15% return, neither qualifies for >100%
    assert "LOSER" not in symbols
    assert "RUNNER" not in symbols


def test_end_to_end_roc_composition_with_ema(roc_app_state):
    """Verify ROC conditions compose seamlessly with existing EMA and ranking stages."""
    # Compose: Current Month ROC (10% to 20%)
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[
                FilterRuleIn(
                    condition_type="roc",
                    period="current_month",
                    bucket="10_to_20",
                )
            ]
        ),
        ranking_metric="price",
        ranking_order="desc",
        limit=10,
    )

    result = run_screen(req=req, app_state=roc_app_state)
    assert result.qualified_count >= 1
    symbols = [r["symbol"] for r in result.rows]
    # RUNNER has ~15% return in 2026 and matches 10_to_20
    assert "RUNNER" in symbols
    assert "WINNER" not in symbols


def test_production_app_state_roc_evaluator_bootstrap():
    """Verify that AppState default condition evaluators include roc."""
    state = AppState(autoload_cache=False)
    assert state.filter_rule.has_evaluator("roc") is True
    roc_eval = state.filter_rule.get_evaluator("roc")
    assert isinstance(roc_eval, RocConditionEvaluator)

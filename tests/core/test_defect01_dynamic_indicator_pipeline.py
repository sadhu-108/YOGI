"""Regression tests for DEFECT-01: Dynamic indicator records preservation in pipeline orchestration.

Verifies that:
1. Dynamic indicator values survive the qualification stage.
2. The ranking stage receives the correct enriched values.
3. Dynamic-indicator ranking produces the expected order and tie behavior.
4. Dynamic indicator fields are present in the final API/result payload.
5. Original record fields remain intact.
6. A combined screen using existing filters and dynamic indicators still behaves correctly.
7. Missing or unavailable dynamic indicator values are handled according to the existing contract.
"""

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
import pytest

from yogi.core.registry.hub import RegistryHub
from yogi.calculation.trend.calculator import TrendCalculator
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.ranking import RankingOrder
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.selection.engine import SelectionEngine
from yogi.timeframe.engine import TimeframeEngine


class DeterministicProv(IDataProvider):
    name = "det_prov"
    supports_intraday = False
    supports_live_ticks = False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["WINNER_A", "WINNER_B", "MODERATE", "NO_DATA"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        if symbol == "NO_DATA":
            return []
        base = datetime(2026, 1, 1)
        bars = []
        for i in range(180):
            # In June 2026 (indices 151..179):
            # WINNER_A: +25% return
            # WINNER_B: +25% return (tied with WINNER_A)
            # MODERATE: +12% return
            if symbol == "WINNER_A":
                p = 100.0 if i < 151 else (100.0 + (i - 151) * (25.0 / 28.0))
            elif symbol == "WINNER_B":
                p = 200.0 if i < 151 else (200.0 + (i - 151) * (50.0 / 28.0))
            elif symbol == "MODERATE":
                p = 100.0 if i < 151 else (100.0 + (i - 151) * (12.0 / 28.0))
            else:
                p = 50.0
            bars.append(MarketBar(timestamp=base + timedelta(days=i), open=p, high=p * 1.01, low=p * 0.99, close=p, volume=1000.0))
        return bars

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> float:
        return 100.0

    def intraday(self, *args: Any, **kwargs: Any) -> Sequence[Any]:
        return ()

    def subscribe_ticks(self, *args: Any, **kwargs: Any) -> None:
        return None

    def trading_holidays(self, *args: Any, **kwargs: Any) -> Sequence[Any]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="det_prov", ok=True)


class StubBands(IBandsRepository):
    def get_band(self, symbol: str, timeframe: str) -> float:
        return 0.15

    def get_all_bands(self, symbol: str) -> Mapping[str, float]:
        return {"D": 0.15}

    def set_band(self, symbol: str, timeframe: str, value: float, who: str = "app", source: str = "app") -> float:
        return value


@pytest.fixture
def pipeline_env():
    hub = RegistryHub()
    prov = DeterministicProv()
    hub.providers.register("det_prov", prov)
    hub.bands.register("det_prov", StubBands())
    hub.calculations.register("trend", TrendCalculator())

    bars_cache = {s: prov.daily_history(s) for s in prov.universe()}

    orch = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        timeframe_engine=TimeframeEngine(),
        bars_cache=bars_cache,
    )

    records = {
        "WINNER_A": {"symbol": "WINNER_A", "name": "Winner A Corp", "price": 125.0, "exchange": "NSE", "provider": "det_prov", "sector": "TECH", "BANDST_M": "ABOVE"},
        "WINNER_B": {"symbol": "WINNER_B", "name": "Winner B Corp", "price": 250.0, "exchange": "NSE", "provider": "det_prov", "sector": "HEALTH", "BANDST_M": "ABOVE"},
        "MODERATE": {"symbol": "MODERATE", "name": "Moderate Corp", "price": 112.0, "exchange": "NSE", "provider": "det_prov", "sector": "FIN", "BANDST_M": "IN"},
        "NO_DATA": {"symbol": "NO_DATA", "name": "No Data Corp", "price": 50.0, "exchange": "NSE", "provider": "det_prov", "sector": "AUTO", "BANDST_M": "BELOW"},
    }

    return orch, records, bars_cache


def test_dynamic_indicator_values_survive_qualification_and_ranking(pipeline_env):
    """Verify DEFECT-01: Dynamic indicator values are not discarded and survive into ranking and results."""
    orch, records, bars_cache = pipeline_env

    # Both WINNER_A (+25%), WINNER_B (+25%), and MODERATE (+12%) qualify for >= 10%
    rule_roc = FilterRuleSpec(
        field="ROC_CURRENT_MONTH",
        condition_type="roc",
        params={"period": "current_month", "bucket": "10_to_20"},
    )
    # Qualify WINNER_A and WINNER_B for 20_to_30 bucket
    rule_roc_winners = FilterRuleSpec(
        field="ROC_CURRENT_MONTH",
        condition_type="roc",
        params={"period": "current_month", "bucket": "20_to_30"},
    )

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(rules=[rule_roc_winners]),
        ranking_metric="ROC_CURRENT_MONTH",
        ranking_order=RankingOrder.DESCENDING,
    )

    res = orch.execute_screen(query=query, records=records, bars_cache=bars_cache)

    assert res.qualified_count == 2
    assert len(res.rows) == 2

    # 1 & 2. Verify dynamic indicator values survived into qualified and ranked records
    row_symbols = [r["symbol"] for r in res.rows]
    assert "WINNER_A" in row_symbols
    assert "WINNER_B" in row_symbols

    # 3. Verify ranking tie behavior: WINNER_A and WINNER_B both have ~25.0% return, so tied at Rank 1
    for r in res.rows:
        assert r["RANK_ROC_CURRENT_MONTH"] == 1
        # 4. Verify dynamic indicator field is present in final result payload
        roc_data = r.get("ROC_CURRENT_MONTH")
        assert roc_data is not None
        assert isinstance(roc_data, dict)
        assert pytest.approx(roc_data["roc"], rel=1e-2) == 25.0

        # 5. Verify original record fields remain completely intact
        assert r["name"] in ("Winner A Corp", "Winner B Corp")
        assert r["exchange"] == "NSE"
        assert r["sector"] in ("TECH", "HEALTH")
        assert r["BANDST_M"] == "ABOVE"


def test_dynamic_indicator_strict_ordering_and_delta(pipeline_env):
    """Verify that distinct dynamic indicator values produce strict, correct ordering."""
    orch, records, bars_cache = pipeline_env

    # Qualify WINNER_A (25%) and MODERATE (12%)
    rule_or = FilterGroupSpec(
        match="any",
        rules=[
            FilterRuleSpec(field="ROC_CURRENT_MONTH", condition_type="roc", params={"period": "current_month", "bucket": "20_to_30"}),
            FilterRuleSpec(field="ROC_CURRENT_MONTH", condition_type="roc", params={"period": "current_month", "bucket": "10_to_20"}),
        ],
    )

    query = ScreeningQuery(
        filter_group=rule_or,
        ranking_metric="ROC_CURRENT_MONTH",
        ranking_order=RankingOrder.DESCENDING,
    )

    res = orch.execute_screen(query=query, records=records, bars_cache=bars_cache)

    assert res.qualified_count == 3
    # First two are tied at 25% (rank 1), MODERATE is 12% (rank 3)
    symbols_order = [r["symbol"] for r in res.rows]
    assert symbols_order[2] == "MODERATE"
    assert res.rows[2]["RANK_ROC_CURRENT_MONTH"] == 3


def test_combined_screen_static_and_dynamic(pipeline_env):
    """Verify combined screen using existing static filters and dynamic indicators."""
    orch, records, bars_cache = pipeline_env

    # Combined: BANDST_M == "IN" AND ROC_CURRENT_MONTH in 10_to_20 -> only MODERATE matches
    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            match="all",
            rules=[
                FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="IN"),
                FilterRuleSpec(field="ROC_CURRENT_MONTH", condition_type="roc", params={"period": "current_month", "bucket": "10_to_20"}),
            ],
        ),
        ranking_metric="ROC_CURRENT_MONTH",
    )

    res = orch.execute_screen(query=query, records=records, bars_cache=bars_cache)
    assert res.qualified_count == 1
    assert len(res.rows) == 1
    assert res.rows[0]["symbol"] == "MODERATE"
    assert res.rows[0]["price"] == 112.0
    assert res.rows[0]["BANDST_M"] == "IN"


def test_missing_or_unavailable_dynamic_indicators(pipeline_env):
    """Verify that symbols with missing bars / unavailable dynamic indicators do not qualify for positive buckets."""
    orch, records, bars_cache = pipeline_env

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            rules=[
                FilterRuleSpec(field="ROC_CURRENT_MONTH", condition_type="roc", params={"period": "current_month", "bucket": "10_to_20"}),
            ],
        ),
    )

    res = orch.execute_screen(query=query, records=records, bars_cache=bars_cache)
    # NO_DATA has no bars, so its ROC is None and it never qualifies
    matched_syms = [r["symbol"] for r in res.rows]
    assert "NO_DATA" not in matched_syms

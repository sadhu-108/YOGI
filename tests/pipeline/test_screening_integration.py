"""Integration tests for the complete Screening Engine pipeline.

Tests stage progression across QUALIFY -> ORDER -> SHOW -> RESULTS using
real FilterEngine, RankingEngine, SelectionEngine, and StrategyCatalog.
"""

import pytest

from yogi.core.configuration.catalog import StrategyCatalog
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.results import QueryResultPayload
from yogi.core.contracts.selection import RankCutoffSpec, SelectionMode
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.selection.engine import SelectionEngine
from yogi.strategy.presets import load_mentor_presets


@pytest.fixture
def test_hub():
    return RegistryHub()


@pytest.fixture
def screener_orchestrator(test_hub):
    return PipelineOrchestrator(
        registry=test_hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )


@pytest.fixture
def market_dataset():
    """Synthetic multi-stock calculated feature dataset."""
    return {
        "STOCK_A": {
            "symbol": "STOCK_A",
            "price": 500.0,
            "BANDST_M": "ABOVE",
            "EMA_M": "upcut",
            "RANK_CHG": 12,
            "SPD_M": 14.5,
            "M_CUR": 22.0,
            "YROC": 65.0,
            "ACCEL_L": 2.5,
        },
        "STOCK_B": {
            "symbol": "STOCK_B",
            "price": 1200.0,
            "BANDST_M": "ABOVE",
            "EMA_M": "yes",
            "RANK_CHG": 5,
            "SPD_M": 8.0,
            "M_CUR": 15.0,
            "YROC": 40.0,
            "ACCEL_L": 1.1,
        },
        "STOCK_C": {
            "symbol": "STOCK_C",
            "price": 350.0,
            "BANDST_M": "IN",
            "EMA_M": "yes",
            "RANK_CHG": -2,
            "SPD_M": -1.5,
            "M_CUR": -3.0,
            "YROC": 10.0,
            "ACCEL_L": -0.5,
        },
        "STOCK_D": {
            "symbol": "STOCK_D",
            "price": 2400.0,
            "BANDST_M": "ABOVE",
            "EMA_M": "upcut",
            "RANK_CHG": 8,
            "SPD_M": 20.0,
            "M_CUR": 30.0,
            "YROC": 80.0,
            "ACCEL_L": 3.0,
        },
        "STOCK_E": {
            "symbol": "STOCK_E",
            "price": 950.0,
            "BANDST_M": "BELOW",
            "EMA_M": "downcut",
            "RANK_CHG": -10,
            "SPD_M": -5.0,
            "M_CUR": -12.0,
            "YROC": -25.0,
            "ACCEL_L": -2.0,
        },
    }


def test_screening_end_to_end_qualify_order_show(screener_orchestrator, market_dataset):
    """Test full progression: QUALIFY -> ORDER -> SHOW -> RESULTS."""
    # Strategy: A1 Impulse confirmed (BANDST_M == ABOVE & EMA_M in UP & RANK_CHG > 0)
    # Ranked by SPD_M desc, cutoff top 2
    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            match="all",
            rules=[
                FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE"),
                FilterRuleSpec(field="EMA_M", op=FilterOperator.IN, value=("upcut", "yes")),
                FilterRuleSpec(field="RANK_CHG", op=FilterOperator.GT, value=0.0),
            ],
        ),
        ranking_metric="SPD_M",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="SPD_M", max_rank=2),),
    )

    payload = screener_orchestrator.execute_screen(query=query, records=market_dataset)

    assert isinstance(payload, QueryResultPayload)
    assert payload.universe_count == 5

    # Qualified by A1: STOCK_A, STOCK_B, STOCK_D (3 stocks)
    assert payload.qualified_count == 3

    # Ranking on SPD_M (descending):
    # STOCK_D: 20.0 -> Rank 1
    # STOCK_A: 14.5 -> Rank 2
    # STOCK_B: 8.0  -> Rank 3
    # Selection cutoff max_rank <= 2 -> STOCK_D, STOCK_A
    assert payload.selected_count == 2
    assert len(payload.rows) == 2

    # Verify rows order and injected cohort rank
    assert payload.rows[0]["symbol"] == "STOCK_D"
    assert payload.rows[0]["RANK_SPD_M"] == 1
    assert payload.rows[1]["symbol"] == "STOCK_A"
    assert payload.rows[1]["RANK_SPD_M"] == 2


def test_screening_mentor_preset_via_strategy_catalog(screener_orchestrator, market_dataset):
    """Test running a strategy query directly translated from StrategyCatalog."""
    catalog = load_mentor_presets()

    # Run B1_SPRINTERS_MONTH: SPD_M > 0
    query_b1 = catalog.to_query("B1_SPRINTERS_MONTH")
    payload = screener_orchestrator.execute_screen(query=query_b1, records=market_dataset)

    # Stocks with SPD_M > 0: STOCK_D (20), STOCK_A (14.5), STOCK_B (8.0)
    assert payload.qualified_count == 3
    assert payload.selected_count == 3
    # Verify ranking order: STOCK_D (1), STOCK_A (2), STOCK_B (3)
    assert [r["symbol"] for r in payload.rows] == ["STOCK_D", "STOCK_A", "STOCK_B"]


def test_selection_cutoff_vs_presentation_limit_boundary(screener_orchestrator, market_dataset):
    """Critical architectural boundary: selection_cutoffs vs query.limit.
    
    Selection cutoffs determine analytical qualification (e.g. top 3 qualify).
    query.limit determines display/export page size (e.g. display top 1).
    """
    query = ScreeningQuery(
        ranking_metric="YROC",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="YROC", max_rank=3),),
        limit=1,  # User only wants the first row displayed
    )

    payload = screener_orchestrator.execute_screen(query=query, records=market_dataset)

    # Analytical qualification: 3 stocks have rank <= 3
    assert payload.selected_count == 3
    # Presentation assembly: truncated to limit=1
    assert len(payload.rows) == 1
    assert payload.rows[0]["symbol"] == "STOCK_D"  # Highest YROC (80.0)
    assert payload.metadata["limit"] == 1
    assert payload.metadata["selected_count"] == 3


def test_query_limit_does_not_influence_ranking_or_selection(screener_orchestrator, market_dataset):
    """Architectural invariant: query.limit does not alter qualification, ranking, or selection."""
    base_query = dict(
        ranking_metric="YROC",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="YROC", max_rank=3),),
    )

    # 1. No limit
    payload_all = screener_orchestrator.execute_screen(
        query=ScreeningQuery(**base_query, limit=None),
        records=market_dataset,
    )
    # 2. Limit 2
    payload_2 = screener_orchestrator.execute_screen(
        query=ScreeningQuery(**base_query, limit=2),
        records=market_dataset,
    )
    # 3. Limit 1
    payload_1 = screener_orchestrator.execute_screen(
        query=ScreeningQuery(**base_query, limit=1),
        records=market_dataset,
    )

    # Qualification and selection counts must be completely identical
    assert payload_all.qualified_count == payload_2.qualified_count == payload_1.qualified_count == 5
    assert payload_all.selected_count == payload_2.selected_count == payload_1.selected_count == 3

    # Ranking values assigned to symbols must be identical regardless of limit
    assert payload_all.rows[0]["RANK_YROC"] == payload_2.rows[0]["RANK_YROC"] == payload_1.rows[0]["RANK_YROC"] == 1
    assert payload_all.rows[1]["RANK_YROC"] == payload_2.rows[1]["RANK_YROC"] == 2

    # Only output rows presentation length is affected by limit
    assert len(payload_all.rows) == 3
    assert len(payload_2.rows) == 2
    assert len(payload_1.rows) == 1


def test_pipeline_preserves_ranking_authoritative_order_through_selection(screener_orchestrator, market_dataset):
    """Architectural invariant: Pipeline preserves RankingEngine's authoritative order through Selection."""
    # Market dataset has YROC: D=80, A=65, B=40, C=10, E=-25
    query = ScreeningQuery(
        ranking_metric="YROC",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="YROC", max_rank=4),),
    )

    payload = screener_orchestrator.execute_screen(query=query, records=market_dataset)

    # Order must strictly match descending YROC rank: STOCK_D (1), STOCK_A (2), STOCK_B (3), STOCK_C (4)
    expected_order = ["STOCK_D", "STOCK_A", "STOCK_B", "STOCK_C"]
    assert [r["symbol"] for r in payload.rows] == expected_order
    assert [r["RANK_YROC"] for r in payload.rows] == [1, 2, 3, 4]


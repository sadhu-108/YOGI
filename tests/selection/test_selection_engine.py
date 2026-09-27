"""Tests for SelectionEngine — Rank cutoffs and cohort survival."""

import pytest

from yogi.core.contracts.selection import (
    ISelectionRule,
    RankCutoffSpec,
    SelectionMode,
    SelectionResult,
)
from yogi.selection.engine import SelectionEngine


@pytest.fixture
def ranked_records():
    return {
        "A": {"symbol": "A", "RANK_M": 5, "RANK_Y": 50, "RANK_M_PERIODS": 3},
        "B": {"symbol": "B", "RANK_M": 20, "RANK_Y": 150, "RANK_M_PERIODS": 1},
        "C": {"symbol": "C", "RANK_M": 105, "RANK_Y": 10, "RANK_M_PERIODS": 2},
        "D": {"symbol": "D", "RANK_M": 120, "RANK_Y": 200, "RANK_M_PERIODS": 0},
        "E": {"symbol": "E", "RANK_M": None, "RANK_Y": None},
    }


def test_selection_engine_implements_contract():
    engine = SelectionEngine()
    assert isinstance(engine, ISelectionRule)


def test_selection_engine_single_cutoff(ranked_records):
    engine = SelectionEngine()

    result = engine.select(
        ranked_records,
        cutoffs=[RankCutoffSpec(rank_metric="RANK_M", max_rank=100)],
    )

    assert isinstance(result, SelectionResult)
    assert result.total_evaluated == 5
    assert result.matched_count == 2
    assert result.selected_symbols == ["A", "B"]
    assert "RANK_M <= 100" in result.spec_summary


def test_selection_engine_flexible_metric_alias():
    engine = SelectionEngine()

    # Record contains 'RANK_M_CUR'
    records = {
        "A": {"symbol": "A", "RANK_M_CUR": 10},
        "B": {"symbol": "B", "RANK_M_CUR": 200},
    }

    # Cutoff specified as 'M_CUR'
    res = engine.select(
        records,
        cutoffs=[RankCutoffSpec(rank_metric="M_CUR", max_rank=100)],
    )
    assert res.selected_symbols == ["A"]


def test_selection_engine_mode_all_intersection(ranked_records):
    engine = SelectionEngine()

    # RANK_M <= 100 AND RANK_Y <= 100
    result = engine.select(
        ranked_records,
        cutoffs=[
            RankCutoffSpec(rank_metric="RANK_M", max_rank=100),
            RankCutoffSpec(rank_metric="RANK_Y", max_rank=100),
        ],
        mode=SelectionMode.ALL,
    )

    # A has M=5 (<=100) and Y=50 (<=100) -> PASS
    # B has M=20 (<=100) and Y=150 (>100) -> FAIL
    # C has M=105 (>100) and Y=10 (<=100) -> FAIL
    assert result.selected_symbols == ["A"]
    assert result.matched_count == 1


def test_selection_engine_mode_any_union(ranked_records):
    engine = SelectionEngine()

    # RANK_M <= 100 OR RANK_Y <= 100
    result = engine.select(
        ranked_records,
        cutoffs=[
            RankCutoffSpec(rank_metric="RANK_M", max_rank=100),
            RankCutoffSpec(rank_metric="RANK_Y", max_rank=100),
        ],
        mode=SelectionMode.ANY,
    )

    # A (both), B (M<=100), C (Y<=100) -> PASS
    # D (M=120, Y=200) -> FAIL
    # E (None) -> FAIL
    assert result.selected_symbols == ["A", "B", "C"]
    assert result.matched_count == 3


def test_selection_engine_empty_cutoffs_returns_all(ranked_records):
    engine = SelectionEngine()

    result = engine.select(ranked_records, cutoffs=[])
    assert result.total_evaluated == 5
    assert result.matched_count == 5
    assert result.selected_symbols == ["A", "B", "C", "D", "E"]
    assert result.spec_summary == "ALL"


def test_selection_engine_sustained_periods(ranked_records):
    engine = SelectionEngine()

    # RANK_M <= 100 with min_periods=2
    result = engine.select(
        ranked_records,
        cutoffs=[RankCutoffSpec(rank_metric="RANK_M", max_rank=100, min_periods=2)],
    )

    # A: RANK_M=5 (<=100), PERIODS=3 (>=2) -> PASS
    # B: RANK_M=20 (<=100), PERIODS=1 (<2) -> FAIL
    assert result.selected_symbols == ["A"]


def test_selection_engine_does_not_truncate_by_row_limit():
    """Architectural invariant: SelectionEngine qualifies all matching ranks; display limit is separate."""
    engine = SelectionEngine()

    # 15 records all with rank <= 50
    records = {f"SYM_{i}": {"symbol": f"SYM_{i}", "RANK_M": i} for i in range(1, 16)}

    result = engine.select(
        records,
        cutoffs=[RankCutoffSpec(rank_metric="RANK_M", max_rank=50)],
    )

    # All 15 records must be selected; selection must NOT truncate to 10
    assert result.matched_count == 15
    assert len(result.selected_symbols) == 15


def test_selection_engine_preserves_incoming_order_regardless_of_metric_values():
    """Architectural invariant: SelectionEngine must NOT sort or reorder records.
    
    RankingEngine establishes order; SelectionEngine merely filters by cutoff,
    preserving the authoritative incoming order exactly.
    """
    engine = SelectionEngine()

    # Input order: Z, A, M (deliberately not sorted by RANK_M: 50, 10, 25)
    records = {
        "Z": {"symbol": "Z", "RANK_M": 50},
        "A": {"symbol": "A", "RANK_M": 10},
        "M": {"symbol": "M", "RANK_M": 25},
    }

    result = engine.select(
        records,
        cutoffs=[RankCutoffSpec(rank_metric="RANK_M", max_rank=100)],
    )

    # Output MUST preserve exact incoming order Z, A, M (must NOT sort to A, M, Z)
    assert result.selected_symbols == ["Z", "A", "M"]
    assert result.matched_count == 3


def test_selection_engine_removes_failing_records_preserving_relative_order():
    """Architectural invariant: When records fail cutoffs, surviving records preserve relative order."""
    engine = SelectionEngine()

    # Incoming ranked order: A, B, C, D, E
    records = {
        "A": {"symbol": "A", "RANK_M": 10},
        "B": {"symbol": "B", "RANK_M": 150},
        "C": {"symbol": "C", "RANK_M": 20},
        "D": {"symbol": "D", "RANK_M": 200},
        "E": {"symbol": "E", "RANK_M": 30},
    }

    # Cutoff: RANK_M <= 100 -> B and D fail
    result = engine.select(
        records,
        cutoffs=[RankCutoffSpec(rank_metric="RANK_M", max_rank=100)],
    )

    # Output must strictly be ["A", "C", "E"]
    assert result.selected_symbols == ["A", "C", "E"]
    assert result.matched_count == 3


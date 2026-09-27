"""Tests for RankingEngine — Relative ordering across metrics."""

import pytest

from yogi.core.contracts.ranking import (
    IRankingRule,
    RankingMethod,
    RankingOrder,
    RankingResult,
)
from yogi.ranking.engine import RankingEngine


@pytest.fixture
def sample_records():
    return {
        "A": {"symbol": "A", "ROC": 25.0, "exchange": "NSE", "M_CUR": 15.0, "M_P1": 10.0},
        "B": {"symbol": "B", "ROC": 50.0, "exchange": "NSE", "M_CUR": 20.0, "M_P1": 5.0},
        "C": {"symbol": "C", "ROC": 25.0, "exchange": "BSE", "M_CUR": 5.0, "M_P1": 25.0},
        "D": {"symbol": "D", "ROC": 10.0, "exchange": "BSE", "M_CUR": 30.0, "M_P1": 15.0},
        "E": {"symbol": "E", "ROC": None, "exchange": "NSE", "M_CUR": None, "M_P1": 2.0},
    }


def test_ranking_engine_implements_contract():
    engine = RankingEngine()
    assert isinstance(engine, IRankingRule)


def test_ranking_engine_descending_min_ties(sample_records):
    engine = RankingEngine()

    result = engine.rank(
        sample_records,
        metric="ROC",
        order=RankingOrder.DESCENDING,
        method=RankingMethod.MIN,
    )

    assert isinstance(result, RankingResult)
    assert result.metric == "ROC"
    # Order: B (50) -> 1, A (25) & C (25) -> tied at 2, D (10) -> 4, E (None) -> 5 (placed last)
    assert result.ranks["B"] == 1
    assert result.ranks["A"] == 2
    assert result.ranks["C"] == 2
    assert result.ranks["D"] == 4
    assert result.ranks["E"] == 5

    # Confirm NO records were dropped
    assert len(result.ranks) == 5


def test_ranking_engine_ascending_order(sample_records):
    engine = RankingEngine()

    result = engine.rank(
        sample_records,
        metric="ROC",
        order=RankingOrder.ASCENDING,
        method=RankingMethod.MIN,
    )

    # Ascending valid: D (10) -> 1, A (25) & C (25) -> 2, B (50) -> 4, E (None) -> 5
    assert result.ranks["D"] == 1
    assert result.ranks["A"] == 2
    assert result.ranks["C"] == 2
    assert result.ranks["B"] == 4
    assert result.ranks["E"] == 5


def test_ranking_engine_dense_method(sample_records):
    engine = RankingEngine()

    result = engine.rank(
        sample_records,
        metric="ROC",
        order=RankingOrder.DESCENDING,
        method=RankingMethod.DENSE,
    )

    # Dense ranks: B (50) -> 1, A & C (25) -> 2, D (10) -> 3, E (None) -> 4
    assert result.ranks["B"] == 1
    assert result.ranks["A"] == 2
    assert result.ranks["C"] == 2
    assert result.ranks["D"] == 3
    assert result.ranks["E"] == 4


def test_ranking_engine_average_method():
    engine = RankingEngine()

    records = {
        "A": {"ROC": 100.0},
        "B": {"ROC": 80.0},
        "C": {"ROC": 80.0},
        "D": {"ROC": 60.0},
    }

    result = engine.rank(
        records,
        metric="ROC",
        order=RankingOrder.DESCENDING,
        method=RankingMethod.AVERAGE,
    )

    assert result.ranks["A"] == 1
    # B and C occupy positions 2 and 3 -> avg = 2.5 -> rounded to int 2 or 3
    assert result.ranks["B"] in (2, 3)
    assert result.ranks["C"] in (2, 3)
    assert result.ranks["D"] == 4


def test_ranking_engine_group_by(sample_records):
    engine = RankingEngine()

    result = engine.rank(
        sample_records,
        metric="ROC",
        order=RankingOrder.DESCENDING,
        method=RankingMethod.MIN,
        group_by="exchange",
    )

    assert result.grouped_by == "exchange"
    # NSE group: B (50) -> 1, A (25) -> 2, E (None) -> 3
    assert result.ranks["B"] == 1
    assert result.ranks["A"] == 2
    assert result.ranks["E"] == 3
    # BSE group: C (25) -> 1, D (10) -> 2
    assert result.ranks["C"] == 1
    assert result.ranks["D"] == 2


def test_ranking_engine_rank_changes_m_cur_vs_m_p1(sample_records):
    engine = RankingEngine()

    result = engine.rank(
        sample_records,
        metric="M_CUR",
        order=RankingOrder.DESCENDING,
        method=RankingMethod.MIN,
    )

    # Current ranks for M_CUR:
    # D: 30 -> 1
    # B: 20 -> 2
    # A: 15 -> 3
    # C: 5  -> 4
    # E: None -> 5
    assert result.ranks["D"] == 1
    assert result.ranks["B"] == 2
    assert result.ranks["A"] == 3
    assert result.ranks["C"] == 4
    assert result.ranks["E"] == 5

    # Previous ranks for M_P1:
    # C: 25 -> 1
    # D: 15 -> 2
    # A: 10 -> 3
    # B: 5  -> 4
    # E: 2  -> 5
    # rank_changes = rank(M_P1) - rank(M_CUR):
    # D: 2 - 1 = +1 (climbed)
    # B: 4 - 2 = +2 (climbed)
    # A: 3 - 3 = 0 (same)
    # C: 1 - 4 = -3 (fell)
    # E: 5 - 5 = 0
    assert result.rank_changes is not None
    assert result.rank_changes["D"] == 1
    assert result.rank_changes["B"] == 2
    assert result.rank_changes["A"] == 0
    assert result.rank_changes["C"] == -3
    assert result.rank_changes["E"] == 0


def test_ranking_engine_empty_records():
    engine = RankingEngine()
    result = engine.rank({}, metric="ROC")
    assert result.ranks == {}
    assert result.rank_changes is None

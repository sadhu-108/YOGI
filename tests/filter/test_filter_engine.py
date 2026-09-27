"""Tests for FilterEngine — Boolean qualification criteria."""

import pytest

from yogi.core.contracts.filter import (
    FilterEvaluationResult,
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    FilterStepMetric,
    IFilterRule,
)
from yogi.filter.engine import FilterEngine


@pytest.fixture
def sample_records():
    return {
        "RELIANCE": {
            "symbol": "RELIANCE",
            "price": 2500.0,
            "EMA_W": "upcut",
            "EMA_M": "yes",
            "BANDST_M": "ABOVE",
            "S4": 2.5,
            "S52": 1.2,
            "RANK_CHG": 5,
            "note": "Top Bluechip",
            "empty_val": None,
            "blank_str": "   ",
        },
        "TCS": {
            "symbol": "TCS",
            "price": 3800.0,
            "EMA_W": "yes",
            "EMA_M": "yes",
            "BANDST_M": "IN",
            "S4": 1.0,
            "S52": 1.5,
            "RANK_CHG": -2,
            "note": "IT giant",
            "empty_val": float("nan"),
            "blank_str": "",
        },
        "INFY": {
            "symbol": "INFY",
            "price": 1600.0,
            "EMA_W": "downcut",
            "EMA_M": "no",
            "BANDST_M": "BELOW",
            "S4": 0.5,
            "S52": 0.8,
            "RANK_CHG": 0,
            "note": "IT challenger",
            "empty_val": 10.0,
            "blank_str": "valid",
        },
        "HDFCBANK": {
            "symbol": "HDFCBANK",
            "price": 1500.0,
            "EMA_W": "no",
            "EMA_M": "upcut",
            "BANDST_M": "ABOVE",
            "S4": 3.0,
            "S52": 2.0,
            "RANK_CHG": 8,
            "note": None,
            "empty_val": None,
            "blank_str": "bank",
        },
    }


def test_filter_engine_implements_contract():
    engine = FilterEngine()
    assert isinstance(engine, IFilterRule)


def test_filter_engine_numeric_operators(sample_records):
    engine = FilterEngine()

    # GT
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.GT, value=2000.0),
    )
    assert res.matching_symbols == ["RELIANCE", "TCS"]
    assert res.matched_count == 2
    assert res.universe_size == 4

    # GTE
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.GTE, value=2500.0),
    )
    assert res.matching_symbols == ["RELIANCE", "TCS"]

    # LT
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.LT, value=2000.0),
    )
    assert res.matching_symbols == ["INFY", "HDFCBANK"]

    # LTE
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.LTE, value=1600.0),
    )
    assert res.matching_symbols == ["INFY", "HDFCBANK"]


def test_filter_engine_equality_operators(sample_records):
    engine = FilterEngine()

    # EQ string case-insensitive
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="above"),
    )
    assert res.matching_symbols == ["RELIANCE", "HDFCBANK"]

    # EQ numeric
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.EQ, value=3800),
    )
    assert res.matching_symbols == ["TCS"]

    # NEQ
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="BANDST_M", op=FilterOperator.NEQ, value="ABOVE"),
    )
    assert res.matching_symbols == ["TCS", "INFY"]


def test_filter_engine_in_and_not_in_operators(sample_records):
    engine = FilterEngine()

    # IN case-insensitive
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="EMA_W", op=FilterOperator.IN, value=["UPCUT", "YES"]),
    )
    assert res.matching_symbols == ["RELIANCE", "TCS"]

    # NOT_IN
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="EMA_W", op=FilterOperator.NOT_IN, value=["upcut", "yes"]),
    )
    assert res.matching_symbols == ["INFY", "HDFCBANK"]


def test_filter_engine_between_operator(sample_records):
    engine = FilterEngine()

    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="price", op=FilterOperator.BETWEEN, value=[1500.0, 2500.0]),
    )
    assert res.matching_symbols == ["RELIANCE", "INFY", "HDFCBANK"]


def test_filter_engine_blank_and_not_blank_operators(sample_records):
    engine = FilterEngine()

    # BLANK matches None, NaN, and empty/whitespace strings
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="empty_val", op=FilterOperator.BLANK),
    )
    assert res.matching_symbols == ["RELIANCE", "TCS", "HDFCBANK"]

    res_str = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="blank_str", op=FilterOperator.BLANK),
    )
    assert res_str.matching_symbols == ["RELIANCE", "TCS"]

    # NOT_BLANK
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="empty_val", op=FilterOperator.NOT_BLANK),
    )
    assert res.matching_symbols == ["INFY"]


def test_filter_engine_contains_operator(sample_records):
    engine = FilterEngine()

    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="note", op=FilterOperator.CONTAINS, value="it"),
    )
    # "IT giant", "IT challenger" match, case-insensitive
    assert res.matching_symbols == ["TCS", "INFY"]


def test_filter_engine_cross_column_comparison(sample_records):
    engine = FilterEngine()

    # S4 > S52
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="S4", op=FilterOperator.GT, field2="S52"),
    )
    # RELIANCE: 2.5 > 1.2 (True)
    # TCS: 1.0 > 1.5 (False)
    # INFY: 0.5 > 0.8 (False)
    # HDFCBANK: 3.0 > 2.0 (True)
    assert res.matching_symbols == ["RELIANCE", "HDFCBANK"]


def test_filter_engine_rule_and_group_negation(sample_records):
    engine = FilterEngine()

    # Leaf rule negation: NOT (BANDST_M == "ABOVE")
    res = engine.evaluate(
        sample_records,
        FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE", is_negated=True),
    )
    assert res.matching_symbols == ["TCS", "INFY"]

    # Group negation
    group = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE"),
        ],
        is_negated=True,
    )
    res_group = engine.evaluate(sample_records, group)
    assert res_group.matching_symbols == ["TCS", "INFY"]


def test_filter_engine_group_and_or_logic(sample_records):
    engine = FilterEngine()

    # AND logic (match="all")
    and_group = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE"),
            FilterRuleSpec(field="RANK_CHG", op=FilterOperator.GT, value=0),
        ],
    )
    res_and = engine.evaluate(sample_records, and_group)
    assert res_and.matching_symbols == ["RELIANCE", "HDFCBANK"]

    # OR logic (match="any")
    or_group = FilterGroupSpec(
        match="any",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.GT, value=3000),
            FilterRuleSpec(field="price", op=FilterOperator.LT, value=1600),
        ],
    )
    res_or = engine.evaluate(sample_records, or_group)
    assert res_or.matching_symbols == ["TCS", "HDFCBANK"]


def test_filter_engine_nested_groups(sample_records):
    engine = FilterEngine()

    # (BANDST_M == "ABOVE" AND S4 > S52) OR (price > 3500)
    nested_group = FilterGroupSpec(
        match="any",
        rules=[
            FilterGroupSpec(
                match="all",
                rules=[
                    FilterRuleSpec(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE"),
                    FilterRuleSpec(field="S4", op=FilterOperator.GT, field2="S52"),
                ],
            ),
            FilterRuleSpec(field="price", op=FilterOperator.GT, value=3500.0),
        ],
    )
    res = engine.evaluate(sample_records, nested_group)
    assert res.matching_symbols == ["RELIANCE", "TCS", "HDFCBANK"]


def test_filter_engine_empty_group(sample_records):
    engine = FilterEngine()

    empty_group = FilterGroupSpec(rules=[])
    res = engine.evaluate(sample_records, empty_group)
    assert res.matched_count == 4
    assert res.matching_symbols == list(sample_records.keys())
    assert res.explanation == "everything"


def test_filter_engine_funnel_telemetry_and_explanation(sample_records):
    engine = FilterEngine()

    group = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.GT, value=2000.0),
            FilterRuleSpec(field="EMA_W", op=FilterOperator.IN, value=["upcut", "yes"]),
        ],
    )
    res = engine.evaluate(sample_records, group)

    assert len(res.steps) == 2
    assert res.steps[0].passing_count == 2  # RELIANCE, TCS > 2000
    assert res.steps[1].passing_count == 2  # RELIANCE, TCS EMA_W in [upcut, yes]
    assert "price > 2000.0 AND EMA_W in ['upcut', 'yes']" in res.explanation

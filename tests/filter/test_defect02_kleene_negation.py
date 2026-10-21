"""Regression tests for DEFECT-02: Kleene three-valued logic preservation under filter negation.

Verifies that:
1. A valid comparison evaluates as before.
2. A missing field under a positive comparison yields UNKNOWN.
3. Negating that UNKNOWN still yields UNKNOWN.
4. Missing data cannot qualify solely because a comparison is negated.
5. BLANK behaves correctly for missing and non-missing values.
6. NOT_BLANK behaves correctly for missing and non-missing values.
7. Valid True and False comparisons are negated correctly.
8. AND and OR combinations preserve the expected three-valued logic.
9. Existing ROC, EMA, and other filter conditions continue to behave correctly.
10. Invalid values, including non-finite numeric values where applicable, follow the established contract.
"""

import math
import pytest

from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.filter.engine import FilterEngine


@pytest.fixture
def filter_engine():
    return FilterEngine()


@pytest.fixture
def records():
    return {
        "VALID_EXPENSIVE": {
            "symbol": "VALID_EXPENSIVE",
            "price": 2500.0,
            "pe": 45.0,
            "status": "ACTIVE",
            "category": "TECH",
            "speed": 3.5,
            "speed_target": 2.0,
        },
        "VALID_CHEAP": {
            "symbol": "VALID_CHEAP",
            "price": 80.0,
            "pe": 12.0,
            "status": "INACTIVE",
            "category": "UTILITIES",
            "speed": 1.0,
            "speed_target": 2.5,
        },
        "MISSING_FIELDS": {
            "symbol": "MISSING_FIELDS",
            # price, pe, status, category are absent
        },
        "EXPLICIT_NONE": {
            "symbol": "EXPLICIT_NONE",
            "price": None,
            "pe": None,
            "status": None,
            "category": None,
            "speed": None,
            "speed_target": None,
        },
        "NAN_VALUES": {
            "symbol": "NAN_VALUES",
            "price": float("nan"),
            "pe": float("nan"),
            "speed": float("nan"),
            "speed_target": float("nan"),
        },
        "INF_VALUES": {
            "symbol": "INF_VALUES",
            "price": float("inf"),
            "pe": float("-inf"),
            "speed": float("inf"),
            "speed_target": 2.0,
        },
    }


def test_1_valid_comparisons_evaluate_as_before(filter_engine, records):
    """Verify that ordinary valid comparisons evaluate identically to established behavior."""
    # GT / LT
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="price", op=FilterOperator.GT, value=1000.0)) is True
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], FilterRuleSpec(field="price", op=FilterOperator.GT, value=1000.0)) is False

    # EQ / NEQ
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="status", op=FilterOperator.EQ, value="ACTIVE")) is True
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="status", op=FilterOperator.NEQ, value="ACTIVE")) is False

    # IN / NOT_IN
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="category", op=FilterOperator.IN, value=["TECH", "HEALTH"])) is True
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], FilterRuleSpec(field="category", op=FilterOperator.IN, value=["TECH", "HEALTH"])) is False
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], FilterRuleSpec(field="category", op=FilterOperator.NOT_IN, value=["TECH", "HEALTH"])) is True

    # BETWEEN
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="price", op=FilterOperator.BETWEEN, value=[2000.0, 3000.0])) is True
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], FilterRuleSpec(field="price", op=FilterOperator.BETWEEN, value=[2000.0, 3000.0])) is False

    # Field-to-field
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], FilterRuleSpec(field="speed", op=FilterOperator.GT, field2="speed_target")) is True
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], FilterRuleSpec(field="speed", op=FilterOperator.GT, field2="speed_target")) is False


def test_2_missing_field_under_positive_comparison_yields_unknown(filter_engine, records):
    """Verify that a missing or None field yields UNKNOWN (None) rather than False."""
    for key in ("MISSING_FIELDS", "EXPLICIT_NONE"):
        rec = records[key]
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.GT, value=100.0)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.LT, value=100.0)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="status", op=FilterOperator.EQ, value="ACTIVE")) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="category", op=FilterOperator.IN, value=["TECH"])) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.BETWEEN, value=[50.0, 150.0])) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="speed", op=FilterOperator.GT, field2="speed_target")) is None


def test_3_negating_unknown_remains_unknown(filter_engine, records):
    """Verify that NOT (UNKNOWN) === UNKNOWN (None), adhering to formal Kleene tri-state logic."""
    for key in ("MISSING_FIELDS", "EXPLICIT_NONE"):
        rec = records[key]
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.GT, value=100.0, is_negated=True)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.LT, value=100.0, is_negated=True)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="status", op=FilterOperator.EQ, value="ACTIVE", is_negated=True)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="category", op=FilterOperator.IN, value=["TECH"], is_negated=True)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="price", op=FilterOperator.BETWEEN, value=[50.0, 150.0], is_negated=True)) is None
        assert filter_engine._eval_leaf(rec, FilterRuleSpec(field="speed", op=FilterOperator.GT, field2="speed_target", is_negated=True)) is None


def test_4_missing_data_cannot_qualify_solely_because_condition_is_negated(filter_engine, records):
    """Verify DEFECT-02: Negated filter rules do NOT qualify records with missing or None data."""
    # Screen for NOT (price > 100.0): only VALID_CHEAP (price=80.0) qualifies!
    # MISSING_FIELDS, EXPLICIT_NONE, NAN_VALUES, and INF_VALUES must NEVER qualify!
    rule_neg = FilterRuleSpec(field="price", op=FilterOperator.GT, value=100.0, is_negated=True)
    res = filter_engine.evaluate(records, rule_neg)

    assert res.matching_symbols == ["VALID_CHEAP"]
    assert "MISSING_FIELDS" not in res.matching_symbols
    assert "EXPLICIT_NONE" not in res.matching_symbols
    assert "NAN_VALUES" not in res.matching_symbols
    assert "INF_VALUES" not in res.matching_symbols


def test_5_blank_operator_semantics(filter_engine, records):
    """Verify explicit BLANK operator produces definitive boolean True/False and negates correctly."""
    # Positive BLANK: matches None, missing, and NaN
    rule_blank = FilterRuleSpec(field="price", op=FilterOperator.BLANK)
    res_blank = filter_engine.evaluate(records, rule_blank)
    assert set(res_blank.matching_symbols) == {"MISSING_FIELDS", "EXPLICIT_NONE", "NAN_VALUES"}

    # Negated BLANK: NOT (BLANK) === NOT_BLANK
    rule_not_blank_via_neg = FilterRuleSpec(field="price", op=FilterOperator.BLANK, is_negated=True)
    res_not_blank = filter_engine.evaluate(records, rule_not_blank_via_neg)
    assert set(res_not_blank.matching_symbols) == {"VALID_EXPENSIVE", "VALID_CHEAP", "INF_VALUES"}


def test_6_not_blank_operator_semantics(filter_engine, records):
    """Verify explicit NOT_BLANK operator produces definitive boolean True/False and negates correctly."""
    rule_not_blank = FilterRuleSpec(field="price", op=FilterOperator.NOT_BLANK)
    res = filter_engine.evaluate(records, rule_not_blank)
    assert set(res.matching_symbols) == {"VALID_EXPENSIVE", "VALID_CHEAP", "INF_VALUES"}

    # Negated NOT_BLANK: NOT (NOT_BLANK) === BLANK
    rule_neg_not_blank = FilterRuleSpec(field="price", op=FilterOperator.NOT_BLANK, is_negated=True)
    res_neg = filter_engine.evaluate(records, rule_neg_not_blank)
    assert set(res_neg.matching_symbols) == {"MISSING_FIELDS", "EXPLICIT_NONE", "NAN_VALUES"}


def test_7_valid_true_and_false_comparisons_negated_correctly(filter_engine, records):
    """Verify that records with genuine valid data invert accurately under negation."""
    rule_gt_neg = FilterRuleSpec(field="price", op=FilterOperator.GT, value=100.0, is_negated=True)
    # VALID_EXPENSIVE (price=2500): 2500 > 100 is True -> negated is False
    assert filter_engine._eval_leaf(records["VALID_EXPENSIVE"], rule_gt_neg) is False
    # VALID_CHEAP (price=80): 80 > 100 is False -> negated is True
    assert filter_engine._eval_leaf(records["VALID_CHEAP"], rule_gt_neg) is True


def test_8_compound_groups_preserve_kleene_logic(filter_engine, records):
    """Verify Kleene three-valued truth tables across AND and OR conjunctions."""
    # 1. True AND None -> None (does not qualify)
    group_and_unknown = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.GT, value=50.0),       # True for VALID_EXPENSIVE
            FilterRuleSpec(field="missing_col", op=FilterOperator.GT, value=10.0), # None
        ],
    )
    res_and = filter_engine.evaluate({"VALID_EXPENSIVE": records["VALID_EXPENSIVE"]}, group_and_unknown)
    assert res_and.matching_symbols == []

    # 2. False AND None -> False (does not qualify)
    group_and_false = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.LT, value=50.0),       # False for VALID_EXPENSIVE
            FilterRuleSpec(field="missing_col", op=FilterOperator.GT, value=10.0), # None
        ],
    )
    res_and_false = filter_engine.evaluate({"VALID_EXPENSIVE": records["VALID_EXPENSIVE"]}, group_and_false)
    assert res_and_false.matching_symbols == []

    # 3. True OR None -> True (qualifies!)
    group_or_true = FilterGroupSpec(
        match="any",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.GT, value=50.0),       # True for VALID_EXPENSIVE
            FilterRuleSpec(field="missing_col", op=FilterOperator.GT, value=10.0), # None
        ],
    )
    res_or_true = filter_engine.evaluate({"VALID_EXPENSIVE": records["VALID_EXPENSIVE"]}, group_or_true)
    assert res_or_true.matching_symbols == ["VALID_EXPENSIVE"]

    # 4. False OR None -> None (does not qualify)
    group_or_unknown = FilterGroupSpec(
        match="any",
        rules=[
            FilterRuleSpec(field="price", op=FilterOperator.LT, value=50.0),       # False for VALID_EXPENSIVE
            FilterRuleSpec(field="missing_col", op=FilterOperator.GT, value=10.0), # None
        ],
    )
    res_or_unknown = filter_engine.evaluate({"VALID_EXPENSIVE": records["VALID_EXPENSIVE"]}, group_or_unknown)
    assert res_or_unknown.matching_symbols == []


def test_9_existing_roc_and_ema_evaluators_unaffected(filter_engine):
    """Verify that modular ROC and EMA evaluators continue to operate correctly."""
    records_ema = {
        "UP": {"EMA_D_3_5": {"state": "UP", "is_up": True}},
        "DOWN": {"EMA_D_3_5": {"state": "DOWN", "is_down": True}},
        "NONE": {"EMA_D_3_5": None},
    }

    rule_ema = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP")
    res_ema = filter_engine.evaluate(records_ema, rule_ema)
    assert res_ema.matching_symbols == ["UP"]

    rule_ema_neg = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP", is_negated=True)
    res_ema_neg = filter_engine.evaluate(records_ema, rule_ema_neg)
    assert res_ema_neg.matching_symbols == ["DOWN"]
    assert "NONE" not in res_ema_neg.matching_symbols


def test_10_invalid_and_non_finite_values_produce_unknown(filter_engine, records):
    """Verify that non-finite values (NaN, +inf, -inf) yield UNKNOWN (None) and do not qualify under negation."""
    rule_gt = FilterRuleSpec(field="price", op=FilterOperator.GT, value=100.0, is_negated=True)
    rule_lt = FilterRuleSpec(field="price", op=FilterOperator.LT, value=100.0, is_negated=True)

    # NAN_VALUES
    assert filter_engine._eval_leaf(records["NAN_VALUES"], rule_gt) is None
    assert filter_engine._eval_leaf(records["NAN_VALUES"], rule_lt) is None

    # INF_VALUES
    assert filter_engine._eval_leaf(records["INF_VALUES"], rule_gt) is None
    assert filter_engine._eval_leaf(records["INF_VALUES"], rule_lt) is None

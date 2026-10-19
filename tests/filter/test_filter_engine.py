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


def test_filter_engine_evaluator_unregistered_raises_value_error():
    """Verify that FilterEngine raises ValueError when a rule specifies an unregistered condition_type."""
    engine = FilterEngine()
    rule = FilterRuleSpec(field="X", condition_type="unregistered_type")
    with pytest.raises(ValueError) as exc_info:
        engine.evaluate({"SYM": {"X": 10}}, rule)
    assert "No condition evaluator registered for condition_type 'unregistered_type'" in str(exc_info.value)


def test_filter_engine_evaluator_unevaluated_or_none_does_not_qualify_under_negation():
    """Verify that uncomputed (None) and insufficient history ('na') states never qualify under negation."""
    engine = FilterEngine()
    records = {
        "SYM_UP": {"EMA_D_3_5": {"state": "UP", "is_up": True, "is_down": False}},
        "SYM_DOWN": {"EMA_D_3_5": {"state": "DOWN", "is_up": False, "is_down": True}},
        "SYM_NA": {"EMA_D_3_5": {"state": "na", "is_up": False, "is_down": False}},
        "SYM_NONE": {"EMA_D_3_5": None},
        "SYM_MISSING": {},
    }

    # 1. Non-negated UP: only SYM_UP qualifies
    rule_up = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
        is_negated=False,
    )
    res_up = engine.evaluate(records, rule_up)
    assert res_up.matching_symbols == ["SYM_UP"]

    # 2. Negated UP: ONLY SYM_DOWN qualifies!
    # SYM_NA, SYM_NONE, and SYM_MISSING must NEVER qualify under negation.
    rule_not_up = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
        is_negated=True,
    )
    res_not_up = engine.evaluate(records, rule_not_up)
    assert res_not_up.matching_symbols == ["SYM_DOWN"]

    # 3. Non-negated DOWN: only SYM_DOWN qualifies
    rule_down = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="DOWN",
        is_negated=False,
    )
    res_down = engine.evaluate(records, rule_down)
    assert res_down.matching_symbols == ["SYM_DOWN"]

    # 4. Negated DOWN: ONLY SYM_UP qualifies!
    rule_not_down = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="DOWN",
        is_negated=True,
    )
    res_not_down = engine.evaluate(records, rule_not_down)
    assert res_not_down.matching_symbols == ["SYM_UP"]


def test_filter_engine_leaf_tri_state_evaluation():
    """Verify that leaf evaluation respects tri-state semantics (True, False, None) for both positive and negated rules."""
    engine = FilterEngine()
    records = {
        "S_TRUE": {"EMA_D_3_5": {"state": "UP", "is_up": True, "is_down": False}},
        "S_FALSE": {"EMA_D_3_5": {"state": "DOWN", "is_up": False, "is_down": True}},
        "S_NONE": {"EMA_D_3_5": None},
    }

    # Positive (non-negated) leaf: True qualifies; False and None do not qualify
    rule_pos = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP", is_negated=False)
    res_pos = engine.evaluate(records, rule_pos)
    assert res_pos.matching_symbols == ["S_TRUE"]

    # Negated leaf: False qualifies; True and None do not qualify
    rule_neg = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP", is_negated=True)
    res_neg = engine.evaluate(records, rule_neg)
    assert res_neg.matching_symbols == ["S_FALSE"]


def test_filter_engine_group_negation_tri_state_protection():
    """Verify that group-level negation does NOT turn missing data, 'na', or uncomputed conditions into matches."""
    engine = FilterEngine()
    records = {
        "SYM_MATCH": {"EMA_D_3_5": {"state": "UP", "is_up": True, "is_down": False}},
        "SYM_NON_MATCH": {"EMA_D_3_5": {"state": "DOWN", "is_up": False, "is_down": True}},
        "SYM_MISSING_DATA": {"EMA_D_3_5": None},
        "SYM_EMPTY_RECORD": {},
        "SYM_NA_DICT": {"EMA_D_3_5": {"state": "na", "is_up": False, "is_down": False}},
        "SYM_NA_STR": {"EMA_D_3_5": "na"},
    }

    rule_up = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP")

    # 1. Non-negated group: only SYM_MATCH qualifies
    group_pos = FilterGroupSpec(match="all", rules=[rule_up], is_negated=False)
    res_pos = engine.evaluate(records, group_pos)
    assert res_pos.matching_symbols == ["SYM_MATCH"]

    # 2. Negated group: ONLY genuine non-match SYM_NON_MATCH qualifies!
    # Missing data, empty records, and 'na' states must NEVER qualify under group negation!
    group_neg = FilterGroupSpec(match="all", rules=[rule_up], is_negated=True)
    res_neg = engine.evaluate(records, group_neg)
    assert res_neg.matching_symbols == ["SYM_NON_MATCH"]

    # 3. Negated ANY group: ONLY SYM_NON_MATCH qualifies
    group_any_neg = FilterGroupSpec(match="any", rules=[rule_up], is_negated=True)
    res_any_neg = engine.evaluate(records, group_any_neg)
    assert res_any_neg.matching_symbols == ["SYM_NON_MATCH"]


def test_filter_engine_tri_state_and_or_and_nesting():
    """Verify Kleene 3-valued logic across AND, OR, negation, and nested group hierarchies."""
    engine = FilterEngine()
    records = {
        "S_VALID_AND": {"price": 150.0, "EMA_D_3_5": {"state": "UP", "is_up": True, "is_down": False}},
        "S_VALID_OR_ONLY": {"price": 150.0, "EMA_D_3_5": None},
        "S_FAIL_BOTH": {"price": 50.0, "EMA_D_3_5": {"state": "DOWN", "is_up": False, "is_down": True}},
        "S_FAIL_PRICE_NONE_EMA": {"price": 50.0, "EMA_D_3_5": None},
    }

    rule_price = FilterRuleSpec(field="price", op=">", value=100.0)
    rule_ema = FilterRuleSpec(field="EMA_D_3_5", condition_type="ema", state="UP")

    # 1. OR group with independently satisfied branch (Price > 100 OR EMA UP)
    # S_VALID_AND: True or True -> True
    # S_VALID_OR_ONLY: True or None -> True (independently satisfied by price!)
    # S_FAIL_BOTH: False or False -> False
    # S_FAIL_PRICE_NONE_EMA: False or None -> None
    group_or = FilterGroupSpec(match="any", rules=[rule_price, rule_ema])
    res_or = engine.evaluate(records, group_or)
    assert set(res_or.matching_symbols) == {"S_VALID_AND", "S_VALID_OR_ONLY"}

    # 2. Negated OR group: NOT (Price > 100 OR EMA UP)
    # Equivalent to Price <= 100 AND NOT (EMA UP).
    # S_VALID_AND: not True -> False
    # S_VALID_OR_ONLY: not True -> False
    # S_FAIL_BOTH: not False -> True (qualifies!)
    # S_FAIL_PRICE_NONE_EMA: not None -> None (does NOT qualify!)
    group_or_neg = FilterGroupSpec(match="any", rules=[rule_price, rule_ema], is_negated=True)
    res_or_neg = engine.evaluate(records, group_or_neg)
    assert res_or_neg.matching_symbols == ["S_FAIL_BOTH"]

    # 3. AND group (Price > 100 AND EMA UP)
    # S_VALID_AND: True and True -> True
    # S_VALID_OR_ONLY: True and None -> None (does not qualify)
    # S_FAIL_BOTH: False and False -> False (does not qualify)
    # S_FAIL_PRICE_NONE_EMA: False and None -> False (does not qualify)
    group_and = FilterGroupSpec(match="all", rules=[rule_price, rule_ema])
    res_and = engine.evaluate(records, group_and)
    assert res_and.matching_symbols == ["S_VALID_AND"]

    # 4. Negated AND group: NOT (Price > 100 AND EMA UP)
    # S_VALID_AND: not True -> False
    # S_VALID_OR_ONLY: not None -> None (cannot prove it did not satisfy)
    # S_FAIL_BOTH: not False -> True (price <= 100 proves failure, so negation is True!)
    # S_FAIL_PRICE_NONE_EMA: not False -> True (price <= 100 proves failure!)
    group_and_neg = FilterGroupSpec(match="all", rules=[rule_price, rule_ema], is_negated=True)
    res_and_neg = engine.evaluate(records, group_and_neg)
    assert set(res_and_neg.matching_symbols) == {"S_FAIL_BOTH", "S_FAIL_PRICE_NONE_EMA"}

    # 5. Nested group with child unevaluated: NOT ( (EMA UP) AND price > 100 )
    inner_group = FilterGroupSpec(match="all", rules=[rule_ema])
    nested_neg = FilterGroupSpec(match="all", rules=[inner_group, rule_price], is_negated=True)
    res_nested = engine.evaluate(records, nested_neg)
    assert set(res_nested.matching_symbols) == {"S_FAIL_BOTH", "S_FAIL_PRICE_NONE_EMA"}


def test_filter_engine_evaluator_registration_and_duplicate_policy():
    """Verify evaluator registration integrity: duplicate policy, collision rejection, atomicity, and normalization."""
    from yogi.core.contracts.filter import IConditionEvaluator

    class DummyEvaluator(IConditionEvaluator):
        def __init__(self, name: str):
            self.name = name

        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
            return True

        def describe(self, rule: FilterRuleSpec) -> str:
            return f"Dummy({self.name})"

    engine = FilterEngine(evaluators={})  # Start with completely clean engine
    assert engine.has_evaluator("rsi") is False

    # 1. First registration succeeds
    eval1 = DummyEvaluator("v1")
    engine.register_evaluator("rsi", eval1)
    assert engine.has_evaluator("rsi") is True
    assert engine.get_evaluator("rsi") is eval1

    # 2. Case and whitespace normalization: "  RSI " matches "rsi"
    assert engine.has_evaluator("  RSI  ") is True
    assert engine.get_evaluator("  RSI  ") is eval1

    # 3. Safe idempotent re-registration of the exact same instance succeeds
    engine.register_evaluator("rsi", eval1)
    engine.register_evaluator("  RSI  ", eval1)
    assert engine.get_evaluator("rsi") is eval1

    # 4. Conflicting registration with a different instance is rejected
    eval2 = DummyEvaluator("v2")
    with pytest.raises(ValueError) as exc_info:
        engine.register_evaluator("rsi", eval2)
    assert "Condition evaluator for 'rsi' is already registered" in str(exc_info.value)

    # 5. Atomicity: Original evaluator remains intact after rejection
    assert engine.get_evaluator("rsi") is eval1

    # 6. Invalid condition_type produces clear ValueError
    with pytest.raises(ValueError) as exc_empty:
        engine.register_evaluator("", eval2)
    assert "condition_type must be a non-empty string" in str(exc_empty.value)

    with pytest.raises(ValueError):
        engine.register_evaluator("   ", eval2)

    with pytest.raises(ValueError):
        engine.register_evaluator(None, eval2)

    # 7. Invalid evaluator type produces TypeError
    with pytest.raises(TypeError) as exc_type:
        engine.register_evaluator("valid_name", "not_an_evaluator")
    assert "must implement IConditionEvaluator" in str(exc_type.value)

    # 8. Distinct condition types can coexist cleanly
    eval_bands = DummyEvaluator("bands")
    engine.register_evaluator("bands", eval_bands)
    assert engine.get_evaluator("bands") is eval_bands
    assert engine.get_evaluator("rsi") is eval1


def test_filter_engine_bootstrap_and_custom_evaluators():
    """Verify production bootstrap, default registration, and custom evaluator injection."""
    from yogi.core.contracts.filter import IConditionEvaluator
    from yogi.filter import create_default_filter_engine, get_default_condition_evaluators

    class CustomEmaEvaluator(IConditionEvaluator):
        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
            return True

        def describe(self, rule: FilterRuleSpec) -> str:
            return "CustomEMA"

    class CustomRsiEvaluator(IConditionEvaluator):
        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
            return True

        def describe(self, rule: FilterRuleSpec) -> str:
            return "CustomRSI"

    # 1. get_default_condition_evaluators returns standard production evaluators
    defaults = get_default_condition_evaluators()
    assert "ema" in defaults

    # 2. FilterEngine() with no args loads default evaluators
    engine_default = FilterEngine()
    assert engine_default.has_evaluator("ema") is True

    # 3. FilterEngine(evaluators={}) constructs empty engine without loading defaults
    engine_clean = FilterEngine(evaluators={})
    assert engine_clean.has_evaluator("ema") is False
    with pytest.raises(ValueError) as exc_missing:
        engine_clean.evaluate(
            {"SYM": {}},
            FilterRuleSpec(field="EMA", condition_type="ema"),
        )
    assert "No condition evaluator registered for condition_type 'ema'" in str(exc_missing.value)

    # 4. FilterEngine with custom evaluator injection replaces default cleanly without collision
    custom_ema = CustomEmaEvaluator()
    engine_custom = FilterEngine(evaluators={"ema": custom_ema})
    assert engine_custom.get_evaluator("ema") is custom_ema

    # 5. create_default_filter_engine returns populated engine and supports adding extra evaluators
    custom_rsi = CustomRsiEvaluator()
    engine_boostrapped = create_default_filter_engine(evaluators={"rsi": custom_rsi})
    assert engine_boostrapped.has_evaluator("ema") is True
    assert engine_boostrapped.get_evaluator("rsi") is custom_rsi

    # 6. Duplicate registration during create_default_filter_engine is rejected if conflicting
    with pytest.raises(ValueError):
        create_default_filter_engine(evaluators={"ema": custom_ema})



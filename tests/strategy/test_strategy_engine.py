"""Tests for Strategy engine and validation."""

import pytest

from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.strategy import IStrategy, StrategySpec, StrategyValidationResult
from yogi.strategy.engine import Strategy


def test_strategy_implements_contract():
    spec = StrategySpec(
        name="TEST_STRAT",
        filter_group=FilterGroupSpec(rules=[]),
    )
    strat = Strategy(spec)
    assert isinstance(strat, IStrategy)
    assert strat.get_spec() == spec


def test_strategy_validation_success():
    spec = StrategySpec(
        name="VALID_STRAT",
        filter_group=FilterGroupSpec(
            match="all",
            rules=[
                FilterRuleSpec(field="M_CUR", op=FilterOperator.GT, value=0.0),
                FilterRuleSpec(field="S4", op=FilterOperator.GT, field2="S52"),
                FilterGroupSpec(
                    match="any",
                    rules=[
                        FilterRuleSpec(field="EMA_W", op=FilterOperator.EQ, value="upcut"),
                    ],
                ),
            ],
        ),
    )
    strat = Strategy(spec)

    available = ["M_CUR", "S4", "S52", "EMA_W", "price"]
    res = strat.validate(available)

    assert isinstance(res, StrategyValidationResult)
    assert res.is_valid is True
    assert len(res.problems) == 0


def test_strategy_validation_identifies_unknown_fields_and_operators():
    spec = StrategySpec(
        name="INVALID_STRAT",
        filter_group=FilterGroupSpec(
            match="all",
            rules=[
                FilterRuleSpec(field="UNKNOWN_FIELD", op=FilterOperator.GT, value=0.0),
                FilterRuleSpec(field="S4", op=FilterOperator.GT, field2="UNKNOWN_FIELD2"),
                FilterRuleSpec(field="price", op="INVALID_OP", value=100.0),  # type: ignore
            ],
        ),
    )
    strat = Strategy(spec)

    available = ["price", "S4"]
    res = strat.validate(available)

    assert res.is_valid is False
    assert any("unknown field: UNKNOWN_FIELD" in p for p in res.problems)
    assert any("unknown field2: UNKNOWN_FIELD2" in p for p in res.problems)
    assert any("unknown operator" in p for p in res.problems)

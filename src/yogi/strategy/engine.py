"""Strategy Engine — Rule composition and strategy specification validation.

Implements IStrategy wrapping StrategySpec.
"""

from typing import Sequence

from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.strategy import IStrategy, StrategySpec, StrategyValidationResult

VALID_OPERATORS = {op.value for op in FilterOperator} | set(FilterOperator)


class Strategy(IStrategy):
    """Encapsulates a named strategy definition and its validation against available metrics."""

    def __init__(self, spec: StrategySpec) -> None:
        if not isinstance(spec, StrategySpec):
            raise TypeError(f"Expected StrategySpec, got {type(spec).__name__}")
        self._spec = spec

    def get_spec(self) -> StrategySpec:
        """Return the immutable strategy specification."""
        return self._spec

    def validate(self, available_fields: Sequence[str]) -> StrategyValidationResult:
        """Validate rule field names and operators against available metric definitions."""
        problems: list[str] = []
        field_set = set(available_fields)

        def _walk_group(group: FilterGroupSpec) -> None:
            for rule in group.rules:
                if isinstance(rule, FilterGroupSpec):
                    _walk_group(rule)
                elif isinstance(rule, FilterRuleSpec):
                    if rule.field not in field_set:
                        problems.append(f"unknown field: {rule.field}")
                    if rule.field2 is not None and rule.field2 not in field_set:
                        problems.append(f"unknown field2: {rule.field2}")
                    if rule.op not in VALID_OPERATORS:
                        problems.append(f"unknown operator: {rule.op}")
                else:
                    problems.append(f"unknown rule type: {type(rule).__name__}")

        _walk_group(self._spec.filter_group)

        return StrategyValidationResult(
            is_valid=len(problems) == 0,
            problems=problems,
        )

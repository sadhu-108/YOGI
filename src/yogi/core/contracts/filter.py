"""Filter Engine Contract — Boolean qualification criteria ("Does it qualify?")."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Union


class FilterOperator(str, Enum):
    """Supported operators in the filter evaluation engine."""
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    BLANK = "blank"
    NOT_BLANK = "not_blank"
    CONTAINS = "contains"


@dataclass(frozen=True)
class FilterRuleSpec:
    """Specification for a single leaf filter rule.
    
    Can compare a field against a constant value, or against another column (field2).
    """
    field: str
    op: FilterOperator = FilterOperator.EQ
    value: Any = None
    field2: Optional[str] = None
    is_negated: bool = False


@dataclass(frozen=True)
class FilterGroupSpec:
    """A collection of rules evaluated with 'all' (AND) or 'any' (OR) logic.
    
    Can be nested recursively.
    """
    match: str = "all"  # "all" | "any"
    rules: Sequence[Union[FilterRuleSpec, "FilterGroupSpec"]] = field(default_factory=list)
    is_negated: bool = False


@dataclass(frozen=True)
class FilterStepMetric:
    """Funnel step telemetry recording how many securities passed a particular rule."""
    rule_description: str
    passing_count: int


@dataclass(frozen=True)
class FilterEvaluationResult:
    """Result of evaluating a qualification filter across a dataset."""
    universe_size: int
    matched_count: int
    matching_symbols: Sequence[str]
    steps: Sequence[FilterStepMetric] = field(default_factory=list)
    explanation: str = ""


class IFilterRule(ABC):
    """The contract for evaluating qualification criteria.
    
    Migrated from prototype yogi.screening.strategy._leaf_mask and _block_mask.
    Solely responsible for determining if a security qualifies.
    """

    @abstractmethod
    def evaluate(
        self,
        records: Mapping[str, Mapping[str, Any]],
        spec: Union[FilterRuleSpec, FilterGroupSpec],
    ) -> FilterEvaluationResult:
        """Evaluate qualification rules against records and return matches and funnel steps."""
        pass

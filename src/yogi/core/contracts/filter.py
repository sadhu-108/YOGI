"""Filter Engine Contract — Boolean qualification criteria ("Does it qualify?")."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping as TMapping, Optional, Sequence, Union


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


def _freeze_param(val: Any) -> Any:
    """Recursively freeze parameter collections into immutable, hashable equivalents."""
    if isinstance(val, FrozenDict):
        return val
    if isinstance(val, Mapping):
        return FrozenDict(val)
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_param(x) for x in val)
    if isinstance(val, (set, frozenset)):
        return frozenset(_freeze_param(x) for x in val)
    return val


class FrozenDict(TMapping[str, Any]):
    """An immutable, hashable, pickleable mapping for filter rule parameters."""

    __slots__ = ("_data", "_hash")

    def __init__(
        self,
        data: Optional[Union[TMapping[str, Any], Iterable[tuple[str, Any]]]] = None,
        **kwargs: Any,
    ) -> None:
        raw = dict(data or {}, **kwargs) if data is not None else dict(**kwargs)
        for k in raw:
            if not isinstance(k, str):
                raise TypeError(f"FilterRuleSpec parameter keys must be strings, got {type(k).__name__}: {k!r}")
        object.__setattr__(
            self,
            "_data",
            {k: _freeze_param(v) for k, v in raw.items()},
        )
        object.__setattr__(self, "_hash", None)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TMapping):
            if len(self) != len(other):
                return False
            for k, v in self.items():
                if k not in other or other[k] != v:
                    return False
            return True
        return False

    def __ne__(self, other: Any) -> bool:
        return not (self == other)

    def __hash__(self) -> int:
        h = self._hash
        if h is None:
            try:
                h = hash(frozenset(self._data.items()))
            except TypeError as err:
                raise TypeError(f"Unhashable element in '{type(self).__name__}': {err}") from err
            object.__setattr__(self, "_hash", h)
        return h

    def __reduce__(self) -> tuple[Any, ...]:
        return (FrozenDict, (self._data,))

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def __copy__(self) -> "FrozenDict":
        return self

    def __deepcopy__(self, memo: Any) -> "FrozenDict":
        return self

    def copy(self) -> "FrozenDict":
        return self

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError(f"'{type(self).__name__}' object does not support item assignment")

    def __delitem__(self, key: Any) -> None:
        raise TypeError(f"'{type(self).__name__}' object does not support item deletion")

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(f"'{type(self).__name__}' object is immutable")

    def popitem(self) -> Any:
        raise TypeError(f"'{type(self).__name__}' object is immutable")

    def clear(self) -> None:
        raise TypeError(f"'{type(self).__name__}' object is immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(f"'{type(self).__name__}' object is immutable")

    def setdefault(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(f"'{type(self).__name__}' object is immutable")


@dataclass(frozen=True)
class FilterRuleSpec:
    """Specification for a single leaf filter rule.
    
    Can compare a field against a constant value, or against another column (field2),
    or evaluate a domain-specific condition type with dynamic parameters.
    """
    field: str
    op: FilterOperator = FilterOperator.EQ
    value: Any = None
    field2: Optional[str] = None
    is_negated: bool = False
    condition_type: Optional[str] = None
    params: TMapping[str, Any] = field(default_factory=FrozenDict)
    # Backward compatibility attributes (automatically synced with params)
    timeframe: Optional[str] = None
    p1: Optional[int] = None
    p2: Optional[int] = None
    state: Optional[str] = None
    lookback: Optional[int] = None

    def __post_init__(self) -> None:
        p_dict = dict(self.params) if self.params else {}

        # 1. Reconcile conflicts between legacy attributes and params
        if self.timeframe is not None and "timeframe" in p_dict:
            tf_legacy = str(self.timeframe).strip().upper()
            tf_param = str(p_dict["timeframe"]).strip().upper()
            if tf_legacy != tf_param:
                raise ValueError(
                    f"Conflicting 'timeframe' parameter in FilterRuleSpec: legacy '{self.timeframe}' != params['timeframe'] '{p_dict['timeframe']}'"
                )
            p_dict["timeframe"] = self.timeframe
        if self.p1 is not None and "p1" in p_dict:
            if self.p1 != p_dict["p1"]:
                raise ValueError(
                    f"Conflicting 'p1' parameter in FilterRuleSpec: legacy '{self.p1}' != params['p1'] '{p_dict['p1']}'"
                )
        if self.p2 is not None and "p2" in p_dict:
            if self.p2 != p_dict["p2"]:
                raise ValueError(
                    f"Conflicting 'p2' parameter in FilterRuleSpec: legacy '{self.p2}' != params['p2'] '{p_dict['p2']}'"
                )
        if self.state is not None and "state" in p_dict:
            st_legacy = str(self.state).strip().upper()
            st_param = str(p_dict["state"]).strip().upper()
            if st_legacy != st_param:
                raise ValueError(
                    f"Conflicting 'state' parameter in FilterRuleSpec: legacy '{self.state}' != params['state'] '{p_dict['state']}'"
                )
            p_dict["state"] = self.state
        if self.lookback is not None and "lookback" in p_dict:
            if self.lookback != p_dict["lookback"]:
                raise ValueError(
                    f"Conflicting 'lookback' parameter in FilterRuleSpec: legacy '{self.lookback}' != params['lookback'] '{p_dict['lookback']}'"
                )

        # 2. Populate missing entries in params from legacy fields
        if self.timeframe is not None and "timeframe" not in p_dict:
            p_dict["timeframe"] = self.timeframe
        if self.p1 is not None and "p1" not in p_dict:
            p_dict["p1"] = self.p1
        if self.p2 is not None and "p2" not in p_dict:
            p_dict["p2"] = self.p2
        if self.state is not None and "state" not in p_dict:
            p_dict["state"] = self.state
        if self.lookback is not None and "lookback" not in p_dict:
            p_dict["lookback"] = self.lookback

        # 3. Populate missing legacy fields from params
        if self.timeframe is None and "timeframe" in p_dict:
            object.__setattr__(self, "timeframe", p_dict["timeframe"])
        if self.p1 is None and "p1" in p_dict:
            object.__setattr__(self, "p1", p_dict["p1"])
        if self.p2 is None and "p2" in p_dict:
            object.__setattr__(self, "p2", p_dict["p2"])
        if self.state is None and "state" in p_dict:
            object.__setattr__(self, "state", p_dict["state"])
        if self.lookback is None and "lookback" in p_dict:
            object.__setattr__(self, "lookback", p_dict["lookback"])

        object.__setattr__(self, "params", FrozenDict(p_dict))


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


class ScreeningCancelledError(Exception):
    """Raised when an active screening operation is cancelled by caller or user."""
    pass


class IConditionEvaluator(ABC):
    """Contract for modular condition evaluators in the qualification filter engine."""

    @abstractmethod
    def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
        """Evaluate whether a single security record satisfies the rule condition.

        Returns:
            True if the record satisfies the condition.
            False if the record was evaluated and does not satisfy the condition.
            None if the condition cannot be evaluated (e.g. missing data, uncomputed
                 indicator, or insufficient history). An unevaluated condition never
                 satisfies a filter, even under negation.
        """
        pass

    @abstractmethod
    def describe(self, rule: FilterRuleSpec) -> str:
        """Generate a human-readable explanation description for this rule."""
        pass


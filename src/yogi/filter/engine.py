"""Filter Engine — Boolean qualification criteria ("Does it qualify?").

Evaluates qualification rules against securities records and generates
funnel step telemetry and explanation sentences.
"""

import math
from typing import Any, Mapping, Optional, Sequence, Union

from yogi.core.contracts.filter import (
    FilterEvaluationResult,
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    FilterStepMetric,
    IConditionEvaluator,
    IFilterRule,
)


def _to_float(v: Any) -> Optional[float]:
    """Safely convert value to float, excluding booleans and NaN."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _is_blank(v: Any) -> bool:
    """Check if a value is missing, empty string, or NaN."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if isinstance(v, (float, int)) and not isinstance(v, bool):
        if math.isnan(v):
            return True
    return False


def _eval_operator(op: Union[FilterOperator, str], val: Any, target_val: Any) -> bool:
    """Evaluate a single binary or unary operator between val and target_val."""
    op_str = op.value if isinstance(op, FilterOperator) else str(op)

    if op_str == FilterOperator.BLANK.value:
        return _is_blank(val)

    if op_str == FilterOperator.NOT_BLANK.value:
        return not _is_blank(val)

    if op_str == FilterOperator.CONTAINS.value:
        if val is None or target_val is None:
            return False
        return str(target_val).upper() in str(val).upper()

    if op_str == FilterOperator.IN.value:
        if val is None:
            return False
        candidates = target_val if isinstance(target_val, (list, tuple, set)) else [target_val]
        candidates_str = {str(c).strip().upper() for c in candidates}
        return str(val).strip().upper() in candidates_str

    if op_str == FilterOperator.NOT_IN.value:
        if val is None:
            return True
        candidates = target_val if isinstance(target_val, (list, tuple, set)) else [target_val]
        candidates_str = {str(c).strip().upper() for c in candidates}
        return str(val).strip().upper() not in candidates_str

    if op_str == FilterOperator.BETWEEN.value:
        if val is None or not isinstance(target_val, (list, tuple)) or len(target_val) < 2:
            return False
        val_f = _to_float(val)
        lo_f = _to_float(target_val[0])
        hi_f = _to_float(target_val[1])
        if val_f is None or lo_f is None or hi_f is None:
            return False
        return lo_f <= val_f <= hi_f

    if op_str == FilterOperator.EQ.value:
        if val is None and target_val is None:
            return True
        if val is None or target_val is None:
            return False
        val_f = _to_float(val)
        tgt_f = _to_float(target_val)
        if val_f is not None and tgt_f is not None:
            return val_f == tgt_f
        if isinstance(val, str) or isinstance(target_val, str):
            return str(val).strip().upper() == str(target_val).strip().upper()
        return val == target_val

    if op_str == FilterOperator.NEQ.value:
        return not _eval_operator(FilterOperator.EQ, val, target_val)

    # Numeric inequality operators
    val_f = _to_float(val)
    tgt_f = _to_float(target_val)
    if val_f is None or tgt_f is None:
        return False

    if op_str == FilterOperator.GT.value:
        return val_f > tgt_f
    if op_str == FilterOperator.GTE.value:
        return val_f >= tgt_f
    if op_str == FilterOperator.LT.value:
        return val_f < tgt_f
    if op_str == FilterOperator.LTE.value:
        return val_f <= tgt_f

    return False


def _tri_and(values: Sequence[Optional[bool]]) -> Optional[bool]:
    """Kleene 3-valued logic AND (conjunction)."""
    if any(v is False for v in values):
        return False
    if any(v is None for v in values):
        return None
    return True


def _tri_or(values: Sequence[Optional[bool]]) -> Optional[bool]:
    """Kleene 3-valued logic OR (disjunction)."""
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


def _tri_not(val: Optional[bool]) -> Optional[bool]:
    """Kleene 3-valued logic NOT (negation)."""
    if val is None:
        return None
    return not val


def get_default_condition_evaluators() -> dict[str, IConditionEvaluator]:
    """Return standard production condition evaluators."""
    from yogi.filter.evaluators import EmaConditionEvaluator

    return {"ema": EmaConditionEvaluator()}


def create_default_filter_engine(
    evaluators: Optional[Mapping[str, IConditionEvaluator]] = None,
) -> "FilterEngine":
    """Construct and return a FilterEngine populated with default evaluators and optional extras."""
    engine = FilterEngine()
    if evaluators:
        for c_type, evaluator in evaluators.items():
            engine.register_evaluator(c_type, evaluator)
    return engine


class FilterEngine(IFilterRule):
    """Qualification rule evaluation engine.
    
    Evaluates leaf rules and nested filter groups across tabular mapping records,
    providing funnel step metrics and human-readable explanation sentences.
    """

    def __init__(self, evaluators: Optional[Mapping[str, IConditionEvaluator]] = None) -> None:
        self._evaluators: dict[str, IConditionEvaluator] = {}
        if evaluators is not None:
            for c_type, evaluator in evaluators.items():
                self.register_evaluator(c_type, evaluator)
        else:
            for c_type, evaluator in get_default_condition_evaluators().items():
                self.register_evaluator(c_type, evaluator)

    def register_evaluator(self, condition_type: str, evaluator: IConditionEvaluator) -> None:
        """Register a modular condition evaluator for a specific condition type.

        Policy:
        - If condition_type is previously unregistered: succeeds.
        - If condition_type is registered with the exact same evaluator instance: no-op (idempotent).
        - If condition_type is registered with a different evaluator: raises ValueError and preserves original.

        Raises:
            ValueError: If condition_type is empty or already registered with a different evaluator.
            TypeError: If evaluator does not implement IConditionEvaluator.
        """
        if condition_type is None or not str(condition_type).strip():
            raise ValueError("condition_type must be a non-empty string")
        norm_key = str(condition_type).strip().lower()

        if not isinstance(evaluator, IConditionEvaluator):
            raise TypeError(
                f"Evaluator for '{norm_key}' must implement IConditionEvaluator, got {type(evaluator).__name__}"
            )

        if norm_key in self._evaluators:
            if self._evaluators[norm_key] is evaluator:
                return  # Safe idempotent re-registration of the exact same instance
            raise ValueError(
                f"Condition evaluator for '{norm_key}' is already registered with {type(self._evaluators[norm_key]).__name__}"
            )

        self._evaluators[norm_key] = evaluator

    def has_evaluator(self, condition_type: str) -> bool:
        """Check if a condition evaluator is registered for condition_type."""
        if condition_type is None:
            return False
        return str(condition_type).strip().lower() in self._evaluators

    def get_evaluator(self, condition_type: str) -> Optional[IConditionEvaluator]:
        """Retrieve the registered evaluator for condition_type, or None."""
        if condition_type is None:
            return None
        return self._evaluators.get(str(condition_type).strip().lower())

    def evaluate(
        self,
        records: Mapping[str, Mapping[str, Any]],
        spec: Union[FilterRuleSpec, FilterGroupSpec],
    ) -> FilterEvaluationResult:
        """Evaluate qualification rules against records and return matches and funnel steps."""
        if isinstance(spec, FilterRuleSpec):
            group_spec = FilterGroupSpec(rules=[spec])
        elif isinstance(spec, FilterGroupSpec):
            group_spec = spec
        else:
            raise TypeError(f"Expected FilterRuleSpec or FilterGroupSpec, got {type(spec).__name__}")

        symbols = list(records.keys())
        matches, steps, explanation = self._eval_group(records, group_spec, depth=0)
        matching_symbols = [s for s in symbols if matches.get(s) is True]

        return FilterEvaluationResult(
            universe_size=len(records),
            matched_count=len(matching_symbols),
            matching_symbols=matching_symbols,
            steps=steps,
            explanation=explanation,
        )

    def _eval_leaf(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
        """Evaluate a single leaf rule on a record returning True, False, or None."""
        if rule.condition_type is not None:
            evaluator = self.get_evaluator(rule.condition_type)
            if evaluator is not None:
                matched = evaluator.evaluate(record, rule)
                if matched is None:
                    return None
                return not matched if rule.is_negated else matched
            raise ValueError(f"No condition evaluator registered for condition_type '{rule.condition_type}'")

        val = record.get(rule.field)

        if rule.field2 is not None:
            target_val = record.get(rule.field2)
        else:
            target_val = rule.value

        res = _eval_operator(rule.op, val, target_val)
        return not res if rule.is_negated else res

    def _rule_description(self, rule: FilterRuleSpec) -> str:
        """Generate human-readable explanation for a single leaf rule."""
        if rule.condition_type is not None:
            evaluator = self.get_evaluator(rule.condition_type)
            if evaluator is not None:
                desc = evaluator.describe(rule)
                return f"NOT ({desc})" if rule.is_negated else desc
            desc = f"{rule.condition_type} {rule.field} {rule.value}".strip()
            return f"NOT ({desc})" if rule.is_negated else desc

        op_str = rule.op.value if isinstance(rule.op, FilterOperator) else str(rule.op)
        f = rule.field

        if rule.field2 is not None:
            desc = f"{f} {op_str} {rule.field2}"
        elif op_str == FilterOperator.BLANK.value:
            desc = f"{f} is blank"
        elif op_str == FilterOperator.NOT_BLANK.value:
            desc = f"{f} is not blank"
        elif op_str in (FilterOperator.IN.value, FilterOperator.NOT_IN.value):
            v = list(rule.value) if isinstance(rule.value, (list, tuple, set)) else [rule.value]
            desc = f"{f} {op_str} {v}"
        elif op_str == FilterOperator.BETWEEN.value:
            lo, hi = (list(rule.value) + [None, None])[:2] if isinstance(rule.value, (list, tuple)) else (None, None)
            desc = f"{f} between {lo} and {hi}"
        elif op_str == FilterOperator.CONTAINS.value:
            desc = f"{f} contains {rule.value}"
        else:
            desc = f"{f} {op_str} {rule.value}"

        return f"NOT ({desc})" if rule.is_negated else desc

    def _eval_group(
        self,
        records: Mapping[str, Mapping[str, Any]],
        group: FilterGroupSpec,
        depth: int = 0,
    ) -> tuple[dict[str, Optional[bool]], list[FilterStepMetric], str]:
        """Recursively evaluate a FilterGroupSpec preserving tri-state evaluation."""
        symbols = list(records.keys())

        if not group.rules:
            # Empty rules evaluate to all True
            res: dict[str, Optional[bool]] = {s: True for s in symbols}
            if group.is_negated:
                res = {s: False for s in symbols}
            return res, [], "everything"

        steps: list[FilterStepMetric] = []
        rule_results: list[dict[str, Optional[bool]]] = []
        labels: list[str] = []

        for r in group.rules:
            if isinstance(r, FilterGroupSpec):
                sub_res, _, sub_desc = self._eval_group(records, r, depth=depth + 1)
                rule_results.append(sub_res)
                label = f"({sub_desc})"
                labels.append(label)
                if depth == 0:
                    passing = sum(1 for m in sub_res.values() if m is True)
                    steps.append(FilterStepMetric(rule_description=label, passing_count=passing))
            elif isinstance(r, FilterRuleSpec):
                leaf_res = {s: self._eval_leaf(records[s], r) for s in symbols}
                rule_results.append(leaf_res)
                label = self._rule_description(r)
                labels.append(label)
                if depth == 0:
                    passing = sum(1 for m in leaf_res.values() if m is True)
                    steps.append(FilterStepMetric(rule_description=label, passing_count=passing))
            else:
                raise TypeError(f"Unknown rule type in FilterGroupSpec: {type(r).__name__}")

        match_mode = str(group.match).lower()
        if match_mode == "all":
            combined = {
                s: _tri_and([rr[s] for rr in rule_results])
                for s in symbols
            }
            joiner = " AND "
        else:
            combined = {
                s: _tri_or([rr[s] for rr in rule_results])
                for s in symbols
            }
            joiner = " OR "

        explanation = joiner.join(labels)
        if group.is_negated:
            combined = {s: _tri_not(m) for s, m in combined.items()}
            explanation = f"NOT ({explanation})"

        return combined, steps, explanation

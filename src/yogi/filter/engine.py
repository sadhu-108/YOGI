"""Filter Engine — Boolean qualification criteria ("Does it qualify?").

Evaluates qualification rules against securities records and generates
funnel step telemetry and explanation sentences.
"""

import math
from typing import Any, Mapping, Optional, Union

from yogi.core.contracts.filter import (
    FilterEvaluationResult,
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    FilterStepMetric,
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


class FilterEngine(IFilterRule):
    """Qualification rule evaluation engine.
    
    Evaluates leaf rules and nested filter groups across tabular mapping records,
    providing funnel step metrics and human-readable explanation sentences.
    """

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
        matching_symbols = [s for s in symbols if matches.get(s, False)]

        return FilterEvaluationResult(
            universe_size=len(records),
            matched_count=len(matching_symbols),
            matching_symbols=matching_symbols,
            steps=steps,
            explanation=explanation,
        )

    def _eval_leaf(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> bool:
        """Evaluate a single leaf rule on a record."""
        val = record.get(rule.field)

        if rule.field2 is not None:
            target_val = record.get(rule.field2)
        else:
            target_val = rule.value

        res = _eval_operator(rule.op, val, target_val)
        return not res if rule.is_negated else res

    def _rule_description(self, rule: FilterRuleSpec) -> str:
        """Generate human-readable explanation for a single leaf rule."""
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
    ) -> tuple[dict[str, bool], list[FilterStepMetric], str]:
        """Recursively evaluate a FilterGroupSpec."""
        symbols = list(records.keys())

        if not group.rules:
            # Empty rules evaluate to all True
            res = {s: True for s in symbols}
            if group.is_negated:
                res = {s: False for s in symbols}
            return res, [], "everything"

        steps: list[FilterStepMetric] = []
        rule_results: list[dict[str, bool]] = []
        labels: list[str] = []

        for r in group.rules:
            if isinstance(r, FilterGroupSpec):
                sub_res, _, sub_desc = self._eval_group(records, r, depth=depth + 1)
                rule_results.append(sub_res)
                label = f"({sub_desc})"
                labels.append(label)
                if depth == 0:
                    passing = sum(1 for m in sub_res.values() if m)
                    steps.append(FilterStepMetric(rule_description=label, passing_count=passing))
            elif isinstance(r, FilterRuleSpec):
                leaf_res = {s: self._eval_leaf(records[s], r) for s in symbols}
                rule_results.append(leaf_res)
                label = self._rule_description(r)
                labels.append(label)
                if depth == 0:
                    passing = sum(1 for m in leaf_res.values() if m)
                    steps.append(FilterStepMetric(rule_description=label, passing_count=passing))
            else:
                raise TypeError(f"Unknown rule type in FilterGroupSpec: {type(r).__name__}")

        match_mode = str(group.match).lower()
        if match_mode == "all":
            combined = {
                s: all(rr[s] for rr in rule_results)
                for s in symbols
            }
            joiner = " AND "
        else:
            combined = {
                s: any(rr[s] for rr in rule_results)
                for s in symbols
            }
            joiner = " OR "

        explanation = joiner.join(labels)
        if group.is_negated:
            combined = {s: not m for s, m in combined.items()}
            explanation = f"NOT ({explanation})"

        return combined, steps, explanation

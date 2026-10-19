"""Modular Condition Evaluators for Filter Engine."""

from typing import Any, Mapping, Optional

from yogi.core.contracts.filter import FilterRuleSpec, IConditionEvaluator


class EmaConditionEvaluator(IConditionEvaluator):
    """Condition evaluator for Exponential Moving Average (EMA) rules."""

    def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
        """Evaluate an EMA rule on a single record.

        Returns:
            True if the record satisfies the condition.
            False if the record was evaluated and does not satisfy the condition.
            None if the condition cannot be evaluated (e.g. missing data, uncomputed
                 indicator, or insufficient history 'na' state).
        Negation is handled by the calling FilterEngine.
        """
        dyn_val = record.get(rule.field)
        if dyn_val is None and rule.timeframe and rule.p1 and rule.p2:
            dyn_val = record.get(f"EMA_{rule.timeframe}_{rule.p1}_{rule.p2}")
        if dyn_val is None:
            return None

        target_state = (rule.state or rule.value or (rule.params.get("state") if rule.params else None) or "").strip().upper()
        if isinstance(dyn_val, dict):
            if dyn_val.get("state") == "na":
                return True if target_state == "NA" else None
            if target_state == "UP":
                return bool(dyn_val.get("is_up", False))
            elif target_state == "DOWN":
                return bool(dyn_val.get("is_down", False))
            elif target_state == "UPCUT":
                return bool(dyn_val.get("is_upcut", False))
            elif target_state == "DOWNCUT":
                return bool(dyn_val.get("is_downcut", False))
            return False
        elif isinstance(dyn_val, str):
            st = dyn_val.strip().upper()
            if st == "NA":
                return True if target_state == "NA" else None
            if target_state == "UP":
                return st in ("UP", "UPCUT", "YES")
            elif target_state == "DOWN":
                return st in ("DOWN", "DOWNCUT", "NO")
            elif target_state == "UPCUT":
                return st == "UPCUT"
            elif target_state == "DOWNCUT":
                return st == "DOWNCUT"
            return st == target_state
        return None

    def describe(self, rule: FilterRuleSpec) -> str:
        """Generate human-readable explanation for an EMA rule."""
        tf_names = {
            "D": "Daily",
            "W": "Weekly",
            "M": "Monthly",
            "Q": "Quarterly",
            "H": "Half-Yearly",
            "Y": "Yearly",
        }
        tf = rule.timeframe or (rule.params.get("timeframe") if rule.params else None) or ""
        tf_lbl = tf_names.get(tf, tf)
        p1 = rule.p1 if rule.p1 is not None else (rule.params.get("p1") if rule.params else None)
        p2 = rule.p2 if rule.p2 is not None else (rule.params.get("p2") if rule.params else None)
        st = (rule.state or rule.value or (rule.params.get("state") if rule.params else None) or "").upper()
        return f"{tf_lbl} EMA({p1}, {p2}) {st}".strip()

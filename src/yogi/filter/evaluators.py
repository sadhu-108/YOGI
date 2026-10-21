import math
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
        if dyn_val is None and rule.timeframe:
            tf = str(rule.timeframe).upper()
            p1 = rule.p1 if rule.p1 is not None else (rule.params.get("p1") if rule.params else None)
            p2 = rule.p2 if rule.p2 is not None else (rule.params.get("p2") if rule.params else None)
            params = rule.params or {}
            if (p1, p2) in ((3, 5), (5, 3)) and tf in ("D", "W", "M", "Q", "H", "Y") and not params.get("closed_candle_only", False):
                dyn_val = record.get(f"EMA_{tf}")
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


class RocConditionEvaluator(IConditionEvaluator):
    """Condition evaluator for Rate of Change (ROC) rules."""

    BUCKET_INTERVALS: dict[str, str] = {
        "lt_10": "lt_10",
        "less_than_10": "lt_10",
        "<10": "lt_10",
        "less than 10%": "lt_10",
        "10_to_20": "10_to_20",
        "10-20": "10_to_20",
        "10% to 20%": "10_to_20",
        "20_to_30": "20_to_30",
        "20-30": "20_to_30",
        "20% to 30%": "20_to_30",
        "30_to_40": "30_to_40",
        "30-40": "30_to_40",
        "30% to 40%": "30_to_40",
        "40_to_50": "40_to_50",
        "40-50": "40_to_50",
        "40% to 50%": "40_to_50",
        "50_to_60": "50_to_60",
        "50-60": "50_to_60",
        "50% to 60%": "50_to_60",
        "60_to_70": "60_to_70",
        "60-70": "60_to_70",
        "60% to 70%": "60_to_70",
        "70_to_80": "70_to_80",
        "70-80": "70_to_80",
        "70% to 80%": "70_to_80",
        "80_to_90": "80_to_90",
        "80-90": "80_to_90",
        "80% to 90%": "80_to_90",
        "90_to_100": "90_to_100",
        "90-100": "90_to_100",
        "90% to 100%": "90_to_100",
        "gt_100": "gt_100",
        "more_than_100": "gt_100",
        ">100": "gt_100",
        "more than 100%": "gt_100",
    }

    def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
        """Evaluate an ROC rule on a single record.

        Returns:
            True if the record satisfies the condition.
            False if the record was evaluated and does not satisfy the condition
                  (including negative ROC values, which match none of the 11 buckets).
            None if the condition cannot be evaluated (e.g. missing data, uncomputed
                 indicator, non-finite values, or insufficient history).
        Negation is handled by the calling FilterEngine.
        """
        val = record.get(rule.field)
        if val is None and rule.params and "period" in rule.params:
            p = str(rule.params["period"]).upper()
            val = record.get(f"ROC_{p}")

        if val is None:
            return None

        roc_val = None
        if isinstance(val, dict):
            roc_val = val.get("roc")
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            roc_val = float(val)

        if roc_val is None:
            return None

        if isinstance(roc_val, bool) or not isinstance(roc_val, (int, float)):
            return None

        roc_f = float(roc_val)
        if math.isnan(roc_f) or math.isinf(roc_f):
            return None

        # Negative ROC values do not match any of the 11 supported non-negative buckets
        if roc_f < 0.0:
            return False

        # Determine target bucket
        bucket_raw = None
        if rule.params and "bucket" in rule.params:
            bucket_raw = rule.params["bucket"]
        elif rule.value is not None:
            bucket_raw = rule.value
        elif rule.state is not None:
            bucket_raw = rule.state

        if not bucket_raw:
            bucket_raw = "gt_100"

        canonical_bucket = self.BUCKET_INTERVALS.get(str(bucket_raw).strip().lower())
        if not canonical_bucket:
            return False

        if canonical_bucket == "lt_10":
            return 0.0 <= roc_f < 10.0
        elif canonical_bucket == "10_to_20":
            return 10.0 <= roc_f < 20.0
        elif canonical_bucket == "20_to_30":
            return 20.0 <= roc_f < 30.0
        elif canonical_bucket == "30_to_40":
            return 30.0 <= roc_f < 40.0
        elif canonical_bucket == "40_to_50":
            return 40.0 <= roc_f < 50.0
        elif canonical_bucket == "50_to_60":
            return 50.0 <= roc_f < 60.0
        elif canonical_bucket == "60_to_70":
            return 60.0 <= roc_f < 70.0
        elif canonical_bucket == "70_to_80":
            return 70.0 <= roc_f < 80.0
        elif canonical_bucket == "80_to_90":
            return 80.0 <= roc_f < 90.0
        elif canonical_bucket == "90_to_100":
            return 90.0 <= roc_f <= 100.0
        elif canonical_bucket == "gt_100":
            return roc_f > 100.0

        return False

    def describe(self, rule: FilterRuleSpec) -> str:
        """Generate human-readable explanation for an ROC rule."""
        period_names = {
            "current_month": "Current Month",
            "last_month": "Last Month",
            "last_to_last_month": "Last to Last Month",
            "current_quarter": "Current Quarter",
            "last_quarter": "Last Quarter",
            "current_half_year": "Current Half-Year",
            "ytd": "YTD / Current Year",
            "last_year": "Last Year",
            "preceding_last_4_years": "Preceding Last 4 Years",
            "avg_preceding_last_5_years": "Average of Preceding Last 5 Years",
        }
        bucket_labels = {
            "lt_10": "< 10%",
            "10_to_20": "10% to 20%",
            "20_to_30": "20% to 30%",
            "30_to_40": "30% to 40%",
            "40_to_50": "40% to 50%",
            "50_to_60": "50% to 60%",
            "60_to_70": "60% to 70%",
            "70_to_80": "70% to 80%",
            "80_to_90": "80% to 90%",
            "90_to_100": "90% to 100%",
            "gt_100": "> 100%",
        }
        p = rule.params.get("period") if rule.params else None
        if not p and rule.field and rule.field.upper().startswith("ROC_"):
            p = rule.field[4:].lower()

        b = (rule.params.get("bucket") if rule.params else None) or rule.value or rule.state or "gt_100"
        canon_b = self.BUCKET_INTERVALS.get(str(b).strip().lower(), str(b).strip().lower())

        p_lbl = period_names.get(str(p).strip().lower(), str(p)) if p else "ROC"
        b_lbl = bucket_labels.get(canon_b, str(b))
        return f"{p_lbl} ROC {b_lbl}".strip()

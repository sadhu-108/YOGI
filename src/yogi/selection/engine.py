"""Selection Engine — Rank-based cutoffs and cohort survival ("Does its rank qualify?").

Applies rank-based threshold cutoffs and sustained-rank survival rules.
Answers: "Does its rank qualify for inclusion?"
"""

import math
from typing import Any, Mapping, Optional, Sequence

from yogi.core.contracts.selection import (
    ISelectionRule,
    RankCutoffSpec,
    SelectionMode,
    SelectionResult,
)

# Common timeframe to rank column aliases
TIMEFRAME_RANK_ALIASES: dict[str, str] = {
    "M_CUR": "RANK_M",
    "M": "RANK_M",
    "YROC": "RANK_Y",
    "Y": "RANK_Y",
    "WROC": "RANK_W",
    "W": "RANK_W",
    "QROC": "RANK_Q",
    "Q": "RANK_Q",
    "HROC": "RANK_H",
    "H": "RANK_H",
    "DROC": "RANK_D",
    "D": "RANK_D",
    "YTD": "RANK_YTD",
    "ROC_YTD": "RANK_YTD",
    "3M": "RANK_3M",
    "ROC_3M": "RANK_3M",
    "3Y": "RANK_3Y",
    "ROC_3Y": "RANK_3Y",
    "4Y": "RANK_4Y",
    "ROC_4Y": "RANK_4Y",
    "5Y": "RANK_5Y",
    "ROC_5Y": "RANK_5Y",
    "AVG5Y": "RANK_AVG5Y",
    "ROC_AVG5Y": "RANK_AVG5Y",
}

TIMEFRAME_REVERSE_RANK_ALIASES: dict[str, tuple[str, ...]] = {
    "RANK_M": ("RANK_M_CUR", "RANK_MROC", "RANK_M"),
    "RANK_Y": ("RANK_YROC", "RANK_Y"),
    "RANK_W": ("RANK_WROC", "RANK_W"),
    "RANK_D": ("RANK_DROC", "RANK_D"),
    "RANK_Q": ("RANK_Q_CUR", "RANK_QROC", "RANK_Q"),
    "RANK_H": ("RANK_H_CUR", "RANK_HROC", "RANK_H"),
    "RANK_YTD": ("RANK_YTD", "YTD"),
    "RANK_3M": ("RANK_3M", "3M"),
    "RANK_3Y": ("RANK_3Y", "3Y"),
    "RANK_4Y": ("RANK_4Y", "4Y"),
    "RANK_5Y": ("RANK_5Y", "5Y"),
    "RANK_AVG5Y": ("RANK_AVG5Y", "AVG5Y"),
}


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


def _resolve_rank(record: Mapping[str, Any], metric: str) -> Optional[float]:
    """Resolve ordinal rank from record, prioritizing rank columns over raw return values."""
    # Priority 1: Injected rank column (e.g. metric="SPD_M" -> "RANK_SPD_M", metric="YROC" -> "RANK_YROC")
    if not metric.startswith("RANK_"):
        val = record.get(f"RANK_{metric}")
        if val is not None:
            f = _to_float(val)
            if f is not None:
                return f

    # Priority 2: Forward timeframe rank aliases (e.g. metric="M_CUR" -> "RANK_M")
    alias = TIMEFRAME_RANK_ALIASES.get(metric)
    if alias and alias in record:
        f = _to_float(record[alias])
        if f is not None:
            return f

    # Priority 3: Exact metric name if it is already a rank (e.g. metric="RANK_M")
    if metric.startswith("RANK_"):
        val = record.get(metric)
        if val is not None:
            f = _to_float(val)
            if f is not None:
                return f

        # Priority 4: Reverse timeframe rank aliases (e.g. metric="RANK_M" -> "RANK_M_CUR")
        if metric in TIMEFRAME_REVERSE_RANK_ALIASES:
            for alt_key in TIMEFRAME_REVERSE_RANK_ALIASES[metric]:
                if alt_key in record:
                    f = _to_float(record[alt_key])
                    if f is not None:
                        return f

    return None


class SelectionEngine(ISelectionRule):
    """Rank cutoff evaluation engine.
    
    Evaluates rank thresholds across ranked records adhering to SelectionMode (ALL / ANY).
    Decoupled strictly from presentation row limits (query.limit) and relative ordering (RankingEngine).
    Preserves the authoritative incoming order of ranked records without sorting.
    """

    def select(
        self,
        ranked_records: Mapping[str, Mapping[str, Any]],
        cutoffs: Sequence[RankCutoffSpec],
        mode: SelectionMode = SelectionMode.ALL,
    ) -> SelectionResult:
        """Select ranked records based on rank cutoff criteria."""
        total_evaluated = len(ranked_records)

        if not cutoffs:
            symbols = list(ranked_records.keys())
            return SelectionResult(
                selected_symbols=symbols,
                total_evaluated=total_evaluated,
                matched_count=len(symbols),
                spec_summary="ALL",
            )

        selected_symbols: list[str] = []

        for sym, rec in ranked_records.items():
            cutoff_evaluations: list[bool] = [
                self._evaluate_cutoff(rec, cutoff)
                for cutoff in cutoffs
            ]

            if mode == SelectionMode.ALL:
                passed = all(cutoff_evaluations)
            else:
                passed = any(cutoff_evaluations)

            if passed:
                selected_symbols.append(sym)

        # Build human-readable spec summary
        joiner = " AND " if mode == SelectionMode.ALL else " OR "
        spec_summary = joiner.join(
            f"{c.rank_metric} <= {c.max_rank}" + (f" (min_periods={c.min_periods})" if c.min_periods > 1 else "")
            for c in cutoffs
        )

        return SelectionResult(
            selected_symbols=selected_symbols,
            total_evaluated=total_evaluated,
            matched_count=len(selected_symbols),
            spec_summary=spec_summary,
        )

    def _evaluate_cutoff(self, record: Mapping[str, Any], cutoff: RankCutoffSpec) -> bool:
        """Evaluate a single RankCutoffSpec against a ranked record."""
        # 1. Resolve rank value prioritizing rank columns over raw return percentages
        rank_f = _resolve_rank(record, cutoff.rank_metric)
        if rank_f is None:
            return False

        # 2. Check rank threshold
        if rank_f > cutoff.max_rank:
            return False

        # 3. Check sustained-rank periods if min_periods > 1
        if cutoff.min_periods > 1:
            periods_val = (
                record.get(f"{cutoff.rank_metric}_PERIODS")
                or record.get(f"RANK_{cutoff.rank_metric}_PERIODS")
                or record.get("SUSTAINED_PERIODS")
            )
            periods_f = _to_float(periods_val)
            if periods_f is None or periods_f < cutoff.min_periods:
                return False

        return True

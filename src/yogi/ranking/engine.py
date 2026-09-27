"""Ranking Engine — Relative ordering across metrics ("Where does it stand?").

Establishes relative standing across criteria without filtering or dropping securities.
Supports ASCENDING/DESCENDING order, MIN/DENSE/AVERAGE tie-breaking, missing value handling,
and cohort grouping.
"""

import math
from typing import Any, Mapping, Optional

from yogi.core.contracts.ranking import (
    IRankingRule,
    RankingMethod,
    RankingOrder,
    RankingResult,
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


class RankingEngine(IRankingRule):
    """Relative ordering engine computing ordinal standing without dropping securities.
    
    Adheres strictly to the IRankingRule contract and prototype ranking semantics:
    - 1-based ranks (1 = highest in DESCENDING, lowest in ASCENDING).
    - Ties broken per RankingMethod (default MIN, matching prototype df.rank(method='min')).
    - Secondary deterministic sort on symbol ascending.
    - Missing/NaN values placed last (na_position='last') without dropping records.
    - Optional grouping (e.g. group_by='exchange' or 'sector').
    - Automatic rank_changes calculation for M_CUR relative to M_P1.
    """

    def rank(
        self,
        records: Mapping[str, Mapping[str, Any]],
        metric: str,
        order: RankingOrder = RankingOrder.DESCENDING,
        method: RankingMethod = RankingMethod.MIN,
        group_by: Optional[str] = None,
    ) -> RankingResult:
        """Compute relative rank positions across the provided records."""
        if not records:
            return RankingResult(metric=metric, ranks={}, rank_changes=None, grouped_by=group_by)

        if group_by is not None:
            # Partition into groups
            groups: dict[Any, dict[str, Mapping[str, Any]]] = {}
            for sym, rec in records.items():
                g_key = rec.get(group_by)
                if g_key not in groups:
                    groups[g_key] = {}
                groups[g_key][sym] = rec

            merged_ranks: dict[str, int] = {}
            merged_changes: Optional[dict[str, int]] = {} if metric == "M_CUR" else None

            for g_key, group_records in groups.items():
                g_ranks, g_changes = self._rank_cohort(group_records, metric, order, method)
                merged_ranks.update(g_ranks)
                if merged_changes is not None and g_changes is not None:
                    merged_changes.update(g_changes)

            return RankingResult(
                metric=metric,
                ranks=merged_ranks,
                rank_changes=merged_changes if merged_changes else None,
                grouped_by=group_by,
            )

        ranks, rank_changes = self._rank_cohort(records, metric, order, method)
        return RankingResult(
            metric=metric,
            ranks=ranks,
            rank_changes=rank_changes,
            grouped_by=None,
        )

    def _rank_cohort(
        self,
        records: Mapping[str, Mapping[str, Any]],
        metric: str,
        order: RankingOrder,
        method: RankingMethod,
    ) -> tuple[dict[str, int], Optional[dict[str, int]]]:
        """Rank a single unified cohort of records."""
        valid_items: list[tuple[str, float]] = []
        missing_symbols: list[str] = []

        for sym, rec in records.items():
            val_f = _to_float(rec.get(metric))
            if val_f is not None:
                valid_items.append((sym, val_f))
            else:
                missing_symbols.append(sym)

        # Deterministic sorting
        # Secondary sort key: symbol ascending
        if order == RankingOrder.DESCENDING:
            valid_items.sort(key=lambda item: (-item[1], item[0]))
        else:
            valid_items.sort(key=lambda item: (item[1], item[0]))

        missing_symbols.sort()

        ranks: dict[str, int] = {}
        n_valid = len(valid_items)

        if n_valid > 0:
            if method == RankingMethod.MIN:
                current_rank = 1
                for i in range(n_valid):
                    if i > 0 and valid_items[i][1] != valid_items[i - 1][1]:
                        current_rank = i + 1
                    ranks[valid_items[i][0]] = current_rank

            elif method == RankingMethod.DENSE:
                current_rank = 1
                for i in range(n_valid):
                    if i > 0 and valid_items[i][1] != valid_items[i - 1][1]:
                        current_rank += 1
                    ranks[valid_items[i][0]] = current_rank

            elif method == RankingMethod.AVERAGE:
                i = 0
                while i < n_valid:
                    j = i
                    while j < n_valid and valid_items[j][1] == valid_items[i][1]:
                        j += 1
                    # 1-based positions from (i + 1) to j
                    avg_rank = int(round(sum(range(i + 1, j + 1)) / (j - i)))
                    for k in range(i, j):
                        ranks[valid_items[k][0]] = avg_rank
                    i = j

        # Assign ranks to missing values placed last
        last_rank = (max(ranks.values()) + 1) if ranks else 1
        for sym in missing_symbols:
            ranks[sym] = last_rank

        # Compute rank_changes if metric is M_CUR and M_P1 exists in records
        rank_changes: Optional[dict[str, int]] = None
        if metric == "M_CUR" and any("M_P1" in rec for rec in records.values()):
            p1_ranks, _ = self._rank_cohort(records, "M_P1", order, method)
            # Positive = climbing (e.g. rank last month was 10, this month is 2 -> 10 - 2 = +8)
            rank_changes = {
                sym: p1_ranks[sym] - ranks[sym]
                for sym in ranks
                if sym in p1_ranks
            }

        return ranks, rank_changes

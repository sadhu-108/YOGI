"""Screening query configuration representing QUALIFY -> ORDER -> SHOW intent."""

from dataclasses import dataclass, field
from typing import Optional, Sequence

from yogi.core.contracts.filter import FilterGroupSpec
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.selection import RankCutoffSpec, SelectionMode


@dataclass(frozen=True)
class ScreeningQuery:
    """User-level screening query intent representing qualification, ordering, and selection.

    Strictly adheres to the QUALIFY -> ORDER -> SHOW pipeline model:
    - QUALIFY: Boolean qualification filter tree (FilterGroupSpec)
    - ORDER:   Relative standing metric and sort direction (ranking_metric, ranking_order)
    - SHOW:    Rank cutoff criteria and survival limits (selection_cutoffs, selection_mode, limit)

    Does NOT contain presentation-column projection (columns), which is the
    exclusive responsibility of the Results Engine (IResultAssembler).
    """
    # QUALIFY
    filter_group: Optional[FilterGroupSpec] = None

    # ORDER
    ranking_metric: Optional[str] = None
    ranking_order: RankingOrder = RankingOrder.DESCENDING

    # SHOW
    selection_cutoffs: Sequence[RankCutoffSpec] = field(default_factory=tuple)
    selection_mode: SelectionMode = SelectionMode.ALL

    # RESULT CARDINALITY / PRESENTATION
    limit: Optional[int] = None

"""Selection Engine Contract — Rank-based cutoffs and cohort survival ("Does its rank qualify?").

Applies rank-based threshold cutoffs and sustained-rank rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class SelectionMode(str, Enum):
    """Mode when multiple rank criteria are provided."""
    ALL = "all"  # Intersection: must qualify on all rank criteria
    ANY = "any"  # Union: qualifies on at least one rank criterion


@dataclass(frozen=True)
class RankCutoffSpec:
    """A rank cutoff rule (e.g. RANK_M <= 100)."""
    rank_metric: str
    max_rank: int
    min_periods: int = 1  # For sustained-rank survival


@dataclass(frozen=True)
class SelectionResult:
    """Result of applying rank selection cutoffs to ranked securities."""
    selected_symbols: Sequence[str]
    total_evaluated: int
    matched_count: int
    spec_summary: str = ""


class ISelectionRule(ABC):
    """The contract for evaluating rank cutoffs and cohort survival.
    
    Migrated from prototype verify_lists.py selection logic.
    Separated from boolean filters to cleanly isolate relative position cutoffs.
    Answers: "Does its rank qualify for inclusion?"
    """

    @abstractmethod
    def select(
        self,
        ranked_records: Mapping[str, Mapping[str, Any]],
        cutoffs: Sequence[RankCutoffSpec],
        mode: SelectionMode = SelectionMode.ALL,
    ) -> SelectionResult:
        """Select ranked records based on rank cutoff criteria."""
        pass

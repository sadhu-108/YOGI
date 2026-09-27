"""Ranking Engine Contract — Relative ordering across metrics ("Where does it stand?").

Establishes relative standing across criteria without filtering or dropping securities.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class RankingOrder(str, Enum):
    """Direction of ranking (highest value = rank 1 vs lowest = rank 1)."""
    DESCENDING = "desc"  # Standard for financial metrics (highest ROC = Rank 1)
    ASCENDING = "asc"


class RankingMethod(str, Enum):
    """Tie-breaking method when two securities have identical values."""
    MIN = "min"          # Matches prototype: df.rank(method="min")
    AVERAGE = "average"
    DENSE = "dense"


@dataclass(frozen=True)
class RankingResult:
    """Result of ranking securities on a specific metric."""
    metric: str
    ranks: Mapping[str, int]  # symbol -> 1-based rank
    rank_changes: Optional[Mapping[str, int]] = None  # symbol -> rank delta (positive = climbing)
    grouped_by: Optional[str] = None


class IRankingRule(ABC):
    """The contract for relative standing evaluation.
    
    Migrated from prototype yogi.core_math.pipeline._add_ranks.
    Solely determines ordering; does not drop securities.
    """

    @abstractmethod
    def rank(
        self,
        records: Mapping[str, Mapping[str, Any]],
        metric: str,
        order: RankingOrder = RankingOrder.DESCENDING,
        method: RankingMethod = RankingMethod.MIN,
        group_by: Optional[str] = None,
    ) -> RankingResult:
        """Compute relative rank positions across the provided records."""
        pass

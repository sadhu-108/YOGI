"""Strategy Engine Contract — Rule composition and mentor preset management.

Answers "How are conditions combined into a strategy/signal?"
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Sequence

from yogi.core.contracts.filter import FilterGroupSpec


@dataclass(frozen=True)
class StrategyValidationResult:
    """Validation report for a strategy definition."""
    is_valid: bool
    problems: Sequence[str] = field(default_factory=list)


@dataclass(frozen=True)
class StrategySpec:
    """Specification of a named strategy.
    
    Migrated from prototype strategies.json and strategy.py.
    Decoupled from presentation sorting and display truncation.
    """
    name: str
    filter_group: FilterGroupSpec
    description: Optional[str] = None
    target_ranking_metric: Optional[str] = None
    target_cutoff_limit: Optional[int] = None
    is_mentor_preset: bool = False


class IStrategy(ABC):
    """The contract for a strategy definition or preset.
    
    Migrated from prototype yogi.screening.strategy.
    Encapsulates rule composition and signal emission.
    """

    @abstractmethod
    def get_spec(self) -> StrategySpec:
        """Return the immutable strategy specification."""
        pass

    @abstractmethod
    def validate(self, available_fields: Sequence[str]) -> StrategyValidationResult:
        """Validate rule field names and operators against available metric definitions."""
        pass

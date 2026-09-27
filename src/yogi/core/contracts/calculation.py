"""Calculation Module Contract — Interface for pure analytical calculations.

Preserves the 4 verified pillars: Bands, Velocity, Impulse, and Trend.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from yogi.core.contracts.market_data import MarketContext


@dataclass(frozen=True)
class CalculationContext:
    """Input context passed to calculation modules."""
    market_context: MarketContext
    bands_lookup: Optional[Mapping[str, float]] = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalculationResult:
    """Standardized output container returned by any ICalcModule.
    
    Contains the calculated metrics keyed by indicator name (e.g. DROC, EMA_W,
    S4, ACCEL_L, IC, BANDST_M, ADX_D).
    """
    symbol: str
    module_name: str
    metrics: Mapping[str, Any]


class ICalcModule(ABC):
    """The contract every analytical calculation module must satisfy.
    
    Required by AGENTS.md for the 4 pillars:
    - bands
    - velocity
    - impulse
    - trend
    """
    name: str
    required_timeframes: Sequence[str] = ("D",)

    @abstractmethod
    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute the calculation on market bars and return structured metrics."""
        pass

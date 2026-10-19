"""Timeframe synthesis contract for multi-timeframe candle construction and market context."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Sequence, Union

from yogi.core.contracts.market_data import MarketBar, MarketContext, Timeframe


class ITimeframeEngine(ABC):
    """The contract for multi-timeframe candle synthesis and MarketContext construction.

    Translates canonical daily bars into higher-order timeframes and packages
    multi-timeframe MarketContext instances for calculation modules.
    """

    @abstractmethod
    def resample(
        self,
        bars: Sequence[MarketBar],
        timeframe: Union[str, Timeframe],
    ) -> Sequence[MarketBar]:
        """Resample daily bars into the specified target timeframe."""
        pass

    @abstractmethod
    def build_context(
        self,
        symbol: str,
        exchange: str,
        daily_bars: Sequence[MarketBar],
        timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
        as_of: Optional[datetime] = None,
        half_year_policy: Optional[str] = None,
    ) -> MarketContext:
        """Construct an immutable MarketContext across requested timeframes."""
        pass

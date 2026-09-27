"""Canonical market data representations and contexts across all data feeds and timeframes."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Sequence


class Timeframe(str, Enum):
    """Supported standard timeframes in YOGI."""
    DAILY = "D"
    WEEKLY = "W"
    MONTHLY = "M"
    QUARTERLY = "Q"
    HALF_YEARLY = "H"
    YEARLY = "Y"


@dataclass(frozen=True)
class MarketBar:
    """Canonical price bar for any timeframe.
    
    Migrated from the prototype's implicit DataFrame columns:
    {"open", "high", "low", "close", "volume"}.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


@dataclass(frozen=True)
class TickData:
    """Live streaming price tick.
    
    Migrated from prototype zerodha_provider.py tick listener signature:
    (symbol, timestamp, last_price, last_traded_quantity).
    """
    symbol: str
    timestamp: datetime
    last_price: float
    last_quantity: int = 0


@dataclass(frozen=True)
class MarketContext:
    """Context holding multi-timeframe bar series for a specific security.
    
    Provides standardized access to bars across timeframes without requiring
    redundant resample passes.
    """
    symbol: str
    exchange: str
    bars_by_timeframe: Mapping[str, Sequence[MarketBar]]
    as_of: Optional[datetime] = None

    def get_bars(self, timeframe: str = "D") -> Sequence[MarketBar]:
        """Return bars for the requested timeframe, or empty sequence if unavailable."""
        return self.bars_by_timeframe.get(timeframe, ())

    def get_closes(self, timeframe: str = "D") -> Sequence[float]:
        """Return closing prices for the requested timeframe."""
        return [b.close for b in self.get_bars(timeframe)]

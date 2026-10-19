"""Data Provider Contract — Interface for external market data sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from yogi.core.contracts.market_data import MarketBar, TickData


@dataclass(frozen=True)
class ProviderHealth:
    """Health check status for an external market data provider."""
    provider: str
    ok: bool
    sample_price: Optional[float] = None
    error: Optional[str] = None


class IDataProvider(ABC):
    """The abstract contract every market data source must satisfy.
    
    Migrated from prototype yogi.data_feed.base.MarketDataProvider.
    Defines abstract interface only; concrete provider logic belongs in data/providers/.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the data provider."""
        pass

    @property
    @abstractmethod
    def supports_intraday(self) -> bool:
        """Whether the provider supports intraday historical queries."""
        pass

    @property
    @abstractmethod
    def supports_live_ticks(self) -> bool:
        """Whether the provider supports real-time tick streaming."""
        pass

    @abstractmethod
    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        """Return the list of tradable symbols for the specified exchange."""
        pass

    @abstractmethod
    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Sequence[MarketBar]:
        """Return historical daily OHLCV bars for a single symbol."""
        pass

    @abstractmethod
    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        """Batch fetch daily history for multiple symbols."""
        pass

    @abstractmethod
    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        """Return the most recent close or traded price for a symbol."""
        pass

    @abstractmethod
    def intraday(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 5,
    ) -> Sequence[MarketBar]:
        """Fetch intraday bars."""
        pass

    @abstractmethod
    def subscribe_ticks(
        self,
        symbols: Sequence[str],
        on_tick: Callable[[TickData], None],
        exchange: str = "NSE",
    ) -> Any:
        """Subscribe to live ticks with a callback."""
        pass

    @abstractmethod
    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        """Return list of trading holiday date strings (YYYY-MM-DD)."""
        pass

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Verify provider connectivity and return health status."""
        pass

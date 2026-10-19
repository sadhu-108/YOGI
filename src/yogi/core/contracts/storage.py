"""Storage and Cache Contracts — Abstract Protocols for Historical Bars and Materialized Datasets."""

from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from yogi.core.contracts.market_data import MarketBar


@runtime_checkable
class IBarsCache(Protocol):
    """Structural protocol for persistent daily market bar storage and retrieval."""

    def save_bars(
        self,
        bars_map: Mapping[str, Sequence[MarketBar]],
        exchange: str = ...,
        provider: str = ...,
    ) -> Optional[Path]:
        """Atomically merge and persist daily market bars across symbols."""
        ...

    def load_bars(
        self,
        exchange: str = ...,
        provider: str = ...,
    ) -> dict[str, Sequence[MarketBar]]:
        """Load and return all cached market bars across symbols for the namespace."""
        ...

    def get_bars_for_symbols(
        self,
        symbols: Sequence[str],
        exchange: str = ...,
        provider: str = ...,
        min_bars: int = ...,
    ) -> tuple[dict[str, Sequence[MarketBar]], list[str]]:
        """Partition requested symbols into usable cached bars and missing symbols."""
        ...

    def clear(
        self,
        exchange: str = ...,
        provider: str = ...,
    ) -> bool:
        """Clear cached bars for the namespace."""
        ...


@runtime_checkable
class IDatasetCache(Protocol):
    """Structural protocol for persistent pre-calculated feature dataset storage."""

    def save(
        self,
        dataset: Mapping[str, Mapping[str, Any]],
        exchange: str = ...,
        provider: str = ...,
        half_year_policy: str = ...,
        historical_years: int = ...,
        metadata: Optional[Mapping[str, Any]] = ...,
    ) -> Optional[Path]:
        """Atomically persist a computed feature dataset with schema envelope."""
        ...

    def load(
        self,
        exchange: str = ...,
        provider: str = ...,
        half_year_policy: Optional[str] = ...,
    ) -> Optional[dict[str, Any]]:
        """Load and validate persisted dataset. Returns None if invalid or missing."""
        ...

    def validate(
        self,
        payload: Any,
        exchange: str = ...,
        provider: str = ...,
        half_year_policy: Optional[str] = ...,
    ) -> bool:
        """Validate payload structure, version compatibility, and policy consistency."""
        ...

    def clear(
        self,
        exchange: str = ...,
        provider: str = ...,
    ) -> bool:
        """Remove cached dataset file for the namespace."""
        ...

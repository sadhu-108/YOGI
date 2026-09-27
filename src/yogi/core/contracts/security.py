"""Security Master Contract — Security identification, categorization, and metadata."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Set


class InstrumentType(str, Enum):
    """Categorization of traded securities, migrated from classify.py."""
    EQ = "EQ"
    ETF = "ETF"
    SME = "SME"
    BE = "BE"
    REIT_INVIT = "REIT_INVIT"
    ILLIQUID = "ILLIQUID"
    UNKNOWN = "UNKNOWN"


class ListingStatus(str, Enum):
    """Listing status of a security."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


@dataclass(frozen=True)
class SecurityMetadata:
    """Canonical security metadata.
    
    Migrated from prototype master.py and meta.py.
    """
    symbol: str
    exchange: str = "NSE"
    name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    grade: Optional[str] = None
    is_fno: bool = False
    mcap: Optional[float] = None
    instrument_type: InstrumentType = InstrumentType.EQ
    listing_status: ListingStatus = ListingStatus.ACTIVE
    series_or_group: Optional[str] = None
    notes: Optional[str] = None


class ISecurityMetadataRepository(ABC):
    """Authoritative repository contract for security identification and metadata.

    Provides thread-safe access to canonical SecurityMetadata and F&O universe membership.
    """

    @abstractmethod
    def get_metadata(self, symbol: str, exchange: str = "NSE") -> Optional[SecurityMetadata]:
        """Retrieve canonical metadata for a single symbol."""
        pass

    @abstractmethod
    def get_all_metadata(self, exchange: str = "NSE") -> Mapping[str, SecurityMetadata]:
        """Retrieve metadata for all known symbols on the specified exchange."""
        pass

    @abstractmethod
    def get_fno_symbols(self) -> Set[str]:
        """Return the set of underlying equity symbols eligible for NSE F&O."""
        pass

    @abstractmethod
    def update_metadata(
        self,
        symbol: str,
        field: str,
        value: Any,
        exchange: str = "NSE",
    ) -> Optional[SecurityMetadata]:
        """Update and persist a specific metadata field for a symbol."""
        pass

    def is_fno(self, symbol: str) -> bool:
        """Check whether a symbol is eligible for NSE F&O trading."""
        return symbol.strip().upper() in self.get_fno_symbols()



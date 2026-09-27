"""Bands Repository Contract — Read/write interface for trader band definitions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Sequence

BAND_TIMEFRAMES: Sequence[str] = ("D", "W", "M", "Q", "H", "Y")


@dataclass(frozen=True)
class BandEntry:
    """A single band width configuration."""
    symbol: str
    timeframe: str
    width_fraction: float  # e.g. 0.12 for 12%


@dataclass(frozen=True)
class BandAuditEntry:
    """Audit record for a band edit, migrated from band_log.py."""
    timestamp: datetime
    symbol: str
    timeframe: str
    old_value: Optional[float]
    new_value: Optional[float]
    changed_by: str = "app"
    source: str = "app"

    @property
    def when(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def old_pct(self) -> str:
        return "" if self.old_value is None else str(round(float(self.old_value) * 100, 4))

    @property
    def new_pct(self) -> str:
        return "" if self.new_value is None else str(round(float(self.new_value) * 100, 4))


@dataclass(frozen=True)
class BandBackupInfo:
    """Metadata describing a dated band backup snapshot."""
    filename: str
    date_str: str
    symbol_count: Optional[int]
    size_kb: float


class IBandsRepository(ABC):
    """The contract for accessing and updating discretionary band widths.
    
    Migrated from prototype yogi.theories.bands.Bands and _BandsView.
    Decouples band calculation from Excel/openpyxl storage.
    """

    @abstractmethod
    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        """Return the band width fraction for a symbol and timeframe (e.g. 0.12)."""
        pass

    @abstractmethod
    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        """Return band width fractions across all standard timeframes (D, W, M, Q, H, Y)."""
        pass

    @abstractmethod
    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "app",
        source: str = "app",
    ) -> float:
        """Update a band width and record an audit entry."""
        pass


class IBandAuditRepository(ABC):
    """The contract for persisting and querying discretionary band edit audit records."""

    @abstractmethod
    def record_change(self, entry: BandAuditEntry) -> bool:
        """Append an audit record for a verified band change. Returns True if written."""
        pass

    @abstractmethod
    def get_history(self, symbol: Optional[str] = None, limit: int = 500) -> Sequence[BandAuditEntry]:
        """Return audit history in reverse chronological order (newest first)."""
        pass


class IBandBackupService(ABC):
    """The contract for managing dated band backups and restorations."""

    @abstractmethod
    def create_snapshot(self, reason: str = "auto") -> Optional[str]:
        """Create a dated snapshot of all bands and prune old backups. Returns created filename."""
        pass

    @abstractmethod
    def list_backups(self) -> Sequence[BandBackupInfo]:
        """Return available snapshots ordered from newest to oldest."""
        pass

    @abstractmethod
    def restore_backup(self, filename: str) -> bool:
        """Safely and atomically restore bands from a backup snapshot."""
        pass


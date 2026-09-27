"""Results Engine Contract — Presentation assembly and export payload formatting.

Answers "What should be returned?"
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class ExportFormat(str, Enum):
    """Supported tabular export formats."""
    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


@dataclass(frozen=True)
class ColumnDefinition:
    """Definition of an exportable or displayable metric column."""
    key: str
    label: str
    category: str
    is_numeric: bool = True
    format_string: Optional[str] = None


@dataclass(frozen=True)
class QueryResultPayload:
    """Consolidated presentation payload assembled by the Results Engine.
    
    Migrated from prototype api/routes.py /api/table and /api/strategy/run responses.
    """
    universe_count: int
    qualified_count: int
    selected_count: int
    rows: Sequence[Mapping[str, Any]]
    columns: Sequence[ColumnDefinition] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class IResultAssembler(ABC):
    """The contract for assembling calculation, ranking, and selection outputs into a presentation payload."""

    @abstractmethod
    def assemble(
        self,
        records: Sequence[Mapping[str, Any]],
        columns: Optional[Sequence[str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> QueryResultPayload:
        """Package selected records and project columns for presentation."""
        pass


class IExportFormatter(ABC):
    """The contract for serializing presentation payloads into exportable binary or text bytes."""

    @abstractmethod
    def format(
        self,
        payload: QueryResultPayload,
        export_format: ExportFormat = ExportFormat.XLSX,
    ) -> bytes:
        """Format the payload into export bytes (e.g. Excel openpyxl or CSV)."""
        pass

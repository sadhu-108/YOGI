"""YOGI Core Contracts — Invariant Interfaces, Protocols, and DTOs.

Migrated from the prototype per AGENTS.md.
"""

from yogi.core.contracts.bands import (
    BAND_TIMEFRAMES,
    BandAuditEntry,
    BandBackupInfo,
    BandEntry,
    IBandAuditRepository,
    IBandBackupService,
    IBandsRepository,
)
from yogi.core.contracts.calculation import (
    CalculationContext,
    CalculationResult,
    ICalcModule,
)
from yogi.core.contracts.filter import (
    FilterEvaluationResult,
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    FilterStepMetric,
    FrozenDict,
    IConditionEvaluator,
    IFilterRule,
    ScreeningCancelledError,
)
from yogi.core.contracts.market_data import (
    MarketBar,
    MarketContext,
    TickData,
    Timeframe,
)
from yogi.core.contracts.timeframe import (
    ITimeframeEngine,
)
from yogi.core.contracts.provider import (
    IDataProvider,
    ProviderHealth,
)
from yogi.core.contracts.ranking import (
    IRankingRule,
    RankingMethod,
    RankingOrder,
    RankingResult,
)
from yogi.core.contracts.results import (
    ColumnDefinition,
    ExportFormat,
    IExportFormatter,
    IResultAssembler,
    QueryResultPayload,
)
from yogi.core.contracts.security import (
    ISecurityMetadataRepository,
    InstrumentType,
    ListingStatus,
    SecurityMetadata,
)
from yogi.core.contracts.selection import (
    ISelectionRule,
    RankCutoffSpec,
    SelectionMode,
    SelectionResult,
)
from yogi.core.contracts.storage import (
    IBarsCache,
    IDatasetCache,
)
from yogi.core.contracts.strategy import (
    IStrategy,
    StrategySpec,
    StrategyValidationResult,
)

__all__ = [
    # Market Data
    "MarketBar",
    "TickData",
    "MarketContext",
    "Timeframe",
    "ITimeframeEngine",
    # Provider
    "IDataProvider",
    "ProviderHealth",
    # Calculation
    "ICalcModule",
    "CalculationContext",
    "CalculationResult",
    # Bands
    "IBandsRepository",
    "BandEntry",
    "BandAuditEntry",
    "BandBackupInfo",
    "IBandAuditRepository",
    "IBandBackupService",
    "BAND_TIMEFRAMES",
    # Filter
    "IFilterRule",
    "IConditionEvaluator",
    "FilterOperator",
    "FilterRuleSpec",
    "FilterGroupSpec",
    "FilterStepMetric",
    "FilterEvaluationResult",
    "FrozenDict",
    # Strategy
    "IStrategy",
    "StrategySpec",
    "StrategyValidationResult",
    # Ranking
    "IRankingRule",
    "RankingOrder",
    "RankingMethod",
    "RankingResult",
    # Selection
    "ISelectionRule",
    "SelectionMode",
    "RankCutoffSpec",
    "SelectionResult",
    # Results
    "IResultAssembler",
    "IExportFormatter",
    "ColumnDefinition",
    "QueryResultPayload",
    "ExportFormat",
    # Security Master / Metadata
    "SecurityMetadata",
    "InstrumentType",
    "ListingStatus",
    "ISecurityMetadataRepository",
    # Storage / Cache
    "IBarsCache",
    "IDatasetCache",
]

"""Cockpit Application State & Dataset Immutability Container.

Provides:
1. Deeply immutable in-memory dataset view via types.MappingProxyType at both outer
   and inner mapping levels.
2. Atomic dataset reference replacement under concurrency guard.
3. ColumnProjectingAssembler adapter bridging custom presentation columns to IResultAssembler
   without modifying frozen Core orchestration.
4. ZERO business logic, filtering, ranking, or financial mathematics.
"""

import asyncio
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

from yogi.calculation.bands import BandsCalculator
from yogi.calculation.candles import CandleCalculator
from yogi.calculation.impulse import ImpulseCalculator
from yogi.calculation.trend import TrendCalculator
from yogi.calculation.velocity import VelocityCalculator
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.services import RaceDataService
from yogi.cockpit.demo import DemoBandsRepository
from yogi.data.providers.demo import DemoDataProvider
from yogi.cockpit.schemas import (
    RankCutoffIn,
    StockDetailPanelOut,
    StrategyDetailOut,
    TimeframeRowOut,
    from_core_filter_group,
)
from yogi.core.configuration.catalog import StrategyCatalog
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.results import IExportFormatter, IResultAssembler, QueryResultPayload
from yogi.core.contracts.security import ISecurityMetadataRepository
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.results.formatter import ExportFormatter
from yogi.selection.engine import SelectionEngine
from yogi.strategy.presets import load_mentor_presets
from yogi.timeframe.engine import TimeframeEngine


def _freeze_value(val: Any) -> Any:
    """Recursively convert nested mutable collections into immutable equivalents."""
    if isinstance(val, dict):
        return MappingProxyType({k: _freeze_value(v) for k, v in val.items()})
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_value(v) for v in val)
    if isinstance(val, set):
        return frozenset(_freeze_value(v) for v in val)
    return val


def freeze_dataset(raw_dataset: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Mapping[str, Any]]:
    """Produce a deeply immutable read-only view of the canonical feature dataset.
    
    Guarantees:
    - Outer mapping is a MappingProxyType (cannot add, delete, or reassign symbols).
    - Inner metric mappings are copies wrapped in MappingProxyType (cannot mutate metrics in place).
    - Nested dictionaries, lists, and sets are recursively frozen into immutable types.
    - Underlying dictionary references cannot be retained by callers to mutate data post-freeze.
    """
    frozen: dict[str, MappingProxyType[str, Any]] = {
        symbol: MappingProxyType({k: _freeze_value(v) for k, v in dict(metrics).items()})
        for symbol, metrics in raw_dataset.items()
    }
    return MappingProxyType(frozen)


class ColumnProjectingAssembler(IResultAssembler):
    """Cockpit-boundary adapter allowing requested presentation columns to be projected
    through PipelineOrchestrator.execute_screen() without modifying frozen Core contracts
    or Core orchestration code.
    """

    def __init__(self, delegate: IResultAssembler, columns: Sequence[str]) -> None:
        self._delegate = delegate
        self._columns = tuple(columns)

    def assemble(
        self,
        records: Sequence[Mapping[str, Any]],
        columns: Optional[Sequence[str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> QueryResultPayload:
        # Override the hardcoded columns=None from execute_screen with the bound presentation columns
        return self._delegate.assemble(
            records=records,
            columns=self._columns,
            metadata=metadata,
        )


class AppState:
    """Thread-safe dependency container and in-memory pre-calculated dataset cache."""

    def __init__(
        self,
        orchestrator: Optional[PipelineOrchestrator] = None,
        catalog: Optional[StrategyCatalog] = None,
        bands_repo: Optional[IBandsRepository] = None,
        chart_service: Optional[ChartDataService] = None,
        race_service: Optional[RaceDataService] = None,
        provider: Optional[IDataProvider] = None,
        assembler: Optional[IResultAssembler] = None,
        formatter: Optional[IExportFormatter] = None,
        config: Optional[EngineConfig] = None,
        initial_dataset: Optional[Mapping[str, Mapping[str, Any]]] = None,
        timeframe_engine: Optional[ITimeframeEngine] = None,
        metadata_repo: Optional[ISecurityMetadataRepository] = None,
    ) -> None:
        self._config = config if config is not None else EngineConfig()
        self._catalog = catalog if catalog is not None else load_mentor_presets()
        self._assembler = assembler if assembler is not None else ResultAssembler()
        self._formatter = formatter if formatter is not None else ExportFormatter()

        # Retain configured live provider and bands repository keys for switching back from demo
        self._live_provider_key = (
            self._config.provider if self._config.provider != "demo" else "yfinance"
        )
        self._live_bands_key = (
            self._config.bands_repository if self._config.bands_repository not in ("demo",) else "csv"
        )

        if orchestrator is not None:
            self._orchestrator = orchestrator
        else:
            hub = RegistryHub()
            # Register verified Core calculation modules
            hub.calculations.register("bands", BandsCalculator())
            hub.calculations.register("velocity", VelocityCalculator())
            hub.calculations.register("impulse", ImpulseCalculator())
            hub.calculations.register("trend", TrendCalculator())
            hub.calculations.register("candles", CandleCalculator())

            # Register verified offline demo provider and bands repository
            try:
                demo_provider = DemoDataProvider()
                demo_bands = DemoBandsRepository()
                hub.providers.register("demo", demo_provider)
                hub.bands.register("demo", demo_bands)
            except Exception as exc:
                logger.error("Failed to initialize demo capabilities: %s", exc)

            # Register persistent bands repository (CSV/file-backed)
            try:
                from yogi.storage.bands import CsvBandsRepository
                csv_bands = CsvBandsRepository()
                hub.bands.register("csv", csv_bands)
            except Exception as exc:
                logger.warning("Failed to initialize CsvBandsRepository: %s", exc)

            tf_engine = timeframe_engine if timeframe_engine is not None else TimeframeEngine()

            self._orchestrator = PipelineOrchestrator(
                registry=hub,
                filter_rule=FilterEngine(),
                ranking_rule=RankingEngine(),
                selection_rule=SelectionEngine(),
                result_assembler=self._assembler,
                timeframe_engine=tf_engine,
            )

        # Discretionary bands repository resolution (strictly through DI or Registry)
        self._bands_repo = bands_repo
        if self._bands_repo is None and self._orchestrator.registry.bands.has(self._config.bands_repository):
            self._bands_repo = self._orchestrator.registry.bands.get(self._config.bands_repository)

        # Security metadata repository resolution (strictly through DI or storage/demo)
        self._metadata_repo = metadata_repo
        if self._metadata_repo is None:
            if self.is_demo:
                try:
                    from yogi.cockpit.demo import DemoMetadataRepository
                    self._metadata_repo = DemoMetadataRepository()
                except Exception as exc:
                    logger.warning("Failed to initialize DemoMetadataRepository: %s", exc)
            else:
                try:
                    from yogi.storage.metadata import CsvMetadataRepository
                    self._metadata_repo = CsvMetadataRepository(data_dir=Path("data"))
                except Exception as exc:
                    logger.warning("Failed to initialize CsvMetadataRepository: %s", exc)

        if self._orchestrator.metadata_repository is None and self._metadata_repo is not None:
            self._orchestrator.metadata_repository = self._metadata_repo

        # Presentation chart data service and race data service resolution (strictly through DI or Registry)
        self._chart_service = chart_service
        self._race_service = race_service
        if (self._chart_service is None or self._race_service is None) and initial_dataset:
            resolved_provider = provider
            if resolved_provider is None and self._orchestrator.registry.providers.has(self._config.provider):
                resolved_provider = self._orchestrator.registry.providers.get(self._config.provider)

            if resolved_provider is not None:
                if self._chart_service is None:
                    self._chart_service = ChartDataService(
                        provider=resolved_provider,
                        timeframe_engine=self._orchestrator.timeframe_engine,
                        bands_repo=self._bands_repo,
                    )
                if self._race_service is None:
                    self._race_service = RaceDataService(
                        provider=resolved_provider,
                        dataset_provider=lambda: self._dataset,
                    )

        # In-memory dataset cache (strictly read-only views)
        if initial_dataset:
            self._dataset: Mapping[str, Mapping[str, Any]] = freeze_dataset(initial_dataset)
            self._last_built_at: Optional[datetime] = datetime.now(timezone.utc)
        else:
            self._dataset = MappingProxyType({})
            self._last_built_at = None

        # User-defined presets storage (in-memory + local JSON fallback)
        self._user_presets: dict[str, dict[str, Any]] = {}
        self._presets_file = Path("data/user_presets.json")
        self._load_user_presets()

        # Ephemeral bounded LRU cache for on-demand stock detail panels (YOGI-F05)
        self._panel_cache: OrderedDict[str, StockDetailPanelOut] = OrderedDict()
        self._panel_cache_max_size: int = 100
        self._panel_cache_provider: str = self._config.provider
        self._panel_cache_lock = threading.Lock()

        self._lock = asyncio.Lock()

    @property
    def panel_cache(self) -> Mapping[str, StockDetailPanelOut]:
        """Return a read-only view of the on-demand stock panel cache."""
        with self._panel_cache_lock:
            return MappingProxyType(dict(self._panel_cache))

    def clear_panel_cache(self) -> None:
        """Clear the on-demand stock detail panel cache."""
        with self._panel_cache_lock:
            self._panel_cache.clear()

    @property
    def dataset(self) -> Mapping[str, Mapping[str, Any]]:
        """Return the deeply immutable pre-calculated feature dataset."""
        return self._dataset

    @property
    def last_built_at(self) -> Optional[datetime]:
        """Return UTC timestamp of when dataset was materialized."""
        return self._last_built_at

    @property
    def orchestrator(self) -> PipelineOrchestrator:
        return self._orchestrator

    @property
    def catalog(self) -> StrategyCatalog:
        return self._catalog

    @property
    def bands_repo(self) -> Optional[IBandsRepository]:
        return self._bands_repo

    @property
    def metadata_repository(self) -> Optional[ISecurityMetadataRepository]:
        """Authoritative security metadata repository for application layer."""
        return self._metadata_repo

    @property
    def chart_service(self) -> Optional[ChartDataService]:
        return self._chart_service

    @property
    def race_service(self) -> Optional[RaceDataService]:
        """Return presentation race data service if configured."""
        if self._race_service is None:
            if self._orchestrator.registry.providers.has(self._config.provider):
                resolved_provider = self._orchestrator.registry.providers.get(self._config.provider)
                self._race_service = RaceDataService(
                    provider=resolved_provider,
                    dataset_provider=lambda: self._dataset,
                )
        return self._race_service

    @property
    def assembler(self) -> IResultAssembler:
        return self._assembler

    @property
    def formatter(self) -> IExportFormatter:
        return self._formatter

    @property
    def config(self) -> EngineConfig:
        return self._config

    @property
    def is_demo(self) -> bool:
        """Return True if active configuration uses the demo data provider."""
        return self._config.provider == "demo"

    async def refresh(
        self,
        symbols: Optional[Sequence[str]] = None,
        symbol_limit: Optional[int] = None,
        provider: Optional[str] = None,
        bands_repository: Optional[str] = None,
    ) -> None:
        """Rebuild feature dataset asynchronously and replace the reference atomically."""
        async with self._lock:
            # 1. Resolve target provider and bands repository with explicit demo/live switching support
            if provider == "demo":
                target_provider = "demo"
                target_bands_repo = "demo"
            elif provider in ("live", "yfinance"):
                target_provider = "yfinance"
                target_bands_repo = (
                    bands_repository
                    if bands_repository is not None and self._orchestrator.registry.bands.has(bands_repository)
                    else (self._live_bands_key if self._orchestrator.registry.bands.has(self._live_bands_key) else "csv")
                )
            elif provider is not None:
                target_provider = provider
                target_bands_repo = (
                    bands_repository
                    if bands_repository is not None and self._orchestrator.registry.bands.has(bands_repository)
                    else ("demo" if target_provider == "demo" else (self._live_bands_key if self._orchestrator.registry.bands.has(self._live_bands_key) else "csv"))
                )
            else:
                target_provider = self._config.provider if self._config.provider != "demo" else "yfinance"
                target_bands_repo = (
                    self._config.bands_repository
                    if self._orchestrator.registry.bands.has(self._config.bands_repository)
                    else ("demo" if target_provider == "demo" else "csv")
                )

            # 2. Guarantee demo capabilities are registered in the active registry if demo was requested
            if target_provider == "demo":
                if not self._orchestrator.registry.providers.has("demo"):
                    self._orchestrator.registry.providers.register("demo", DemoDataProvider())
                if not self._orchestrator.registry.bands.has("demo"):
                    self._orchestrator.registry.bands.register("demo", DemoBandsRepository())

            # 3. Dynamic lazy registration for live provider (yfinance) if requested and not yet in registry
            if target_provider == "yfinance" and not self._orchestrator.registry.providers.has("yfinance"):
                try:
                    from yogi.data.providers.yfinance import YFinanceDataProvider
                    self._orchestrator.registry.providers.register("yfinance", YFinanceDataProvider())
                except Exception as exc:
                    logger.warning("Could not register live YFinanceDataProvider: %s", exc)

            if target_bands_repo in ("csv", "excel") and not self._orchestrator.registry.bands.has(target_bands_repo):
                try:
                    from yogi.storage.bands import CsvBandsRepository
                    csv_repo = CsvBandsRepository()
                    self._orchestrator.registry.bands.register("csv", csv_repo)
                    self._orchestrator.registry.bands.register("excel", csv_repo)
                except Exception as exc:
                    logger.warning("Could not register persistent CsvBandsRepository: %s", exc)

            # Synchronize metadata repository between Demo and Live
            if target_provider == "demo" and not isinstance(self._metadata_repo, DemoMetadataRepository if "DemoMetadataRepository" in globals() else object):
                try:
                    from yogi.cockpit.demo import DemoMetadataRepository
                    self._metadata_repo = DemoMetadataRepository()
                    self._orchestrator.metadata_repository = self._metadata_repo
                except Exception as exc:
                    logger.warning("Could not switch to DemoMetadataRepository: %s", exc)
            elif self._config.provider == "demo" and target_provider != "demo":
                try:
                    from yogi.storage.metadata import CsvMetadataRepository
                    self._metadata_repo = CsvMetadataRepository(data_dir=Path("data"))
                    self._orchestrator.metadata_repository = self._metadata_repo
                except Exception as exc:
                    logger.warning("Could not switch to CsvMetadataRepository: %s", exc)

            # 4. Determine target symbols (full universe / configured symbols - NO INFY WORKAROUND, NO ARTIFICIAL LIMITATION)
            if symbols is not None:
                target_symbols = symbols
            elif target_provider == "demo":
                target_symbols = None
            else:
                target_symbols = self._config.symbols

            active_config = EngineConfig(
                provider=target_provider,
                bands_repository=target_bands_repo,
                calculation_modules=self._config.calculation_modules,
                exchange=self._config.exchange,
                timeframes=self._config.timeframes,
                historical_years=self._config.historical_years,
                symbol_limit=symbol_limit if symbol_limit is not None else self._config.symbol_limit,
                symbols=target_symbols,
                provider_options=self._config.provider_options,
            )

            # Build off-thread using canonical PipelineOrchestrator
            raw_dataset = await asyncio.to_thread(self._orchestrator.build_dataset, active_config)

            # Freeze deeply and atomically swap pointer
            self._dataset = freeze_dataset(raw_dataset)
            self._last_built_at = datetime.now(timezone.utc)
            self._config = active_config

            # Clear isolated panel cache to prevent cross-contamination between Demo and Live
            with self._panel_cache_lock:
                self._panel_cache.clear()
                self._panel_cache_provider = active_config.provider

            # Synchronize active bands repository, chart service, and race service to the new provider/bands
            if self._orchestrator.registry.bands.has(active_config.bands_repository):
                self._bands_repo = self._orchestrator.registry.bands.get(active_config.bands_repository)
            if self._orchestrator.registry.providers.has(active_config.provider):
                resolved_provider = self._orchestrator.registry.providers.get(active_config.provider)
                self._chart_service = ChartDataService(
                    provider=resolved_provider,
                    timeframe_engine=self._orchestrator.timeframe_engine,
                    bands_repo=self._bands_repo,
                )
                self._race_service = RaceDataService(
                    provider=resolved_provider,
                    dataset_provider=lambda: self._dataset,
                )

    def _load_user_presets(self) -> None:
        """Load user-defined presets from storage file if present."""
        try:
            if self._presets_file.is_file():
                content = self._presets_file.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    self._user_presets = data
        except Exception as exc:
            logger.warning("Could not load user presets: %s", exc)

    def _save_user_presets(self) -> None:
        """Persist user-defined presets to local JSON storage file."""
        try:
            self._presets_file.parent.mkdir(parents=True, exist_ok=True)
            self._presets_file.write_text(json.dumps(self._user_presets, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not persist user presets: %s", exc)

    def list_user_presets(self) -> list[dict[str, Any]]:
        """List all user-defined screening presets."""
        return list(self._user_presets.values())

    def get_user_preset(self, name: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific user-defined preset by name."""
        return self._user_presets.get(name)

    def save_user_preset(self, preset_dict: dict[str, Any]) -> dict[str, Any]:
        """Save or overwrite a user-defined screening preset."""
        name = preset_dict["name"]
        self._user_presets[name] = preset_dict
        self._save_user_presets()
        return preset_dict

    def delete_user_preset(self, name: str) -> bool:
        """Delete a user-defined screening preset by name."""
        if name in self._user_presets:
            del self._user_presets[name]
            self._save_user_presets()
            return True
        return False

    def get_strategy_detail(self, name: str) -> Optional[StrategyDetailOut]:
        """Return the complete specification of a mentor preset or registered strategy."""
        if self._catalog.has(name):
            spec = self._catalog.get(name)
            fg = from_core_filter_group(spec.filter_group)
            cutoffs = []
            if spec.target_cutoff_limit and spec.target_ranking_metric:
                cutoffs.append(
                    RankCutoffIn(
                        metric=spec.target_ranking_metric,
                        max_rank=spec.target_cutoff_limit,
                    )
                )
            return StrategyDetailOut(
                name=spec.name,
                description=spec.description,
                is_mentor_preset=spec.is_mentor_preset,
                target_ranking_metric=spec.target_ranking_metric,
                target_cutoff_limit=spec.target_cutoff_limit,
                ranking_metric=spec.target_ranking_metric,
                ranking_order="desc",
                limit=spec.target_cutoff_limit,
                filter_group=fg,
                selection_cutoffs=cutoffs,
            )
        if name in self._user_presets:
            u = self._user_presets[name]
            return StrategyDetailOut(
                name=u.get("name", name),
                description=u.get("description"),
                is_mentor_preset=False,
                target_ranking_metric=u.get("ranking_metric"),
                target_cutoff_limit=u.get("limit"),
                ranking_metric=u.get("ranking_metric"),
                ranking_order=u.get("ranking_order", "desc"),
                limit=u.get("limit"),
                columns=u.get("columns"),
                filter_group=u.get("filter_group"),
                selection_cutoffs=u.get("selection_cutoffs", []),
            )
        return None

    @staticmethod
    def _row_to_panel(symbol: str, row: Mapping[str, Any]) -> StockDetailPanelOut:
        """Convert a feature dictionary record into StockDetailPanelOut."""
        timeframes = []
        for tf in ("D", "W", "M", "Q", "H", "Y"):
            timeframes.append(
                TimeframeRowOut(
                    timeframe=tf,
                    ema_state=row.get(f"EMA_{tf}"),
                    band_state=row.get(f"BANDST_{tf}"),
                    band_distance=row.get(f"BD_{tf}"),
                    band_width=row.get(f"BAND_{tf}"),
                    roc=row.get(f"{tf}ROC"),
                    speed=row.get(f"SPD_{tf}"),
                    band_upper=row.get(f"BANDUP_{tf}"),
                    band_lower=row.get(f"BANDLO_{tf}"),
                )
            )

        key_metrics = {
            "DROC": row.get("DROC"),
            "WROC": row.get("WROC"),
            "MROC": row.get("MROC"),
            "M_CUR": row.get("M_CUR"),
            "YROC": row.get("YROC"),
            "S4": row.get("S4"),
            "S13": row.get("S13"),
            "S26": row.get("S26"),
            "S52": row.get("S52"),
            "ACCEL_L": row.get("ACCEL_L"),
            "ACCEL_S": row.get("ACCEL_S"),
            "SPR_CONSIST": row.get("SPR_CONSIST"),
            "ATH_DIFF": row.get("ATH_DIFF"),
            "OUT_ABOVE": row.get("OUT_ABOVE"),
            "OUT_BELOW": row.get("OUT_BELOW"),
            "N_ABOVE": row.get("N_ABOVE"),
            "N_BELOW": row.get("N_BELOW"),
            "DIP_D": row.get("DIP_D"),
            "DIM_D": row.get("DIM_D"),
            "ADX_D": row.get("ADX_D"),
            "DMI_STATE_D": row.get("DMI_STATE_D"),
        }

        # Multi-timeframe DMI trend & ADX enrichment for drawer matrix
        for tf_code in ("D", "W", "M", "Q", "H", "Y"):
            for dmi_key in (f"DMI_STATE_{tf_code}", f"ADX_{tf_code}", f"DIP_{tf_code}", f"DIM_{tf_code}"):
                if dmi_key in row:
                    key_metrics[dmi_key] = row.get(dmi_key)

        # Historical breakdown enrichment (CAGR, Annual Returns, Sprints)
        for k, v in row.items():
            if (
                k.startswith("CAGR_")
                or k.startswith("Y2")
                or k == "Y_OLDER"
                or k.startswith("SPA_")
                or k.startswith("SPR_")
            ):
                if k not in key_metrics:
                    key_metrics[k] = v

        return StockDetailPanelOut(
            symbol=symbol,
            exchange=row.get("exchange", "NSE"),
            price=row.get("price"),
            name=row.get("name"),
            sector=row.get("sector"),
            grade=row.get("grade"),
            mcap=row.get("mcap"),
            fno=row.get("fno"),
            instr=row.get("instr"),
            grp=row.get("grp"),
            ic=row.get("IC"),
            ic_ratio=row.get("IC_RATIO"),
            accel_l=row.get("ACCEL_L"),
            accel_s=row.get("ACCEL_S"),
            spr_consist=row.get("SPR_CONSIST"),
            ath_diff=row.get("ATH_DIFF"),
            timeframes=timeframes,
            key_metrics=key_metrics,
        )

    def get_stock_panel(self, symbol: str) -> Optional[StockDetailPanelOut]:
        """Extract multi-timeframe analytical panel metrics for the specified symbol.

        Resolution hierarchy (YOGI-F05):
        1. Check self._dataset: instant O(1) read for pre-screened cohort stocks.
        2. Check self._panel_cache: instant O(1) read for previously resolved on-demand stocks.
        3. Canonical on-demand execution: invoke PipelineOrchestrator.build_dataset(single_config).
           - Preserves self._dataset immutability (zero mutations or merges into self._dataset).
           - Preserves Demo/Live isolation (queries active provider only; Demo never contacts networks).
           - Caches ONLY successful panel results in bounded LRU cache (max 100 entries).
           - Propagates provider exceptions un-cached for explicit HTTP status mapping in router.
           - Returns None for unknown or unavailable symbols (triggering HTTP 404).
        """
        sym = symbol.strip().upper()
        if not sym:
            return None

        # 1. Instant lookup in materialized screening cohort
        row = self._dataset.get(sym)
        if row is not None:
            return self._row_to_panel(sym, row)

        # 2. Check bounded LRU panel cache (with Demo/Live isolation check)
        with self._panel_cache_lock:
            if self._config.provider != self._panel_cache_provider:
                self._panel_cache.clear()
                self._panel_cache_provider = self._config.provider
            cached = self._panel_cache.get(sym)
            if cached is not None:
                self._panel_cache.move_to_end(sym)
                return cached

        # 3. Canonical on-demand execution via PipelineOrchestrator
        provider_key = self._config.provider

        # Lazy registration for demo or live providers if missing from registry
        if provider_key == "demo" and not self._orchestrator.registry.providers.has("demo"):
            try:
                self._orchestrator.registry.providers.register("demo", DemoDataProvider())
            except Exception as exc:
                logger.warning("Could not lazy-register DemoDataProvider: %s", exc)

        if provider_key == "yfinance" and not self._orchestrator.registry.providers.has(provider_key):
            try:
                from yogi.data.providers.yfinance import YFinanceDataProvider
                self._orchestrator.registry.providers.register(provider_key, YFinanceDataProvider())
            except Exception as exc:
                logger.warning("Could not lazy-register YFinanceDataProvider for '%s': %s", provider_key, exc)

        if not self._orchestrator.registry.providers.has(provider_key):
            logger.warning("Active provider '%s' not registered in orchestrator registry", provider_key)
            return None

        bands_repo_name = self._config.bands_repository
        if not self._orchestrator.registry.bands.has(bands_repo_name):
            if self._orchestrator.registry.bands.has("demo"):
                bands_repo_name = "demo"
            elif self._bands_repo is not None:
                bands_repo_name = getattr(self._bands_repo, "name", "demo")
            else:
                try:
                    self._orchestrator.registry.bands.register("demo", DemoBandsRepository())
                    bands_repo_name = "demo"
                except Exception as exc:
                    logger.warning("Could not lazy-register DemoBandsRepository: %s", exc)
                    return None

        calc_modules = tuple(
            m for m in self._config.calculation_modules
            if self._orchestrator.registry.calculations.has(m)
        )

        single_config = EngineConfig(
            provider=provider_key,
            bands_repository=bands_repo_name,
            calculation_modules=calc_modules,
            exchange=self._config.exchange,
            timeframes=self._config.timeframes,
            historical_years=self._config.historical_years,
            symbols=[sym],
            provider_options=self._config.provider_options,
        )

        # Canonical execution through PipelineOrchestrator (do not catch provider exceptions here;
        # let them propagate un-cached to router for explicit HTTP 401/429/503 status mapping)
        records = self._orchestrator.build_dataset(single_config)
        single_row = records.get(sym)
        if not single_row or single_row.get("price") is None:
            return None

        panel = self._row_to_panel(sym, single_row)

        # Cache ONLY successful results in bounded LRU cache
        with self._panel_cache_lock:
            if sym in self._panel_cache:
                self._panel_cache.move_to_end(sym)
            else:
                if len(self._panel_cache) >= self._panel_cache_max_size:
                    self._panel_cache.popitem(last=False)
                self._panel_cache[sym] = panel

        return panel



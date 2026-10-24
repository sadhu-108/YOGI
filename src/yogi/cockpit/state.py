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
from dataclasses import dataclass, field
import inspect
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.services import RaceDataService
from yogi.cockpit.schemas import (
    RankCutoffIn,
    StockDetailPanelOut,
    StrategyDetailOut,
    TimeframeRowOut,
    from_core_filter_group,
)
from yogi.storage.cache import DatasetCache, MarketBarsCache
from yogi.storage.paths import get_data_dir
from yogi.core.configuration.catalog import StrategyCatalog
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.filter import IConditionEvaluator, IFilterRule
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.storage import IBarsCache, IDatasetCache
from yogi.core.contracts.results import IExportFormatter, IResultAssembler, QueryResultPayload
from yogi.core.contracts.security import ISecurityMetadataRepository
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry import RegistryHub, create_default_registry_hub
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.filter import FilterEngine, create_default_filter_engine
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


@dataclass
class ScreeningTask:
    """Request-scoped tracking record for in-flight and completed screening executions."""
    request_id: str
    status: str = "running"  # "running", "cancelling", "cancelled", "completed", "failed"
    progress: float = 0.0    # 0.0 to 100.0
    stage: str = "initializing"
    message: str = "Screening in progress..."
    processed_count: int = 0
    total_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_requested: bool = False
    cancelled_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


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
        autoload_cache: bool = False,
        dataset_cache: Optional[IDatasetCache] = None,
        bars_cache: Optional[IBarsCache] = None,
        filter_rule: Optional[IFilterRule] = None,
        condition_evaluators: Optional[Mapping[str, IConditionEvaluator]] = None,
    ) -> None:
        self._config = config if config is not None else EngineConfig()
        self._catalog = catalog if catalog is not None else load_mentor_presets()
        self._assembler = assembler if assembler is not None else ResultAssembler()
        self._formatter = formatter if formatter is not None else ExportFormatter()

        # Cache persistence repositories (for fast startup and bar reuse)
        self._dataset_cache = dataset_cache if dataset_cache is not None else DatasetCache()
        self._bars_cache = bars_cache if bars_cache is not None else MarketBarsCache()
        self._build_status: str = "IDLE"
        self._build_progress: float = 0.0
        self._build_stage: str = "idle"
        self._build_error: Optional[str] = None
        self._build_task: Optional[asyncio.Task] = None
        self._build_thread: Optional[threading.Thread] = None
        self._is_cached: bool = False

        # Retain configured live provider and bands repository keys for switching back from demo
        self._live_provider_key = (
            self._config.provider if self._config.provider != "demo" else "yfinance"
        )
        self._live_bands_key = (
            self._config.bands_repository if self._config.bands_repository not in ("demo",) else "csv"
        )

        # Settings persistence (data/settings.json)
        self._settings_file = get_data_dir() / "settings.json"
        self._half_year_policy: str = "prototype"
        self._load_settings()
        if self._config.half_year_policy and self._config.half_year_policy != "prototype":
            self._half_year_policy = self._config.half_year_policy

        if orchestrator is not None:
            self._orchestrator = orchestrator
            if hasattr(self._orchestrator.timeframe_engine, "half_year_policy"):
                self._orchestrator.timeframe_engine.half_year_policy = self._half_year_policy
            if filter_rule is not None:
                self._orchestrator.filter_rule = filter_rule
            if condition_evaluators:
                for c_type, evaluator in condition_evaluators.items():
                    self.register_condition_evaluator(c_type, evaluator)
        else:
            hub = create_default_registry_hub()
            tf_engine = (
                timeframe_engine
                if timeframe_engine is not None
                else TimeframeEngine(half_year_policy=self._half_year_policy)
            )
            if hasattr(tf_engine, "half_year_policy"):
                tf_engine.half_year_policy = self._half_year_policy

            f_rule = (
                filter_rule
                if filter_rule is not None
                else create_default_filter_engine(evaluators=condition_evaluators)
            )

            self._orchestrator = PipelineOrchestrator(
                registry=hub,
                filter_rule=f_rule,
                ranking_rule=RankingEngine(),
                selection_rule=SelectionEngine(),
                result_assembler=self._assembler,
                timeframe_engine=tf_engine,
                bars_cache=self._bars_cache,
            )
            if filter_rule is not None and condition_evaluators:
                for c_type, evaluator in condition_evaluators.items():
                    self.register_condition_evaluator(c_type, evaluator)

        # Discretionary bands repository resolution (strictly through DI or Registry)
        self._bands_repo = bands_repo
        if self._bands_repo is not None:
            self._orchestrator.registry.bands.override(self._config.bands_repository, self._bands_repo)
        elif self._orchestrator.registry.bands.has(self._config.bands_repository):
            self._bands_repo = self._orchestrator.registry.bands.get(self._config.bands_repository)

        if provider is not None:
            self._orchestrator.registry.providers.override(self._config.provider, provider)

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
                    self._metadata_repo = CsvMetadataRepository(data_dir=get_data_dir())
                except Exception as exc:
                    logger.warning("Failed to initialize CsvMetadataRepository: %s", exc)

        if self._orchestrator.metadata_repository is None and self._metadata_repo is not None:
            self._orchestrator.metadata_repository = self._metadata_repo

        # Presentation chart data service and race data service resolution (strictly through DI or Registry)
        self._chart_service = chart_service
        self._chart_service_injected: bool = chart_service is not None
        if self._chart_service is not None and getattr(self._chart_service, "bars_cache", None) is None and self._bars_cache is not None:
            self._chart_service.bars_cache = self._bars_cache
        self._race_service = race_service
        self._race_service_injected: bool = race_service is not None
        if self._race_service is not None and getattr(self._race_service, "bars_cache", None) is None and self._bars_cache is not None:
            self._race_service.bars_cache = self._bars_cache
        if self._race_service is not None and getattr(self._race_service, "timeframe_engine", None) is None and hasattr(self._orchestrator, "timeframe_engine"):
            self._race_service.timeframe_engine = self._orchestrator.timeframe_engine
        if initial_dataset or provider is not None:
            self._init_presentation_services(provider=provider)

        # In-memory dataset cache (strictly read-only views)
        if initial_dataset:
            self._dataset: Mapping[str, Mapping[str, Any]] = freeze_dataset(initial_dataset)
            self._last_built_at: Optional[datetime] = datetime.now(timezone.utc)
            self._build_status = "READY"
            self._build_stage = "Initialized with custom dataset"
            self._is_cached = False
        elif autoload_cache:
            loaded = self.load_persisted_cache()
            if not loaded:
                self._dataset = MappingProxyType({})
                self._last_built_at = None
        else:
            self._dataset = MappingProxyType({})
            self._last_built_at = None

        # User-defined presets storage (in-memory + local JSON fallback)
        self._user_presets: dict[str, dict[str, Any]] = {}
        self._presets_file = get_data_dir() / "user_presets.json"
        self._load_user_presets()

        # Ephemeral bounded LRU cache for on-demand stock detail panels (YOGI-F05)
        self._panel_cache: OrderedDict[str, StockDetailPanelOut] = OrderedDict()
        self._panel_cache_max_size: int = 100
        self._panel_cache_provider: str = self._config.provider
        self._panel_cache_lock = threading.Lock()
        self._dirty_symbols: set[str] = set()

        # Request-scoped active and historical screening tasks
        self._screening_tasks: dict[str, ScreeningTask] = {}
        self._screening_tasks_lock = threading.Lock()

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

    def invalidate_symbol(self, symbol: str) -> None:
        """Invalidate cached panel and mark symbol dirty for on-demand recalculation."""
        sym = symbol.strip().upper()
        with self._panel_cache_lock:
            self._dirty_symbols.add(sym)
            self._panel_cache.pop(sym, None)

    def invalidate_all_symbols(self) -> None:
        """Invalidate all cached panels and mark cohort dirty when global configuration changes."""
        with self._panel_cache_lock:
            self._dirty_symbols.update(self._dataset.keys())
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
    def filter_rule(self) -> Optional[IFilterRule]:
        """Return the active filter rule from the orchestrator."""
        return self._orchestrator.filter_rule if self._orchestrator else None

    def register_condition_evaluator(self, condition_type: str, evaluator: IConditionEvaluator) -> None:
        """Register a condition evaluator on the active orchestrator's filter rule."""
        if self._orchestrator and hasattr(self._orchestrator.filter_rule, "register_evaluator"):
            self._orchestrator.filter_rule.register_evaluator(condition_type, evaluator)
        else:
            raise AttributeError("Active orchestrator filter_rule does not support evaluator registration")

    def _init_presentation_services(self, provider: Optional[IDataProvider] = None) -> None:
        """Initialize presentation chart and race data services strictly through DI or Registry."""
        # 1. Discretionary bands repository resolution
        if self._bands_repo is None and self._orchestrator.registry.bands.has(self._config.bands_repository):
            self._bands_repo = self._orchestrator.registry.bands.get(self._config.bands_repository)

        # 2. Provider resolution
        provider_key = self._config.provider
        resolved_provider = provider
        if resolved_provider is None and self._orchestrator.registry.providers.has(provider_key):
            resolved_provider = self._orchestrator.registry.providers.get(provider_key)

        # 3. Presentation services instantiation
        if resolved_provider is not None:
            if self._chart_service is None or self._chart_service.provider is not resolved_provider:
                self._chart_service = ChartDataService(
                    provider=resolved_provider,
                    timeframe_engine=self._orchestrator.timeframe_engine,
                    bands_repo=self.bands_repo,
                    bars_cache=self._bars_cache,
                )
            elif self._chart_service.bands_repo is None and self.bands_repo is not None:
                self._chart_service.bands_repo = self.bands_repo
            if self._chart_service.bars_cache is None and self._bars_cache is not None:
                self._chart_service.bars_cache = self._bars_cache

            if self._race_service is None or self._race_service.provider is not resolved_provider:
                self._race_service = RaceDataService(
                    provider=resolved_provider,
                    dataset_provider=lambda: self._dataset,
                    bars_cache=self._bars_cache,
                    timeframe_engine=self._orchestrator.timeframe_engine,
                )

    @property
    def bands_repo(self) -> Optional[IBandsRepository]:
        return self._bands_repo

    @property
    def metadata_repository(self) -> Optional[ISecurityMetadataRepository]:
        """Authoritative security metadata repository for application layer."""
        return self._metadata_repo

    @property
    def chart_service(self) -> Optional[ChartDataService]:
        if self._chart_service_injected:
            return self._chart_service
        provider_key = self._config.provider
        if self._chart_service is None and len(self._dataset) > 0:
            if self._orchestrator.registry.providers.has(provider_key):
                resolved_provider = self._orchestrator.registry.providers.get(provider_key)
                self._init_presentation_services(provider=resolved_provider)
        elif self._chart_service is not None:
            if self._orchestrator.registry.providers.has(provider_key):
                resolved_provider = self._orchestrator.registry.providers.get(provider_key)
                if self._chart_service.provider is not resolved_provider:
                    self._init_presentation_services(provider=resolved_provider)
                elif self._chart_service.bands_repo is None and self.bands_repo is not None:
                    self._chart_service.bands_repo = self.bands_repo
            if getattr(self._chart_service, "bars_cache", None) is None and self._bars_cache is not None:
                self._chart_service.bars_cache = self._bars_cache
        return self._chart_service

    @property
    def race_service(self) -> Optional[RaceDataService]:
        """Return presentation race data service if configured."""
        if self._race_service_injected:
            return self._race_service
        if self._race_service is not None:
            if getattr(self._race_service, "bars_cache", None) is None and self._bars_cache is not None:
                self._race_service.bars_cache = self._bars_cache
            provider_key = self._config.provider
            if self._orchestrator.registry.providers.has(provider_key):
                resolved_provider = self._orchestrator.registry.providers.get(provider_key)
                if self._race_service.provider is not resolved_provider:
                    self._init_presentation_services(provider=resolved_provider)
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

    @property
    def is_cached(self) -> bool:
        """Return True if active dataset was loaded from local persistence cache."""
        return self._is_cached

    @property
    def build_status(self) -> str:
        """Return current rebuild lifecycle state: IDLE, BUILDING, READY, or FAILED."""
        return self._build_status

    @property
    def build_progress(self) -> float:
        """Return measurable rebuild progress from 0.0 to 1.0."""
        return self._build_progress

    @property
    def build_stage(self) -> str:
        """Return human-readable description of current build stage."""
        return self._build_stage

    @property
    def build_error(self) -> Optional[str]:
        """Return failure message if last build failed, otherwise None."""
        return self._build_error

    @property
    def is_building(self) -> bool:
        """Return True if a background rebuild job is actively executing."""
        if self._build_thread is not None and self._build_thread.is_alive():
            return True
        return self._build_status == "BUILDING"

    @property
    def build_thread(self) -> Optional[threading.Thread]:
        """Return the active background rebuild thread, if any."""
        return self._build_thread

    @property
    def dataset_cache(self) -> IDatasetCache:
        return self._dataset_cache

    @property
    def bars_cache(self) -> IBarsCache:
        return self._bars_cache

    def load_persisted_cache(self) -> bool:
        """Attempt to load valid persisted dataset from disk for fast startup."""
        if self._config.provider == "demo":
            return False
        cached = self._dataset_cache.load(
            exchange=self._config.exchange,
            provider=self._config.provider,
            half_year_policy=self._half_year_policy,
        )
        if cached and "dataset" in cached and cached["dataset"]:
            self._dataset = freeze_dataset(cached["dataset"])
            self._last_built_at = (
                datetime.fromisoformat(cached["saved_at"])
                if cached.get("saved_at")
                else datetime.now(timezone.utc)
            )
            self._is_cached = True
            self._build_status = "READY"
            self._build_stage = "Loaded from local cache"
            logger.info(
                "AppState: loaded valid persisted dataset (%d stocks) in fast startup mode.",
                len(self._dataset),
            )
            if self._bands_repo is None and self._orchestrator.registry.bands.has(self._config.bands_repository):
                self._bands_repo = self._orchestrator.registry.bands.get(self._config.bands_repository)

            self._init_presentation_services()
            return True
        return False

    def start_background_rebuild(
        self,
        symbols: Optional[Sequence[str]] = None,
        symbol_limit: Optional[int] = None,
        provider: Optional[str] = None,
        bands_repository: Optional[str] = None,
        force_refresh_bars: bool = False,
    ) -> Optional[threading.Thread]:
        """Initiate an asynchronous background dataset rebuild on a dedicated daemon thread."""
        if self.is_building:
            logger.warning("AppState: Rebuild already in progress. Ignoring duplicate start request.")
            return self._build_thread

        self._build_status = "BUILDING"
        self._build_progress = 0.0
        self._build_stage = "Initializing background rebuild..."
        self._build_error = None

        def _worker() -> None:
            try:
                asyncio.run(
                    self.refresh(
                        symbols=symbols,
                        symbol_limit=symbol_limit,
                        provider=provider,
                        bands_repository=bands_repository,
                        force_refresh_bars=force_refresh_bars,
                    )
                )
            except Exception as exc:
                logger.error("AppState: Background rebuild encountered error: %s", exc)
                self._build_status = "FAILED"
                self._build_error = str(exc)
                self._build_stage = f"Failed: {exc}"
            finally:
                if self._build_status != "FAILED":
                    self._build_status = "READY"
                    self._build_progress = 1.0
                    self._build_stage = "Build complete"
                self._build_thread = None

        thread = threading.Thread(target=_worker, name="yogi-background-rebuild", daemon=True)
        self._build_thread = thread
        thread.start()
        return thread

    async def refresh(
        self,
        symbols: Optional[Sequence[str]] = None,
        symbol_limit: Optional[int] = None,
        provider: Optional[str] = None,
        bands_repository: Optional[str] = None,
        force_refresh_bars: bool = False,
    ) -> None:
        """Rebuild feature dataset asynchronously and replace the reference atomically."""
        t_refresh_start = time.perf_counter()
        self._build_status = "BUILDING"
        self._build_progress = 0.0
        self._build_stage = "Rebuilding dataset..."
        self._build_error = None
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

            # Synchronize metadata repository between Demo and Live without premature mutation
            target_meta_repo = self._metadata_repo
            if target_provider == "demo" and not isinstance(self._metadata_repo, DemoMetadataRepository if "DemoMetadataRepository" in globals() else object):
                try:
                    from yogi.cockpit.demo import DemoMetadataRepository
                    target_meta_repo = DemoMetadataRepository()
                except Exception as exc:
                    logger.warning("Could not instantiate DemoMetadataRepository: %s", exc)
            elif self._config.provider == "demo" and target_provider != "demo":
                try:
                    from yogi.storage.metadata import CsvMetadataRepository
                    target_meta_repo = CsvMetadataRepository(data_dir=get_data_dir())
                except Exception as exc:
                    logger.warning("Could not instantiate CsvMetadataRepository: %s", exc)

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
                half_year_policy=self._half_year_policy,
            )

            logger.info(
                "AppState.refresh: starting dataset rebuild (target_provider='%s', target_bands='%s', symbols_count=%s, symbol_limit=%s)",
                target_provider,
                target_bands_repo,
                len(target_symbols) if target_symbols is not None else "universe",
                symbol_limit,
            )

            # Build off-thread using canonical PipelineOrchestrator
            build_kwargs = {}
            try:
                sig = inspect.signature(self._orchestrator.build_dataset)
                if "metadata_repository" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                ):
                    build_kwargs["metadata_repository"] = target_meta_repo
                if "bars_cache" in sig.parameters:
                    build_kwargs["bars_cache"] = self._bars_cache
                if "force_refresh_bars" in sig.parameters:
                    build_kwargs["force_refresh_bars"] = force_refresh_bars
                if "progress_callback" in sig.parameters:
                    def _on_prog(stage: str, pct: float, done: Optional[int] = None, total: Optional[int] = None) -> None:
                        self._build_stage = stage
                        self._build_progress = round(pct, 3)
                    build_kwargs["progress_callback"] = _on_prog
            except (ValueError, TypeError):
                pass

            try:
                raw_dataset = await asyncio.to_thread(
                    self._orchestrator.build_dataset,
                    active_config,
                    **build_kwargs,
                )
            except Exception as exc:
                elapsed = time.perf_counter() - t_refresh_start
                logger.error(
                    "AppState.refresh: build_dataset failed after %.2fs: %s. Preserving current dataset (%s, %d stocks).",
                    elapsed,
                    exc,
                    "demo" if self.is_demo else self._config.provider,
                    len(self._dataset),
                )
                self._build_status = "FAILED"
                self._build_error = str(exc)
                self._build_stage = f"Failed: {exc}"
                raise

            # Preserve state integrity: empty rebuild must not be reported as a successful LIVE transition
            if not raw_dataset and target_provider != "demo":
                from yogi.data.providers.exceptions import DataProviderError
                elapsed = time.perf_counter() - t_refresh_start
                logger.error(
                    "AppState.refresh: provider '%s' produced no usable records after %.2fs. Preserving current dataset (%s, %d stocks).",
                    target_provider,
                    elapsed,
                    "demo" if self.is_demo else self._config.provider,
                    len(self._dataset),
                )
                self._build_status = "FAILED"
                self._build_error = f"No usable records produced by provider '{target_provider}'."
                self._build_stage = "Failed: No usable records"
                raise DataProviderError(
                    f"Live dataset rebuild failed: No usable records produced by provider '{target_provider}'."
                )

            # Enrich raw_dataset with canonical timeframe universe ranks using RankingEngine
            # Matching prototype _add_ranks (all 12 canonical periods and RANK_CHG)
            if raw_dataset and hasattr(self._orchestrator, "ranking_rule") and self._orchestrator.ranking_rule:
                r_rule = self._orchestrator.ranking_rule
                tf_metrics = {
                    "D": "DROC",
                    "W": "WROC",
                    "M": "M_CUR",
                    "Q": "Q_CUR",
                    "H": "H_CUR",
                    "Y": "YROC",
                    "YTD": "YTD",
                    "3M": "3M",
                    "3Y": "3Y",
                    "4Y": "4Y",
                    "5Y": "5Y",
                    "AVG5Y": "AVG5Y",
                }
                tf_fallbacks = {
                    "M": "MROC",
                    "Q": "QROC",
                    "H": "HROC",
                    "YTD": "ROC_YTD",
                    "3M": "ROC_3M",
                    "3Y": "ROC_3Y",
                    "4Y": "ROC_4Y",
                    "5Y": "ROC_5Y",
                    "AVG5Y": "ROC_AVG5Y",
                }
                for tf, met in tf_metrics.items():
                    target_met = met
                    if not any(met in rec for rec in raw_dataset.values()):
                        fallback = tf_fallbacks.get(tf)
                        if fallback and any(fallback in rec for rec in raw_dataset.values()):
                            target_met = fallback
                        else:
                            continue

                    try:
                        rank_res = r_rule.rank(raw_dataset, metric=target_met)
                        for sym, r_val in rank_res.ranks.items():
                            if sym in raw_dataset:
                                rec_dict = dict(raw_dataset[sym])
                                rec_dict[f"RANK_{tf}"] = r_val
                                rec_dict[f"RANK_{target_met}"] = r_val
                                if tf == "M":
                                    rec_dict["RANK_M_CUR"] = r_val
                                raw_dataset[sym] = rec_dict
                    except Exception as r_exc:
                        logger.debug("Failed computing universe rank for %s (%s): %s", tf, target_met, r_exc)

                # Rank change (M_CUR vs M_P1)
                if any("M_CUR" in rec and "M_P1" in rec for rec in raw_dataset.values()):
                    try:
                        m_ranks = r_rule.rank(raw_dataset, metric="M_CUR").ranks
                        p1_ranks = r_rule.rank(raw_dataset, metric="M_P1").ranks
                        for sym in raw_dataset:
                            if sym in m_ranks and sym in p1_ranks:
                                raw_dataset[sym] = {
                                    **raw_dataset[sym],
                                    "RANK_CHG": p1_ranks[sym] - m_ranks[sym],
                                }
                    except Exception as chg_exc:
                        logger.debug("Failed computing RANK_CHG: %s", chg_exc)

            # Freeze deeply and atomically swap pointer and active components
            self._dataset = freeze_dataset(raw_dataset)
            self._last_built_at = datetime.now(timezone.utc)
            self._config = active_config
            self._metadata_repo = target_meta_repo
            self._orchestrator.metadata_repository = target_meta_repo

            # Persist live dataset to disk
            if target_provider != "demo":
                try:
                    self._dataset_cache.save(
                        dataset=raw_dataset,
                        exchange=active_config.exchange,
                        provider=active_config.provider,
                        half_year_policy=self._half_year_policy,
                        historical_years=active_config.historical_years,
                    )
                except Exception as cache_save_err:
                    logger.warning("AppState: Could not persist dataset to cache: %s", cache_save_err)
                self._is_cached = False
            else:
                self._is_cached = False

            self._build_status = "READY"
            self._build_progress = 1.0
            self._build_stage = "Build complete"
            self._build_error = None

            elapsed = time.perf_counter() - t_refresh_start
            logger.info(
                "AppState.refresh: atomically swapped active dataset to '%s' (%d stocks) in %.2fs",
                active_config.provider,
                len(self._dataset),
                elapsed,
            )

            # Clear isolated panel cache and reset dirty symbols
            with self._panel_cache_lock:
                self._dirty_symbols.clear()
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
                    bars_cache=self._bars_cache,
                )
                self._race_service = RaceDataService(
                    provider=resolved_provider,
                    dataset_provider=lambda: self._dataset,
                    bars_cache=self._bars_cache,
                    timeframe_engine=self._orchestrator.timeframe_engine,
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

    @property
    def half_year_policy(self) -> str:
        """Return the active half-year timeframe policy ('prototype' or 'calendar')."""
        return self._half_year_policy

    def _load_settings(self) -> None:
        """Load persistent cockpit application settings from storage file."""
        try:
            if self._settings_file.is_file():
                content = self._settings_file.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, dict):
                    policy = data.get("half_year_policy")
                    if policy in ("prototype", "calendar"):
                        self._half_year_policy = policy
        except Exception as exc:
            logger.warning("Could not load cockpit settings: %s", exc)

    def _save_settings(self) -> None:
        """Persist cockpit application settings atomically to local storage."""
        try:
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "half_year_policy": self._half_year_policy,
            }
            tmp_file = self._settings_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_file, self._settings_file)
        except Exception as exc:
            logger.warning("Could not persist cockpit settings: %s", exc)

    async def set_half_year_policy(self, policy: str) -> str:
        """Update and persist the active half-year timeframe policy."""
        if policy not in ("prototype", "calendar"):
            raise ValueError(
                f"Invalid half_year_policy '{policy}'. Must be 'prototype' or 'calendar'."
            )

        async with self._lock:
            self._half_year_policy = policy
            self._save_settings()

            # Synchronize active TimeframeEngine
            if hasattr(self._orchestrator.timeframe_engine, "half_year_policy"):
                self._orchestrator.timeframe_engine.half_year_policy = policy

            # Clear isolated panel cache
            with self._panel_cache_lock:
                self._panel_cache.clear()

            # If dataset is currently populated, rebuild it with the new policy
            if self._dataset:
                active_config = EngineConfig(
                    provider=self._config.provider,
                    bands_repository=self._config.bands_repository,
                    calculation_modules=self._config.calculation_modules,
                    exchange=self._config.exchange,
                    timeframes=self._config.timeframes,
                    historical_years=self._config.historical_years,
                    symbol_limit=self._config.symbol_limit,
                    symbols=self._config.symbols,
                    provider_options=dict(self._config.provider_options),
                    half_year_policy=policy,
                )
                raw_dataset = await asyncio.to_thread(
                    self._orchestrator.build_dataset,
                    active_config,
                    bars_cache=self._bars_cache,
                )
                self._dataset = freeze_dataset(raw_dataset)
                self._last_built_at = datetime.now(timezone.utc)
                self._config = active_config
                if active_config.provider != "demo":
                    try:
                        self._dataset_cache.save(
                            dataset=raw_dataset,
                            exchange=active_config.exchange,
                            provider=active_config.provider,
                            half_year_policy=policy,
                            historical_years=active_config.historical_years,
                        )
                    except Exception as cache_save_err:
                        logger.warning("AppState: Could not persist dataset to cache: %s", cache_save_err)
                    self._is_cached = False


            return self._half_year_policy

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
                    band_width=float(row[f"BAND_{tf}"]) if row.get(f"BAND_{tf}") is not None else 0.0,
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
            "QROC": row.get("QROC"),
            "HROC": row.get("HROC"),
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
            "EMA_UP_COUNT": row.get("EMA_UP_COUNT"),
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

        # 1. Instant lookup in materialized screening cohort (if not modified)
        with self._panel_cache_lock:
            is_dirty = sym in self._dirty_symbols

        if not is_dirty:
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
                logger.warning("Active bands repository '%s' not registered in orchestrator registry", bands_repo_name)
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
            half_year_policy=self._half_year_policy,
        )

        # Canonical execution through PipelineOrchestrator (do not catch provider exceptions here;
        # let them propagate un-cached to router for explicit HTTP 401/429/503 status mapping)
        records = self._orchestrator.build_dataset(
            single_config,
            bars_cache=self._bars_cache,
            metadata_repository=self._metadata_repo,
        )
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

    # -----------------------------------------------------------------------
    # Request-Scoped Screening Task & Cancellation Management
    # -----------------------------------------------------------------------

    def register_screening_task(self, request_id: str, total_count: int = 0) -> ScreeningTask:
        """Register and initialize a new screening execution task."""
        with self._screening_tasks_lock:
            self._cleanup_old_screening_tasks()
            task = ScreeningTask(
                request_id=request_id,
                status="running",
                progress=0.0,
                stage="initializing",
                message="Screening started...",
                processed_count=0,
                total_count=total_count,
            )
            self._screening_tasks[request_id] = task
            return task

    def update_screening_progress(
        self,
        request_id: str,
        progress: float,
        stage: str,
        message: str,
        processed_count: int = 0,
        total_count: int = 0,
    ) -> None:
        """Update screening task progress monotonically."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if not task or task.status in ("completed", "cancelled"):
                return
            # Guarantee monotonically non-decreasing progress clamped between 0.0 and 100.0
            clamped = min(100.0, max(task.progress, float(progress)))
            task.progress = clamped
            task.stage = stage
            task.message = message
            task.processed_count = processed_count
            if total_count > 0:
                task.total_count = total_count
            task.updated_at = time.time()

    def request_screening_cancellation(self, request_id: str) -> tuple[str, str]:
        """Request graceful cancellation of a screening task.
        
        Returns (status, message).
        Guarantees that a task that has already completed successfully is not marked cancelled.
        """
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if task is None:
                return "not_found", f"Screening request '{request_id}' not found."
            if task.status == "completed":
                return "completed", "Screening request has already completed successfully."
            if task.status in ("cancelling", "cancelled"):
                return task.status, "Screening cancellation already requested."

            task.cancel_requested = True
            task.status = "cancelling"
            task.stage = "cancelling"
            task.message = "Screening cancellation requested."
            task.cancelled_at = time.time()
            task.updated_at = time.time()
            return "cancelling", "Screening cancellation requested."

    def is_screening_cancelled(self, request_id: str) -> bool:
        """Check whether cancellation has been requested for a given screening task."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            return task.cancel_requested if task else False

    def complete_screening_task(self, request_id: str) -> None:
        """Mark a screening task as completed successfully at 100%."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if not task or task.status in ("cancelled", "cancelling"):
                return
            task.status = "completed"
            task.progress = 100.0
            task.stage = "completed"
            task.message = "Screening completed successfully."
            task.completed_at = time.time()
            task.updated_at = time.time()

    def cancel_screening_task(self, request_id: str) -> None:
        """Mark a screening task as definitively cancelled."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if not task:
                return
            task.status = "cancelled"
            task.stage = "cancelled"
            task.message = "Screening cancelled by user."
            task.cancelled_at = time.time()
            task.updated_at = time.time()

    def fail_screening_task(self, request_id: str, error_msg: str) -> None:
        """Mark a screening task as failed."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if not task:
                return
            task.status = "failed"
            task.stage = "failed"
            task.message = f"Screening failed: {error_msg}"
            task.error = error_msg
            task.updated_at = time.time()

    def get_screening_task(self, request_id: str) -> Optional[ScreeningTask]:
        """Retrieve a thread-safe snapshot of a screening task if it exists."""
        with self._screening_tasks_lock:
            task = self._screening_tasks.get(request_id)
            if task is None:
                return None
            return ScreeningTask(
                request_id=task.request_id,
                status=task.status,
                progress=task.progress,
                stage=task.stage,
                message=task.message,
                processed_count=task.processed_count,
                total_count=task.total_count,
                created_at=task.created_at,
                updated_at=task.updated_at,
                cancel_requested=task.cancel_requested,
                cancelled_at=task.cancelled_at,
                completed_at=task.completed_at,
                error=task.error,
            )

    def _cleanup_old_screening_tasks(self, max_age_seconds: float = 600.0, max_entries: int = 100) -> None:
        """Remove finished tasks older than max_age_seconds when entries exceed limit."""
        now = time.time()
        if len(self._screening_tasks) > max_entries:
            expired = [
                k for k, t in self._screening_tasks.items()
                if (now - t.updated_at) > max_age_seconds and t.status in ("completed", "cancelled", "failed")
            ]
            for k in expired:
                del self._screening_tasks[k]




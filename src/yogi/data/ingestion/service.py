"""Market data ingestion service for YOGI.

Separates market-data acquisition and persistence from pipeline orchestration:
- Determines required market-data date range, freshness, and refresh work.
- Evaluates cached bars and plans incremental or missing-data requests.
- Executes batch or individual provider requests with graceful fallbacks.
- Merges incremental updates with cached histories.
- Persists newly fetched updates through IBarsCache contract.
- Evaluates provider failure policies (systemic failure, required symbols).
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
import inspect
import logging
import time
from typing import Any, Callable, Optional, Union

from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.storage import IBarsCache
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.cache import IngestionCohort, IngestionPlan, merge_market_bars, plan_ingestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionResult(Mapping[str, Sequence[MarketBar]]):
    """Immutable result of a market data ingestion run.

    Provides dictionary-like access to symbol bars while exposing
    ingestion diagnostics such as failed symbols.
    """

    bars: Mapping[str, Sequence[MarketBar]] = field(default_factory=dict)
    failed_symbols: Sequence[tuple[str, Exception]] = field(default_factory=tuple)

    def __getitem__(self, key: str) -> Sequence[MarketBar]:
        return self.bars[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.bars)

    def __len__(self) -> int:
        return len(self.bars)

    def get(self, key: str, default: Any = None) -> Any:
        return self.bars.get(key, default)

    @property
    def failed_symbol_names(self) -> set[str]:
        """Set of symbol strings that failed during ingestion."""
        return {sym for sym, _ in self.failed_symbols}


class MarketDataIngestionService:
    """Service responsible for acquiring, updating, and caching market data bars.

    Extracts ingestion workflow out of PipelineOrchestrator to separate market-data
    acquisition and disk persistence from analytical pipeline coordination.
    """

    def __init__(self, chunk_size: int = 50) -> None:
        self.chunk_size = chunk_size

    def ingest_daily_bars(
        self,
        symbols: Sequence[str],
        provider: IDataProvider,
        exchange: str = "NSE",
        bars_cache: Optional[IBarsCache] = None,
        historical_years: int = 10,
        provider_options: Optional[Mapping[str, Any]] = None,
        progress_callback: Optional[Callable[[str, float, Optional[int], Optional[int]], None]] = None,
        force_refresh_bars: bool = False,
        as_of: Optional[Union[datetime, date, str]] = None,
        target_date: Optional[Union[datetime, date, str]] = None,
        provider_name: Optional[str] = None,
    ) -> IngestionResult:
        """Acquire historical daily bars across symbols using deterministic ingestion planning.

        Args:
            symbols: List of symbols to ingest bars for.
            provider: Resolved IDataProvider instance.
            exchange: Target stock exchange (NSE / BSE).
            bars_cache: Optional storage cache implementing IBarsCache.
            historical_years: Historical span in years for backfill.
            provider_options: Additional options (target_date, as_of, session_completed,
                              overlap_days, min_bars, holidays, end_date, require_all_symbols,
                              required_symbols).
            progress_callback: Optional progress hook (msg, fraction, current, total).
            force_refresh_bars: If True, bypass cached bars and fetch fresh from provider.
            as_of: Reference date or timestamp for evaluation.
            target_date: Explicit target date for freshness evaluation.
            provider_name: Explicit provider identifier string (defaults to provider.name).

        Returns:
            IngestionResult containing symbol bars and failure diagnostics.

        Raises:
            DataProviderError: If all symbols fail (systemic provider failure) or if any
                               symbol marked as required fails.
        """
        t_bars0 = time.perf_counter()
        daily_bars_map: dict[str, Sequence[MarketBar]] = {}
        failed_symbols: list[tuple[str, Exception]] = []
        newly_fetched_to_persist: dict[str, Sequence[MarketBar]] = {}

        opts = dict(provider_options or {})
        resolved_provider_name = provider_name or getattr(provider, "name", "unknown")

        # Resolve reference target_date for freshness evaluation
        resolved_target_date = target_date
        if resolved_target_date is None:
            resolved_target_date = as_of
        if resolved_target_date is None:
            resolved_target_date = opts.get("target_date") or opts.get("as_of")

        session_completed_opt = opts.get("session_completed")
        if session_completed_opt is not None:
            session_completed = bool(session_completed_opt)
        elif resolved_target_date is not None:
            session_completed = False
        else:
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist_tz)
            resolved_target_date = now_ist.date()
            # Indian markets close at 15:30 IST
            session_completed = (now_ist.time() >= dt_time(15, 30))

        overlap_days = int(opts.get("overlap_days", 5))
        min_bars = int(opts.get("min_bars", 60))
        holidays = opts.get("holidays", None)
        end_date = opts.get("end_date", None)

        chunk_size = self.chunk_size
        can_batch = (
            hasattr(provider, "batch_daily_history")
            and callable(getattr(provider, "batch_daily_history", None))
        )
        supports_date_range = False
        try:
            sig = inspect.signature(provider.daily_history)
            supports_date_range = "start_date" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (ValueError, TypeError):
            supports_date_range = False

        batch_supports_date_range = False
        if can_batch:
            try:
                b_sig = inspect.signature(provider.batch_daily_history)
                batch_supports_date_range = "start_date" in b_sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in b_sig.parameters.values()
                )
            except (ValueError, TypeError):
                batch_supports_date_range = False

        plan: Optional[IngestionPlan] = None
        cached_bars_store: dict[str, Sequence[MarketBar]] = {}
        if (
            bars_cache is not None
            and not force_refresh_bars
            and resolved_provider_name != "demo"
            and supports_date_range
        ):
            try:
                cached_bars_store = bars_cache.load_bars(
                    exchange=exchange,
                    provider=resolved_provider_name,
                )
                if hasattr(bars_cache, "plan_ingestion"):
                    plan = bars_cache.plan_ingestion(
                        symbols=symbols,
                        target_date=resolved_target_date,
                        exchange=exchange,
                        provider=resolved_provider_name,
                        overlap_days=overlap_days,
                        min_bars=min_bars,
                        holidays=holidays,
                        session_completed=session_completed,
                    )
                else:
                    plan = plan_ingestion(
                        symbols=symbols,
                        target_date=resolved_target_date,
                        cached_bars=cached_bars_store,
                        overlap_days=overlap_days,
                        min_bars=min_bars,
                        holidays=holidays,
                        session_completed=session_completed,
                    )
            except Exception as plan_err:
                logger.warning(
                    "MarketDataIngestionService: Ingestion planning failed (%s). Falling back to legacy download.",
                    plan_err,
                )
                plan = None

        if plan is not None:
            # -------------------------------------------------------------
            # Cohort A: UP_TO_DATE (Reuse cached bars, zero provider calls)
            # -------------------------------------------------------------
            for sym in plan.up_to_date:
                bars = cached_bars_store.get(sym)
                if bars:
                    daily_bars_map[sym] = bars

            logger.info(
                "MarketDataIngestionService: Plan generated: %d up_to_date, %d incremental, %d full_backfill",
                len(plan.up_to_date),
                len(plan.incremental),
                len(plan.full_backfill),
            )
            if progress_callback:
                progress_callback(
                    f"Market bars planned: {len(plan.up_to_date)} up to date, {len(plan.incremental)} incremental, {len(plan.full_backfill)} backfill",
                    0.20,
                    len(plan.up_to_date),
                    len(symbols),
                )

            # -------------------------------------------------------------
            # Cohort B: INCREMENTAL_UPDATE (Fetch from start_date, merge)
            # -------------------------------------------------------------
            if plan.incremental:
                # Group by start_date to allow batching where start_dates match
                incremental_by_start: dict[date, list[str]] = {}
                for sym in plan.incremental:
                    sym_plan = plan.for_symbol(sym)
                    start_d = sym_plan.start_date if sym_plan else None
                    if start_d is not None:
                        incremental_by_start.setdefault(start_d, []).append(sym)

                total_inc = len(plan.incremental)
                processed_inc = 0
                for start_d, inc_syms in incremental_by_start.items():
                    if can_batch and batch_supports_date_range and len(inc_syms) > 1:
                        for i in range(0, len(inc_syms), chunk_size):
                            chunk = inc_syms[i : i + chunk_size]
                            if progress_callback:
                                pct = 0.20 + 0.25 * (processed_inc / max(1, total_inc))
                                progress_callback(
                                    f"Downloading incremental bars ({processed_inc}/{total_inc} symbols)",
                                    pct,
                                    processed_inc,
                                    total_inc,
                                )
                            try:
                                batch_kwargs: dict[str, Any] = {
                                    "symbols": chunk,
                                    "exchange": exchange,
                                    "start_date": start_d,
                                }
                                if end_date is not None:
                                    batch_kwargs["end_date"] = end_date
                                chunk_res = provider.batch_daily_history(**batch_kwargs)

                                for sym in chunk:
                                    if sym in chunk_res and chunk_res[sym] is not None:
                                        new_bars = chunk_res[sym]
                                        merged = merge_market_bars(cached_bars_store.get(sym), new_bars)
                                        daily_bars_map[sym] = merged
                                        newly_fetched_to_persist[sym] = new_bars
                                    else:
                                        # Fallback to individual retrieval for missing batch symbol
                                        try:
                                            indiv_kwargs: dict[str, Any] = {
                                                "symbol": sym,
                                                "exchange": exchange,
                                                "start_date": start_d,
                                            }
                                            if end_date is not None:
                                                indiv_kwargs["end_date"] = end_date
                                            indiv_bars = provider.daily_history(**indiv_kwargs)
                                            merged = merge_market_bars(cached_bars_store.get(sym), indiv_bars)
                                            daily_bars_map[sym] = merged
                                            newly_fetched_to_persist[sym] = indiv_bars
                                        except Exception as sym_err:
                                            logger.warning("Incremental daily_history failed for '%s': %s", sym, sym_err)
                                            failed_symbols.append((sym, sym_err))
                            except Exception as batch_err:
                                logger.warning(
                                    "Incremental batch_daily_history failed for %d symbols: %s. Falling back to individual retrieval.",
                                    len(chunk),
                                    batch_err,
                                )
                                for sym in chunk:
                                    try:
                                        indiv_kwargs = {
                                            "symbol": sym,
                                            "exchange": exchange,
                                            "start_date": start_d,
                                        }
                                        if end_date is not None:
                                            indiv_kwargs["end_date"] = end_date
                                        indiv_bars = provider.daily_history(**indiv_kwargs)
                                        merged = merge_market_bars(cached_bars_store.get(sym), indiv_bars)
                                        daily_bars_map[sym] = merged
                                        newly_fetched_to_persist[sym] = indiv_bars
                                    except Exception as sym_err:
                                        logger.warning("Incremental daily_history failed for '%s': %s", sym, sym_err)
                                        failed_symbols.append((sym, sym_err))
                            processed_inc += len(chunk)
                    else:
                        for sym in inc_syms:
                            try:
                                indiv_kwargs = {
                                    "symbol": sym,
                                    "exchange": exchange,
                                    "start_date": start_d,
                                }
                                if end_date is not None:
                                    indiv_kwargs["end_date"] = end_date
                                indiv_bars = provider.daily_history(**indiv_kwargs)
                                merged = merge_market_bars(cached_bars_store.get(sym), indiv_bars)
                                daily_bars_map[sym] = merged
                                newly_fetched_to_persist[sym] = indiv_bars
                            except Exception as sym_err:
                                logger.warning("Incremental daily_history failed for '%s': %s", sym, sym_err)
                                failed_symbols.append((sym, sym_err))
                            processed_inc += 1

            # -------------------------------------------------------------
            # Cohort C: FULL_BACKFILL (Configured historical years)
            # -------------------------------------------------------------
            backfill_syms = list(plan.full_backfill)
            if backfill_syms:
                total_backfill = len(backfill_syms)
                processed_backfill = 0
                if can_batch and len(backfill_syms) > 1:
                    for i in range(0, len(backfill_syms), chunk_size):
                        chunk = backfill_syms[i : i + chunk_size]
                        if progress_callback:
                            pct = 0.45 + 0.25 * (processed_backfill / max(1, total_backfill))
                            progress_callback(
                                f"Downloading backfill bars ({processed_backfill}/{total_backfill} symbols)",
                                pct,
                                processed_backfill,
                                total_backfill,
                            )
                        try:
                            chunk_res = provider.batch_daily_history(
                                symbols=chunk,
                                exchange=exchange,
                                years=historical_years,
                            )
                            for sym in chunk:
                                if sym in chunk_res and chunk_res[sym] is not None:
                                    bars = chunk_res[sym]
                                    daily_bars_map[sym] = bars
                                    newly_fetched_to_persist[sym] = bars
                                else:
                                    try:
                                        indiv_bars = provider.daily_history(
                                            symbol=sym,
                                            exchange=exchange,
                                            years=historical_years,
                                        )
                                        daily_bars_map[sym] = indiv_bars
                                        newly_fetched_to_persist[sym] = indiv_bars
                                    except Exception as sym_err:
                                        logger.warning("Backfill daily_history failed for '%s': %s", sym, sym_err)
                                        failed_symbols.append((sym, sym_err))
                        except Exception as batch_err:
                            logger.warning(
                                "Backfill batch_daily_history failed for %d symbols: %s. Falling back to individual retrieval.",
                                len(chunk),
                                batch_err,
                            )
                            for sym in chunk:
                                try:
                                    indiv_bars = provider.daily_history(
                                        symbol=sym,
                                        exchange=exchange,
                                        years=historical_years,
                                    )
                                    daily_bars_map[sym] = indiv_bars
                                    newly_fetched_to_persist[sym] = indiv_bars
                                except Exception as sym_err:
                                    logger.warning("Backfill daily_history failed for '%s': %s", sym, sym_err)
                                    failed_symbols.append((sym, sym_err))
                        processed_backfill += len(chunk)
                else:
                    for sym in backfill_syms:
                        try:
                            indiv_bars = provider.daily_history(
                                symbol=sym,
                                exchange=exchange,
                                years=historical_years,
                            )
                            daily_bars_map[sym] = indiv_bars
                            newly_fetched_to_persist[sym] = indiv_bars
                        except Exception as sym_err:
                            logger.warning("Backfill daily_history failed for '%s': %s", sym, sym_err)
                            failed_symbols.append((sym, sym_err))
                        processed_backfill += 1
        else:
            # Fallback / un-cached / demo / legacy provider path: reuse cached bars if available
            symbols_to_download = list(symbols)
            if bars_cache is not None and not force_refresh_bars and resolved_provider_name != "demo":
                try:
                    cached_bars, missing = bars_cache.get_bars_for_symbols(
                        symbols=symbols,
                        exchange=exchange,
                        provider=resolved_provider_name,
                        min_bars=min_bars,
                    )
                    daily_bars_map.update(cached_bars)
                    symbols_to_download = missing
                    logger.info(
                        "MarketDataIngestionService: reused %d symbols from cache, %d to download",
                        len(cached_bars),
                        len(symbols_to_download),
                    )
                except Exception as cache_err:
                    logger.warning("MarketDataIngestionService: Could not load bars from cache: %s", cache_err)
                    symbols_to_download = list(symbols)

            total_dl = len(symbols_to_download)
            if can_batch and len(symbols_to_download) > 1:
                for chunk_idx, i in enumerate(range(0, len(symbols_to_download), chunk_size)):
                    chunk = symbols_to_download[i : i + chunk_size]
                    if progress_callback:
                        pct = 0.10 + 0.58 * (i / max(1, total_dl))
                        progress_callback(
                            f"Downloading market bars ({i}/{total_dl} symbols)",
                            pct,
                            i,
                            total_dl,
                        )
                    try:
                        chunk_bars = provider.batch_daily_history(
                            symbols=chunk,
                            exchange=exchange,
                            years=historical_years,
                        )
                        for sym in chunk:
                            if sym in chunk_bars and chunk_bars[sym] is not None:
                                daily_bars_map[sym] = chunk_bars[sym]
                                newly_fetched_to_persist[sym] = chunk_bars[sym]
                            else:
                                try:
                                    indiv_bars = provider.daily_history(
                                        symbol=sym,
                                        exchange=exchange,
                                        years=historical_years,
                                    )
                                    daily_bars_map[sym] = indiv_bars
                                    newly_fetched_to_persist[sym] = indiv_bars
                                except Exception as sym_err:
                                    logger.warning("Daily history failed for '%s': %s", sym, sym_err)
                                    failed_symbols.append((sym, sym_err))
                    except Exception as batch_err:
                        logger.warning(
                            "MarketDataIngestionService: chunk failed: %s. Falling back to individual retrieval.",
                            batch_err,
                        )
                        for sym in chunk:
                            try:
                                indiv_bars = provider.daily_history(
                                    symbol=sym,
                                    exchange=exchange,
                                    years=historical_years,
                                )
                                daily_bars_map[sym] = indiv_bars
                                newly_fetched_to_persist[sym] = indiv_bars
                            except Exception as sym_err:
                                logger.warning("Daily history failed for '%s': %s", sym, sym_err)
                                failed_symbols.append((sym, sym_err))
            elif symbols_to_download:
                for s_idx, sym in enumerate(symbols_to_download, 1):
                    if progress_callback and (s_idx % 25 == 0 or s_idx == total_dl):
                        pct = 0.10 + 0.58 * (s_idx / total_dl)
                        progress_callback(
                            f"Downloading market bars ({s_idx}/{total_dl} symbols)",
                            pct,
                            s_idx,
                            total_dl,
                        )
                    try:
                        indiv_bars = provider.daily_history(
                            symbol=sym,
                            exchange=exchange,
                            years=historical_years,
                        )
                        daily_bars_map[sym] = indiv_bars
                        newly_fetched_to_persist[sym] = indiv_bars
                    except Exception as sym_err:
                        logger.warning("Daily history failed for '%s': %s", sym, sym_err)
                        failed_symbols.append((sym, sym_err))

        # Save newly downloaded bars to cache (merging with existing cache on disk)
        if bars_cache is not None and resolved_provider_name != "demo" and newly_fetched_to_persist:
            try:
                bars_cache.save_bars(
                    newly_fetched_to_persist,
                    exchange=exchange,
                    provider=resolved_provider_name,
                )
            except Exception as cache_err:
                logger.warning("MarketDataIngestionService: Could not persist bars to cache: %s", cache_err)

        logger.info(
            "MarketDataIngestionService: completed in %.2fs (loaded: %d, failed: %d)",
            time.perf_counter() - t_bars0,
            len(daily_bars_map),
            len(failed_symbols),
        )

        # Systemic provider failure: if symbols were requested and every single symbol failed
        if symbols and len(failed_symbols) == len(symbols):
            first_err = failed_symbols[0][1] if failed_symbols else "all symbols failed"
            raise DataProviderError(
                f"Data provider '{resolved_provider_name}' systemic failure: all {len(symbols)} symbols failed ({first_err})"
            )

        # Required symbols failure: if configured to require all symbols
        require_all = bool(opts.get("require_all_symbols", False))
        if require_all and failed_symbols:
            first_sym, first_err = failed_symbols[0]
            raise DataProviderError(
                f"Data provider '{resolved_provider_name}' failed for required symbol '{first_sym}': {first_err}"
            )

        req_syms = opts.get("required_symbols")
        if req_syms and isinstance(req_syms, (list, tuple, set)):
            req_set = {str(s).strip().upper() for s in req_syms}
            for sym, err in failed_symbols:
                if sym in req_set:
                    raise DataProviderError(
                        f"Data provider '{resolved_provider_name}' failed for required symbol '{sym}': {err}"
                    )

        return IngestionResult(
            bars=daily_bars_map,
            failed_symbols=tuple(failed_symbols),
        )

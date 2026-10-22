import logging
import time
from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.filter import FilterGroupSpec, FilterRuleSpec, IFilterRule, ScreeningCancelledError
from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.ranking import IRankingRule, RankingMethod
from yogi.core.contracts.results import IResultAssembler, QueryResultPayload
from yogi.core.contracts.security import ISecurityMetadataRepository, InstrumentType
from yogi.core.contracts.selection import ISelectionRule, SelectionMode
from yogi.core.contracts.storage import IBarsCache
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.core.registry.hub import RegistryHub
from yogi.data.ingestion import IngestionResult, MarketDataIngestionService
from yogi.data.providers.exceptions import DataProviderError

logger = logging.getLogger(__name__)


def _extract_dynamic_rules(group: Optional[Union[FilterRuleSpec, FilterGroupSpec]]) -> list[FilterRuleSpec]:
    """Recursively extract all FilterRuleSpec instances configured with a dynamic condition_type."""
    rules: list[FilterRuleSpec] = []
    if group is None:
        return rules
    if isinstance(group, FilterRuleSpec):
        if getattr(group, "condition_type", None) is not None:
            rules.append(group)
        return rules
    if isinstance(group, FilterGroupSpec):
        for r in group.rules:
            if isinstance(r, FilterRuleSpec):
                if getattr(r, "condition_type", None) is not None:
                    rules.append(r)
            elif isinstance(r, FilterGroupSpec):
                rules.extend(_extract_dynamic_rules(r))
    return rules


def _resolve_precalculated_field(rule: FilterRuleSpec, sample_rec: Mapping[str, Any]) -> Optional[str]:
    """Check if a dynamic rule maps to an existing precalculated metric in records.

    Returns the precalculated field name in sample_rec if an exact mathematical
    match exists, otherwise None.
    """
    if not sample_rec:
        return None

    # 1. Exact field name already present in records
    if rule.field and rule.field in sample_rec:
        return rule.field

    # 2. Standard EMA 3/5 on supported timeframes with default forming candle semantics
    if rule.condition_type == "ema":
        tf = (rule.timeframe or (rule.params.get("timeframe") if rule.params else None) or "D").strip().upper()
        p1 = rule.p1 if rule.p1 is not None else (rule.params.get("p1") if rule.params else None)
        p2 = rule.p2 if rule.p2 is not None else (rule.params.get("p2") if rule.params else None)
        params = rule.params or {}

        if (p1, p2) in ((3, 5), (5, 3)) and tf in ("D", "W", "M", "Q", "H", "Y"):
            if not params.get("closed_candle_only", False):
                precalc_key = f"EMA_{tf}"
                if precalc_key in sample_rec:
                    return precalc_key

    return None


# Backward compatibility alias
_extract_dynamic_ema_rules = _extract_dynamic_rules


def _freeze_param_val(val: Any) -> Any:
    """Recursively convert parameter values into an immutable, deterministically sorted representation."""
    if isinstance(val, Mapping):
        return tuple(sorted((str(k), _freeze_param_val(v)) for k, v in val.items()))
    elif isinstance(val, (list, tuple)):
        return tuple(_freeze_param_val(x) for x in val)
    elif isinstance(val, (set, frozenset)):
        return tuple(sorted(_freeze_param_val(x) for x in val))
    return val


def _extract_calc_param_key(rule: FilterRuleSpec) -> tuple[tuple[str, Any], ...]:
    """Extract and normalize all calculation-affecting parameters from a dynamic filter rule."""
    c_type = (rule.condition_type or "").lower()
    p_dict = dict(rule.params) if rule.params else {}
    # Remove metadata that only affects filter qualification, not calculation
    p_dict.pop("state", None)
    p_dict.pop("timeframe", None)

    if c_type == "ema":
        p1 = rule.p1 if rule.p1 is not None else p_dict.get("p1")
        p2 = rule.p2 if rule.p2 is not None else p_dict.get("p2")
        if p1 is not None:
            p_dict["p1"] = int(p1)
        if p2 is not None:
            p_dict["p2"] = int(p2)
    elif c_type == "roc":
        period = getattr(rule, "period", None) or p_dict.get("period")
        if period is None and getattr(rule, "field", None):
            f = str(rule.field).strip()
            if f.upper().startswith("ROC_"):
                period = f[4:].lower()
        if period is not None:
            p_dict["period"] = str(period).lower()

    return tuple(sorted((str(k), _freeze_param_val(v)) for k, v in p_dict.items()))



class PipelineOrchestrator:
    """Coordinates execution across Registry capabilities and screening contract stages.

    Adheres strictly to the architectural discipline:
    - Pure coordinator: contains NO financial formulas, NO filtering math, NO ranking
      algorithms, NO selection logic, NO timeframe resampling, and NO persistence.
    - Resolves replaceable capabilities (provider, bands, calculations) exclusively via RegistryHub.
    - Sequences data acquisition and calculations into canonical in-memory records.
    - Executes screening intent adhering strictly to QUALIFY -> ORDER -> SHOW -> RESULTS.
    """

    def __init__(
        self,
        registry: RegistryHub,
        filter_rule: Optional[IFilterRule] = None,
        ranking_rule: Optional[IRankingRule] = None,
        selection_rule: Optional[ISelectionRule] = None,
        result_assembler: Optional[IResultAssembler] = None,
        timeframe_engine: Optional[ITimeframeEngine] = None,
        metadata_repository: Optional[ISecurityMetadataRepository] = None,
        ingestion_service: Optional[MarketDataIngestionService] = None,
        bars_cache: Optional[IBarsCache] = None,
    ) -> None:
        self.registry = registry
        self.filter_rule = filter_rule
        self.ranking_rule = ranking_rule
        self.selection_rule = selection_rule
        self.result_assembler = result_assembler
        self.timeframe_engine = timeframe_engine
        self.metadata_repository = metadata_repository
        self.ingestion_service = ingestion_service or MarketDataIngestionService()
        self.bars_cache = bars_cache

    def build_dataset(
        self,
        config: EngineConfig,
        timeframe_engine: Optional[ITimeframeEngine] = None,
        metadata_repository: Optional[ISecurityMetadataRepository] = None,
        bars_cache: Optional[IBarsCache] = None,
        progress_callback: Optional[Callable[[str, float, Optional[int], Optional[int]], None]] = None,
        force_refresh_bars: bool = False,
        as_of: Optional[Union[datetime, date, str]] = None,
        target_date: Optional[Union[datetime, date, str]] = None,
        ingestion_service: Optional[MarketDataIngestionService] = None,
    ) -> Mapping[str, Mapping[str, Any]]:
        """Coordinate data acquisition and calculation module execution across the universe.

        Execution sequence:
        1. Resolve IDataProvider, IBandsRepository, and ICalcModule list via RegistryHub.get().
        2. Acquire universe symbols (respecting config.symbols override and config.symbol_limit).
        3. Acquire historical daily bars for each symbol.
        4. Construct MarketContext holding the available bars.
        5. Retrieve band definitions and filter out None values for CalculationContext.
        6. Dispatch each configured calculation module and merge CalculationResult.metrics.
        7. Produce canonical feature records keyed by symbol.
        """
        t_start = time.perf_counter()
        logger.info(
            "PipelineOrchestrator: build_dataset started (provider='%s', exchange='%s', requested_symbols=%s, limit=%s)",
            config.provider,
            config.exchange,
            len(config.symbols) if config.symbols is not None else "universe",
            config.symbol_limit,
        )

        tf_engine = timeframe_engine if timeframe_engine is not None else self.timeframe_engine
        if tf_engine is None:
            raise ValueError("ITimeframeEngine implementation is required to build dataset.")

        meta_repo = metadata_repository if metadata_repository is not None else self.metadata_repository
        ingest_svc = ingestion_service if ingestion_service is not None else self.ingestion_service

        # 1. Resolve capabilities via RegistryHub (.get() method)
        provider: IDataProvider = self.registry.providers.get(config.provider)
        bands_repo: IBandsRepository = self.registry.bands.get(config.bands_repository)
        calc_modules: Sequence[ICalcModule] = [
            self.registry.calculations.get(mod_key) for mod_key in config.calculation_modules
        ]

        # 2. Acquire universe symbols
        if progress_callback:
            progress_callback("Discovering universe symbols...", 0.05, 0, None)
        t_u0 = time.perf_counter()
        if config.symbols is not None:
            symbols: Sequence[str] = config.symbols
        else:
            symbols = provider.universe(exchange=config.exchange)

        # Apply symbol limit
        if config.symbol_limit is not None:
            symbols = symbols[: config.symbol_limit]

        logger.info(
            "PipelineOrchestrator Stage 1/3 (Universe): resolved %d symbols in %.2fs",
            len(symbols),
            time.perf_counter() - t_u0,
        )
        if progress_callback:
            progress_callback(f"Resolved universe: {len(symbols)} symbols", 0.10, 0, len(symbols))

        # Resolve timeframe engine half-year policy once outside the universe symbol loop
        h_policy = getattr(config, "half_year_policy", None)

        # 3. Acquire historical daily bars across symbols via MarketDataIngestionService
        t_bars0 = time.perf_counter()
        ingestion_res = ingest_svc.ingest_daily_bars(
            symbols=symbols,
            provider=provider,
            exchange=config.exchange,
            bars_cache=bars_cache,
            historical_years=config.historical_years,
            provider_options=config.provider_options,
            progress_callback=progress_callback,
            force_refresh_bars=force_refresh_bars,
            as_of=as_of or getattr(config, "as_of", None),
            target_date=target_date or getattr(config, "target_date", None),
            provider_name=config.provider,
        )

        daily_bars_map = ingestion_res.bars
        failed_symbols = list(ingestion_res.failed_symbols)
        logger.info(
            "PipelineOrchestrator Stage 2/3 (Market Bars): acquired bars for %d symbols (failed: %d) in %.2fs",
            len(daily_bars_map),
            len(failed_symbols),
            time.perf_counter() - t_bars0,
        )

        failed_sym_set = {s for s, _ in failed_symbols}
        calculated_records: dict[str, dict[str, Any]] = {}
        active_calc_symbols = [s for s in symbols if s not in failed_sym_set]

        # 4. Process each symbol
        t_calc0 = time.perf_counter()
        total_calc = len(active_calc_symbols)
        logger.info(
            "PipelineOrchestrator Stage 3/3 (Calculations): calculating features for %d symbols across %d modules...",
            total_calc,
            len(calc_modules),
        )

        for c_idx, symbol in enumerate(active_calc_symbols, 1):
            if progress_callback and (c_idx % 50 == 0 or c_idx == total_calc):
                pct = 0.70 + 0.28 * (c_idx / max(1, total_calc))
                progress_callback(
                    f"Computing features ({c_idx}/{total_calc} symbols)",
                    pct,
                    c_idx,
                    total_calc,
                )
            daily_bars: Sequence[MarketBar] = daily_bars_map.get(symbol, ())

            # Extract price safely guarding against empty history
            price: Optional[float] = daily_bars[-1].close if daily_bars else None

            # Construct MarketContext via Timeframe Engine
            market_ctx = tf_engine.build_context(
                symbol=symbol,
                exchange=config.exchange,
                daily_bars=daily_bars,
                timeframes=config.timeframes,
                half_year_policy=h_policy,
            )

            # Retrieve bands and filter out None values for CalculationContext.bands_lookup
            all_bands = bands_repo.get_all_bands(symbol)
            bands_lookup: dict[str, float] = {
                tf: val for tf, val in all_bands.items() if val is not None
            }

            # Construct CalculationContext
            if h_policy and h_policy != "prototype":
                calc_params = dict(config.provider_options)
                calc_params.setdefault("half_year_policy", h_policy)
            else:
                calc_params = config.provider_options

            calc_ctx = CalculationContext(
                market_context=market_ctx,
                bands_lookup=bands_lookup if bands_lookup else None,
                parameters=calc_params,
            )

            # Initialize canonical base record with metadata enrichment
            sec = meta_repo.get_metadata(symbol=symbol, exchange=config.exchange) if meta_repo else None
            is_fno = (sec.is_fno if sec else False) or (meta_repo.is_fno(symbol) if meta_repo else False)

            symbol_metrics: dict[str, Any] = {
                "symbol": symbol,
                "exchange": config.exchange,
                "price": price,
                "name": sec.name if (sec and sec.name) else symbol,
                "sector": sec.sector if sec else None,
                "grade": sec.grade if sec else None,
                "mcap": sec.mcap if sec else None,
                "fno": "Y" if is_fno else "N",
                "instr": sec.instrument_type.value if sec else InstrumentType.UNKNOWN.value,
                "grp": sec.series_or_group if (sec and sec.series_or_group) else "",
            }

            # Dispatch each configured calculation module and merge metrics
            for module in calc_modules:
                res: CalculationResult = module.calculate(symbol=symbol, context=calc_ctx)
                symbol_metrics.update(res.metrics)

            calculated_records[symbol] = symbol_metrics

        elapsed_calc = time.perf_counter() - t_calc0
        elapsed_total = time.perf_counter() - t_start
        logger.info(
            "PipelineOrchestrator Stage 3/3 (Calculations): completed in %.2fs. Total build_dataset time: %.2fs (%d records produced)",
            elapsed_calc,
            elapsed_total,
            len(calculated_records),
        )

        if progress_callback:
            progress_callback("Dataset build complete", 1.0, len(calculated_records), len(symbols))

        # Preserve clear failure behavior if symbols were requested but no usable records were built
        if symbols and not calculated_records and failed_symbols:
            first_err = failed_symbols[0][1] if failed_symbols else "no usable records"
            raise DataProviderError(
                f"Data provider '{config.provider}' failed to produce usable data: {first_err}"
            )

        return calculated_records

    def _find_calc_module_for_condition(self, condition_type: str) -> Optional[ICalcModule]:
        """Resolve an ICalcModule from registry that supports the given dynamic condition type."""
        if self.registry and hasattr(self.registry, "calculations"):
            for calc in self.registry.calculations.all().values():
                if hasattr(calc, "supports_condition") and calc.supports_condition(condition_type):
                    return calc
        return None

    def execute_screen(
        self,
        query: ScreeningQuery,
        records: Mapping[str, Mapping[str, Any]],
        filter_rule: Optional[IFilterRule] = None,
        ranking_rule: Optional[IRankingRule] = None,
        selection_rule: Optional[ISelectionRule] = None,
        result_assembler: Optional[IResultAssembler] = None,
        bars_cache: Optional[IBarsCache] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[float, str, str, int, int], None]] = None,
    ) -> QueryResultPayload:
        """Execute an analytical screening query strictly adhering to QUALIFY -> ORDER -> SHOW -> RESULTS.

        Stage boundaries:
        - QUALIFY: Evaluates query.filter_group via IFilterRule.
        - ORDER:   Evaluates query.ranking_metric via IRankingRule.
        - SHOW:    Evaluates query.selection_cutoffs via ISelectionRule.
        - RESULTS: Applies query.limit row cap, then packages payload via IResultAssembler.
        """
        f_rule = filter_rule if filter_rule is not None else self.filter_rule
        r_rule = ranking_rule if ranking_rule is not None else self.ranking_rule
        s_rule = selection_rule if selection_rule is not None else self.selection_rule
        assembler = (
            result_assembler
            if result_assembler is not None
            else self.result_assembler
        )

        universe_count = len(records)

        if cancel_check and cancel_check():
            raise ScreeningCancelledError("Screening cancelled before evaluation.")
        if progress_callback:
            progress_callback(0.0, "initializing", "Initializing screening...", 0, universe_count)

        # -------------------------------------------------------------------
        # 1. QUALIFY (Filter Engine)
        # -------------------------------------------------------------------
        if query.filter_group is not None:
            if f_rule is None:
                raise ValueError("IFilterRule implementation is required when query has a filter_group.")

            # Dynamic on-demand evaluation of arbitrary dynamic conditions
            dynamic_rules = _extract_dynamic_rules(query.filter_group)
            if dynamic_rules and self.timeframe_engine is not None and records:
                effective_cache = bars_cache or self.bars_cache
                enriched_records: dict[str, dict[str, Any]] = {
                    sym: dict(rec) for sym, rec in records.items()
                }
                symbols = list(records.keys())

                sample_sym = symbols[0] if symbols else ""
                sample_rec = records.get(sample_sym, {})
                ex = sample_rec.get("exchange", "NSE")
                pv = sample_rec.get("provider", "demo" if sample_rec.get("price") is not None and "DEMO" in str(sample_rec.get("name", "")).upper() else "yfinance")

                # Separate dynamic rules into those resolvable from precalculated records vs genuinely dynamic
                rules_to_calculate: list[tuple[FilterRuleSpec, str, Optional[str], str]] = []
                for rule in dynamic_rules:
                    tf = (rule.timeframe or (rule.params.get("timeframe") if rule.params else None) or "D").strip().upper()
                    param_key = _extract_calc_param_key(rule)
                    p_dict = dict(param_key)
                    c_type_upper = (rule.condition_type or "").upper()

                    if rule.condition_type == "ema" and "p1" in p_dict and "p2" in p_dict:
                        default_key = f"EMA_{tf}_{p_dict['p1']}_{p_dict['p2']}"
                    elif rule.condition_type == "roc" and "period" in p_dict:
                        default_key = f"ROC_{tf}_{p_dict['period']}"
                    elif param_key:
                        param_str = "_".join(f"{k}_{v}" for k, v in param_key if isinstance(v, (str, int, float, bool)))
                        default_key = f"{c_type_upper}_{tf}_{param_str}"
                    else:
                        default_key = f"{c_type_upper}_{tf}"

                    field_key = rule.field or default_key
                    canonical_key = default_key if (rule.field and rule.field != default_key) else None

                    precalc_key = _resolve_precalculated_field(rule, sample_rec)
                    if precalc_key is not None:
                        # Precalculated metric available: map directly across all symbols without disk reads or recalculation
                        for sym in symbols:
                            sym_rec = records.get(sym, {})
                            val = sym_rec.get(precalc_key)
                            enriched_records[sym][field_key] = val
                            if canonical_key:
                                enriched_records[sym][canonical_key] = val
                    else:
                        rules_to_calculate.append((rule, field_key, canonical_key, tf))

                # Batch lookup daily bars from cache only if there are rules requiring calculation
                daily_bars_map: dict[str, Sequence[MarketBar]] = {}
                if rules_to_calculate and effective_cache is not None:
                    if hasattr(effective_cache, "get_bars_for_symbols"):

                        def _on_bars_prog(curr: int, tot: int) -> None:
                            if progress_callback:
                                pct = 15.0 * (curr / max(1, tot))
                                progress_callback(
                                    pct,
                                    "fetching_bars",
                                    f"Loading market bars ({curr}/{tot})",
                                    curr,
                                    tot,
                                )

                        try:
                            found, _ = effective_cache.get_bars_for_symbols(
                                symbols=symbols,
                                exchange=ex,
                                provider=pv,
                                min_bars=2,
                                cancel_check=cancel_check,
                                progress_callback=_on_bars_prog,
                            )
                            daily_bars_map = found
                        except TypeError:
                            found, _ = effective_cache.get_bars_for_symbols(
                                symbols=symbols,
                                exchange=ex,
                                provider=pv,
                                min_bars=2,
                            )
                            daily_bars_map = found
                        except ScreeningCancelledError:
                            raise
                        except Exception as cache_err:
                            logger.debug("execute_screen: bars_cache batch lookup failed: %s", cache_err)

                        # For any symbol missing from batch lookup, try fallback
                        for sym in symbols:
                            if cancel_check and cancel_check():
                                raise ScreeningCancelledError("Screening cancelled during bar retrieval fallback.")
                            if sym not in daily_bars_map:
                                try:
                                    f_single, _ = effective_cache.get_bars_for_symbols([sym], exchange="NSE", min_bars=2)
                                    if f_single and sym in f_single:
                                        daily_bars_map[sym] = f_single[sym]
                                    elif hasattr(effective_cache, "get_bars"):
                                        f_b = effective_cache.get_bars(sym, exchange="NSE")
                                        if f_b:
                                            daily_bars_map[sym] = f_b
                                except Exception as fallback_err:
                                    logger.warning("execute_screen: fallback bar lookup failed for symbol '%s': %s", sym, fallback_err)
                    elif isinstance(effective_cache, Mapping):
                        daily_bars_map = {s: effective_cache[s] for s in symbols if s in effective_cache}

                # Evaluate dynamic indicator signals for each symbol and dynamic rule that needs calculation
                total_rules = len(rules_to_calculate)
                total_symbols = len(symbols)
                total_calcs = total_rules * total_symbols
                completed_calcs = 0

                # Request-scoped execution caches with bounded lifetime
                req_ctx_cache: dict[tuple[str, str, str], MarketContext] = {}
                req_series_cache: dict[tuple[str, str], Any] = {}
                req_ema_cache: dict[tuple[int, int], Any] = {}
                req_sig_cache: dict[tuple[str, str, str, str, tuple[tuple[str, Any], ...]], Any] = {}

                for rule, field_key, canonical_key, tf in rules_to_calculate:
                    calc_module = self._find_calc_module_for_condition(rule.condition_type)
                    if calc_module is None:
                        raise ValueError(
                            f"No calculation module registered supporting condition_type '{rule.condition_type}'"
                        )

                    p1 = rule.p1 if rule.p1 is not None else (rule.params.get("p1") if rule.params else None)
                    p2 = rule.p2 if rule.p2 is not None else (rule.params.get("p2") if rule.params else None)

                    if p1 is not None and p2 is not None:
                        rule_label = f"{rule.condition_type.upper()} {tf}({p1},{p2})"
                    elif p1 is not None:
                        rule_label = f"{rule.condition_type.upper()} {tf}({p1})"
                    else:
                        rule_label = f"{rule.condition_type.upper()} {tf}"

                    stage_name = f"calculating_{rule.condition_type}"
                    param_key = _extract_calc_param_key(rule)

                    for s_idx, sym in enumerate(symbols):
                        if cancel_check and (s_idx % 25 == 0 or s_idx == total_symbols - 1):
                            if cancel_check():
                                raise ScreeningCancelledError("Screening cancelled during dynamic indicator calculation.")

                        completed_calcs += 1
                        if progress_callback and (completed_calcs % 50 == 0 or completed_calcs == total_calcs):
                            pct = 15.0 + 77.0 * (completed_calcs / max(1, total_calcs))
                            progress_callback(
                                pct,
                                stage_name,
                                f"Calculating {rule_label} ({completed_calcs}/{total_calcs})",
                                completed_calcs,
                                total_calcs,
                            )

                        if field_key in enriched_records[sym]:
                            continue
                        if canonical_key and canonical_key in enriched_records[sym]:
                            enriched_records[sym][field_key] = enriched_records[sym][canonical_key]
                            continue
                        if sym in records and (field_key in records[sym] or (canonical_key and canonical_key in records[sym])):
                            val = records[sym].get(field_key) if field_key in records[sym] else records[sym].get(canonical_key)
                            enriched_records[sym][field_key] = val
                            if canonical_key:
                                enriched_records[sym][canonical_key] = val
                            continue

                        sym_rec = records.get(sym, {})
                        sym_ex = (sym_rec.get("exchange") or ex or "NSE").strip().upper()

                        daily_b = daily_bars_map.get(sym)
                        if daily_b:
                            sig_key = (sym_ex, sym, rule.condition_type, tf, param_key)
                            if sig_key in req_sig_cache:
                                sig = req_sig_cache[sig_key]
                            else:
                                ctx_key = (sym_ex, sym, tf)
                                market_ctx = req_ctx_cache.get(ctx_key)
                                if market_ctx is None:
                                    target_tfs = ["D"] if tf == "D" else [tf, "D"]
                                    market_ctx = self.timeframe_engine.build_context(
                                        symbol=sym,
                                        exchange=sym_ex,
                                        daily_bars=daily_b,
                                        timeframes=target_tfs,
                                    )
                                    req_ctx_cache[ctx_key] = market_ctx

                                calc_ctx = CalculationContext(
                                    market_context=market_ctx,
                                    parameters={
                                        "series_cache": req_series_cache,
                                        "ema_cache": req_ema_cache,
                                    },
                                )
                                try:
                                    sig = calc_module.calculate_dynamic(symbol=sym, rule=rule, context=calc_ctx)
                                    req_sig_cache[sig_key] = sig
                                except Exception as calc_err:
                                    logger.error(
                                        "execute_screen: calculation module '%s' failed for symbol '%s' and rule %s: %s",
                                        getattr(calc_module, "name", type(calc_module).__name__),
                                        sym,
                                        rule,
                                        calc_err,
                                    )
                                    raise
                        else:
                            sig = None

                        enriched_records[sym][field_key] = sig
                        if canonical_key:
                            enriched_records[sym][canonical_key] = sig

                if cancel_check and cancel_check():
                    raise ScreeningCancelledError("Screening cancelled before filtering.")
                if progress_callback:
                    progress_callback(93.0, "filtering", "Evaluating filter rules...", len(enriched_records), universe_count)

                eval_result = f_rule.evaluate(records=enriched_records, spec=query.filter_group)
                source_records = enriched_records
            else:
                if cancel_check and cancel_check():
                    raise ScreeningCancelledError("Screening cancelled before filtering.")
                if progress_callback:
                    progress_callback(50.0, "filtering", "Evaluating filter rules...", universe_count, universe_count)

                eval_result = f_rule.evaluate(records=records, spec=query.filter_group)
                source_records = records

            qualified_records: dict[str, Mapping[str, Any]] = {
                sym: source_records[sym]
                for sym in eval_result.matching_symbols
                if sym in source_records
            }
            qualified_count = eval_result.matched_count
        else:
            if cancel_check and cancel_check():
                raise ScreeningCancelledError("Screening cancelled before assembly.")
            qualified_records = dict(records)
            qualified_count = universe_count

        # -------------------------------------------------------------------
        # 2. ORDER (Ranking Engine)
        # -------------------------------------------------------------------
        if cancel_check and cancel_check():
            raise ScreeningCancelledError("Screening cancelled before ranking.")
        if progress_callback:
            progress_callback(96.0, "ranking", "Ranking qualified stocks...", qualified_count, universe_count)

        if query.ranking_metric is not None and qualified_records:
            if r_rule is None:
                raise ValueError("IRankingRule implementation is required when query specifies ranking_metric.")
            rank_result = r_rule.rank(
                records=qualified_records,
                metric=query.ranking_metric,
                order=query.ranking_order,
                method=RankingMethod.MIN,
            )
            # Inject dynamic cohort ranks into ranked records ordered by assigned rank
            sorted_symbols = sorted(
                (sym for sym in qualified_records if sym in rank_result.ranks),
                key=lambda s: rank_result.ranks[s],
            )
            rank_col_name = (
                query.ranking_metric
                if query.ranking_metric.startswith("RANK_")
                else f"RANK_{query.ranking_metric}"
            )
            ranked_records: dict[str, Mapping[str, Any]] = {
                sym: {**qualified_records[sym], rank_col_name: rank_result.ranks[sym]}
                for sym in sorted_symbols
            }
        else:
            ranked_records = qualified_records

        # -------------------------------------------------------------------
        # 3. SHOW (Selection Engine)
        # -------------------------------------------------------------------
        if cancel_check and cancel_check():
            raise ScreeningCancelledError("Screening cancelled before selection.")
        if progress_callback:
            progress_callback(98.0, "selecting", "Applying cutoffs and limits...", len(ranked_records), universe_count)

        if query.selection_cutoffs and ranked_records:
            if s_rule is None:
                raise ValueError("ISelectionRule implementation is required when query specifies selection_cutoffs.")
            sel_mode = getattr(query, "selection_mode", SelectionMode.ALL)
            sel_result = s_rule.select(
                ranked_records=ranked_records,
                cutoffs=query.selection_cutoffs,
                mode=sel_mode,
            )
            selected_records: list[Mapping[str, Any]] = [
                ranked_records[sym]
                for sym in sel_result.selected_symbols
                if sym in ranked_records
            ]
            selected_count = sel_result.matched_count
        else:
            selected_records = list(ranked_records.values())
            selected_count = len(selected_records)

        # -------------------------------------------------------------------
        # 4. RESULTS (Result Assembly Engine)
        # -------------------------------------------------------------------
        if cancel_check and cancel_check():
            raise ScreeningCancelledError("Screening cancelled before result assembly.")
        if progress_callback:
            progress_callback(99.0, "assembling", "Assembling presentation results...", len(selected_records), universe_count)

        # Row limit cap is applied BEFORE calling assembler (assemble has no 'limit' param)
        rows_to_assemble = (
            selected_records[: query.limit]
            if query.limit is not None
            else selected_records
        )

        metadata: dict[str, Any] = {
            "universe_count": universe_count,
            "qualified_count": qualified_count,
            "selected_count": selected_count,
            "limit": query.limit,
        }
        if query.filter_group is not None and "eval_result" in locals() and eval_result.explanation:
            metadata["filter_explanation"] = eval_result.explanation

        if assembler is not None:
            assembled = assembler.assemble(
                records=rows_to_assemble,
                columns=None,
                metadata=metadata,
            )
        else:
            # Fallback payload construction if assembler is not injected
            assembled = QueryResultPayload(
                universe_count=universe_count,
                qualified_count=qualified_count,
                selected_count=selected_count,
                rows=rows_to_assemble,
                metadata=metadata,
            )

        if progress_callback:
            progress_callback(100.0, "completed", "Screening completed successfully.", selected_count, universe_count)

        return assembled

    def run(
        self,
        config: EngineConfig,
        query: Optional[ScreeningQuery] = None,
        timeframe_engine: Optional[ITimeframeEngine] = None,
    ) -> QueryResultPayload:
        """Execute end-to-end dataset building and optional screening query."""
        records = self.build_dataset(config, timeframe_engine=timeframe_engine)

        if query is not None:
            return self.execute_screen(query=query, records=records)

        # If no query provided, package entire built dataset
        rows_to_assemble = list(records.values())
        metadata: dict[str, Any] = {
            "universe_count": len(records),
            "qualified_count": len(records),
            "selected_count": len(records),
            "limit": None,
        }

        if self.result_assembler is not None:
            return self.result_assembler.assemble(
                records=rows_to_assemble,
                columns=None,
                metadata=metadata,
            )

        return QueryResultPayload(
            universe_count=len(records),
            qualified_count=len(records),
            selected_count=len(records),
            rows=rows_to_assemble,
            metadata=metadata,
        )

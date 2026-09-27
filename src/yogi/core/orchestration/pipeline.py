"""Core Pipeline Orchestrator — Capability coordination, data flow, and screening execution."""

from typing import Any, Mapping, Optional, Sequence

from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.filter import IFilterRule
from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.ranking import IRankingRule, RankingMethod
from yogi.core.contracts.results import IResultAssembler, QueryResultPayload
from yogi.core.contracts.security import ISecurityMetadataRepository, InstrumentType
from yogi.core.contracts.selection import ISelectionRule, SelectionMode
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.core.registry.hub import RegistryHub


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
    ) -> None:
        self.registry = registry
        self.filter_rule = filter_rule
        self.ranking_rule = ranking_rule
        self.selection_rule = selection_rule
        self.result_assembler = result_assembler
        self.timeframe_engine = timeframe_engine
        self.metadata_repository = metadata_repository

    def build_dataset(
        self,
        config: EngineConfig,
        timeframe_engine: Optional[ITimeframeEngine] = None,
        metadata_repository: Optional[ISecurityMetadataRepository] = None,
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
        tf_engine = timeframe_engine if timeframe_engine is not None else self.timeframe_engine
        if tf_engine is None:
            raise ValueError("ITimeframeEngine implementation is required to build dataset.")

        meta_repo = metadata_repository if metadata_repository is not None else self.metadata_repository

        # 1. Resolve capabilities via RegistryHub (.get() method)
        provider: IDataProvider = self.registry.providers.get(config.provider)
        bands_repo: IBandsRepository = self.registry.bands.get(config.bands_repository)
        calc_modules: Sequence[ICalcModule] = [
            self.registry.calculations.get(mod_key) for mod_key in config.calculation_modules
        ]

        # 2. Acquire universe symbols
        if config.symbols is not None:
            symbols: Sequence[str] = config.symbols
        else:
            symbols = provider.universe(exchange=config.exchange)

        # Apply symbol limit
        if config.symbol_limit is not None:
            symbols = symbols[: config.symbol_limit]

        calculated_records: dict[str, dict[str, Any]] = {}

        # 3. Process each symbol
        for symbol in symbols:
            daily_bars: Sequence[MarketBar] = provider.daily_history(
                symbol=symbol,
                exchange=config.exchange,
                years=config.historical_years,
            )

            # Extract price safely guarding against empty history
            price: Optional[float] = daily_bars[-1].close if daily_bars else None

            # 4. Construct MarketContext via Timeframe Engine
            market_ctx = tf_engine.build_context(
                symbol=symbol,
                exchange=config.exchange,
                daily_bars=daily_bars,
                timeframes=config.timeframes,
            )

            # 5. Retrieve bands and filter out None values for CalculationContext.bands_lookup
            all_bands = bands_repo.get_all_bands(symbol)
            bands_lookup: dict[str, float] = {
                tf: val for tf, val in all_bands.items() if val is not None
            }

            # 6. Construct CalculationContext
            calc_ctx = CalculationContext(
                market_context=market_ctx,
                bands_lookup=bands_lookup if bands_lookup else None,
                parameters=config.provider_options,
            )

            # 7. Initialize canonical base record with metadata enrichment
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

            # 8. Dispatch each configured calculation module and merge metrics
            for module in calc_modules:
                res: CalculationResult = module.calculate(symbol=symbol, context=calc_ctx)
                symbol_metrics.update(res.metrics)

            calculated_records[symbol] = symbol_metrics

        return calculated_records

    def execute_screen(
        self,
        query: ScreeningQuery,
        records: Mapping[str, Mapping[str, Any]],
        filter_rule: Optional[IFilterRule] = None,
        ranking_rule: Optional[IRankingRule] = None,
        selection_rule: Optional[ISelectionRule] = None,
        result_assembler: Optional[IResultAssembler] = None,
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

        # -------------------------------------------------------------------
        # 1. QUALIFY (Filter Engine)
        # -------------------------------------------------------------------
        if query.filter_group is not None:
            if f_rule is None:
                raise ValueError("IFilterRule implementation is required when query has a filter_group.")
            eval_result = f_rule.evaluate(records=records, spec=query.filter_group)
            qualified_records: dict[str, Mapping[str, Any]] = {
                sym: records[sym]
                for sym in eval_result.matching_symbols
                if sym in records
            }
            qualified_count = eval_result.matched_count
        else:
            qualified_records = dict(records)
            qualified_count = universe_count

        # -------------------------------------------------------------------
        # 2. ORDER (Ranking Engine)
        # -------------------------------------------------------------------
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
            ranked_records: dict[str, Mapping[str, Any]] = {
                sym: {**qualified_records[sym], f"RANK_{query.ranking_metric}": rank_result.ranks[sym]}
                for sym in sorted_symbols
            }
        else:
            ranked_records = qualified_records

        # -------------------------------------------------------------------
        # 3. SHOW (Selection Engine)
        # -------------------------------------------------------------------
        if query.selection_cutoffs and ranked_records:
            if s_rule is None:
                raise ValueError("ISelectionRule implementation is required when query specifies selection_cutoffs.")
            sel_result = s_rule.select(
                ranked_records=ranked_records,
                cutoffs=query.selection_cutoffs,
                mode=SelectionMode.ALL,
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

        if assembler is not None:
            return assembler.assemble(
                records=rows_to_assemble,
                columns=None,
                metadata=metadata,
            )

        # Fallback payload construction if assembler is not injected
        return QueryResultPayload(
            universe_count=universe_count,
            qualified_count=qualified_count,
            selected_count=selected_count,
            rows=rows_to_assemble,
            metadata=metadata,
        )

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

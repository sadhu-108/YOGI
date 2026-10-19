"""Tests for YOGI Core Orchestration — Capability Coordination and Pipeline Execution."""

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

import pytest

from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.filter import (
    FilterEvaluationResult,
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
    IFilterRule,
)
from yogi.core.contracts.market_data import MarketBar, MarketContext, Timeframe
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.ranking import IRankingRule, RankingMethod, RankingOrder, RankingResult
from yogi.core.contracts.results import ColumnDefinition, IResultAssembler, QueryResultPayload
from yogi.core.contracts.selection import ISelectionRule, RankCutoffSpec, SelectionMode, SelectionResult
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.base import RegistrationNotFoundError
from yogi.core.registry.hub import RegistryHub


# ---------------------------------------------------------------------------
# Test Mocks for Step 2 Contracts
# ---------------------------------------------------------------------------


class MockDataProvider(IDataProvider):
    """Mock provider satisfying IDataProvider contract without network calls."""

    def __init__(
        self,
        universe_symbols: Sequence[str] = ("RELIANCE", "TCS", "INFY"),
        history_map: Optional[Mapping[str, Sequence[MarketBar]]] = None,
    ) -> None:
        self._universe = universe_symbols
        self._history_map = history_map or {}
        self.recorded_calls: list[str] = []

    @property
    def name(self) -> str:
        return "mock_provider"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        self.recorded_calls.append(f"universe({exchange})")
        return self._universe

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
    ) -> Sequence[MarketBar]:
        self.recorded_calls.append(f"daily_history({symbol}, {exchange}, {years})")
        return self._history_map.get(symbol, ())

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else None

    def intraday(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 5,
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock", ok=True)


class MockBandsRepo(IBandsRepository):
    """Mock repository satisfying IBandsRepository contract."""

    def __init__(self, bands_store: Optional[Mapping[str, Mapping[str, Optional[float]]]] = None) -> None:
        self._store = bands_store or {}
        self.recorded_calls: list[str] = []

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return self._store.get(symbol, {}).get(timeframe)

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        self.recorded_calls.append(f"get_all_bands({symbol})")
        return self._store.get(symbol, {"D": 0.10, "W": 0.12, "M": None})

    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "app",
        source: str = "app",
    ) -> float:
        return value


class MockCalcModule(ICalcModule):
    """Mock calculation module satisfying ICalcModule contract."""

    def __init__(self, module_name: str, metric_payload: Mapping[str, Any]) -> None:
        self.name = module_name
        self.metric_payload = metric_payload
        self.recorded_contexts: list[CalculationContext] = []

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        self.recorded_contexts.append(context)
        return CalculationResult(
            symbol=symbol,
            module_name=self.name,
            metrics=self.metric_payload,
        )


class MockFilterRule(IFilterRule):
    """Mock qualification rule engine."""

    def __init__(self, matching_symbols: Sequence[str]) -> None:
        self.matching_symbols = matching_symbols
        self.recorded_spec: Optional[Union[FilterRuleSpec, FilterGroupSpec]] = None

    def evaluate(
        self,
        records: Mapping[str, Mapping[str, Any]],
        spec: Union[FilterRuleSpec, FilterGroupSpec],
    ) -> FilterEvaluationResult:
        self.recorded_spec = spec
        matches = [s for s in self.matching_symbols if s in records]
        return FilterEvaluationResult(
            universe_size=len(records),
            matched_count=len(matches),
            matching_symbols=matches,
        )


class MockRankingRule(IRankingRule):
    """Mock ranking rule engine."""

    def __init__(self, ranks: Mapping[str, int]) -> None:
        self.ranks = ranks
        self.recorded_call: Optional[tuple[str, RankingOrder, RankingMethod]] = None

    def rank(
        self,
        records: Mapping[str, Mapping[str, Any]],
        metric: str,
        order: RankingOrder = RankingOrder.DESCENDING,
        method: RankingMethod = RankingMethod.MIN,
        group_by: Optional[str] = None,
    ) -> RankingResult:
        self.recorded_call = (metric, order, method)
        return RankingResult(
            metric=metric,
            ranks={s: self.ranks.get(s, 999) for s in records if s in self.ranks},
        )


class MockSelectionRule(ISelectionRule):
    """Mock selection rule engine."""

    def __init__(self, selected_symbols: Sequence[str]) -> None:
        self.selected_symbols = selected_symbols
        self.recorded_cutoffs: Optional[Sequence[RankCutoffSpec]] = None

    def select(
        self,
        ranked_records: Mapping[str, Mapping[str, Any]],
        cutoffs: Sequence[RankCutoffSpec],
        mode: SelectionMode = SelectionMode.ALL,
    ) -> SelectionResult:
        self.recorded_cutoffs = cutoffs
        matches = [s for s in self.selected_symbols if s in ranked_records]
        return SelectionResult(
            selected_symbols=matches,
            total_evaluated=len(ranked_records),
            matched_count=len(matches),
        )


class MockResultAssembler(IResultAssembler):
    """Mock result assembler verifying exact assemble() contract parameters."""

    def __init__(self) -> None:
        self.assembled_records: Optional[Sequence[Mapping[str, Any]]] = None
        self.assembled_metadata: Optional[Mapping[str, Any]] = None

    def assemble(
        self,
        records: Sequence[Mapping[str, Any]],
        columns: Optional[Sequence[str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> QueryResultPayload:
        self.assembled_records = records
        self.assembled_metadata = metadata
        cols = [ColumnDefinition(key="symbol", label="Symbol", category="ID")]
        return QueryResultPayload(
            universe_count=metadata.get("universe_count", len(records)) if metadata else len(records),
            qualified_count=metadata.get("qualified_count", len(records)) if metadata else len(records),
            selected_count=metadata.get("selected_count", len(records)) if metadata else len(records),
            rows=records,
            columns=cols,
            metadata=metadata or {},
        )


class MockTimeframeEngine(ITimeframeEngine):
    """Mock timeframe engine satisfying ITimeframeEngine contract without dependencies."""

    def __init__(self) -> None:
        self.recorded_calls: list[str] = []

    def resample(
        self,
        bars: Sequence[MarketBar],
        timeframe: Union[str, Timeframe],
    ) -> Sequence[MarketBar]:
        self.recorded_calls.append(f"resample({timeframe})")
        return tuple(bars)

    def build_context(
        self,
        symbol: str,
        exchange: str,
        daily_bars: Sequence[MarketBar],
        timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
        as_of: Optional[datetime] = None,
        half_year_policy: Optional[str] = None,
    ) -> MarketContext:
        self.recorded_calls.append(f"build_context({symbol})")
        tfs = timeframes or ("D", "W", "M", "Q", "H", "Y")
        bars_by_tf = {str(tf): tuple(daily_bars) for tf in tfs}
        return MarketContext(
            symbol=symbol,
            exchange=exchange,
            bars_by_timeframe=bars_by_tf,
            as_of=as_of,
        )


# ---------------------------------------------------------------------------
# Test Fixtures & Utilities
# ---------------------------------------------------------------------------


def make_bar(close: float) -> MarketBar:
    return MarketBar(
        timestamp=datetime(2026, 8, 14, 15, 30),
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=10000.0,
    )


def build_test_hub(
    provider: Optional[IDataProvider] = None,
    bands_repo: Optional[IBandsRepository] = None,
    calc_modules: Optional[Mapping[str, ICalcModule]] = None,
) -> RegistryHub:
    hub = RegistryHub()
    hub.providers.register("mock_provider", provider or MockDataProvider())
    hub.bands.register("mock_bands", bands_repo or MockBandsRepo())
    modules = calc_modules or {
        "velocity": MockCalcModule("velocity", {"DROC": 5.0, "WROC": 12.0}),
        "trend": MockCalcModule("trend", {"EMA_W": "upcut", "M_CUR": 8.5}),
    }
    for key, mod in modules.items():
        hub.calculations.register(key, mod)
    return hub


# ---------------------------------------------------------------------------
# Tests: Capability Resolution & Data Acquisition
# ---------------------------------------------------------------------------


def test_orchestrator_resolves_capabilities_via_get():
    """Test 1: Orchestrator correctly resolves capabilities using .get() on RegistryHub."""
    hub = build_test_hub()
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity", "trend"),
    )

    records = orchestrator.build_dataset(config)

    assert "RELIANCE" in records
    assert "TCS" in records
    assert "INFY" in records


def test_orchestrator_raises_on_unregistered_capability():
    """Test 2: Unregistered provider or calculation key fails cleanly with RegistrationNotFoundError."""
    hub = build_test_hub()
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    bad_config = EngineConfig(provider="nonexistent_provider")

    with pytest.raises(RegistrationNotFoundError):
        orchestrator.build_dataset(bad_config)


def test_orchestrator_provider_universe_acquisition():
    """Test 3: Provider.universe() is invoked when no explicit symbols are configured."""
    provider = MockDataProvider(universe_symbols=["TCS", "INFY"])
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        exchange="NSE",
        symbols=None,
    )

    records = orchestrator.build_dataset(config)

    assert "universe(NSE)" in provider.recorded_calls
    assert set(records.keys()) == {"TCS", "INFY"}


def test_orchestrator_explicit_symbols_override():
    """Test 4: config.symbols overrides provider universe acquisition."""
    provider = MockDataProvider(universe_symbols=["RELIANCE", "TCS", "INFY"])
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        symbols=("RELIANCE",),
    )

    records = orchestrator.build_dataset(config)

    # universe() must NOT have been called
    assert not any("universe" in c for c in provider.recorded_calls)
    assert set(records.keys()) == {"RELIANCE"}


def test_orchestrator_symbol_limit_applied():
    """Test 5: config.symbol_limit slices the acquired universe."""
    provider = MockDataProvider(universe_symbols=["A", "B", "C", "D", "E"])
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        symbol_limit=2,
    )

    records = orchestrator.build_dataset(config)

    assert len(records) == 2
    assert set(records.keys()) == {"A", "B"}


# ---------------------------------------------------------------------------
# Tests: Historical Bars, Price Behavior & Bands
# ---------------------------------------------------------------------------


def test_orchestrator_historical_data_and_price_extraction():
    """Test 6: Historical daily bars are fetched and latest close is assigned to price."""
    history = {
        "RELIANCE": [make_bar(2500.0), make_bar(2550.0)],
        "TCS": [make_bar(3400.0)],
    }
    provider = MockDataProvider(universe_symbols=["RELIANCE", "TCS"], history_map=history)
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        historical_years=7,
    )

    records = orchestrator.build_dataset(config)

    assert "daily_history(RELIANCE, NSE, 7)" in provider.recorded_calls
    assert records["RELIANCE"]["price"] == 2550.0
    assert records["TCS"]["price"] == 3400.0
    assert records["RELIANCE"]["exchange"] == "NSE"


def test_orchestrator_empty_history_produces_none_price_without_crash():
    """Test 7: Empty historical data sets price=None and does not raise IndexError."""
    provider = MockDataProvider(universe_symbols=["EMPTY_SYM"], history_map={"EMPTY_SYM": []})
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
    )

    records = orchestrator.build_dataset(config)

    assert "EMPTY_SYM" in records
    assert records["EMPTY_SYM"]["price"] is None


def test_orchestrator_bands_lookup_filters_none_values():
    """Test 8: Bands repository None values are filtered before populating CalculationContext.bands_lookup."""
    bands_repo = MockBandsRepo(
        bands_store={
            "RELIANCE": {"D": 0.12, "W": 0.15, "M": None, "Q": None},
        }
    )
    velocity_mod = MockCalcModule("velocity", {"DROC": 3.0})
    hub = build_test_hub(bands_repo=bands_repo, calc_modules={"velocity": velocity_mod})
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        symbols=("RELIANCE",),
    )

    orchestrator.build_dataset(config)

    assert len(velocity_mod.recorded_contexts) == 1
    ctx: CalculationContext = velocity_mod.recorded_contexts[0]
    # Verify bands_lookup contains only float values, no None
    assert ctx.bands_lookup == {"D": 0.12, "W": 0.15}
    assert None not in ctx.bands_lookup.values()


def test_orchestrator_calculation_context_and_parameters():
    """Test 9: CalculationContext correctly wraps MarketContext and passes provider_options."""
    history = {"INFY": [make_bar(1500.0)]}
    provider = MockDataProvider(universe_symbols=["INFY"], history_map=history)
    velocity_mod = MockCalcModule("velocity", {"DROC": 1.5})
    hub = build_test_hub(provider=provider, calc_modules={"velocity": velocity_mod})
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
        symbols=("INFY",),
        provider_options={"fast_mode": True},
    )

    orchestrator.build_dataset(config)

    ctx: CalculationContext = velocity_mod.recorded_contexts[0]
    assert ctx.market_context.symbol == "INFY"
    assert ctx.market_context.exchange == "NSE"
    assert len(ctx.market_context.get_bars("D")) == 1
    assert len(ctx.market_context.get_bars("W")) == 1
    assert len(ctx.market_context.get_bars("M")) == 1
    assert ctx.parameters == {"fast_mode": True}


def test_orchestrator_merges_disjoint_metrics_from_multiple_modules():
    """Test 10: Multiple calculation modules have their CalculationResult.metrics merged into canonical records."""
    vel_mod = MockCalcModule("velocity", {"DROC": 4.5, "ACCEL_L": 1.2})
    trend_mod = MockCalcModule("trend", {"EMA_W": "upcut", "M_CUR": 10.0})
    impulse_mod = MockCalcModule("impulse", {"IC": "IP", "IC_PCT": 52.0})
    hub = build_test_hub(
        calc_modules={
            "velocity": vel_mod,
            "trend": trend_mod,
            "impulse": impulse_mod,
        }
    )
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity", "trend", "impulse"),
        symbols=("TCS",),
    )

    records = orchestrator.build_dataset(config)

    rec = records["TCS"]
    assert rec["DROC"] == 4.5
    assert rec["ACCEL_L"] == 1.2
    assert rec["EMA_W"] == "upcut"
    assert rec["M_CUR"] == 10.0
    assert rec["IC"] == "IP"
    assert rec["IC_PCT"] == 52.0
    assert rec["symbol"] == "TCS"


# ---------------------------------------------------------------------------
# Tests: Screening Pipeline (QUALIFY -> ORDER -> SHOW -> RESULTS)
# ---------------------------------------------------------------------------


def test_orchestrator_screening_qualify_order_show_results():
    """Test 11: Full screening pipeline executes QUALIFY -> ORDER -> SHOW -> RESULTS in sequence."""
    sample_records = {
        "A": {"symbol": "A", "price": 100.0, "M_CUR": 20.0},
        "B": {"symbol": "B", "price": 105.0, "M_CUR": 15.0},
        "C": {"symbol": "C", "price": 95.0, "M_CUR": -5.0},
        "D": {"symbol": "D", "price": 110.0, "M_CUR": 25.0},
    }

    # A, B, D pass QUALIFY
    filter_rule = MockFilterRule(matching_symbols=["A", "B", "D"])
    # Order: D=1, A=2, B=3
    ranking_rule = MockRankingRule(ranks={"D": 1, "A": 2, "B": 3})
    # Cutoff: top 2 -> D, A pass SHOW
    selection_rule = MockSelectionRule(selected_symbols=["D", "A"])
    assembler = MockResultAssembler()

    orchestrator = PipelineOrchestrator(
        registry=build_test_hub(),
        filter_rule=filter_rule,
        ranking_rule=ranking_rule,
        selection_rule=selection_rule,
        result_assembler=assembler,
    )

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(
            match="all",
            rules=[FilterRuleSpec(field="M_CUR", op=FilterOperator.GT, value=0.0)],
        ),
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="M_CUR", max_rank=2),),
        limit=10,
    )

    payload = orchestrator.execute_screen(query=query, records=sample_records)

    assert isinstance(payload, QueryResultPayload)
    assert payload.universe_count == 4
    assert payload.qualified_count == 3
    assert payload.selected_count == 2
    assert len(payload.rows) == 2
    # Verify records have ranked order D, A
    assert payload.rows[0]["symbol"] == "D"
    assert payload.rows[1]["symbol"] == "A"
    # Verify injected cohort rank metric
    assert payload.rows[0]["RANK_M_CUR"] == 1
    assert payload.rows[1]["RANK_M_CUR"] == 2


def test_orchestrator_applies_limit_before_calling_assembler():
    """Test 12: query.limit slices records BEFORE passing them to IResultAssembler.assemble()."""
    sample_records = {
        "A": {"symbol": "A", "price": 10.0},
        "B": {"symbol": "B", "price": 20.0},
        "C": {"symbol": "C", "price": 30.0},
        "D": {"symbol": "D", "price": 40.0},
    }

    assembler = MockResultAssembler()
    orchestrator = PipelineOrchestrator(
        registry=build_test_hub(),
        result_assembler=assembler,
    )

    # Query with no filters/cutoffs but limit=2
    query = ScreeningQuery(limit=2)
    payload = orchestrator.execute_screen(query=query, records=sample_records)

    # Result assembler must have received only 2 rows, not 4
    assert assembler.assembled_records is not None
    assert len(assembler.assembled_records) == 2
    assert len(payload.rows) == 2
    assert assembler.assembled_metadata["limit"] == 2
    assert assembler.assembled_metadata["selected_count"] == 4


def test_orchestrator_screening_missing_engines_raises_value_error():
    """Test 13: Asking to evaluate a filter or ranking without providing the rule engine raises ValueError."""
    orchestrator = PipelineOrchestrator(registry=build_test_hub())
    sample_records = {"A": {"symbol": "A"}}

    # Filter group without filter_rule raises
    q_filter = ScreeningQuery(filter_group=FilterGroupSpec(rules=[]))
    with pytest.raises(ValueError, match="IFilterRule"):
        orchestrator.execute_screen(q_filter, sample_records)

    # Ranking metric without ranking_rule raises
    q_rank = ScreeningQuery(ranking_metric="M_CUR")
    with pytest.raises(ValueError, match="IRankingRule"):
        orchestrator.execute_screen(q_rank, sample_records)

    # Selection cutoff without selection_rule raises
    q_sel = ScreeningQuery(selection_cutoffs=(RankCutoffSpec(rank_metric="M_CUR", max_rank=10),))
    with pytest.raises(ValueError, match="ISelectionRule"):
        orchestrator.execute_screen(q_sel, sample_records)


def test_orchestrator_run_convenience_method():
    """Test 14: run() coordinates build_dataset() followed by execute_screen()."""
    provider = MockDataProvider(
        universe_symbols=["RELIANCE", "TCS"],
        history_map={"RELIANCE": [make_bar(2500.0)], "TCS": [make_bar(3400.0)]},
    )
    hub = build_test_hub(provider=provider)
    assembler = MockResultAssembler()

    orchestrator = PipelineOrchestrator(
        registry=hub,
        result_assembler=assembler,
        timeframe_engine=MockTimeframeEngine(),
    )

    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("velocity",),
    )

    # 1. Run without query returns full dataset
    payload_full = orchestrator.run(config=config, query=None)
    assert payload_full.selected_count == 2
    assert len(payload_full.rows) == 2

    # 2. Run with query coordinates through screening
    filter_rule = MockFilterRule(matching_symbols=["RELIANCE"])
    orchestrator.filter_rule = filter_rule
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[]))

    payload_screened = orchestrator.run(config=config, query=query)
    assert payload_screened.selected_count == 1
    assert payload_screened.rows[0]["symbol"] == "RELIANCE"


def test_orchestrator_contains_no_timeframe_resampling():
    """Test 15: Confirms orchestrator does not import or implement timeframe resampling logic or concrete TimeframeEngine."""
    import inspect
    import re
    import yogi.core.orchestration.pipeline as pipe_mod

    source = inspect.getsource(pipe_mod)

    # Must NOT contain pandas resample or timeframe synthesis
    assert ".resample(" not in source
    assert "resample" not in source.lower()
    assert "pd.to_datetime" not in source
    assert "DateOffset" not in source

    # Must NOT import concrete TimeframeEngine (Layer 2 implementation)
    assert "yogi.timeframe" not in source
    assert not re.search(r"\bTimeframeEngine\b", source)


def test_execute_screen_explicit_method_injection_overrides_constructor_defaults():
    """Test 16: Explicit method-level rule and assembler arguments take precedence over constructor defaults."""
    # 1. Setup sample records
    sample_records = {
        "SYM_A": {"symbol": "SYM_A", "score": 10.0},
        "SYM_B": {"symbol": "SYM_B", "score": 20.0},
    }

    # 2. Setup constructor-level fallback rules
    default_filter = MockFilterRule(matching_symbols=["SYM_A"])
    default_ranking = MockRankingRule(ranks={"SYM_A": 99, "SYM_B": 99})
    default_selection = MockSelectionRule(selected_symbols=["SYM_A"])
    default_assembler = MockResultAssembler()

    hub = build_test_hub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=default_filter,
        ranking_rule=default_ranking,
        selection_rule=default_selection,
        result_assembler=default_assembler,
    )

    # 3. Setup method-level override rules
    override_filter = MockFilterRule(matching_symbols=["SYM_B"])
    override_ranking = MockRankingRule(ranks={"SYM_B": 1})
    override_selection = MockSelectionRule(selected_symbols=["SYM_B"])
    override_assembler = MockResultAssembler()

    query = ScreeningQuery(
        filter_group=FilterGroupSpec(rules=[]),
        ranking_metric="score",
        selection_cutoffs=(RankCutoffSpec(rank_metric="score", max_rank=5),),
    )

    # 4. Execute screen with explicit method-level overrides
    payload = orchestrator.execute_screen(
        query=query,
        records=sample_records,
        filter_rule=override_filter,
        ranking_rule=override_ranking,
        selection_rule=override_selection,
        result_assembler=override_assembler,
    )

    # 5. Verify method-level implementations were invoked (and constructor defaults were untouched)
    assert override_filter.recorded_spec is not None
    assert default_filter.recorded_spec is None

    assert override_ranking.recorded_call is not None
    assert default_ranking.recorded_call is None

    assert override_selection.recorded_cutoffs is not None
    assert default_selection.recorded_cutoffs is None

    assert override_assembler.assembled_records is not None
    assert default_assembler.assembled_records is None

    # Verify end-to-end outcome matches override behavior
    assert payload.selected_count == 1
    assert payload.rows[0]["symbol"] == "SYM_B"
    assert payload.rows[0]["RANK_score"] == 1

    # 6. Verify constructor defaults are used when method arguments are omitted (None)
    payload_fallback = orchestrator.execute_screen(
        query=query,
        records=sample_records,
    )
    assert default_filter.recorded_spec is not None
    assert default_ranking.recorded_call is not None
    assert default_selection.recorded_cutoffs is not None
    assert default_assembler.assembled_records is not None

    assert payload_fallback.selected_count == 1
    assert payload_fallback.rows[0]["symbol"] == "SYM_A"


def test_build_dataset_propagates_provider_options_to_calculation_context():
    """Test 17: EngineConfig.provider_options are propagated to CalculationContext.parameters."""
    provider = MockDataProvider(
        universe_symbols=["RELIANCE"],
        history_map={"RELIANCE": [make_bar(2500.0)]},
    )
    calc_module = MockCalcModule("test_calc", {"METRIC": 1.0})
    hub = build_test_hub(provider=provider, calc_modules={"test_calc": calc_module})

    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=MockTimeframeEngine())
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=("test_calc",),
        provider_options={"foo": "bar"},
    )

    records = orchestrator.build_dataset(config)

    assert "RELIANCE" in records
    assert len(calc_module.recorded_contexts) == 1
    assert calc_module.recorded_contexts[0].parameters == {"foo": "bar"}


def test_orchestrator_raises_when_timeframe_engine_missing():
    """Test 18: build_dataset raises ValueError when ITimeframeEngine is not provided."""
    provider = MockDataProvider(
        universe_symbols=["RELIANCE"],
        history_map={"RELIANCE": [make_bar(2500.0)]},
    )
    hub = build_test_hub(provider=provider)
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=None)
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
    )

    with pytest.raises(ValueError, match="ITimeframeEngine"):
        orchestrator.build_dataset(config)


def test_orchestrator_invokes_injected_timeframe_engine():
    """Test 19: build_dataset invokes the injected ITimeframeEngine implementation."""
    provider = MockDataProvider(
        universe_symbols=["RELIANCE"],
        history_map={"RELIANCE": [make_bar(2500.0)]},
    )
    hub = build_test_hub(provider=provider)
    engine = MockTimeframeEngine()
    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=engine)
    config = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
    )

    orchestrator.build_dataset(config)
    assert len(engine.recorded_calls) == 1
    assert engine.recorded_calls[0] == "build_context(RELIANCE)"


def test_orchestrator_contains_no_concrete_calculation_imports():
    """Verify that PipelineOrchestrator has zero module-level dependency on concrete calculation packages."""
    import inspect
    import yogi.core.orchestration.pipeline as pipe_mod

    source = inspect.getsource(pipe_mod)

    # Must NOT import concrete calculation functions
    assert "calculate_dynamic_ema_signal" not in source
    assert "from yogi.calculation" not in source


def test_dynamic_condition_polymorphic_registry_dispatch():
    """Verify PipelineOrchestrator resolves dynamic calculations polymorphically via RegistryHub.calculations."""
    class CustomDynamicCalc(ICalcModule):
        name = "custom_dynamic"

        def __init__(self) -> None:
            self.dynamic_calls = []

        def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
            return CalculationResult(symbol=symbol, module_name=self.name, metrics={})

        def supports_condition(self, condition_type: str) -> bool:
            return condition_type == "ema"

        def calculate_dynamic(self, symbol: str, rule: Any, context: CalculationContext) -> Any:
            self.dynamic_calls.append((symbol, rule))
            return {
                "state": "UP",
                "is_up": True,
                "is_down": False,
                "is_upcut": False,
                "is_downcut": False,
            }

    custom_calc = CustomDynamicCalc()
    hub = RegistryHub()
    hub.calculations.register("custom_dynamic", custom_calc)

    bar = make_bar(100.0)
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=MockFilterRule(matching_symbols=["RELIANCE"]),
        ranking_rule=MockRankingRule(ranks={"RELIANCE": 1}),
        selection_rule=MockSelectionRule(selected_symbols=["RELIANCE"]),
        result_assembler=MockResultAssembler(),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"RELIANCE": [bar]},
    )

    rule = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
    )
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rule]))
    records = {"RELIANCE": {"symbol": "RELIANCE", "exchange": "NSE"}}

    payload = orchestrator.execute_screen(query=query, records=records)

    assert len(custom_calc.dynamic_calls) == 1
    assert custom_calc.dynamic_calls[0][0] == "RELIANCE"


def test_fifth_filter_extensibility_without_pipeline_or_engine_modification():
    """Verify that a hypothetical 5th filter (e.g., RSI) can be added via contracts without modifying Pipeline or FilterEngine."""
    from yogi.core.contracts.filter import IConditionEvaluator
    from yogi.filter.engine import FilterEngine

    # 1. Custom Calculation Module supporting "rsi"
    class RsiCalcModule(ICalcModule):
        name = "rsi_calc"

        def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
            return CalculationResult(symbol=symbol, module_name=self.name, metrics={})

        def supports_condition(self, condition_type: str) -> bool:
            return condition_type == "rsi"

        def calculate_dynamic(self, symbol: str, rule: Any, context: CalculationContext) -> Any:
            return {"rsi_value": 25.0, "is_oversold": True}

    # 2. Custom Condition Evaluator for "rsi"
    class RsiConditionEvaluator(IConditionEvaluator):
        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> bool:
            val = record.get(rule.field)
            if isinstance(val, dict):
                return bool(val.get("is_oversold", False))
            return False

        def describe(self, rule: FilterRuleSpec) -> str:
            return f"RSI({rule.params.get('period', 14)}) < {rule.params.get('threshold', 30)}"

    # 3. Assemble components via composition
    hub = RegistryHub()
    hub.calculations.register("rsi_calc", RsiCalcModule())

    filter_engine = FilterEngine()
    filter_engine.register_evaluator("rsi", RsiConditionEvaluator())

    bar = make_bar(100.0)
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=filter_engine,
        ranking_rule=MockRankingRule(ranks={"RELIANCE": 1}),
        selection_rule=MockSelectionRule(selected_symbols=["RELIANCE"]),
        result_assembler=MockResultAssembler(),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"RELIANCE": [bar], "TCS": [bar]},
    )

    # 4. Screening query with the 5th filter rule
    rsi_rule = FilterRuleSpec(
        field="RSI_14",
        condition_type="rsi",
        params={"period": 14, "threshold": 30},
    )
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rsi_rule]))
    records = {
        "RELIANCE": {"symbol": "RELIANCE", "exchange": "NSE"},
        "TCS": {"symbol": "TCS", "exchange": "NSE"},
    }

    payload = orchestrator.execute_screen(query=query, records=records)

    # Both symbols evaluated via the new condition evaluator
    assert payload.qualified_count == 2
    assert "RSI(14) < 30" in payload.metadata.get("filter_explanation", "")


# ---------------------------------------------------------------------------
# Surgical Fix 4/5 Regression Tests (EMA-AUDIT-004 and EMA-AUDIT-005)
# ---------------------------------------------------------------------------


def test_unresolved_calculation_module_raises_explicit_value_error():
    """Verify that an unresolvable calculation module raises ValueError, avoiding silent qualification skips."""
    hub = RegistryHub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=MockFilterRule(matching_symbols=[]),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={},
    )
    unsupported_rule = FilterRuleSpec(
        field="CUSTOM_FIELD",
        condition_type="unregistered_indicator",
        timeframe="D",
        params={"p1": 10},
    )
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[unsupported_rule]))
    records = {"RELIANCE": {"symbol": "RELIANCE", "exchange": "NSE"}}

    with pytest.raises(ValueError) as exc_info:
        orchestrator.execute_screen(query=query, records=records)

    assert "No calculation module registered supporting condition_type 'unregistered_indicator'" in str(exc_info.value)


def test_calculation_exception_is_not_swallowed_or_converted():
    """Verify that an exception inside calculate_dynamic is raised rather than swallowed into a non-match."""
    class FailingCalcModule(ICalcModule):
        name = "failing_calc"

        def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
            return CalculationResult(symbol=symbol, module_name=self.name, metrics={})

        def supports_condition(self, condition_type: str) -> bool:
            return condition_type == "buggy"

        def calculate_dynamic(self, symbol: str, rule: Any, context: CalculationContext) -> Any:
            raise RuntimeError("Math calculation exploded unexpectedly")

    hub = RegistryHub()
    hub.calculations.register("failing_calc", FailingCalcModule())

    bar = make_bar(100.0)
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=MockFilterRule(matching_symbols=[]),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"RELIANCE": [bar]},
    )
    rule = FilterRuleSpec(field="BUGGY_D", condition_type="buggy", timeframe="D")
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rule]))
    records = {"RELIANCE": {"symbol": "RELIANCE", "exchange": "NSE"}}

    with pytest.raises(RuntimeError) as exc_info:
        orchestrator.execute_screen(query=query, records=records)

    assert "Math calculation exploded unexpectedly" in str(exc_info.value)


def test_missing_market_data_does_not_fabricate_result_and_does_not_qualify_under_negation():
    """Verify that missing market data produces None (no fabricated dict) and does NOT qualify under negation."""
    from yogi.filter.engine import FilterEngine

    hub = RegistryHub()
    # Register real TrendCalculator
    from yogi.calculation.trend.calculator import TrendCalculator
    hub.calculations.register("trend", TrendCalculator())

    filter_engine = FilterEngine()
    rising_bars = [make_bar(100.0 + i) for i in range(40)]

    # RELIANCE has bars (rising -> EMA UP).
    # TCS has missing market data (no bars in cache).
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=filter_engine,
        ranking_rule=MockRankingRule(ranks={"RELIANCE": 1, "TCS": 2}),
        selection_rule=MockSelectionRule(selected_symbols=["RELIANCE", "TCS"]),
        result_assembler=MockResultAssembler(),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"RELIANCE": rising_bars},  # TCS is missing from cache!
    )

    # 1. Non-negated: EMA D(3,5) == UP
    rule_pos = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
        is_negated=False,
    )
    query_pos = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rule_pos]))
    records = {
        "RELIANCE": {"symbol": "RELIANCE", "exchange": "NSE"},
        "TCS": {"symbol": "TCS", "exchange": "NSE"},
    }

    payload_pos = orchestrator.execute_screen(query=query_pos, records=records)
    # RELIANCE is UP (qualifies). TCS has missing data (does NOT qualify).
    assert "RELIANCE" in payload_pos.rows[0]["symbol"]
    assert payload_pos.qualified_count == 1

    # 2. Negated: NOT (EMA D(3,5) == UP)
    # RELIANCE is UP -> NOT UP is False.
    # TCS has missing data -> unevaluated -> MUST NOT qualify under negation!
    rule_neg = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
        is_negated=True,
    )
    query_neg = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rule_neg]))
    payload_neg = orchestrator.execute_screen(query=query_neg, records=records)

    # Neither should qualify: RELIANCE is UP, and TCS has missing data!
    assert payload_neg.qualified_count == 0


def test_insufficient_history_does_not_qualify_under_negation():
    """Verify that insufficient history ('na' state) does not qualify under negation."""
    from yogi.filter.engine import FilterEngine
    from yogi.calculation.trend.calculator import TrendCalculator

    hub = RegistryHub()
    hub.calculations.register("trend", TrendCalculator())

    filter_engine = FilterEngine()
    # 1 bar is insufficient for EMA(3,5) calculation (min_required is 2)
    scant_bars = [make_bar(100.0)]

    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=filter_engine,
        ranking_rule=MockRankingRule(ranks={"INSUF": 1}),
        selection_rule=MockSelectionRule(selected_symbols=["INSUF"]),
        result_assembler=MockResultAssembler(),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"INSUF": scant_bars},
    )

    # Negated rule: NOT (EMA D(3,5) == UP)
    rule_neg = FilterRuleSpec(
        field="EMA_D_3_5",
        condition_type="ema",
        timeframe="D",
        p1=3,
        p2=5,
        state="UP",
        is_negated=True,
    )
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[rule_neg]))
    records = {"INSUF": {"symbol": "INSUF", "exchange": "NSE"}}

    payload = orchestrator.execute_screen(query=query, records=records)
    # INSUF has state 'na' which must NOT satisfy NOT UP!
    assert payload.qualified_count == 0


def test_generic_progress_reporting_without_ema_hardcoding():
    """Verify progress reporting works generically for non-EMA calculation modules."""
    class MockRocModule(ICalcModule):
        name = "mock_roc"

        def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
            return CalculationResult(symbol=symbol, module_name=self.name, metrics={})

        def supports_condition(self, condition_type: str) -> bool:
            return condition_type == "roc"

        def calculate_dynamic(self, symbol: str, rule: Any, context: CalculationContext) -> Any:
            return {"roc": 15.0}

    hub = RegistryHub()
    hub.calculations.register("mock_roc", MockRocModule())

    bar = make_bar(100.0)
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=MockFilterRule(matching_symbols=["SYM1"]),
        ranking_rule=MockRankingRule(ranks={"SYM1": 1}),
        selection_rule=MockSelectionRule(selected_symbols=["SYM1"]),
        result_assembler=MockResultAssembler(),
        timeframe_engine=MockTimeframeEngine(),
        bars_cache={"SYM1": [bar]},
    )

    progress_events = []
    def on_progress(pct: float, stage: str, msg: str, curr: int, tot: int) -> None:
        progress_events.append((stage, msg))

    roc_rule = FilterRuleSpec(
        field="ROC_D_21",
        condition_type="roc",
        timeframe="D",
        p1=21,
    )
    query = ScreeningQuery(filter_group=FilterGroupSpec(rules=[roc_rule]))
    records = {"SYM1": {"symbol": "SYM1", "exchange": "NSE"}}

    orchestrator.execute_screen(query=query, records=records, progress_callback=on_progress)

    # Check progress stages
    stages = [ev[0] for ev in progress_events]
    messages = [ev[1] for ev in progress_events]

    assert "calculating_roc" in stages
    assert "calculating_emas" not in stages
    assert any("ROC D(21)" in msg for msg in messages)
    assert not any("EMA" in msg for msg in messages)






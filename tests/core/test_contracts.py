"""Tests for YOGI Core Contracts — verifying interface imports and data structures."""

from datetime import datetime

try:
    import pytest
except ImportError:
    pytest = None

from yogi.core.contracts import (
    # Market Data
    MarketBar,
    TickData,
    MarketContext,
    Timeframe,
    # Provider
    IDataProvider,
    ProviderHealth,
    # Calculation
    ICalcModule,
    CalculationContext,
    CalculationResult,
    # Bands
    IBandsRepository,
    BandEntry,
    BandAuditEntry,
    BAND_TIMEFRAMES,
    # Filter
    IFilterRule,
    FilterOperator,
    FilterRuleSpec,
    FilterGroupSpec,
    FilterStepMetric,
    FilterEvaluationResult,
    # Strategy
    IStrategy,
    StrategySpec,
    StrategyValidationResult,
    # Ranking
    IRankingRule,
    RankingOrder,
    RankingMethod,
    RankingResult,
    # Selection
    ISelectionRule,
    SelectionMode,
    RankCutoffSpec,
    SelectionResult,
    # Results
    IResultAssembler,
    IExportFormatter,
    ColumnDefinition,
    QueryResultPayload,
    ExportFormat,
    # Security Master / Metadata
    SecurityMetadata,
    InstrumentType,
    ListingStatus,
)


def test_market_data_contract_instantiation():
    now = datetime(2026, 9, 22, 10, 0, 0)
    bar = MarketBar(timestamp=now, open=100.0, high=105.0, low=98.0, close=102.0, volume=50000.0)
    assert bar.close == 102.0
    assert bar.volume == 50000.0

    tick = TickData(symbol="RELIANCE", timestamp=now, last_price=2950.0, last_quantity=25)
    assert tick.symbol == "RELIANCE"

    ctx = MarketContext(symbol="TCS", exchange="NSE", bars_by_timeframe={"D": [bar]})
    assert ctx.get_closes("D") == [102.0]
    assert ctx.get_bars("W") == ()


def test_provider_contract_subclass():
    class DummyProvider(IDataProvider):
        @property
        def name(self) -> str:
            return "dummy"

        @property
        def supports_intraday(self) -> bool:
            return False

        @property
        def supports_live_ticks(self) -> bool:
            return False

        def universe(self, exchange="NSE"):
            return ["RELIANCE", "TCS"]

        def daily_history(self, symbol, exchange="NSE", years=10):
            return [MarketBar(datetime.now(), 100.0, 105.0, 95.0, 102.0)]

        def batch_daily_history(self, symbols, exchange="NSE", years=10):
            return {s: self.daily_history(s, exchange, years) for s in symbols}

        def last_price(self, symbol, exchange="NSE"):
            bars = self.daily_history(symbol, exchange)
            return bars[-1].close if bars else None

        def intraday(self, symbol, exchange="NSE", interval="5minute", days=5):
            return []

        def subscribe_ticks(self, symbols, on_tick, exchange="NSE"):
            return None

        def trading_holidays(self, year=None):
            return ["2026-01-26"]

        def health(self) -> ProviderHealth:
            return ProviderHealth(provider=self.name, ok=True, sample_price=102.0)

    provider = DummyProvider()
    assert provider.name == "dummy"
    assert provider.universe() == ["RELIANCE", "TCS"]
    assert provider.last_price("TCS") == 102.0
    health = provider.health()
    assert health.ok is True
    assert health.sample_price == 102.0


def test_calculation_contract_subclass():
    class DummyCalc(ICalcModule):
        name = "test_calc"
        required_timeframes = ("D", "W")

        def calculate(self, symbol, context):
            return CalculationResult(symbol=symbol, module_name=self.name, metrics={"TEST_METRIC": 42.0})

    calc = DummyCalc()
    m_ctx = MarketContext(symbol="INFY", exchange="NSE", bars_by_timeframe={})
    c_ctx = CalculationContext(market_context=m_ctx)
    res = calc.calculate("INFY", c_ctx)
    assert res.metrics["TEST_METRIC"] == 42.0


def test_bands_contract_subclass():
    class DummyBands(IBandsRepository):
        def __init__(self):
            self._store = {}

        def get_band(self, symbol, timeframe):
            return self._store.get((symbol, timeframe), 0.12)

        def get_all_bands(self, symbol):
            return {tf: self.get_band(symbol, tf) for tf in BAND_TIMEFRAMES}

        def set_band(self, symbol, timeframe, value, who="app", source="app"):
            self._store[(symbol, timeframe)] = value
            return value

    repo = DummyBands()
    assert repo.get_band("INFY", "M") == 0.12
    repo.set_band("INFY", "M", 0.15)
    assert repo.get_band("INFY", "M") == 0.15


def test_filter_and_strategy_contracts():
    leaf = FilterRuleSpec(field="WROC", op=FilterOperator.GT, value=0.0)
    group = FilterGroupSpec(match="all", rules=[leaf])
    strat_spec = StrategySpec(name="TEST_STRAT", filter_group=group)

    assert strat_spec.name == "TEST_STRAT"
    assert len(strat_spec.filter_group.rules) == 1

    eval_res = FilterEvaluationResult(
        universe_size=100,
        matched_count=2,
        matching_symbols=["RELIANCE", "INFY"],
        steps=[FilterStepMetric(rule_description="WROC > 0", passing_count=2)],
    )
    assert eval_res.matched_count == 2


def test_ranking_and_selection_contracts():
    rank_res = RankingResult(
        metric="M_CUR",
        ranks={"RELIANCE": 1, "TCS": 2},
        rank_changes={"RELIANCE": 5},
    )
    assert rank_res.ranks["RELIANCE"] == 1

    sel_res = SelectionResult(
        selected_symbols=["RELIANCE"],
        total_evaluated=2,
        matched_count=1,
    )
    assert sel_res.selected_symbols == ["RELIANCE"]


def test_results_and_security_contracts():
    class DummyAssembler(IResultAssembler):
        def assemble(self, records, columns=None, metadata=None):
            return QueryResultPayload(
                universe_count=len(records),
                qualified_count=len(records),
                selected_count=len(records),
                rows=records,
                columns=[ColumnDefinition(key=c, label=c, category="GENERAL") for c in (columns or [])],
                metadata=metadata or {},
            )

    assembler = DummyAssembler()
    assembled = assembler.assemble([{"symbol": "RELIANCE", "M_CUR": 8.5}], columns=["symbol", "M_CUR"])
    assert assembled.selected_count == 1
    assert assembled.rows[0]["symbol"] == "RELIANCE"

    col = ColumnDefinition(key="M_CUR", label="Month ROC", category="ROC")
    payload = QueryResultPayload(
        universe_count=100,
        qualified_count=10,
        selected_count=5,
        rows=[{"symbol": "RELIANCE", "M_CUR": 8.5}],
        columns=[col],
    )
    assert payload.selected_count == 5

    sec = SecurityMetadata(
        symbol="RELIANCE",
        exchange="NSE",
        name="Reliance Industries",
        isin="INE002A01018",
        is_fno=True,
        instrument_type=InstrumentType.EQ,
    )
    assert sec.is_fno is True
    assert sec.instrument_type == InstrumentType.EQ


if __name__ == "__main__":
    test_market_data_contract_instantiation()
    test_provider_contract_subclass()
    test_calculation_contract_subclass()
    test_bands_contract_subclass()
    test_filter_and_strategy_contracts()
    test_ranking_and_selection_contracts()
    test_results_and_security_contracts()
    print("ALL 7 CORE CONTRACT TESTS PASSED.")

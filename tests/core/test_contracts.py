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


# -----------------------------------------------------------------------------
# Tests for EMA-AUDIT-002: FilterRuleSpec Serialization & Immutability
# -----------------------------------------------------------------------------

import pickle
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import FrozenDict


def test_filter_rule_spec_pickle_round_trip():
    """Verify that FilterRuleSpec can be pickled and unpickled losslessly."""
    rule = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
        timeframe="D",
        p1=9,
        p2=21,
        state="UP",
    )
    data = pickle.dumps(rule)
    restored = pickle.loads(data)

    assert restored == rule
    assert isinstance(restored.params, FrozenDict)
    assert restored.params["timeframe"] == "D"
    assert restored.params["p1"] == 9
    assert restored.params["p2"] == 21
    assert restored.params["state"] == "UP"
    assert restored.timeframe == "D"
    assert restored.p1 == 9
    assert restored.p2 == 21
    assert restored.state == "UP"


def test_screening_query_pickle_round_trip():
    """Verify that a ScreeningQuery containing FilterRuleSpec can be pickled and unpickled."""
    rule = FilterRuleSpec(
        field="EMA_W_5_20",
        condition_type="ema",
        params={"timeframe": "W", "p1": 5, "p2": 20, "state": "DOWN"},
    )
    group = FilterGroupSpec(match="all", rules=[rule])
    query = ScreeningQuery(
        filter_group=group,
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(RankCutoffSpec(rank_metric="M_CUR", max_rank=50),),
        limit=20,
    )

    data = pickle.dumps(query)
    restored = pickle.loads(data)

    assert restored == query
    assert restored.filter_group.rules[0].params["timeframe"] == "W"
    assert restored.filter_group.rules[0].params["p1"] == 5
    assert restored.filter_group.rules[0].params["p2"] == 20
    assert restored.filter_group.rules[0].params["state"] == "DOWN"


def test_filter_rule_spec_deep_immutability():
    """Verify that FilterRuleSpec.params enforces deep immutability on nested dicts, lists, and sets."""
    nested_list = [1, 2, [3, 4]]
    nested_dict = {"inner_list": [10, 20], "inner_set": {1, 2}}
    params_input = {
        "timeframe": "D",
        "nested_dict": nested_dict,
        "nested_list": nested_list,
    }

    rule = FilterRuleSpec(field="test", params=params_input)

    # 1. Outer mapping immutability
    with pytest.raises(TypeError):
        rule.params["new_key"] = "forbidden"
    with pytest.raises(TypeError):
        del rule.params["timeframe"]
    with pytest.raises(TypeError):
        rule.params.pop("timeframe")
    with pytest.raises(TypeError):
        rule.params.update({"a": 1})

    # 2. Defensive copy against post-construction input mutation
    nested_list.append(5)
    nested_dict["new_val"] = "mutated"
    nested_dict["inner_list"].append(30)
    assert 5 not in rule.params["nested_list"]
    assert "new_val" not in rule.params["nested_dict"]
    assert 30 not in rule.params["nested_dict"]["inner_list"]

    # 3. Nested container immutability
    assert isinstance(rule.params["nested_dict"], FrozenDict)
    assert isinstance(rule.params["nested_list"], tuple)
    assert isinstance(rule.params["nested_list"][2], tuple)
    assert isinstance(rule.params["nested_dict"]["inner_list"], tuple)
    assert isinstance(rule.params["nested_dict"]["inner_set"], frozenset)

    with pytest.raises(TypeError):
        rule.params["nested_dict"]["inner_list"] = (99,)
    with pytest.raises(AttributeError):
        rule.params["nested_list"].append(6)


def test_filter_rule_spec_hashing_and_equality():
    """Verify consistent equality and stable hashing for FilterRuleSpec."""
    rule1 = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
    )
    rule2 = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"p2": 21, "timeframe": "D", "state": "UP", "p1": 9},  # Different insertion order
    )
    rule3 = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "DOWN"},
    )

    # 1. Equality
    assert rule1 == rule2
    assert rule1 != rule3

    # 2. Hash consistency (equal objects MUST have equal hashes)
    assert hash(rule1) == hash(rule2)

    # 3. Usability in set and dict key
    rule_set = {rule1}
    assert rule2 in rule_set
    assert rule3 not in rule_set

    rule_map = {rule1: "alpha"}
    assert rule_map[rule2] == "alpha"


def test_filter_rule_spec_unsupported_key_type():
    """Verify that non-string parameter keys raise a clear TypeError rather than being silently coerced."""
    with pytest.raises(TypeError) as exc_info:
        FilterRuleSpec(field="test", params={123: "invalid_key"})
    assert "keys must be strings" in str(exc_info.value)


def test_filter_rule_spec_evaluator_compatibility():
    """Verify that FrozenDict params is fully compatible with EmaConditionEvaluator and FilterEngine."""
    from yogi.filter.evaluators import EmaConditionEvaluator
    from yogi.filter.engine import FilterEngine

    rule = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
    )

    evaluator = EmaConditionEvaluator()
    desc = evaluator.describe(rule)
    assert "Daily EMA(9, 21)" in desc
    assert "UP" in desc

    row_up = {"EMA_D_9_21": {"state": "UP", "is_up": True, "is_down": False}}
    row_down = {"EMA_D_9_21": {"state": "DOWN", "is_up": False, "is_down": True}}
    assert evaluator.evaluate(row_up, rule) is True
    assert evaluator.evaluate(row_down, rule) is False

    engine = FilterEngine()
    records = {"SYM_UP": row_up, "SYM_DOWN": row_down}
    result = engine.evaluate(records, rule)
    assert result.matched_count == 1
    assert result.matching_symbols == ["SYM_UP"]


# -----------------------------------------------------------------------------
# Tests for EMA-AUDIT-003: Consistent Filter Parameter Precedence
# -----------------------------------------------------------------------------

def test_filter_rule_spec_parameter_precedence_and_conflicts():
    """Verify EMA-AUDIT-003: FilterRuleSpec parameter consistency and conflict rejection."""
    # 1. Generic parameters without legacy fields produce consistent effective values
    rule_generic = FilterRuleSpec(
        field="EMA_D_9_21",
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP", "lookback": 2},
    )
    assert rule_generic.timeframe == "D"
    assert rule_generic.p1 == 9
    assert rule_generic.p2 == 21
    assert rule_generic.state == "UP"
    assert rule_generic.lookback == 2
    assert rule_generic.params["timeframe"] == "D"
    assert rule_generic.params["p1"] == 9
    assert rule_generic.params["p2"] == 21
    assert rule_generic.params["state"] == "UP"
    assert rule_generic.params["lookback"] == 2

    # 2. Legacy fields without generic parameters populate params
    rule_legacy = FilterRuleSpec(
        field="EMA_W_5_20",
        condition_type="ema",
        timeframe="W",
        p1=5,
        p2=20,
        state="DOWN",
        lookback=1,
    )
    assert rule_legacy.params["timeframe"] == "W"
    assert rule_legacy.params["p1"] == 5
    assert rule_legacy.params["p2"] == 20
    assert rule_legacy.params["state"] == "DOWN"
    assert rule_legacy.params["lookback"] == 1

    # 3. Matching dual specifications succeed with normalized case
    rule_matching = FilterRuleSpec(
        field="EMA_M_3_6",
        condition_type="ema",
        timeframe="M",
        p1=3,
        p2=6,
        state="UPCUT",
        lookback=1,
        params={"timeframe": "m", "p1": 3, "p2": 6, "state": "upcut", "lookback": 1},
    )
    assert rule_matching.timeframe == "M"
    assert rule_matching.params["timeframe"] == "M"
    assert rule_matching.state == "UPCUT"
    assert rule_matching.params["state"] == "UPCUT"

    # 4. Conflicting timeframe is rejected
    with pytest.raises(ValueError) as exc:
        FilterRuleSpec(field="test", timeframe="D", params={"timeframe": "W"})
    assert "Conflicting 'timeframe' parameter" in str(exc.value)

    # 5. Conflicting p1 is rejected
    with pytest.raises(ValueError) as exc:
        FilterRuleSpec(field="test", p1=9, params={"p1": 21})
    assert "Conflicting 'p1' parameter" in str(exc.value)

    # 6. Conflicting p2 is rejected
    with pytest.raises(ValueError) as exc:
        FilterRuleSpec(field="test", p2=21, params={"p2": 50})
    assert "Conflicting 'p2' parameter" in str(exc.value)

    # 7. Conflicting state is rejected
    with pytest.raises(ValueError) as exc:
        FilterRuleSpec(field="test", state="UP", params={"state": "DOWN"})
    assert "Conflicting 'state' parameter" in str(exc.value)

    # 8. Conflicting lookback is rejected
    with pytest.raises(ValueError) as exc:
        FilterRuleSpec(field="test", lookback=1, params={"lookback": 5})
    assert "Conflicting 'lookback' parameter" in str(exc.value)


def test_dto_core_round_trip_parameter_consistency():
    """Verify that converting FilterRuleIn to FilterRuleSpec and back maintains 100% parameter agreement."""
    from yogi.cockpit.schemas import FilterGroupIn, FilterRuleIn, from_core_filter_group, to_core_filter_group

    dto = FilterRuleIn(
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP", "lookback": 1},
    )
    spec = dto.to_core_spec()
    assert spec.timeframe == dto.timeframe == "D"
    assert spec.p1 == dto.p1 == 9
    assert spec.p2 == dto.p2 == 21
    assert spec.state == dto.state == "UP"
    assert spec.lookback == dto.lookback == 1
    assert spec.params["timeframe"] == dto.params["timeframe"] == "D"

    # Round trip via group
    group_in = FilterGroupIn(rules=[dto])
    core_group = to_core_filter_group(group_in)
    group_out = from_core_filter_group(core_group)

    rule_out = group_out.rules[0]
    assert rule_out.timeframe == "D"
    assert rule_out.p1 == 9
    assert rule_out.p2 == 21
    assert rule_out.state == "UP"
    assert rule_out.lookback == 1
    assert rule_out.params == {"timeframe": "D", "p1": 9, "p2": 21, "state": "UP", "lookback": 1}


if __name__ == "__main__":
    test_market_data_contract_instantiation()
    test_provider_contract_subclass()
    test_calculation_contract_subclass()
    test_bands_contract_subclass()
    test_filter_and_strategy_contracts()
    test_ranking_and_selection_contracts()
    test_results_and_security_contracts()
    test_filter_rule_spec_pickle_round_trip()
    test_screening_query_pickle_round_trip()
    test_filter_rule_spec_deep_immutability()
    test_filter_rule_spec_hashing_and_equality()
    test_filter_rule_spec_unsupported_key_type()
    test_filter_rule_spec_evaluator_compatibility()
    test_filter_rule_spec_parameter_precedence_and_conflicts()
    test_dto_core_round_trip_parameter_consistency()
    print("ALL CORE CONTRACT TESTS PASSED.")

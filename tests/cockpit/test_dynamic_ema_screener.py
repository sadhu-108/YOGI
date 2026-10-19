"""Integration and validation tests for Dynamic EMA Condition Builder in Screener and Cockpit API."""

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence
import pytest
from pydantic import ValidationError

from yogi.cockpit.router import run_screen
from yogi.cockpit.schemas import FilterGroupIn, FilterRuleIn, ScreenRequestIn
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.selection.engine import SelectionEngine


class MockProvider(IDataProvider):
    name = "mock"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["ALPHA", "BETA"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        base = datetime(2025, 1, 1)
        # ALPHA: rising prices (EMA_fast > EMA_slow)
        # BETA: falling prices (EMA_fast < EMA_slow)
        if symbol == "ALPHA":
            return [
                MarketBar(
                    timestamp=base + timedelta(days=i),
                    open=100.0 + i,
                    high=102.0 + i,
                    low=98.0 + i,
                    close=101.0 + i,
                    volume=500.0,
                )
                for i in range(40)
            ]
        else:
            return [
                MarketBar(
                    timestamp=base + timedelta(days=i),
                    open=200.0 - i,
                    high=202.0 - i,
                    low=198.0 - i,
                    close=199.0 - i,
                    volume=500.0,
                )
                for i in range(40)
            ]

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock", ok=True)


from yogi.core.contracts.bands import IBandsRepository


class MockBandsRepo(IBandsRepository):
    def __init__(self):
        self.bands = {
            "ALPHA": {"D": 0.10, "W": 0.15, "M": 0.20, "Q": 0.25, "H": 0.30, "Y": 0.35},
            "BETA": {"D": 0.08, "W": 0.12, "M": 0.18, "Q": 0.22, "H": 0.28, "Y": 0.32},
        }

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        return self.bands.get(symbol, {}).get(timeframe)

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        return self.bands.get(symbol, {})

    def set_band(self, symbol: str, timeframe: str, value: float, who: str = "app", source: str = "app") -> float:
        if symbol not in self.bands:
            self.bands[symbol] = {}
        self.bands[symbol][timeframe] = value
        return value


@pytest.fixture
def test_app_state():
    from yogi.calculation.trend import TrendCalculator
    from yogi.timeframe.engine import TimeframeEngine

    hub = RegistryHub()
    provider = MockProvider()
    bands_repo = MockBandsRepo()
    hub.providers.register("mock", provider)
    hub.bands.register("mock", bands_repo)
    hub.calculations.register("trend", TrendCalculator())

    bars_cache = {
        "ALPHA": provider.daily_history("ALPHA"),
        "BETA": provider.daily_history("BETA"),
    }

    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        result_assembler=ResultAssembler(),
        timeframe_engine=TimeframeEngine(),
        bars_cache=bars_cache,
    )

    ds = {
        "ALPHA": {"symbol": "ALPHA", "name": "Alpha Ltd", "exchange": "NSE", "price": 100.0, "M_CUR": 25.0},
        "BETA": {"symbol": "BETA", "name": "Beta Ltd", "exchange": "NSE", "price": 200.0, "M_CUR": 15.0},
    }

    state = AppState(
        orchestrator=orchestrator,
        bars_cache=bars_cache,
        provider=provider,
        initial_dataset=ds,
    )
    return state


# -----------------------------------------------------------------------------
# 1. Schema & Validation Tests (P1/P2 Distinctness, Caps, States)
# -----------------------------------------------------------------------------

def test_dynamic_ema_schema_valid():
    """Verify that valid EMA rules pass schema validation and populate defaults."""
    rule = FilterRuleIn(
        condition_type="ema",
        timeframe="D",
        p1=9,
        p2=21,
        state="UPCUT",
    )
    assert rule.condition_type == "ema"
    assert rule.timeframe == "D"
    assert rule.p1 == 9
    assert rule.p2 == 21
    assert rule.state == "UPCUT"
    assert rule.field == "EMA_D_9_21"
    assert rule.value == "UPCUT"


def test_dynamic_ema_schema_equal_periods_rejected():
    """Verify Decision Gate A3: p1 == p2 is strictly disallowed with validation error."""
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(
            condition_type="ema",
            timeframe="D",
            p1=10,
            p2=10,
            state="UP",
        )
    assert "distinct" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "tf, max_cap, invalid_p",
    [
        ("D", 31, 32),
        ("W", 52, 53),
        ("M", 12, 13),
        ("Q", 4, 5),
        ("H", 2, 3),
        ("Y", 1, 2),
    ],
)
def test_dynamic_ema_schema_period_caps(tf, max_cap, invalid_p):
    """Verify timeframe period caps enforced according to Prompt 10 specification."""
    valid_p1 = max_cap
    valid_p2 = max_cap - 1 if max_cap > 1 else 1
    if valid_p1 != valid_p2:
        rule = FilterRuleIn(condition_type="ema", timeframe=tf, p1=valid_p1, p2=valid_p2, state="UP")
        assert rule.p1 == valid_p1

    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(condition_type="ema", timeframe=tf, p1=invalid_p, p2=1, state="UP")
    assert f"cannot exceed maximum {max_cap}" in str(exc_info.value)


def test_dynamic_ema_schema_invalid_state():
    """Verify only UP, DOWN, UPCUT, DOWNCUT are accepted."""
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(
            condition_type="ema",
            timeframe="D",
            p1=9,
            p2=21,
            state="SIDEWAYS",
        )
    assert "Invalid EMA state" in str(exc_info.value)


def test_dynamic_ema_schema_non_positive_period():
    """Verify periods must be positive integers >= 1."""
    with pytest.raises(ValidationError):
        FilterRuleIn(condition_type="ema", timeframe="D", p1=0, p2=10, state="UP")
    with pytest.raises(ValidationError):
        FilterRuleIn(condition_type="ema", timeframe="D", p1=5, p2=-3, state="UP")


# -----------------------------------------------------------------------------
# 2. FilterEngine Leaf Evaluation for Dynamic EMA Signals
# -----------------------------------------------------------------------------

def test_filter_engine_eval_leaf_dynamic_ema():
    """Verify FilterEngine correctly checks dynamic EMA signals dictionary."""
    engine = FilterEngine()
    rule_spec = FilterRuleIn(
        condition_type="ema",
        timeframe="D",
        p1=9,
        p2=21,
        state="UPCUT",
    ).to_core_spec()

    # Case 1: Row with matching UPCUT signal
    row_upcut = {
        "symbol": "AAA",
        "EMA_D_9_21": {
            "state": "UPCUT",
            "is_up": True,
            "is_down": False,
            "is_upcut": True,
            "is_downcut": False,
        },
    }
    assert engine._eval_leaf(row_upcut, rule_spec) is True

    # Case 2: Row with non-matching DOWN signal
    row_down = {
        "symbol": "BBB",
        "EMA_D_9_21": {
            "state": "DOWN",
            "is_up": False,
            "is_down": True,
            "is_upcut": False,
            "is_downcut": False,
        },
    }
    assert engine._eval_leaf(row_down, rule_spec) is False

    # Case 3: Test that target state UP matches both steady UP and UPCUT
    rule_up = FilterRuleIn(
        condition_type="ema",
        timeframe="D",
        p1=9,
        p2=21,
        state="UP",
    ).to_core_spec()
    assert engine._eval_leaf(row_upcut, rule_up) is True  # UPCUT is also UP!

    # Case 4: Row with steady UP (no recent crossover)
    row_steady_up = {
        "symbol": "CCC",
        "EMA_D_9_21": {
            "state": "UP",
            "is_up": True,
            "is_down": False,
            "is_upcut": False,
            "is_downcut": False,
        },
    }
    assert engine._eval_leaf(row_steady_up, rule_up) is True
    assert engine._eval_leaf(row_steady_up, rule_spec) is False  # not UPCUT


# -----------------------------------------------------------------------------
# 3. Cockpit API End-to-End Screening with Dynamic EMA Rules
# -----------------------------------------------------------------------------

def test_cockpit_screen_api_with_dynamic_ema_rule(test_app_state):
    """Verify run_screen executes dynamic EMA screening end-to-end."""
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[
                FilterRuleIn(
                    condition_type="ema",
                    timeframe="D",
                    p1=9,
                    p2=21,
                    state="UP",
                )
            ],
        ),
        limit=10,
    )
    out = run_screen(req=req, app_state=test_app_state)
    assert out.universe_count == 2
    # ALPHA is rising (EMA 9 > 21), BETA is falling (EMA 9 < 21)
    assert out.qualified_count == 1
    assert len(out.rows) == 1
    assert out.rows[0]["symbol"] == "ALPHA"


def test_cockpit_screen_api_multi_timeframe_combination(test_app_state):
    """Verify run_screen with combined Daily and Weekly dynamic EMA rules."""
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[
                FilterRuleIn(
                    condition_type="ema",
                    timeframe="D",
                    p1=3,
                    p2=5,
                    state="UP",
                ),
                FilterRuleIn(
                    condition_type="ema",
                    timeframe="W",
                    p1=5,
                    p2=13,
                    state="UP",
                ),
            ],
        ),
        limit=5,
    )
    out = run_screen(req=req, app_state=test_app_state)
    assert out.universe_count == 2
    # Only ALPHA satisfies both Daily and Weekly rising trends
    assert out.qualified_count == 1
    assert out.rows[0]["symbol"] == "ALPHA"


def test_cockpit_screen_api_rejects_invalid_ema_rule():
    """Verify ScreenRequestIn raises ValidationError for invalid EMA rules (FastAPI 422)."""
    # Period > Daily cap (31)
    with pytest.raises(ValidationError):
        ScreenRequestIn(
            filter_group=FilterGroupIn(
                match="all",
                rules=[
                    FilterRuleIn(
                        condition_type="ema",
                        timeframe="D",
                        p1=50,
                        p2=21,
                        state="UP",
                    )
                ],
            )
        )

    # Equal periods (p1 == p2)
    with pytest.raises(ValidationError):
        ScreenRequestIn(
            filter_group=FilterGroupIn(
                match="all",
                rules=[
                    FilterRuleIn(
                        condition_type="ema",
                        timeframe="D",
                        p1=15,
                        p2=15,
                        state="UP",
                    )
                ],
            )
        )


# -----------------------------------------------------------------------------
# 5. Generic Parameter Validation & Extensibility Tests (EMA-AUDIT-001)
# -----------------------------------------------------------------------------

def test_generic_ema_params_valid_omitting_legacy_fields():
    """Verify EMA-AUDIT-001: FilterRuleIn with generic params passes validation when legacy fields are omitted."""
    rule = FilterRuleIn(
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
    )
    assert rule.condition_type == "ema"
    assert rule.timeframe == "D"
    assert rule.p1 == 9
    assert rule.p2 == 21
    assert rule.state == "UP"
    assert rule.field == "EMA_D_9_21"
    assert rule.value == "UP"
    assert rule.params["timeframe"] == "D"
    assert rule.params["p1"] == 9
    assert rule.params["p2"] == 21
    assert rule.params["state"] == "UP"


def test_generic_ema_params_to_core_spec_conversion():
    """Verify that a generic EMA rule converts to a frozen Core FilterRuleSpec with all fields and params intact."""
    rule = FilterRuleIn(
        condition_type="ema",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UPCUT"},
    )
    spec = rule.to_core_spec()
    assert spec.condition_type == "ema"
    assert spec.field == "EMA_D_9_21"
    assert spec.value == "UPCUT"
    assert spec.timeframe == "D"
    assert spec.p1 == 9
    assert spec.p2 == 21
    assert spec.state == "UPCUT"
    assert dict(spec.params) == {"timeframe": "D", "p1": 9, "p2": 21, "state": "UPCUT"}


def test_generic_ema_params_normalization():
    """Verify that lowercase/whitespace timeframe and state in params are correctly normalized."""
    rule = FilterRuleIn(
        condition_type="ema",
        params={"timeframe": "  w  ", "p1": 5, "p2": 20, "state": "  downcut  "},
    )
    assert rule.timeframe == "W"
    assert rule.state == "DOWNCUT"
    assert rule.field == "EMA_W_5_20"
    assert rule.value == "DOWNCUT"
    assert rule.params["timeframe"] == "W"
    assert rule.params["state"] == "DOWNCUT"


def test_legacy_ema_fields_compatibility_and_sync():
    """Verify legacy EMA requests without params still validate and populate params for downstream consistency."""
    rule = FilterRuleIn(
        condition_type="ema",
        timeframe="M",
        p1=3,
        p2=6,
        state="DOWN",
    )
    assert rule.timeframe == "M"
    assert rule.p1 == 3
    assert rule.p2 == 6
    assert rule.state == "DOWN"
    assert rule.field == "EMA_M_3_6"
    assert rule.value == "DOWN"
    assert rule.params == {"timeframe": "M", "p1": 3, "p2": 6, "state": "DOWN"}

    spec = rule.to_core_spec()
    assert spec.timeframe == "M"
    assert spec.p1 == 3
    assert spec.p2 == 6
    assert spec.state == "DOWN"
    assert dict(spec.params) == {"timeframe": "M", "p1": 3, "p2": 6, "state": "DOWN"}


def test_dual_specification_matching_and_conflict_policy():
    """Verify consistent dual specification succeeds, while conflicting parameters are rejected deterministically."""
    # Matching dual specification succeeds
    rule = FilterRuleIn(
        condition_type="ema",
        timeframe="d",
        p1=9,
        p2=21,
        state="up",
        params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
    )
    assert rule.timeframe == "D"
    assert rule.state == "UP"

    # Conflicting timeframe is rejected
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(
            condition_type="ema",
            timeframe="D",
            p1=9,
            p2=21,
            state="UP",
            params={"timeframe": "W"},
        )
    assert "Conflicting 'timeframe' parameter" in str(exc_info.value)

    # Conflicting p1 is rejected
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(
            condition_type="ema",
            timeframe="D",
            p1=9,
            p2=21,
            state="UP",
            params={"p1": 15},
        )
    assert "Conflicting 'p1' parameter" in str(exc_info.value)

    # Conflicting state is rejected
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(
            condition_type="ema",
            timeframe="D",
            p1=9,
            p2=21,
            state="UP",
            params={"state": "DOWN"},
        )
    assert "Conflicting 'state' parameter" in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_params, expected_substr",
    [
        ({"p1": 9, "p2": 21, "state": "UP"}, "Invalid timeframe 'None'"),
        ({"timeframe": "INVALID", "p1": 9, "p2": 21, "state": "INVALID"}, "Invalid timeframe 'INVALID'"),
        ({"timeframe": "D", "p2": 21, "state": "UP"}, "Both p1 and p2 must be provided"),
        ({"timeframe": "D", "p1": 9, "state": "UP"}, "Both p1 and p2 must be provided"),
        ({"timeframe": "D", "p1": 0, "p2": 21, "state": "UP"}, "must be positive integers"),
        ({"timeframe": "D", "p1": True, "p2": 21, "state": "UP"}, "must be positive integers"),
        ({"timeframe": "D", "p1": 10, "p2": 10, "state": "UP"}, "must be distinct"),
        ({"timeframe": "D", "p1": 32, "p2": 21, "state": "UP"}, "cannot exceed maximum 31"),
        ({"timeframe": "D", "p1": 9, "p2": 21, "state": "INVALID_STATE"}, "Invalid EMA state"),
    ],
)
def test_generic_ema_params_invalid_rejections(invalid_params, expected_substr):
    """Verify invalid generic EMA params fail validation with specific error messages."""
    with pytest.raises(ValidationError) as exc_info:
        FilterRuleIn(condition_type="ema", params=invalid_params)
    assert expected_substr in str(exc_info.value)


def test_cockpit_screen_api_end_to_end_with_generic_params(test_app_state):
    """Verify end-to-end screening execution when EMA rules are supplied via generic params in ScreenRequestIn."""
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[
                FilterRuleIn(
                    condition_type="ema",
                    params={"timeframe": "D", "p1": 9, "p2": 21, "state": "UP"},
                )
            ],
        ),
        limit=10,
    )
    out = run_screen(req=req, app_state=test_app_state)
    assert out.universe_count == 2
    assert out.qualified_count == 1
    assert len(out.rows) == 1
    assert out.rows[0]["symbol"] == "ALPHA"


# -----------------------------------------------------------------------------
# 4. Production Evaluator Bootstrap & AppState Registration (EMA-AUDIT-007)
# -----------------------------------------------------------------------------

def test_production_app_state_evaluator_bootstrap():
    """Verify that production AppState startup reliably bootstraps default condition evaluators."""
    from yogi.cockpit.state import AppState
    from yogi.core.contracts.filter import IConditionEvaluator

    state = AppState(autoload_cache=False)
    assert state.filter_rule is not None
    assert hasattr(state.filter_rule, "has_evaluator")
    assert state.filter_rule.has_evaluator("ema") is True
    ema_eval = state.filter_rule.get_evaluator("ema")
    assert isinstance(ema_eval, IConditionEvaluator)


def test_app_state_register_condition_evaluator_and_isolation():
    """Verify AppState allows registering evaluators, enforces duplicate policy, and isolates instances."""
    from yogi.cockpit.state import AppState
    from yogi.core.contracts.filter import FilterRuleSpec, IConditionEvaluator

    class CustomRsiEvaluator(IConditionEvaluator):
        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
            return True

        def describe(self, rule: FilterRuleSpec) -> str:
            return "CustomRSI"

    class ConflictingRsiEvaluator(IConditionEvaluator):
        def evaluate(self, record: Mapping[str, Any], rule: FilterRuleSpec) -> Optional[bool]:
            return False

        def describe(self, rule: FilterRuleSpec) -> str:
            return "ConflictingRSI"

    state1 = AppState(autoload_cache=False)
    state2 = AppState(autoload_cache=False)

    rsi_eval = CustomRsiEvaluator()
    state1.register_condition_evaluator("rsi", rsi_eval)

    # 1. Registration succeeds on state1
    assert state1.filter_rule.has_evaluator("rsi") is True
    assert state1.filter_rule.get_evaluator("rsi") is rsi_eval

    # 2. Instance isolation: state2 is NOT polluted by state1 registration
    assert state2.filter_rule.has_evaluator("rsi") is False

    # 3. Duplicate registration of same instance on state1 is idempotent
    state1.register_condition_evaluator("rsi", rsi_eval)
    assert state1.filter_rule.get_evaluator("rsi") is rsi_eval

    # 4. Duplicate registration with conflicting instance on state1 is rejected
    conflicting = ConflictingRsiEvaluator()
    with pytest.raises(ValueError) as exc_info:
        state1.register_condition_evaluator("rsi", conflicting)
    assert "already registered" in str(exc_info.value)
    # Original remains intact
    assert state1.filter_rule.get_evaluator("rsi") is rsi_eval

    # 5. AppState with custom condition_evaluators dict at construction
    state3 = AppState(autoload_cache=False, condition_evaluators={"rsi": rsi_eval})
    assert state3.filter_rule.has_evaluator("ema") is True
    assert state3.filter_rule.get_evaluator("rsi") is rsi_eval



"""Tests for YOGI Core Registry — verifying capability mapping, lazy factories, and RegistryHub."""

from datetime import datetime
from typing import Sequence

import pytest

from yogi.core.contracts import (
    CalculationContext,
    CalculationResult,
    IBandsRepository,
    ICalcModule,
    IDataProvider,
    MarketBar,
    MarketContext,
    ProviderHealth,
    SecurityMetadata,
)
from yogi.core.registry import (
    CapabilityRegistry,
    DuplicateRegistrationError,
    RegistrationNotFoundError,
    RegistryHub,
)


# ---------------------------------------------------------------------------
# Lightweight Test Doubles
# ---------------------------------------------------------------------------


class DummyProvider(IDataProvider):
    @property
    def name(self) -> str:
        return "dummy_provider"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange="NSE"):
        return ["RELIANCE"]

    def daily_history(self, symbol, exchange="NSE", years=10):
        return [MarketBar(datetime.now(), 100.0, 105.0, 95.0, 102.0)]

    def batch_daily_history(self, symbols, exchange="NSE", years=10):
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol, exchange="NSE"):
        return 102.0

    def intraday(self, symbol, exchange="NSE", interval="5minute", days=5):
        return []

    def subscribe_ticks(self, symbols, on_tick, exchange="NSE"):
        return None

    def trading_holidays(self, year=None):
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True)


class DummyCalc(ICalcModule):
    def __init__(self, name: str, metric_key: str) -> None:
        self.name = name
        self.metric_key = metric_key
        self.required_timeframes: Sequence[str] = ("D",)

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        return CalculationResult(
            symbol=symbol,
            module_name=self.name,
            metrics={self.metric_key: 100.0},
        )


class DummyBands(IBandsRepository):
    def get_band(self, symbol: str, timeframe: str):
        return 0.12

    def get_all_bands(self, symbol: str):
        return {"D": 0.12}

    def set_band(self, symbol: str, timeframe: str, value: float, who="app", source="app"):
        return value


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_registry_register_and_retrieve():
    """Test 1: Registry can register and retrieve an implementation."""
    registry: CapabilityRegistry[IDataProvider] = CapabilityRegistry("providers", IDataProvider)
    provider = DummyProvider()
    registry.register("dummy", provider)

    retrieved = registry.get("dummy")
    assert retrieved is provider
    assert registry["dummy"] is provider


def test_registry_has_key():
    """Test 2: Registry reports whether a key exists."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("greeting", "hello")

    assert registry.has("greeting") is True
    assert ("greeting" in registry) is True
    assert registry.has("farewell") is False
    assert ("farewell" in registry) is False


def test_registry_list_keys():
    """Test 3: Registry lists registered keys."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("b", "val_b")
    registry.register("a", "val_a")
    registry.register_factory("c", lambda: "val_c")

    assert registry.list_keys() == ["a", "b", "c"]
    assert len(registry) == 3


def test_duplicate_keys_are_rejected():
    """Test 4: Duplicate keys are rejected with DuplicateRegistrationError."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("key1", "first")

    with pytest.raises(DuplicateRegistrationError) as exc_info:
        registry.register("key1", "second")
    assert "Duplicate registration for key 'key1'" in str(exc_info.value)

    with pytest.raises(DuplicateRegistrationError):
        registry.register_factory("key1", lambda: "third")


def test_missing_keys_produce_clear_error():
    """Test 5: Missing keys produce a clear RegistrationNotFoundError."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")

    with pytest.raises(RegistrationNotFoundError) as exc_info:
        registry.get("nonexistent")
    assert "No implementation registered for key 'nonexistent'" in str(exc_info.value)
    assert issubclass(RegistrationNotFoundError, KeyError)


def test_lazy_factories_not_instantiated_during_registration():
    """Test 6: Lazy factories are not instantiated during registration."""
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        return DummyProvider()

    registry: CapabilityRegistry[IDataProvider] = CapabilityRegistry("providers", IDataProvider)
    registry.register_factory("lazy_provider", factory)

    assert registry.has("lazy_provider") is True
    assert call_count == 0


def test_lazy_factories_instantiate_only_when_requested():
    """Test 7: Lazy factories instantiate only when requested, and cache the instance."""
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        return DummyProvider()

    registry: CapabilityRegistry[IDataProvider] = CapabilityRegistry("providers", IDataProvider)
    registry.register_factory("lazy_provider", factory)

    assert call_count == 0

    # First retrieval -> factory executed
    instance1 = registry.get("lazy_provider")
    assert call_count == 1
    assert isinstance(instance1, DummyProvider)

    # Second retrieval -> cached instance returned without re-executing factory
    instance2 = registry.get("lazy_provider")
    assert call_count == 1
    assert instance2 is instance1


def test_registry_hub_exposes_exactly_approved_categories():
    """Test 8: RegistryHub exposes exactly providers, calculations, and bands."""
    hub = RegistryHub()

    assert isinstance(hub.providers, CapabilityRegistry)
    assert isinstance(hub.calculations, CapabilityRegistry)
    assert isinstance(hub.bands, CapabilityRegistry)

    assert hub.providers.capability_name == "providers"
    assert hub.calculations.capability_name == "calculations"
    assert hub.bands.capability_name == "bands"


def test_registry_hub_does_not_expose_unapproved_registries():
    """Test 9: RegistryHub does NOT expose registries for rejected categories."""
    hub = RegistryHub()

    rejected_attributes = [
        "securities",
        "security",
        "filters",
        "filter",
        "strategies",
        "strategy",
        "rankings",
        "ranking",
        "selections",
        "selection",
        "assemblers",
        "assembler",
        "formatters",
        "formatter",
    ]

    for attr in rejected_attributes:
        assert not hasattr(hub, attr), f"RegistryHub must not expose unapproved category '{attr}'"


def test_multiple_calculations_registered_simultaneously():
    """Test 10: Multiple calculation modules can be registered simultaneously."""
    hub = RegistryHub()

    bands_calc = DummyCalc("bands", "BANDST_M")
    velocity_calc = DummyCalc("velocity", "S4")
    impulse_calc = DummyCalc("impulse", "IC")
    trend_calc = DummyCalc("trend", "EMA_W")

    hub.calculations.register("bands", bands_calc)
    hub.calculations.register("velocity", velocity_calc)
    hub.calculations.register("impulse", impulse_calc)
    hub.calculations.register("trend", trend_calc)

    assert hub.calculations.list_keys() == ["bands", "impulse", "trend", "velocity"]
    assert len(hub.calculations) == 4


def test_multiple_calculations_retrieved_without_replacement():
    """Test 11: Multiple calculation modules can be retrieved without one replacing another."""
    hub = RegistryHub()

    bands_calc = DummyCalc("bands", "BANDST_M")
    velocity_calc = DummyCalc("velocity", "S4")
    impulse_calc = DummyCalc("impulse", "IC")
    trend_calc = DummyCalc("trend", "EMA_W")

    hub.calculations.register("bands", bands_calc)
    hub.calculations.register("velocity", velocity_calc)
    hub.calculations.register("impulse", impulse_calc)
    hub.calculations.register("trend", trend_calc)

    all_calcs = hub.calculations.all()
    assert len(all_calcs) == 4
    assert all_calcs["bands"].metric_key == "BANDST_M"
    assert all_calcs["velocity"].metric_key == "S4"
    assert all_calcs["impulse"].metric_key == "IC"
    assert all_calcs["trend"].metric_key == "EMA_W"

    # Individual get calls verify distinct instances
    assert hub.calculations.get("bands") is bands_calc
    assert hub.calculations.get("velocity") is velocity_calc
    assert hub.calculations.get("impulse") is impulse_calc
    assert hub.calculations.get("trend") is trend_calc


def test_type_safety_enforced():
    """Test type checking on registered instances and factories."""
    registry: CapabilityRegistry[IDataProvider] = CapabilityRegistry("providers", IDataProvider)

    # Incompatible instance type raises TypeError
    with pytest.raises(TypeError) as exc_info:
        registry.register("invalid", "not_a_provider")  # type: ignore
    assert "must implement IDataProvider" in str(exc_info.value)

    # Incompatible factory output raises TypeError on get()
    registry.register_factory("invalid_factory", lambda: 123)  # type: ignore
    with pytest.raises(TypeError) as exc_info:
        registry.get("invalid_factory")
    assert "produced int, expected IDataProvider" in str(exc_info.value)


def test_no_global_singleton_leakage():
    """Test that RegistryHub instances are completely isolated."""
    hub1 = RegistryHub()
    hub2 = RegistryHub()

    hub1.providers.register("dummy", DummyProvider())
    assert hub1.providers.has("dummy") is True
    assert hub2.providers.has("dummy") is False


def test_registry_allow_override_replaces_existing_instance():
    """Test that register(allow_override=True) and override() cleanly replace instances."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("key1", "initial")
    assert registry.get("key1") == "initial"

    # Without allow_override -> raises DuplicateRegistrationError
    with pytest.raises(DuplicateRegistrationError):
        registry.register("key1", "second")

    # With allow_override=True -> replaces instance
    registry.register("key1", "second", allow_override=True)
    assert registry.get("key1") == "second"

    # Using override() convenience method
    registry.override("key1", "third")
    assert registry.get("key1") == "third"


def test_registry_override_replaces_lazy_factory():
    """Test that override() replaces an uninvoked lazy factory without executing it."""
    factory_invoked = False

    def factory():
        nonlocal factory_invoked
        factory_invoked = True
        return "from_factory"

    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register_factory("key1", factory)
    assert registry.has("key1") is True

    # Override with instance
    registry.override("key1", "overridden_value")
    assert registry.get("key1") == "overridden_value"
    assert factory_invoked is False  # Factory was never invoked!


def test_registry_override_factory_replaces_existing_instance():
    """Test that override_factory() replaces a cached instance with a new factory."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("key1", "instance_val")
    assert registry.get("key1") == "instance_val"

    registry.override_factory("key1", lambda: "new_factory_val")
    assert registry.get("key1") == "new_factory_val"


def test_registry_unregister():
    """Test that unregister() cleanly removes instances and factories."""
    registry: CapabilityRegistry[str] = CapabilityRegistry("strings")
    registry.register("inst", "val1")
    registry.register_factory("fact", lambda: "val2")

    assert registry.has("inst") is True
    assert registry.has("fact") is True

    registry.unregister("inst")
    assert registry.has("inst") is False
    assert "inst" not in registry.list_keys()

    registry.unregister("fact")
    assert registry.has("fact") is False
    assert "fact" not in registry.list_keys()

    # Unregistering nonexistent key does not raise
    registry.unregister("nonexistent")


def test_create_default_registry_hub_structure():
    """Test that create_default_registry_hub registers all required default capabilities."""
    from yogi.core.registry import create_default_registry_hub

    hub = create_default_registry_hub()

    # Calculations
    assert set(hub.calculations.list_keys()) == {"bands", "candles", "impulse", "trend", "velocity"}
    # Providers
    assert set(hub.providers.list_keys()) == {"demo", "yfinance"}
    # Bands repositories
    assert set(hub.bands.list_keys()) == {"csv", "demo", "excel"}

    # Resolving demo provider does not instantiate yfinance
    assert "yfinance" not in hub.providers._instances
    demo_p = hub.providers.get("demo")
    assert demo_p.name == "demo"
    assert "yfinance" not in hub.providers._instances

    # Resolving csv and excel returns the shared bands repo instance
    csv_bands = hub.bands.get("csv")
    excel_bands = hub.bands.get("excel")
    assert csv_bands is excel_bands


"""Tests for Prompt C: Cockpit Provider-Resolution Decoupling & Centralized RegistryHub."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from typing import Mapping, Optional, Sequence
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.registry import (
    CapabilityRegistry,
    DuplicateRegistrationError,
    create_default_registry_hub,
)
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.bands import CsvBandsRepository
from yogi.storage.cache import DatasetCache, MarketBarsCache
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class MockDecoupledProvider(IDataProvider):
    name = "mock_decoupled"

    def __init__(self, symbols=("RELIANCE", "TCS"), should_fail=False):
        self._symbols = list(symbols)
        self.should_fail = should_fail
        self._bars = [
            MarketBar(
                timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                open=100.0 + i,
                high=105.0 + i,
                low=95.0 + i,
                close=102.0 + i,
                volume=1000.0,
            )
            for i in range(50)
        ]

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        if self.should_fail:
            raise DataProviderError("Simulated universe failure")
        return tuple(self._symbols)

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 10) -> Sequence[MarketBar]:
        if self.should_fail:
            raise DataProviderError(f"Simulated download failure for {symbol}")
        return self._bars

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 10) -> Mapping[str, Sequence[MarketBar]]:
        if self.should_fail:
            raise DataProviderError("Simulated batch failure")
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return self._bars[-1].close if self._bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: any, exchange: str = "NSE") -> any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self, symbol: Optional[str] = None, exchange: Optional[str] = None) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=not self.should_fail, sample_price=102.0)


def test_create_default_registry_hub_registers_all_capabilities():
    """Verify create_default_registry_hub centralizes all required default capability keys."""
    hub = create_default_registry_hub()

    # Required calculations
    assert hub.calculations.has("bands")
    assert hub.calculations.has("velocity")
    assert hub.calculations.has("impulse")
    assert hub.calculations.has("trend")
    assert hub.calculations.has("candles")

    # Required providers
    assert hub.providers.has("demo")
    assert hub.providers.has("yfinance")

    # Required bands repositories
    assert hub.bands.has("demo")
    assert hub.bands.has("csv")
    assert hub.bands.has("excel")


def test_capability_registry_public_override_api():
    """Verify CapabilityRegistry public override and allow_override methods replace instances/factories."""
    reg: CapabilityRegistry[IDataProvider] = CapabilityRegistry("providers", IDataProvider)
    mock1 = MockDecoupledProvider(symbols=["SYM1"])
    mock2 = MockDecoupledProvider(symbols=["SYM2"])

    # Normal registration
    reg.register("p", mock1)
    assert reg.get("p") is mock1

    # Duplicate without allow_override raises
    with pytest.raises(DuplicateRegistrationError):
        reg.register("p", mock2)

    # register with allow_override=True succeeds
    reg.register("p", mock2, allow_override=True)
    assert reg.get("p") is mock2

    # override() convenience method succeeds
    mock3 = MockDecoupledProvider(symbols=["SYM3"])
    reg.override("p", mock3)
    assert reg.get("p") is mock3

    # unregister removes the key
    reg.unregister("p")
    assert not reg.has("p")


def test_app_state_default_init_uses_central_registry():
    """Verify AppState initializes with default RegistryHub containing required keys."""
    state = AppState(autoload_cache=False)

    assert state.orchestrator.registry.providers.has("demo")
    assert state.orchestrator.registry.providers.has("yfinance")
    assert state.orchestrator.registry.bands.has("csv")
    assert state.orchestrator.registry.bands.has("excel")
    assert state.orchestrator.registry.bands.has("demo")


def test_app_state_provider_injection_via_constructor():
    """Verify AppState(provider=...) registers through public override without mutating _instances."""
    mock_p = MockDecoupledProvider(symbols=["INJECTED"])
    config = EngineConfig(provider="custom_mock")
    state = AppState(provider=mock_p, config=config, autoload_cache=False)

    resolved = state.orchestrator.registry.providers.get("custom_mock")
    assert resolved is mock_p
    assert resolved.universe() == ("INJECTED",)


def test_load_persisted_cache_resolves_via_registry_without_adhoc_registration(tmp_path: Path):
    """Verify load_persisted_cache resolves provider and bands via registry."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache = DatasetCache(cache_dir=cache_dir)
    bars_cache = MarketBarsCache(cache_dir=cache_dir)
    bands_repo = CsvBandsRepository(data_dir=tmp_path / "bands")

    mock_p = MockDecoupledProvider(symbols=["TEST1", "TEST2"])
    state = AppState(
        bands_repo=bands_repo,
        autoload_cache=False,
        dataset_cache=dataset_cache,
        bars_cache=bars_cache,
    )
    state.orchestrator.registry.providers.override("yfinance", mock_p)

    # Save mock cache
    raw_data = {
        "TEST1": {"symbol": "TEST1", "close": 150.0, "price": 150.0, "DROC": 1.5},
        "TEST2": {"symbol": "TEST2", "close": 200.0, "price": 200.0, "DROC": 2.0},
    }
    dataset_cache.save(raw_data, exchange="NSE", provider="yfinance", half_year_policy="prototype")

    loaded = state.load_persisted_cache()
    assert loaded is True
    assert state.is_cached is True
    assert len(state.dataset) == 2
    assert "TEST1" in state.dataset
    assert "TEST2" in state.dataset


import asyncio


def test_refresh_uses_registry_and_bubbles_errors(tmp_path: Path):
    """Verify refresh resolves through registry, updates presentation services, and bubbles provider errors."""
    async def _run():
        mock_p = MockDecoupledProvider(symbols=["RELIANCE", "TCS"])
        cache_dir = tmp_path / "cache"
        bands_repo = CsvBandsRepository(data_dir=tmp_path / "bands")

        state = AppState(
            bands_repo=bands_repo,
            dataset_cache=DatasetCache(cache_dir=cache_dir),
            bars_cache=MarketBarsCache(cache_dir=cache_dir),
            autoload_cache=False,
        )
        state.orchestrator.registry.providers.override("yfinance", mock_p)

        # 1. Successful refresh
        await state.refresh(provider="yfinance", symbols=["RELIANCE", "TCS"])
        assert state.build_status == "READY"
        assert len(state.dataset) == 2
        assert state.chart_service is not None
        assert state.chart_service.provider is mock_p
        assert state.race_service is not None
        assert state.race_service.provider is mock_p

        # 2. Failing provider must raise error and bubble up without fallback
        failing_p = MockDecoupledProvider(should_fail=True)
        state.orchestrator.registry.providers.override("yfinance", failing_p)

        with pytest.raises(Exception):
            await state.refresh(provider="yfinance", symbols=["RELIANCE"])
        assert state.build_status == "FAILED"
        assert len(state.dataset) == 2  # Previous dataset preserved!

    asyncio.run(_run())


def test_get_stock_panel_resolves_via_registry(tmp_path: Path):
    """Verify get_stock_panel executes through registry-resolved capabilities."""
    mock_p = MockDecoupledProvider(symbols=["RELIANCE"])
    state = AppState(
        bands_repo=CsvBandsRepository(data_dir=tmp_path / "bands"),
        bars_cache=MarketBarsCache(cache_dir=tmp_path / "bars"),
        autoload_cache=False,
    )
    state.orchestrator.registry.providers.override("yfinance", mock_p)

    panel = state.get_stock_panel("RELIANCE")
    assert panel is not None
    assert panel.symbol == "RELIANCE"
    assert panel.price == mock_p._bars[-1].close

    # Unregistered provider key returns None
    state._config = EngineConfig(provider="nonexistent_provider")
    assert state.get_stock_panel("RELIANCE") is None

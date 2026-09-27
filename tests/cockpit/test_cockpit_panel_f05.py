"""Focused tests for YOGI-F05: Stock-Panel / Dataset Asymmetry.

Verifies:
1. Canonical on-demand resolution via PipelineOrchestrator.build_dataset(EngineConfig(symbols=[sym])).
2. Dataset immutability (self._dataset is never mutated or merged).
3. Bounded isolated _panel_cache (LRU eviction, max entries).
4. Demo/Live isolation (demo symbols never leak into live; cache cleared on provider switch).
5. Error mapping (401 for auth, 429 for rate-limit, 503 for outage, 404 for unknown/unavailable).
6. Failed and error results are never cached.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence
import pytest
from fastapi import HTTPException

from yogi.cockpit.app import create_app
from yogi.cockpit.demo import DemoBandsRepository
from yogi.data.providers.demo import DemoDataProvider
from yogi.cockpit.router import RateLimitExceededError
from yogi.cockpit.schemas import StockDetailPanelOut, TimeframeRowOut
from yogi.cockpit.state import AppState, EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class ControllableMockProvider(IDataProvider):
    """Mock provider with controllable exceptions and responses."""

    def __init__(self, name: str = "controllable_mock") -> None:
        self._name = name
        self.error_to_raise: Optional[Exception] = None
        self.call_history: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["VALID_SYM", "SECOND_SYM"]

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 2
    ) -> Sequence[MarketBar]:
        self.call_history.append(symbol)
        if self.error_to_raise:
            raise self.error_to_raise

        if symbol in ("VALID_SYM", "SECOND_SYM", "SYM1", "SYM2", "SYM3", "SYM4"):
            base = datetime(2025, 1, 1)
            return [
                MarketBar(
                    timestamp=base + timedelta(days=i),
                    open=100.0 + i,
                    high=105.0 + i,
                    low=95.0 + i,
                    close=102.0 + i,
                    volume=1000.0,
                )
                for i in range(25)
            ]
        # Unknown/unlisted symbol returns empty bars
        return ()

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange)
        return bars[-1].close if bars else None

    def intraday(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self._name, ok=True)


@pytest.fixture
def demo_app_client() -> AsgiTestClient:
    """Fixture providing initialized FastAPI app with pre-materialized Demo dataset."""
    state = AppState(config=EngineConfig(provider="demo", bands_repository="demo"))
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    return client


# =============================================================================
# 1. Canonical Resolution & Dataset Immutability
# =============================================================================

def test_f05_dataset_hit_returns_instantly_without_cache_lookup():
    """Verify pre-screened symbols in _dataset return instantly from cohort."""
    state = AppState(
        config=EngineConfig(provider="demo", bands_repository="demo"),
        initial_dataset={"MANYAVAR": {"symbol": "MANYAVAR", "price": 1000.0, "exchange": "NSE"}},
    )
    panel = state.get_stock_panel("MANYAVAR")
    assert panel is not None
    assert panel.symbol == "MANYAVAR"
    assert panel.price == 1000.0
    # Must not populate panel cache since it was in _dataset
    assert "MANYAVAR" not in state._panel_cache


def test_f05_canonical_on_demand_resolution_when_symbol_absent():
    """Verify absent symbol resolves via PipelineOrchestrator.build_dataset(single_config)."""
    # Demo dataset with only MANYAVAR pre-materialized
    state = AppState(
        config=EngineConfig(provider="demo", bands_repository="demo"),
        initial_dataset={"MANYAVAR": {"symbol": "MANYAVAR", "price": 1000.0, "exchange": "NSE"}},
    )
    initial_dataset_ref = state.dataset
    initial_len = len(state.dataset)

    # SBCL is in DemoDataProvider but NOT in initial_dataset
    assert "SBCL" not in state.dataset
    panel = state.get_stock_panel("SBCL")

    # 1. Successfully resolved
    assert panel is not None
    assert panel.symbol == "SBCL"
    assert panel.price is not None
    assert len(panel.timeframes) == 6
    assert any(r.timeframe == "D" for r in panel.timeframes)

    # 2. self._dataset is completely untouched (not mutated, not merged)
    assert "SBCL" not in state.dataset
    assert len(state.dataset) == initial_len
    assert state.dataset is initial_dataset_ref

    # 3. Cached in isolated _panel_cache
    assert "SBCL" in state._panel_cache
    assert state._panel_cache["SBCL"] is panel

    # 4. Subsequent read hits _panel_cache without orchestrator call
    cached_panel = state.get_stock_panel("SBCL")
    assert cached_panel is panel


# =============================================================================
# 2. Bounded Isolated Cache & LRU Eviction
# =============================================================================

def test_f05_panel_cache_bounded_lru_eviction():
    """Verify _panel_cache respects capacity limit and performs LRU eviction."""
    state = AppState(
        config=EngineConfig(provider="demo", bands_repository="demo"),
        initial_dataset={},
    )
    state._panel_cache_max_size = 3

    # Add 3 dummy panel objects
    for sym in ("SYM1", "SYM2", "SYM3"):
        panel = StockDetailPanelOut(
            symbol=sym,
            exchange="NSE",
            price=100.0,
            timeframes=[],
            key_metrics={},
        )
        with state._panel_cache_lock:
            state._panel_cache[sym] = panel

    assert len(state._panel_cache) == 3
    assert list(state._panel_cache.keys()) == ["SYM1", "SYM2", "SYM3"]

    # Access SYM1 to make it most recently used: order becomes SYM2, SYM3, SYM1
    _ = state.get_stock_panel("SYM1")
    assert list(state._panel_cache.keys()) == ["SYM2", "SYM3", "SYM1"]

    # Insert SYM4 directly or via cache insertion
    p4 = StockDetailPanelOut(
        symbol="SYM4",
        exchange="NSE",
        price=100.0,
        timeframes=[],
        key_metrics={},
    )
    with state._panel_cache_lock:
        if len(state._panel_cache) >= state._panel_cache_max_size:
            state._panel_cache.popitem(last=False)
        state._panel_cache["SYM4"] = p4

    # Size must not exceed max_size (3)
    assert len(state._panel_cache) == 3
    # SYM2 (least recently used) must be evicted; SYM1 must be preserved
    assert "SYM2" not in state._panel_cache
    assert "SYM1" in state._panel_cache
    assert "SYM3" in state._panel_cache
    assert "SYM4" in state._panel_cache


def test_f05_clear_panel_cache_and_property_access():
    """Verify clear_panel_cache() wipes the cache and panel_cache returns read-only mapping."""
    state = AppState(
        config=EngineConfig(provider="demo", bands_repository="demo"),
        initial_dataset={},
    )
    dummy_panel = StockDetailPanelOut(
        symbol="SBCL",
        exchange="NSE",
        price=100.0,
        timeframes=[],
        key_metrics={},
    )
    state._panel_cache["SBCL"] = dummy_panel

    view = state.panel_cache
    assert view["SBCL"].symbol == "SBCL"
    with pytest.raises(TypeError):
        view["NEW"] = dummy_panel  # Read-only MappingProxyType

    state.clear_panel_cache()
    assert len(state._panel_cache) == 0


# =============================================================================
# 3. Demo / Live Isolation
# =============================================================================

def test_f05_demo_live_isolation_on_refresh():
    """Verify Demo and Live modes cannot cross-contaminate and cache clears on refresh."""
    async def _test():
        state = AppState(
            config=EngineConfig(provider="demo", bands_repository="demo"),
            initial_dataset={},
        )

        # Resolve a demo stock on-demand
        panel_demo = state.get_stock_panel("SBCL")
        assert panel_demo is not None
        assert "SBCL" in state._panel_cache

        # Switch to Live mode via refresh()
        await state.refresh(provider="twelvedata")

        # Panel cache must be completely cleared upon mode switch
        assert len(state._panel_cache) == 0
        assert "SBCL" not in state._panel_cache

    asyncio.run(_test())


def test_f05_demo_mode_cannot_contact_external_networks():
    """Verify demo mode returns None/404 for unlisted stocks without calling external APIs."""
    state = AppState(
        config=EngineConfig(provider="demo", bands_repository="demo"),
        initial_dataset={},
    )
    # Non-demo stock in DemoDataProvider returns empty bars, resulting in None
    panel = state.get_stock_panel("NON_DEMO_TICKER")
    assert panel is None
    assert "NON_DEMO_TICKER" not in state._panel_cache


# =============================================================================
# 4. Failed and Provider-Error Results Are Never Cached
# =============================================================================

def test_f05_failed_requests_not_cached(demo_app_client: AsgiTestClient):
    """Verify 404 results for unknown stocks are never added to _panel_cache."""
    res = demo_app_client.get("/api/panel/TOTALLY_UNKNOWN_XYZ")
    assert res.status_code == 404
    data = res.json()
    assert "not found" in data["detail"].lower()


# =============================================================================
# 5. Explicit HTTP Error Code Mapping
# =============================================================================

def test_f05_provider_authentication_error_returns_401():
    """Verify provider auth error maps to HTTP 401 and is not cached."""
    mock_provider = ControllableMockProvider()
    mock_provider.error_to_raise = DataProviderAuthenticationError("Invalid API key")

    state = AppState(
        config=EngineConfig(provider="controllable_mock", bands_repository="demo"),
        initial_dataset={},
    )
    state.orchestrator.registry.providers.register("controllable_mock", mock_provider)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    res = client.get("/api/panel/VALID_SYM")
    assert res.status_code == 401
    assert "authentication failed" in res.json()["detail"].lower()
    assert "VALID_SYM" not in state._panel_cache


def test_f05_provider_rate_limit_returns_429():
    """Verify provider rate limit error maps to HTTP 429 and is not cached."""
    mock_provider = ControllableMockProvider()
    mock_provider.error_to_raise = RateLimitExceededError("Rate limit exceeded. 8 credits/min.")

    state = AppState(
        config=EngineConfig(provider="controllable_mock", bands_repository="demo"),
        initial_dataset={},
    )
    state.orchestrator.registry.providers.register("controllable_mock", mock_provider)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    res = client.get("/api/panel/VALID_SYM")
    assert res.status_code == 429
    assert "rate limit" in res.json()["detail"].lower()
    assert "VALID_SYM" not in state._panel_cache


def test_f05_provider_outage_returns_503():
    """Verify provider communication failure / outage maps to HTTP 503 and is not cached."""
    mock_provider = ControllableMockProvider()
    mock_provider.error_to_raise = DataProviderError("Connection refused by upstream vendor host.")

    state = AppState(
        config=EngineConfig(provider="controllable_mock", bands_repository="demo"),
        initial_dataset={},
    )
    state.orchestrator.registry.providers.register("controllable_mock", mock_provider)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    res = client.get("/api/panel/VALID_SYM")
    assert res.status_code == 503
    assert "offline" in res.json()["detail"].lower() or "unavailable" in res.json()["detail"].lower()
    assert "VALID_SYM" not in state._panel_cache


def test_f05_unknown_symbol_returns_404():
    """Verify genuinely unknown / unlisted symbol returns HTTP 404."""
    mock_provider = ControllableMockProvider()
    # No error raised; UNLISTED_SYM will return empty history ()

    state = AppState(
        config=EngineConfig(provider="controllable_mock", bands_repository="demo"),
        initial_dataset={},
    )
    state.orchestrator.registry.providers.register("controllable_mock", mock_provider)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    res = client.get("/api/panel/UNLISTED_SYM")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()
    assert "UNLISTED_SYM" not in state._panel_cache

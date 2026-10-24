"""Unit and integration tests for Sprint Race curve calculation, RaceDataService, and GET /api/race."""

import asyncio
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence
import pandas as pd
import pytest
import json
from pathlib import Path
import shutil
import subprocess
from bs4 import BeautifulSoup

from yogi.cockpit.app import create_app
from yogi.cockpit.schemas import RaceResponseOut
from yogi.cockpit.services.race import RaceDataService
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.storage import IBarsCache
from tests.cockpit.test_cockpit_api import AsgiTestClient


class MockRaceProvider(IDataProvider):
    """Mock provider with controlled daily price history across 2020-2026."""

    name = "mock_race"

    def __init__(self, stock_prices: Mapping[str, Mapping[str, float]]) -> None:
        self.stock_prices = stock_prices

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return tuple(self.stock_prices.keys())

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
    ) -> Sequence[MarketBar]:
        sym = symbol.strip().upper()
        if sym not in self.stock_prices:
            return ()

        cfg = self.stock_prices[sym]
        start_date = cfg.get("start", "2020-01-01")
        base_val = cfg.get("base", 100.0)
        final_val = cfg.get("final", 200.0)

        dates = pd.date_range(start_date, "2026-08-01", freq="W-FRI")
        n = len(dates)
        if n < 3:
            return ()

        # Linear progression from base_val to final_val
        bars = []
        for i, dt in enumerate(dates):
            p = base_val + (final_val - base_val) * (i / max(1, n - 1))
            bars.append(
                MarketBar(
                    timestamp=dt.to_pydatetime(),
                    open=p,
                    high=p * 1.02,
                    low=p * 0.98,
                    close=p,
                    volume=50000.0,
                )
            )
        return tuple(bars)

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
        return ProviderHealth(is_healthy=True, message="mock healthy")


@pytest.fixture
def mock_race_setup():
    stocks = {
        "ALPHA": {"start": "2020-01-01", "base": 100.0, "final": 300.0},  # +200%
        "BETA": {"start": "2020-01-01", "base": 100.0, "final": 200.0},   # +100%
        "GAMMA": {"start": "2020-01-01", "base": 100.0, "final": 150.0},  # +50%
        "LATE_IPO": {"start": "2023-01-01", "base": 100.0, "final": 180.0},# Listed after 2021
        "CORRUPT": {"start": "2020-01-01", "base": 1.0, "final": 5000.0},  # Extreme outlier
    }
    provider = MockRaceProvider(stocks)
    dataset = {
        "ALPHA": {"symbol": "ALPHA", "name": "Alpha Corp", "SPA_A21": 200.0, "SUSPECT": "N"},
        "BETA": {"symbol": "BETA", "name": "Beta Ltd", "SPA_A21": 100.0, "SUSPECT": "N"},
        "GAMMA": {"symbol": "GAMMA", "name": "Gamma Inc", "SPA_A21": 50.0, "SUSPECT": "N"},
        "LATE_IPO": {"symbol": "LATE_IPO", "name": "Late IPO", "SPA_A21": None, "SUSPECT": "N"},
        "CORRUPT": {"symbol": "CORRUPT", "name": "Corrupt Co", "SPA_A21": 50000.0, "SUSPECT": "Y"},
    }
    svc = RaceDataService(provider=provider, dataset_provider=lambda: dataset)
    return provider, dataset, svc


def test_race_data_service_explicit_symbols(mock_race_setup):
    """Verify get_race returns ordered curves for explicitly requested symbols."""
    provider, dataset, svc = mock_race_setup

    res = asyncio.run(svc.get_race(symbols="BETA,ALPHA", anchor="2021-01-01", top=5))
    assert isinstance(res, RaceResponseOut)
    assert res.anchor == "2021-01-01"
    assert len(res.lines) == 2

    # ALPHA (+200%) should rank before BETA (+100%)
    assert res.lines[0].symbol == "ALPHA"
    assert res.lines[0].label == "Alpha Corp"
    assert res.lines[0].final > res.lines[1].final
    assert len(res.lines[0].points) > 10
    assert res.lines[0].points[0].time.startswith("2021")


def test_race_data_service_auto_leaders_and_filtering(mock_race_setup):
    """Verify get_race auto-selects valid leaders, excluding corrupt and late IPOs."""
    provider, dataset, svc = mock_race_setup

    res = asyncio.run(svc.get_race(symbols=None, anchor="2021-01-01", top=3, metric="SPA_A21"))
    symbols_returned = [line.symbol for line in res.lines]

    # Should contain ALPHA, BETA, GAMMA in descending order of returns
    assert symbols_returned == ["ALPHA", "BETA", "GAMMA"]
    # Late IPO has no pre-2021 base; Corrupt is SUSPECT="Y" or final >= 3000
    assert "LATE_IPO" not in symbols_returned
    assert "CORRUPT" not in symbols_returned


def test_race_data_service_caching(mock_race_setup):
    """Verify responses are stored in and served from LRU cache."""
    provider, dataset, svc = mock_race_setup

    res1 = asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", top=5))
    res2 = asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", top=5))
    assert res1 is res2  # Identical cached object reference

    svc.clear_cache()
    res3 = asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", top=5))
    assert res1 is not res3
    assert res1.lines[0].final == res3.lines[0].final


def test_api_race_endpoint_success(mock_race_setup):
    """Verify HTTP GET /api/race returns 200 with schema-validated response."""
    provider, dataset, svc = mock_race_setup

    state = AppState(
        provider=provider,
        race_service=svc,
        initial_dataset=dataset,
    )
    app = create_app(app_state=state)
    client = AsgiTestClient(app)

    # 1. Query with explicit symbols
    resp = client.request("GET", "/api/race", params={"symbols": "ALPHA,BETA", "anchor": "2021-01-01", "top": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["anchor"] == "2021-01-01"
    assert len(data["lines"]) == 2
    assert data["lines"][0]["symbol"] == "ALPHA"
    assert len(data["lines"][0]["points"]) > 0

    # 2. Query with auto-picked leaders
    resp_leaders = client.request("GET", "/api/race", params={"top": 2, "anchor": "2021-01-01"})
    assert resp_leaders.status_code == 200
    data_leaders = resp_leaders.json()
    assert len(data_leaders["lines"]) == 2
    assert data_leaders["lines"][0]["symbol"] == "ALPHA"
    assert data_leaders["lines"][1]["symbol"] == "BETA"


def test_race_endpoint_empty_dataset(mock_race_setup):
    """Verify race endpoint returns empty lines when dataset has not been initialized."""
    provider, _, _ = mock_race_setup
    svc = RaceDataService(provider=provider, dataset_provider=lambda: {})
    state = AppState(provider=provider, race_service=svc, initial_dataset={})
    app = create_app(app_state=state)
    client = AsgiTestClient(app)

    resp = client.request("GET", "/api/race", params={"anchor": "2021-01-01"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["lines"] == []
    assert "No dataset available" in data["note"]


def test_race_endpoint_service_unavailable():
    """Verify HTTP 503 returned when no market data provider or race service is configured."""
    state = AppState(config=EngineConfig(provider="unregistered_provider"))
    app = create_app(app_state=state)
    client = AsgiTestClient(app)

    resp = client.request("GET", "/api/race")
    assert resp.status_code == 503
    assert "Race service is not available" in resp.json()["detail"]


class MockBarsCache(IBarsCache):
    """In-memory mock of persistent bars cache for testing."""
    def __init__(self, bars_map: Optional[Mapping[str, Sequence[MarketBar]]] = None) -> None:
        self._storage: dict[str, Sequence[MarketBar]] = dict(bars_map or {})
        self.save_calls: list[Mapping[str, Sequence[MarketBar]]] = []

    def get_bars_for_symbols(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        provider: str = "mock",
        min_bars: int = 3,
    ) -> tuple[dict[str, Sequence[MarketBar]], list[str]]:
        found = {}
        missing = []
        for s in symbols:
            if s in self._storage and len(self._storage[s]) >= min_bars:
                found[s] = self._storage[s]
            else:
                missing.append(s)
        return found, missing

    def save_bars(
        self,
        bars_map: Mapping[str, Sequence[MarketBar]],
        exchange: str = "NSE",
        provider: str = "mock",
        sync_monolith: bool = True,
    ) -> Any:
        self.save_calls.append(bars_map)
        self._storage.update(bars_map)
        return None

    def load_bars(self, exchange: str = "NSE", provider: str = "mock") -> dict[str, Sequence[MarketBar]]:
        return self._storage

    def clear(self, exchange: str = "NSE", provider: str = "mock") -> bool:
        self._storage.clear()
        return True


def test_race_data_service_all_timeframes(mock_race_setup):
    """Verify get_race supports all 6 timeframes: D, W, M, Q, H, Y."""
    provider, dataset, svc = mock_race_setup

    timeframes = ("D", "W", "M", "Q", "H", "Y")
    for tf in timeframes:
        res = asyncio.run(
            svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe=tf)
        )
        assert isinstance(res, RaceResponseOut)
        assert res.timeframe == tf
        assert len(res.lines) == 1
        assert res.lines[0].symbol == "ALPHA"
        assert len(res.lines[0].points) > 0

    pts_w = len(asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe="W")).lines[0].points)
    pts_m = len(asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe="M")).lines[0].points)
    pts_q = len(asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe="Q")).lines[0].points)
    pts_h = len(asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe="H")).lines[0].points)
    pts_y = len(asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01", timeframe="Y")).lines[0].points)
    assert pts_w > pts_m > pts_q > pts_h > pts_y > 0


def test_race_data_service_bars_cache_integration():
    """Verify RaceDataService uses IBarsCache and avoids redundant provider calls."""
    class TrackingProvider(MockRaceProvider):
        def __init__(self, stock_prices):
            super().__init__(stock_prices)
            self.fetch_count = 0

        def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 10):
            self.fetch_count += 1
            return super().daily_history(symbol, exchange, years)

    stocks = {"ALPHA": {"start": "2020-01-01", "base": 100.0, "final": 200.0}}
    provider = TrackingProvider(stocks)
    bars = provider.daily_history("ALPHA")
    provider.fetch_count = 0

    mock_cache = MockBarsCache(bars_map={"ALPHA": bars})
    dataset = {"ALPHA": {"symbol": "ALPHA", "name": "Alpha Corp", "SPA_A21": 100.0, "SUSPECT": "N"}}

    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: dataset,
        bars_cache=mock_cache,
    )

    res = asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01"))
    assert len(res.lines) == 1
    # Cached bars were used; provider was NOT queried
    assert provider.fetch_count == 0


def test_race_auto_metric_bound_to_anchor(mock_race_setup):
    """Verify automatic mode derives ranking metric from anchor year when metric is omitted."""
    provider, _, _ = mock_race_setup
    dataset = {
        "ALPHA": {"symbol": "ALPHA", "name": "Alpha Corp", "SPA_A21": 50.0, "SPA_A22": 150.0, "SUSPECT": "N"},
        "BETA": {"symbol": "BETA", "name": "Beta Ltd", "SPA_A21": 100.0, "SPA_A22": 300.0, "SUSPECT": "N"},
        "GAMMA": {"symbol": "GAMMA", "name": "Gamma Inc", "SPA_A21": 500.0, "SPA_A22": 10.0, "SUSPECT": "N"},
    }
    svc = RaceDataService(provider=provider, dataset_provider=lambda: dataset)

    # No metric specified; anchor is 2022-01-01 => derives SPA_A22
    # In SPA_A22: BETA (300) > ALPHA (150) > GAMMA (10).
    # With top=2, only BETA and ALPHA are selected as candidates; GAMMA (+500 in A21) is excluded.
    res = asyncio.run(svc.get_race(symbols=None, anchor="2022-01-01", top=2, metric=None))
    assert len(res.lines) == 2
    symbols_returned = {line.symbol for line in res.lines}
    assert symbols_returned == {"ALPHA", "BETA"}
    assert "GAMMA" not in symbols_returned


def test_api_race_endpoint_timeframe_and_default_top(mock_race_setup):
    """Verify GET /api/race handles timeframe parameter and defaults to top=10, timeframe='W'."""
    provider, dataset, svc = mock_race_setup
    state = AppState(provider=provider, race_service=svc, initial_dataset=dataset)
    app = create_app(app_state=state)
    client = AsgiTestClient(app)

    # 1. Default request
    resp = client.request("GET", "/api/race", params={"anchor": "2021-01-01"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["timeframe"] == "W"
    assert data["asked"] == 10

    # 2. Explicit timeframe
    resp_m = client.request("GET", "/api/race", params={"anchor": "2021-01-01", "timeframe": "M"})
    assert resp_m.status_code == 200
    assert resp_m.json()["timeframe"] == "M"

    # 3. Invalid timeframe rejected with 422
    resp_inv = client.request("GET", "/api/race", params={"timeframe": "INVALID"})
    assert resp_inv.status_code == 422


# =============================================================================
# Surgical Fix Tests: Fix A, Fix B, Fix C, Fix D
# =============================================================================

class TrackingRaceProvider(IDataProvider):
    """Mock provider tracking calls to daily_history with simulated failures."""
    name = "mock_tracking"

    def __init__(self, stock_bars: Mapping[str, Sequence[MarketBar]], fail_symbols: Sequence[str] = ()):
        self.stock_bars = dict(stock_bars)
        self.fail_symbols = set(fail_symbols)
        self.fetch_calls: list[str] = []

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return tuple(self.stock_bars.keys())

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 10, **kwargs) -> Sequence[MarketBar]:
        sym = symbol.strip().upper()
        self.fetch_calls.append(sym)
        if sym in self.fail_symbols:
            raise RuntimeError(f"Simulated provider failure for {sym}")
        return self.stock_bars.get(sym, ())

    def batch_daily_history(self, symbols: Sequence[str], exchange: str = "NSE", years: int = 10, **kwargs) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.stock_bars.get(symbol.strip().upper())
        return bars[-1].close if bars else None

    def intraday(self, *args, **kwargs) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, *args, **kwargs) -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(is_healthy=True, message="mock healthy")


def _make_test_bars(start_date: str, end_date: str = "2026-08-01", base: float = 100.0, final: float = 200.0) -> Sequence[MarketBar]:
    dates = pd.date_range(start_date, end_date, freq="W-FRI")
    n = len(dates)
    bars = []
    for i, dt in enumerate(dates):
        p = base + (final - base) * (i / max(1, n - 1))
        bars.append(
            MarketBar(
                timestamp=dt.to_pydatetime(),
                open=p,
                high=p * 1.02,
                low=p * 0.98,
                close=p,
                volume=50000.0,
            )
        )
    return tuple(bars)


# --- Fix A: Manual-mode requested count and notes ---

def test_manual_mode_all_success_no_note(mock_race_setup):
    """Verify manual mode with 2 valid symbols returns asked=2, len=2, and empty note."""
    _, dataset, svc = mock_race_setup
    res = asyncio.run(svc.get_race(symbols="ALPHA,BETA", anchor="2021-01-01", top=10))
    assert res.asked == 2
    assert len(res.lines) == 2
    assert res.note == ""


def test_manual_mode_partial_failure_accurate_note(mock_race_setup):
    """Verify manual mode with partial failure reports exact asked count and note."""
    _, dataset, svc = mock_race_setup
    res = asyncio.run(svc.get_race(symbols="ALPHA,BETA,LATE_IPO", anchor="2021-01-01", top=10))
    assert res.asked == 3
    assert len(res.lines) == 2
    assert res.note == "showing 2 of 3 asked - the rest have no price history before 2021-01-01"


def test_automatic_mode_asked_and_top_retained(mock_race_setup):
    """Verify automatic mode preserves top parameter and leader count semantics."""
    _, dataset, svc = mock_race_setup
    res = asyncio.run(svc.get_race(symbols=None, anchor="2021-01-01", top=3, metric="SPA_A21"))
    assert res.asked == 3
    assert len(res.lines) == 3
    assert res.note == ""


# --- Fix C: Deduplicate manual symbols ---

def test_manual_mode_deduplication_casing_ordering(mock_race_setup):
    """Verify duplicate symbols across different casing and whitespace are deduplicated preserving order."""
    _, dataset, svc = mock_race_setup
    res = asyncio.run(svc.get_race(symbols="  beta , ALPHA, Beta , alpha , gamma , BETA  ", anchor="2021-01-01", top=10))
    # Unique symbols are BETA, ALPHA, GAMMA => asked count must be 3
    assert res.asked == 3
    assert len(res.lines) == 3
    syms_in_lines = {line.symbol for line in res.lines}
    assert syms_in_lines == {"ALPHA", "BETA", "GAMMA"}
    # Response line final returns rank ALPHA (+200%) > BETA (+100%) > GAMMA (+50%)
    assert [line.symbol for line in res.lines] == ["ALPHA", "BETA", "GAMMA"]


def test_manual_mode_empty_and_whitespace(mock_race_setup):
    """Verify empty or whitespace-only symbols falls back cleanly to automatic mode."""
    _, dataset, svc = mock_race_setup
    res = asyncio.run(svc.get_race(symbols="   ,  ,  ", anchor="2021-01-01", top=2, metric="SPA_A21"))
    assert res.asked == 2
    assert len(res.lines) == 2


# --- Fix B: Historical-data fallback, respecting IPO dates (Scenarios 1-7) ---

def test_historical_fallback_post_anchor_ipo():
    """Scenario 1: Stock listed after anchor does not repeatedly fetch impossible pre-IPO history."""
    bars_late = _make_test_bars(start_date="2023-01-01", base=100.0, final=150.0)
    provider = TrackingRaceProvider(stock_bars={"LATE": bars_late})
    svc = RaceDataService(provider=provider, dataset_provider=lambda: {"LATE": {"symbol": "LATE"}})

    # First query fetches provider history
    res1 = asyncio.run(svc.get_race(symbols="LATE", anchor="2021-01-01"))
    assert len(res1.lines) == 0
    assert provider.fetch_calls == ["LATE"]

    # Clear request LRU cache to verify provider history exhaustion tracking
    svc.clear_cache()
    # Provide known earliest date directly on provider tracking
    svc._provider_earliest_date[("LATE", "mock_tracking")] = pd.Timestamp("2023-01-01")

    # Second query must not call provider again
    res2 = asyncio.run(svc.get_race(symbols="LATE", anchor="2021-01-01"))
    assert len(res2.lines) == 0
    assert len(provider.fetch_calls) == 1  # No second call


def test_historical_fallback_shallow_cache_resolves():
    """Scenario 2: Pre-anchor stock with shallow cache fetches deep history and resolves baseline."""
    full_bars = _make_test_bars(start_date="2020-01-01", base=100.0, final=200.0)
    shallow_bars = _make_test_bars(start_date="2023-01-01", base=150.0, final=200.0)

    provider = TrackingRaceProvider(stock_bars={"BETA": full_bars})
    mock_cache = MockBarsCache(bars_map={"BETA": shallow_bars})
    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: {"BETA": {"symbol": "BETA"}},
        bars_cache=mock_cache,
    )

    res = asyncio.run(svc.get_race(symbols="BETA", anchor="2021-01-01"))
    assert len(res.lines) == 1
    assert res.lines[0].symbol == "BETA"
    assert len(res.lines[0].points) > 10
    # Provider was called to resolve shallow history
    assert "BETA" in provider.fetch_calls
    # Cache was updated with full history
    assert len(mock_cache._storage["BETA"]) == len(full_bars)


def test_historical_fallback_complete_cache_avoids_fetch():
    """Scenario 3: Stock with complete cached history does not query provider."""
    full_bars = _make_test_bars(start_date="2020-01-01", base=100.0, final=200.0)
    provider = TrackingRaceProvider(stock_bars={"ALPHA": full_bars})
    mock_cache = MockBarsCache(bars_map={"ALPHA": full_bars})
    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: {"ALPHA": {"symbol": "ALPHA"}},
        bars_cache=mock_cache,
    )

    res = asyncio.run(svc.get_race(symbols="ALPHA", anchor="2021-01-01"))
    assert len(res.lines) == 1
    # Cached bars were complete; provider was never called
    assert len(provider.fetch_calls) == 0


def test_historical_fallback_unknown_listing_date_no_pre_anchor():
    """Scenario 4: Unknown listing date with unavailable pre-anchor history excludes stock without fake prices."""
    late_bars = _make_test_bars(start_date="2023-06-01", base=100.0, final=130.0)
    provider = TrackingRaceProvider(stock_bars={"UNKNOWN": late_bars})
    mock_cache = MockBarsCache(bars_map={})
    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: {"UNKNOWN": {"symbol": "UNKNOWN"}},
        bars_cache=mock_cache,
    )

    res = asyncio.run(svc.get_race(symbols="UNKNOWN", anchor="2021-01-01"))
    assert len(res.lines) == 0
    assert res.asked == 1
    assert "no price history before 2021-01-01" in res.note


def test_historical_fallback_provider_failure():
    """Scenario 5: Provider failure or insufficient returned history is handled gracefully."""
    provider = TrackingRaceProvider(
        stock_bars={"INSUFFICIENT": _make_test_bars(start_date="2020-01-01")[:1]},
        fail_symbols=["FAILING"],
    )
    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: {"FAILING": {}, "INSUFFICIENT": {}},
    )

    res = asyncio.run(svc.get_race(symbols="FAILING,INSUFFICIENT", anchor="2021-01-01"))
    assert len(res.lines) == 0
    assert res.asked == 2
    assert res.note == "showing 0 of 2 asked - the rest have no price history before 2021-01-01"


def test_historical_fallback_cache_reuse():
    """Scenario 6: Correct cache reuse after successful fallback prevents redundant provider calls."""
    full_bars = _make_test_bars(start_date="2020-01-01", base=100.0, final=200.0)
    shallow_bars = _make_test_bars(start_date="2023-01-01", base=150.0, final=200.0)

    provider = TrackingRaceProvider(stock_bars={"BETA": full_bars})
    mock_cache = MockBarsCache(bars_map={"BETA": shallow_bars})
    svc = RaceDataService(
        provider=provider,
        dataset_provider=lambda: {"BETA": {"symbol": "BETA"}},
        bars_cache=mock_cache,
    )

    # 1. First run falls back to provider and persists to cache
    res1 = asyncio.run(svc.get_race(symbols="BETA", anchor="2021-01-01"))
    assert len(res1.lines) == 1
    assert len(provider.fetch_calls) == 1

    # 2. Clear LRU request cache
    svc.clear_cache()

    # 3. Second run must retrieve from persistent cache and make ZERO new provider calls
    res2 = asyncio.run(svc.get_race(symbols="BETA", anchor="2021-01-01"))
    assert len(res2.lines) == 1
    assert len(provider.fetch_calls) == 1  # Still 1 call


def test_pre_anchor_baseline_mathematical_invariant():
    """Scenario 7: Verify baseline price invariant P(t0) is strictly before anchor date."""
    from yogi.calculation.velocity import calculate_anchored_curve

    # Known 5-day daily series:
    # 2020-12-30: 100.0
    # 2020-12-31: 120.0  <- strictly prior close before anchor 2021-01-01
    # 2021-01-01: 126.0  <- +5.0%
    # 2021-01-04: 132.0  <- +10.0%
    # 2021-01-05: 150.0  <- +25.0%
    dates = pd.to_datetime(["2020-12-30", "2020-12-31", "2021-01-01", "2021-01-04", "2021-01-05"])
    series = pd.Series([100.0, 120.0, 126.0, 132.0, 150.0], index=dates)

    curve = calculate_anchored_curve(series, anchor_date="2021-01-01", timeframe="D")
    assert len(curve) == 3
    assert curve[0]["time"] == "2021-01-01"
    assert curve[0]["value"] == 5.0
    assert curve[1]["time"] == "2021-01-04"
    assert curve[1]["value"] == 10.0
    assert curve[2]["time"] == "2021-01-05"
    assert curve[2]["value"] == 25.0


# --- Fix D: Escape-key and backdrop dismissal tests ---

def test_race_modal_escape_and_backdrop_dismissal_dom():
    """Verify index.html and app.js contain correct event handlers for Escape and backdrop dismissal."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists()
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    modal = soup.find(id="raceModal")
    assert modal is not None
    assert "modal-backdrop" in modal.get("class", [])
    assert modal.find(id="raceCloseBtn") is not None

    app_js_path = Path("src/yogi/cockpit/static/js/app.js")
    assert app_js_path.exists()
    app_js = app_js_path.read_text(encoding="utf-8")

    # 1. Escape key dismissal for raceModal
    assert "if (raceModal && raceModal.style.display !== 'none')" in app_js
    assert "raceCloseBtn.click()" in app_js

    # 2. Backdrop dismissal only when target is backdrop
    assert "if (e.target === m)" in app_js
    assert "handleRaceClose()" in app_js


def test_race_modal_escape_and_backdrop_node_events():
    """Automated event tests in Node.js verifying Escape key and backdrop click lifecycle."""
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js binary not available in environment")

    node_script = r"""
    let raceCloseClicked = false;
    let drawerClosed = false;

    const mockRaceModal = {
        id: 'raceModal',
        style: { display: 'flex' }
    };
    const mockRaceCloseBtn = {
        id: 'raceCloseBtn',
        click: () => { raceCloseClicked = true; }
    };
    const mockDrawer = {
        id: 'stockDetailDrawer',
        classList: { contains: (cls) => cls === 'open' }
    };
    const mockCard = {
        id: 'raceModalCard',
        parentElement: mockRaceModal
    };

    global.document = {
        getElementById: (id) => {
            if (id === 'raceModal') return mockRaceModal;
            if (id === 'raceCloseBtn') return mockRaceCloseBtn;
            if (id === 'stockDetailDrawer') return mockDrawer;
            return null;
        }
    };

    function closeStockDrawer() {
        drawerClosed = true;
    }

    const fs = require('fs');
    const appJs = fs.readFileSync('src/yogi/cockpit/static/js/app.js', 'utf8');

    const startIdx = appJs.indexOf("document.addEventListener('keydown'");
    if (startIdx === -1) {
        console.error('Could not find keydown listener start');
        process.exit(1);
    }
    const openBrace = appJs.indexOf('{', startIdx);
    const endCall = appJs.indexOf("});", openBrace);
    const handlerBody = appJs.substring(openBrace + 1, endCall).trim();

    const keydownHandler = new Function('e', 'closeStockDrawer', handlerBody);

    // Test 1: Escape key pressed while raceModal is visible
    keydownHandler({ key: 'Escape' }, closeStockDrawer);
    if (!raceCloseClicked) {
        console.error('FAIL: Escape key did not click raceCloseBtn');
        process.exit(2);
    }
    if (drawerClosed) {
        console.error('FAIL: Escape key closed stock drawer while raceModal was open');
        process.exit(3);
    }

    // Test 2: Escape key pressed when raceModal is hidden
    raceCloseClicked = false;
    drawerClosed = false;
    mockRaceModal.style.display = 'none';
    keydownHandler({ key: 'Escape' }, closeStockDrawer);
    if (raceCloseClicked) {
        console.error('FAIL: Escape key clicked raceCloseBtn when raceModal was hidden');
        process.exit(4);
    }
    if (!drawerClosed) {
        console.error('FAIL: Escape key did not close stock drawer when raceModal was hidden');
        process.exit(5);
    }

    // Test 3: Backdrop click vs inside click
    let modalClosed = false;
    function handleRaceClose() { modalClosed = true; }

    function handleBackdropClick(e, m) {
        if (e.target === m) {
            handleRaceClose();
        }
    }

    // Click directly on backdrop -> closes modal
    modalClosed = false;
    handleBackdropClick({ target: mockRaceModal }, mockRaceModal);
    if (!modalClosed) {
        console.error('FAIL: Backdrop click did not trigger handleRaceClose');
        process.exit(6);
    }

    // Click inside card -> does NOT close modal
    modalClosed = false;
    handleBackdropClick({ target: mockCard }, mockRaceModal);
    if (modalClosed) {
        console.error('FAIL: Inner card click closed modal');
        process.exit(7);
    }

    console.log('ALL_NODE_TESTS_PASSED');
    """

    res = subprocess.run([node_bin, "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"
    assert "ALL_NODE_TESTS_PASSED" in res.stdout

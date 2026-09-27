"""Unit and integration tests for Sprint Race curve calculation, RaceDataService, and GET /api/race."""

import asyncio
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence
import pandas as pd
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.schemas import RaceResponseOut
from yogi.cockpit.services.race import RaceDataService
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
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

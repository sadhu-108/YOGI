"""Deterministic and live integration tests for Twelve Data provider in Cockpit."""

from datetime import datetime, timedelta
import os
from typing import Any, Mapping, Sequence
import pytest

from yogi.cockpit.app import create_app
from yogi.data.providers.demo import DemoDataProvider
from yogi.cockpit.state import AppState
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.exceptions import DataProviderError
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class MockTwelveDataProvider(IDataProvider):
    """Deterministic mock provider mimicking TwelveDataProvider for offline Cockpit regression."""
    name = "twelvedata"

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self._bars = [
            MarketBar(
                timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                open=1500.0 + i,
                high=1520.0 + i,
                low=1490.0 + i,
                close=1510.0 + i,
                volume=10000.0,
            )
            for i in range(50)
        ]

    @property
    def supports_intraday(self) -> bool:
        return True

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        if self.should_fail:
            raise DataProviderError("Twelve Data connection refused.")
        return ["INFY"]

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 2
    ) -> Sequence[MarketBar]:
        if self.should_fail:
            raise DataProviderError("Twelve Data rate limit exceeded.")
        if symbol == "INFY":
            return self._bars
        return []

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> float | None:
        return self._bars[-1].close if self._bars else None

    def intraday(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        raise NotImplementedError()

    def trading_holidays(self, year: int | None = None) -> Sequence[str]:
        return ()

    def health(self, symbol: str | None = None, exchange: str | None = None) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=not self.should_fail, sample_price=1510.0)


def _make_mock_app_state(mock_p: MockTwelveDataProvider) -> AppState:
    state = AppState()
    state.orchestrator.registry.providers._instances["twelvedata"] = mock_p
    state.orchestrator.registry.providers._factories.pop("twelvedata", None)
    return state


def test_twelve_data_provider_selection_and_registry_resolution():
    """Verify selecting 'twelvedata' provider resolves through Registry and reports correct status."""
    mock_p = MockTwelveDataProvider()
    state = _make_mock_app_state(mock_p)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Initial status before loading data
    res = client.get("/api/status")
    assert res.status_code == 200
    status = res.json()
    assert status["status"] == "READY"
    assert status["universe_count"] == 0
    assert status["is_demo"] is False

    # 2. Refresh with twelvedata provider
    res = client.post("/api/dataset/refresh", json={"provider": "twelvedata", "symbols": ["INFY"]})
    assert res.status_code == 200
    status = res.json()
    assert status["universe_count"] == 1
    assert status["provider"] == "twelvedata"
    assert status["is_demo"] is False

    # 3. Table reflects Twelve Data records
    tbl = client.get("/api/table").json()
    assert tbl["universe_count"] == 1
    assert tbl["rows"][0]["symbol"] == "INFY"
    assert tbl["rows"][0]["price"] == mock_p._bars[-1].close


def test_demo_and_twelve_data_isolation_and_no_silent_fallback():
    """Verify strict mode isolation: switching between Demo and Twelve Data clears old data,
    and a Twelve Data failure never silently falls back to DemoDataProvider."""
    mock_p = MockTwelveDataProvider()
    state = _make_mock_app_state(mock_p)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Start with Demo data
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    assert res.json()["is_demo"] is True
    assert res.json()["universe_count"] == 5
    demo_symbols = {r["symbol"] for r in client.get("/api/table").json()["rows"]}
    assert "INFY" not in demo_symbols
    assert "MANYAVAR" in demo_symbols

    # 2. Switch to Twelve Data (Live) -> demo data is wiped from active dataset
    res = client.post("/api/dataset/refresh", json={"provider": "twelvedata", "symbols": ["INFY"]})
    assert res.status_code == 200
    assert res.json()["is_demo"] is False
    assert res.json()["universe_count"] == 1
    live_symbols = {r["symbol"] for r in client.get("/api/table").json()["rows"]}
    assert "MANYAVAR" not in live_symbols
    assert "INFY" in live_symbols

    # 3. Simulate Twelve Data failure: must raise error, MUST NOT silently fall back to demo data
    mock_failing = MockTwelveDataProvider(should_fail=True)
    state.orchestrator.registry.providers._instances["twelvedata"] = mock_failing
    res = client.post("/api/dataset/refresh", json={"provider": "twelvedata", "symbols": ["INFY"]})
    assert res.status_code == 500
    assert "detail" in res.json()
    assert "Failed to refresh dataset" in res.json()["detail"]
    assert state.is_demo is False  # Never silently switched to demo!

    # 4. Switch back to Demo explicitly: restores demo dataset cleanly
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    assert res.json()["is_demo"] is True
    assert res.json()["universe_count"] == 5
    restored_symbols = {r["symbol"] for r in client.get("/api/table").json()["rows"]}
    assert "INFY" not in restored_symbols
    assert "MANYAVAR" in restored_symbols


def test_cockpit_full_workflow_with_twelve_data():
    """Verify screening, ranking, charting, bands tuning, and export all operate cleanly on Twelve Data."""
    mock_p = MockTwelveDataProvider()
    state = _make_mock_app_state(mock_p)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Rebuild live with Twelve Data
    client.post("/api/dataset/refresh", json={"provider": "twelvedata", "symbols": ["INFY"]})

    # 1. Screen and Rank
    res = client.post(
        "/api/screen",
        json={"ranking_metric": "M_CUR", "ranking_order": "desc", "limit": 5},
    )
    assert res.status_code == 200
    screen_data = res.json()
    assert screen_data["universe_count"] == 1
    assert screen_data["qualified_count"] == 1
    assert screen_data["selected_count"] == 1
    assert screen_data["rows"][0]["symbol"] == "INFY"

    # 2. Candlestick Chart across timeframes
    res_d = client.get("/api/candles/INFY", params={"tf": "D", "exchange": "NSE", "years": 1})
    assert res_d.status_code == 200
    d_data = res_d.json()
    assert d_data["symbol"] == "INFY"
    assert len(d_data["candles"]) == len(mock_p._bars)

    # Resample W (verifies presentation cache and timeframe synthesis)
    res_w = client.get("/api/candles/INFY", params={"tf": "W", "exchange": "NSE", "years": 1})
    assert res_w.status_code == 200
    w_data = res_w.json()
    assert len(w_data["candles"]) > 0

    # 3. Discretionary Bands Update
    res_b = client.put("/api/bands/INFY", json={"timeframe": "M", "value": 0.15})
    assert res_b.status_code == 200
    assert res_b.json()["value"] == 0.15

    # 4. CSV & JSON Export
    res_csv = client.post("/api/export", json={"ranking_metric": "M_CUR", "format": "csv"})
    assert res_csv.status_code == 200
    assert "INFY" in res_csv.text

    res_json = client.post("/api/export", json={"ranking_metric": "M_CUR", "format": "json"})
    assert res_json.status_code == 200
    assert "INFY" in res_json.text


@pytest.mark.skipif(
    not (os.getenv("TWELVE_DATA_API_KEY") or os.getenv("TWELVEDATA_API_KEY")),
    reason="Live Twelve Data Cockpit test requires TWELVE_DATA_API_KEY environment variable",
)
def test_live_twelve_data_cockpit_e2e():
    """Opt-in real live network test verifying Twelve Data REST API flowing into Cockpit."""
    state = AppState()
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Rebuild live with benchmark symbol INFY
    res = client.post("/api/dataset/refresh", json={"provider": "twelvedata", "symbols": ["INFY"]})
    assert res.status_code == 200
    status = res.json()
    assert status["is_demo"] is False
    assert status["provider"] == "twelvedata"
    assert status["universe_count"] == 1

    # 2. Table has real INFY price
    tbl = client.get("/api/table").json()
    assert tbl["rows"][0]["symbol"] == "INFY"
    assert tbl["rows"][0]["price"] is not None and tbl["rows"][0]["price"] > 0

    # 3. Chart has real OHLC bars
    c_res = client.get("/api/candles/INFY", params={"tf": "D", "exchange": "NSE", "years": 1})
    assert c_res.status_code == 200
    c_data = c_res.json()
    assert len(c_data["candles"]) > 0
    assert c_data["candles"][-1]["close"] == pytest.approx(tbl["rows"][0]["price"], rel=1e-3)

"""Deterministic and live integration tests for YFinance provider in Cockpit."""

from datetime import datetime, timedelta
import os
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.exceptions import DataProviderError
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class MockYFinanceProvider(IDataProvider):
    """Deterministic mock provider mimicking YFinanceDataProvider for offline Cockpit regression."""
    name = "yfinance"

    def __init__(self, symbols: Optional[Sequence[str]] = None, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self._universe = list(symbols) if symbols is not None else ["RELIANCE", "TCS", "INFY"]
        self._bars = [
            MarketBar(
                timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                open=2500.0 + i,
                high=2520.0 + i,
                low=2490.0 + i,
                close=2510.0 + i,
                volume=50000.0,
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
            raise DataProviderError("Yahoo Finance connection refused.")
        return tuple(self._universe)

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 10
    ) -> Sequence[MarketBar]:
        if self.should_fail:
            raise DataProviderError("Yahoo Finance rate limit or network failure.")
        return self._bars

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 10
    ) -> Mapping[str, Sequence[MarketBar]]:
        if self.should_fail:
            raise DataProviderError("Yahoo Finance batch download failed.")
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return self._bars[-1].close if self._bars else None

    def intraday(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        raise NotImplementedError("yfinance provider does not support real-time tick streaming")

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self, symbol: Optional[str] = None, exchange: Optional[str] = None) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=not self.should_fail, sample_price=2510.0)


from pathlib import Path
from yogi.storage.bands import CsvBandsRepository


def _make_mock_app_state(mock_p: MockYFinanceProvider, tmp_path: Optional[Path] = None) -> AppState:
    bands_repo = CsvBandsRepository(data_dir=tmp_path) if tmp_path is not None else None
    state = AppState(bands_repo=bands_repo)
    if bands_repo is not None:
        state.orchestrator.registry.bands._instances["csv"] = bands_repo
        state.orchestrator.registry.bands._instances["excel"] = bands_repo
        state._bands_repo = bands_repo
    state.orchestrator.registry.providers._instances["yfinance"] = mock_p
    state.orchestrator.registry.providers._factories.pop("yfinance", None)
    return state


def test_yfinance_provider_selection_and_registry_resolution():
    """Verify selecting 'yfinance' provider resolves through Registry and reports correct status."""
    mock_p = MockYFinanceProvider()
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

    # 2. Refresh with yfinance provider
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "symbols": ["RELIANCE", "TCS"]})
    assert res.status_code == 200
    status = res.json()
    assert status["universe_count"] == 2
    assert status["provider"] == "yfinance"
    assert status["is_demo"] is False

    # 3. Table reflects YFinance records
    tbl = client.get("/api/table").json()
    assert tbl["universe_count"] == 2
    symbols = {r["symbol"] for r in tbl["rows"]}
    assert "RELIANCE" in symbols
    assert "TCS" in symbols


def test_demo_and_yfinance_isolation_and_no_silent_fallback():
    """Verify strict mode isolation: switching between Demo and YFinance clears old data,
    and a YFinance failure never silently falls back to DemoDataProvider."""
    mock_p = MockYFinanceProvider()
    state = _make_mock_app_state(mock_p)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Start with Demo data
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    assert res.json()["is_demo"] is True
    assert res.json()["universe_count"] == 5
    demo_symbols = {r["symbol"] for r in client.get("/api/table").json()["rows"]}
    assert "RELIANCE" not in demo_symbols
    assert "MANYAVAR" in demo_symbols

    # 2. Switch to YFinance (Live) -> demo data is wiped from active dataset
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "symbols": ["RELIANCE"]})
    assert res.status_code == 200
    assert res.json()["is_demo"] is False
    assert res.json()["universe_count"] == 1
    live_symbols = {r["symbol"] for r in client.get("/api/table").json()["rows"]}
    assert "MANYAVAR" not in live_symbols
    assert "RELIANCE" in live_symbols

    # 3. Simulate YFinance failure: must raise error, MUST NOT silently fall back to demo data
    mock_failing = MockYFinanceProvider(should_fail=True)
    state.orchestrator.registry.providers._instances["yfinance"] = mock_failing
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "symbols": ["RELIANCE"]})
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
    assert "RELIANCE" not in restored_symbols
    assert "MANYAVAR" in restored_symbols


def test_full_universe_pass_through_no_artificial_limit():
    """Verify that the full discovered universe passes through with NO INFY-only restriction,
    NO 12-stock limit, and NO artificial universe truncation."""
    full_universe = [f"STOCK_{i:02d}" for i in range(1, 26)]  # 25 stocks (> 12 limit)
    mock_p = MockYFinanceProvider(symbols=full_universe)
    state = _make_mock_app_state(mock_p)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Rebuild live without passing symbols (triggers provider.universe() discovery)
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance"})
    assert res.status_code == 200
    status = res.json()
    assert status["is_demo"] is False
    assert status["provider"] == "yfinance"
    # All 25 stocks must be processed!
    assert status["universe_count"] == 25, f"Expected full universe of 25 stocks, got {status['universe_count']}"

    # Verify rows in table
    tbl = client.get("/api/table").json()
    assert tbl["universe_count"] == 25
    returned_symbols = {r["symbol"] for r in tbl["rows"]}
    for expected_sym in full_universe:
        assert expected_sym in returned_symbols, f"{expected_sym} was unexpectedly truncated from universe"


def test_cockpit_full_workflow_with_yfinance(tmp_path: Path):
    """Verify screening, ranking, charting, bands tuning, and export all operate cleanly on YFinance dataset."""
    mock_p = MockYFinanceProvider(symbols=["RELIANCE", "TCS"])
    state = _make_mock_app_state(mock_p, tmp_path=tmp_path)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Rebuild live with YFinance
    client.post("/api/dataset/refresh", json={"provider": "yfinance", "symbols": ["RELIANCE", "TCS"]})

    # 1. Screen and Rank
    res = client.post(
        "/api/screen",
        json={"ranking_metric": "DROC", "ranking_order": "desc", "limit": 5},
    )
    assert res.status_code == 200
    screen_data = res.json()
    assert screen_data["universe_count"] == 2
    assert screen_data["qualified_count"] == 2
    assert screen_data["selected_count"] == 2

    # 2. Candlestick Chart across timeframes
    res_d = client.get("/api/candles/RELIANCE", params={"tf": "D", "exchange": "NSE", "years": 1})
    assert res_d.status_code == 200
    d_data = res_d.json()
    assert d_data["symbol"] == "RELIANCE"
    assert len(d_data["candles"]) == len(mock_p._bars)

    # Resample W (verifies presentation cache and timeframe synthesis)
    res_w = client.get("/api/candles/RELIANCE", params={"tf": "W", "exchange": "NSE", "years": 1})
    assert res_w.status_code == 200
    w_data = res_w.json()
    assert len(w_data["candles"]) > 0

    # 3. Discretionary Bands Update
    res_b = client.put("/api/bands/RELIANCE", json={"timeframe": "M", "value": 0.18})
    assert res_b.status_code == 200
    assert res_b.json()["value"] == 0.18

    # 4. CSV & JSON Export
    res_csv = client.post("/api/export", json={"ranking_metric": "DROC", "format": "csv"})
    assert res_csv.status_code == 200
    assert "RELIANCE" in res_csv.text

    res_json = client.post("/api/export", json={"ranking_metric": "DROC", "format": "json"})
    assert res_json.status_code == 200
    assert "RELIANCE" in res_json.text


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Opt-in live YFinance test requires RUN_LIVE_TESTS=1 environment variable",
)
def test_live_yfinance_cockpit_e2e():
    """Opt-in real live network test verifying real Yahoo Finance download flowing into Cockpit."""
    state = AppState()
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Rebuild live with benchmark symbol INFY
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "symbols": ["INFY"]})
    assert res.status_code == 200
    status = res.json()
    assert status["is_demo"] is False
    assert status["provider"] == "yfinance"
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

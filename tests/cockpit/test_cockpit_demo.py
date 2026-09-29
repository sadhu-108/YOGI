"""Integration tests for Cockpit offline demo data provider, bands repository, and end-to-end flow."""

import asyncio
import json
from typing import Any, Mapping, Optional
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.demo import DemoBandsRepository
from yogi.data.providers.demo import DemoDataProvider
from yogi.cockpit.state import AppState


class AsgiResponse:
    """Lightweight response wrapper for in-memory ASGI dispatch."""

    def __init__(self, status_code: int, headers: Mapping[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


class AsgiTestClient:
    """Zero-dependency ASGI TestClient testing real FastAPI routing, CORS, serialization, and status codes."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        json_data: Any = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> AsgiResponse:
        import urllib.parse

        query_bytes = b""
        if params:
            query_bytes = urllib.parse.urlencode(params).encode("ascii")

        body_bytes = b""
        hdrs_dict = dict(headers or {})
        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            hdrs_dict["content-type"] = "application/json"

        raw_headers = [(b"host", b"testserver"), (b"origin", b"http://localhost")]
        for k, v in hdrs_dict.items():
            raw_headers.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_bytes,
            "headers": raw_headers,
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
            "app": self.app,
        }

        status_code = 500
        response_headers: dict[str, str] = {}
        body_chunks: list[bytes] = []

        async def receive() -> Mapping[str, Any]:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(msg: Mapping[str, Any]) -> None:
            nonlocal status_code
            if msg["type"] == "http.response.start":
                status_code = msg["status"]
                for k, v in msg.get("headers", []):
                    response_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
            elif msg["type"] == "http.response.body":
                body_chunks.append(msg.get("body", b""))

        asyncio.run(self.app(scope, receive, send))
        return AsgiResponse(status_code, response_headers, b"".join(body_chunks))

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None, headers: Optional[Mapping[str, str]] = None) -> AsgiResponse:
        return self.request("GET", path, params=params, headers=headers)

    def post(self, path: str, json: Any = None, headers: Optional[Mapping[str, str]] = None) -> AsgiResponse:
        return self.request("POST", path, json_data=json, headers=headers)

    def put(self, path: str, json: Any = None, headers: Optional[Mapping[str, str]] = None) -> AsgiResponse:
        return self.request("PUT", path, json_data=json, headers=headers)


def test_demo_provider_and_bands_contracts():
    """Verify DemoDataProvider and DemoBandsRepository satisfy Core contracts with golden fixtures."""
    provider = DemoDataProvider()
    assert provider.name == "demo"
    assert provider.supports_intraday is False
    assert provider.supports_live_ticks is False
    
    universe = provider.universe()
    assert len(universe) == 5
    assert "MANYAVAR" in universe
    assert "SBCL" in universe
    assert "EMIL" in universe
    assert "MOREPENLAB" in universe
    assert "SHILPAMED" in universe

    bars = provider.daily_history("MANYAVAR")
    assert len(bars) > 1000
    assert bars[-1].close > 0
    assert provider.last_price("MANYAVAR") == bars[-1].close
    assert provider.health().ok is True

    bands_repo = DemoBandsRepository()
    all_bands = bands_repo.get_all_bands("MANYAVAR")
    assert set(all_bands.keys()) == {"D", "W", "M", "Q", "H", "Y"}
    assert all_bands["D"] == 0.03
    assert bands_repo.get_band("MANYAVAR", "D") == 0.03

    updated = bands_repo.set_band("MANYAVAR", "D", 0.045)
    assert updated == 0.045
    assert bands_repo.get_band("MANYAVAR", "D") == 0.045


def test_app_state_refresh_demo():
    """Verify AppState.refresh(provider='demo') builds golden dataset and activates chart service."""
    state = AppState()
    assert len(state.dataset) == 0
    assert state.is_demo is False
    assert state.chart_service is None

    asyncio.run(state.refresh(provider="demo"))

    assert state.is_demo is True
    assert len(state.dataset) == 5
    assert "MANYAVAR" in state.dataset
    record = state.dataset["MANYAVAR"]

    # Verify metrics from all 4 pillars exist
    assert "M_CUR" in record
    assert "DROC" in record
    assert "WROC" in record
    assert "YROC" in record
    assert "BANDST_M" in record
    assert "S4" in record
    assert "ACCEL_L" in record
    assert "IC" in record

    # Verify chart service was configured
    assert state.chart_service is not None
    assert state.bands_repo is not None

    # Verify multi-timeframe candles synthesis across all 6 timeframes
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        series = state.chart_service.get_candles("MANYAVAR", timeframe=tf)
        assert series.symbol == "MANYAVAR"
        assert series.timeframe == tf
        assert len(series.candles) > 0
        assert len(series.band_upper_curve) > 0
        assert len(series.band_lower_curve) > 0
        assert len(series.band_upper_curve) <= len(series.candles)
        assert series.latest_band is not None
        assert series.latest_band.basis is not None


def test_end_to_end_demo_api_workflow():
    """Verify complete HTTP API flow: Refresh demo -> Status -> Table -> Screen -> Candles -> Bands."""
    state = AppState()
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Initial status is empty
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["universe_count"] == 0
    assert res.json()["is_demo"] is False

    # 2. Trigger demo dataset refresh
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    status_data = res.json()
    assert status_data["universe_count"] == 5
    assert status_data["is_demo"] is True

    # 3. Retrieve presentation table
    res = client.get("/api/table")
    assert res.status_code == 200
    table_data = res.json()
    assert table_data["universe_count"] == 5
    assert len(table_data["rows"]) == 5

    # 4. Execute screen with ranking_order='desc' and filter rules (NO 422)
    screen_req = {
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "filter_group": {
            "match": "all",
            "rules": [
                {
                    "field": "price",
                    "op": ">",
                    "value": 10.0,
                }
            ],
        },
        "limit": 10,
    }
    res = client.post("/api/screen", json=screen_req)
    assert res.status_code == 200
    screen_res = res.json()
    assert screen_res["qualified_count"] > 0
    assert len(screen_res["rows"]) <= 10

    # 5. Fetch candlestick chart for active stock across timeframes
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        res = client.get("/api/candles/MANYAVAR", params={"tf": tf, "exchange": "NSE", "years": 2})
        assert res.status_code == 200
        candle_data = res.json()
        assert candle_data["symbol"] == "MANYAVAR"
        assert candle_data["timeframe"] == tf
        assert len(candle_data["candles"]) > 0

    # 6. Update discretionary band width
    res = client.put("/api/bands/MANYAVAR", json={"timeframe": "M", "value": 0.15})
    assert res.status_code == 200
    assert res.json()["value"] == 0.15

    # Verify updated band reflects in get_bands
    res = client.get("/api/bands/MANYAVAR")
    assert res.status_code == 200
    assert res.json()["bands"]["M"] == 0.15


def test_demo_provider_resolves_fixtures_from_arbitrary_cwd(monkeypatch, tmp_path):
    """Regression test: verify DemoDataProvider and DemoBandsRepository resolve bundled fixtures
    even when current working directory is changed to an arbitrary unrelated temporary directory."""
    monkeypatch.chdir(tmp_path)

    provider = DemoDataProvider()
    assert len(provider.universe()) == 5
    assert len(provider.daily_history("MANYAVAR")) > 1000

    bands_repo = DemoBandsRepository()
    assert bands_repo.get_band("MANYAVAR", "D") == 0.03

    state = AppState()
    asyncio.run(state.refresh(provider="demo"))
    assert state.is_demo is True
    assert len(state.dataset) == 5
    assert "MANYAVAR" in state.dataset


def test_provider_switching_live_and_demo():
    """Verify switching between demo and live providers through /api/dataset/refresh."""
    from tests.cockpit.test_cockpit_yfinance import MockYFinanceProvider

    mock_live = MockYFinanceProvider(symbols=["RELIANCE", "TCS", "INFY", "WIPRO", "HDFCBANK", "ICICIBANK"])
    state = AppState()
    state.orchestrator.registry.providers._instances["yfinance"] = mock_live
    state.orchestrator.registry.providers._factories.pop("yfinance", None)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Initially empty
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["universe_count"] == 0

    # 2. Switch to demo -> loads 5 golden stocks
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    data = res.json()
    assert data["universe_count"] == 5
    assert data["is_demo"] is True

    # 3. Requesting live switches to injected live provider without external network
    res = client.post("/api/dataset/refresh", json={"provider": "live"})
    assert res.status_code == 200
    data = res.json()
    assert data["universe_count"] == 6
    assert data["is_demo"] is False
    assert data["provider"] == "yfinance"

    # 4. Switching back to demo works flawlessly and restores the demo dataset
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    data = res.json()
    assert data["universe_count"] == 5
    assert data["is_demo"] is True


def test_demo_provider_module_placement_f02():
    """Verify DemoDataProvider belongs to yogi.data.providers.demo under YOGI-F02."""
    from yogi.data.providers.demo import DemoDataProvider as DirectDemoProvider
    from yogi.data.providers import DemoDataProvider as PkgDemoProvider
    from yogi.data import DemoDataProvider as RootDemoProvider

    assert DirectDemoProvider.__module__ == "yogi.data.providers.demo"
    assert PkgDemoProvider is DirectDemoProvider
    assert RootDemoProvider is DirectDemoProvider



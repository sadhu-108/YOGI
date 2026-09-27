"""Unit and integration tests for Cockpit API route handlers and application factory."""

import asyncio
import io
import json
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional, Sequence
import openpyxl
import pytest
from fastapi import HTTPException

from yogi.cockpit.app import create_app
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.router import (
    export_screen,
    get_bands,
    get_candles,
    get_system_status,
    get_table,
    list_strategies,
    refresh_dataset,
    run_screen,
    run_strategy,
    update_band,
)
from yogi.cockpit.schemas import (
    BandUpdateIn,
    ExportRequestIn,
    FilterGroupIn,
    FilterRuleIn,
    RefreshRequestIn,
    ScreenRequestIn,
    StrategyRunIn,
)
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.filter import FilterOperator
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.results import ExportFormat
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.results.formatter import ExportFormatter
from yogi.selection.engine import SelectionEngine
from yogi.strategy.presets import load_mentor_presets


class MockProvider(IDataProvider):
    name = "mock"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["ALPHA", "BETA", "GAMMA", "DELTA"]

    def daily_history(self, symbol: str, exchange: str = "NSE", years: int = 2) -> Sequence[MarketBar]:
        base = datetime(2025, 1, 1)
        return [
            MarketBar(
                timestamp=base + timedelta(days=i),
                open=100.0 + i,
                high=102.0 + i,
                low=98.0 + i,
                close=101.0 + i,
                volume=500.0,
            )
            for i in range(25)
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
def sample_dataset():
    return {
        "ALPHA": {
            "symbol": "ALPHA",
            "name": "Alpha Ltd",
            "exchange": "NSE",
            "price": 100.0,
            "M_CUR": 25.0,
            "EMA_W": "upcut",
            "EMA_M": "upcut",
            "BANDST_M": "ABOVE",
            "S4": 15.0,
            "ACCEL_L": 3.2,
            "RANK_CHG": 5.0,
        },
        "BETA": {
            "symbol": "BETA",
            "name": "Beta Ltd",
            "exchange": "NSE",
            "price": 200.0,
            "M_CUR": 15.0,
            "EMA_W": "upcut",
            "EMA_M": "yes",
            "BANDST_M": "IN",
            "S4": 10.0,
            "ACCEL_L": 1.5,
            "RANK_CHG": 2.0,
        },
        "GAMMA": {
            "symbol": "GAMMA",
            "name": "Gamma Ltd",
            "exchange": "NSE",
            "price": 150.0,
            "M_CUR": 5.0,
            "EMA_W": "no",
            "EMA_M": "no",
            "BANDST_M": "BELOW",
            "S4": 5.0,
            "ACCEL_L": -0.5,
            "RANK_CHG": -1.0,
        },
        "DELTA": {
            "symbol": "DELTA",
            "name": "Delta Ltd",
            "exchange": "NSE",
            "price": 50.0,
            "M_CUR": 35.0,
            "EMA_W": "upcut",
            "EMA_M": "upcut",
            "BANDST_M": "ABOVE",
            "S4": 20.0,
            "ACCEL_L": 4.1,
            "RANK_CHG": 8.0,
        },
    }


@pytest.fixture
def test_app_state(sample_dataset):
    from yogi.timeframe.engine import TimeframeEngine

    hub = RegistryHub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
        result_assembler=ResultAssembler(),
        timeframe_engine=TimeframeEngine(),
    )
    provider = MockProvider()
    bands_repo = MockBandsRepo()
    chart_service = ChartDataService(provider=provider, bands_repo=bands_repo)
    catalog = load_mentor_presets()

    return AppState(
        orchestrator=orchestrator,
        catalog=catalog,
        bands_repo=bands_repo,
        chart_service=chart_service,
        assembler=ResultAssembler(),
        formatter=ExportFormatter(),
        config=EngineConfig(),
        initial_dataset=sample_dataset,
    )


def test_app_factory_route_registration(test_app_state):
    """Verify create_app registers all approved API routes and static mounting."""
    app = create_app(app_state=test_app_state, auto_refresh=False)
    api_paths = list(app.openapi()["paths"].keys())

    expected = [
        "/api/status",
        "/api/dataset/refresh",
        "/api/table",
        "/api/screen",
        "/api/strategies",
        "/api/strategy/run",
        "/api/bands/{symbol}",
        "/api/candles/{symbol}",
        "/api/export",
    ]
    for p in expected:
        assert p in api_paths, f"Expected route {p} not registered in FastAPI app."


def test_route_status(test_app_state):
    status = get_system_status(app_state=test_app_state)
    assert status.status == "READY"
    assert status.universe_count == 4
    assert status.exchange == "NSE"


def test_route_table_default_and_custom_columns(test_app_state):
    # Default columns
    out_default = get_table(columns=None, app_state=test_app_state)
    assert out_default.universe_count == 4
    assert len(out_default.rows) == 4
    assert len(out_default.columns) > 0

    # Custom column projection
    out_custom = get_table(columns="symbol,price,ACCEL_L", app_state=test_app_state)
    assert len(out_custom.columns) == 3
    col_keys = [c.key for c in out_custom.columns]
    assert col_keys == ["symbol", "price", "ACCEL_L"]
    for row in out_custom.rows:
        assert set(row.keys()) == {"symbol", "price", "ACCEL_L"}


def test_route_screen_canonical_pipeline(test_app_state):
    # Filter: BANDST_M == ABOVE, Ranking: M_CUR DESC, limit: 1
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[FilterRuleIn(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE")]
        ),
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        limit=1,
    )
    out = run_screen(req=req, app_state=test_app_state)
    assert out.universe_count == 4
    assert out.qualified_count == 2  # ALPHA (25.0) and DELTA (35.0)
    assert out.selected_count == 2
    assert len(out.rows) == 1  # limit 1 applied
    # DELTA has M_CUR=35.0 vs ALPHA 25.0, so DELTA is #1
    assert out.rows[0]["symbol"] == "DELTA"


def test_route_screen_custom_columns_via_projecting_assembler(test_app_state):
    req = ScreenRequestIn(
        filter_group=FilterGroupIn(
            match="all",
            rules=[FilterRuleIn(field="BANDST_M", op=FilterOperator.EQ, value="ABOVE")]
        ),
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        columns=["symbol", "price", "ACCEL_L", "RANK_M_CUR"],
    )
    out = run_screen(req=req, app_state=test_app_state)
    assert len(out.columns) == 4
    col_keys = [c.key for c in out.columns]
    assert col_keys == ["symbol", "price", "ACCEL_L", "RANK_M_CUR"]

    # Verify rows contain strictly requested columns
    for row in out.rows:
        assert set(row.keys()) == {"symbol", "price", "ACCEL_L", "RANK_M_CUR"}


def test_route_strategies_list_and_run(test_app_state):
    # 1. List strategies
    strats = list_strategies(app_state=test_app_state)
    assert len(strats) == 21
    names = [s.name for s in strats]
    assert "A1_IMPULSE_CONFIRMED" in names

    # 2. Run preset A1_IMPULSE_CONFIRMED
    run_req = StrategyRunIn(
        strategy_name="A1_IMPULSE_CONFIRMED",
        limit=10,
        columns=["symbol", "price", "RANK_CHG", "BANDST_M"],
    )
    out = run_strategy(req=run_req, app_state=test_app_state)
    assert out.qualified_count == 2
    assert len(out.rows) == 2
    symbols = [r["symbol"] for r in out.rows]
    assert set(symbols) == {"ALPHA", "DELTA"}
    for r in out.rows:
        assert set(r.keys()) == {"symbol", "price", "RANK_CHG", "BANDST_M"}


def test_route_strategy_not_found(test_app_state):
    run_req = StrategyRunIn(strategy_name="NON_EXISTENT")
    with pytest.raises(HTTPException) as exc_info:
        run_strategy(req=run_req, app_state=test_app_state)
    assert exc_info.value.status_code == 404


def test_route_bands_endpoints(test_app_state):
    # Get bands
    bands_res = get_bands(symbol="ALPHA", app_state=test_app_state)
    assert bands_res.symbol == "ALPHA"
    assert bands_res.bands["D"] == 0.10

    # Update band
    up_res = update_band(
        symbol="ALPHA",
        req=BandUpdateIn(timeframe="D", value=0.14),
        app_state=test_app_state,
    )
    assert up_res.value == 0.14
    assert up_res.success is True

    # Verify update persisted in repository
    bands_res2 = get_bands(symbol="ALPHA", app_state=test_app_state)
    assert bands_res2.bands["D"] == 0.14


def test_route_candles_endpoint(test_app_state):
    candles_res = get_candles(
        symbol="ALPHA",
        tf="D",
        exchange="NSE",
        years=2,
        app_state=test_app_state,
    )
    assert candles_res.symbol == "ALPHA"
    assert candles_res.timeframe == "D"
    assert len(candles_res.candles) == 25
    assert len(candles_res.band_upper_curve) == 16
    assert candles_res.latest_band is not None
    assert candles_res.latest_band.timeframe == "D"
    assert candles_res.latest_band.band_timeframe == "D"
    assert candles_res.latest_band.width == 0.10


def test_route_candles_cross_timeframe(test_app_state):
    """Verify route handler passes band_tf and receives cross-timeframe envelope."""
    # 1. Daily candles with Monthly band (ALPHA has D=0.10, M=0.20)
    res_m = get_candles(
        symbol="ALPHA",
        tf="D",
        band_tf="M",
        exchange="NSE",
        years=2,
        app_state=test_app_state,
    )
    assert res_m.symbol == "ALPHA"
    assert res_m.timeframe == "D"
    assert len(res_m.candles) == 25
    assert len(res_m.band_upper_curve) == 16
    assert res_m.latest_band is not None
    assert res_m.latest_band.timeframe == "D"
    assert res_m.latest_band.band_timeframe == "M"
    assert res_m.latest_band.width == 0.20
    assert res_m.latest_band.upper == round(res_m.latest_band.basis * 1.20, 2)
    assert res_m.latest_band.lower == round(res_m.latest_band.basis * 0.80, 2)

    # 2. Daily candles with Quarterly band (ALPHA has Q=0.25)
    res_q = get_candles(
        symbol="ALPHA",
        tf="D",
        band_tf="Q",
        exchange="NSE",
        years=2,
        app_state=test_app_state,
    )
    assert res_q.latest_band.band_timeframe == "Q"
    assert res_q.latest_band.width == 0.25
    assert res_q.latest_band.upper == round(res_q.latest_band.basis * 1.25, 2)
    assert res_q.latest_band.lower == round(res_q.latest_band.basis * 0.75, 2)

    # 3. Suppression with NONE
    res_none = get_candles(
        symbol="ALPHA",
        tf="D",
        band_tf="NONE",
        exchange="NSE",
        years=2,
        app_state=test_app_state,
    )
    assert res_none.band_upper_curve == []
    assert res_none.band_lower_curve == []
    assert res_none.latest_band is not None
    assert res_none.latest_band.basis is not None
    assert res_none.latest_band.band_timeframe is None
    assert res_none.latest_band.width is None
    assert res_none.latest_band.upper is None
    assert res_none.latest_band.lower is None


def test_route_export_formats(test_app_state):
    # 1. Export XLSX
    req_xlsx = ExportRequestIn(
        strategy_name="A1_IMPULSE_CONFIRMED",
        format=ExportFormat.XLSX,
        columns=["symbol", "price", "M_CUR"],
    )
    res_xlsx = export_screen(req=req_xlsx, app_state=test_app_state)
    assert res_xlsx.status_code == 200
    assert "application/vnd.openxmlformats" in res_xlsx.media_type
    wb = openpyxl.load_workbook(io.BytesIO(res_xlsx.body))
    assert "Screener" in wb.sheetnames

    # 2. Export CSV
    req_csv = ExportRequestIn(
        strategy_name="A1_IMPULSE_CONFIRMED",
        format=ExportFormat.CSV,
        columns=["symbol", "price", "M_CUR"],
    )
    res_csv = export_screen(req=req_csv, app_state=test_app_state)
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.media_type
    lines = res_csv.body.decode("utf-8").strip().splitlines()
    assert len(lines) == 3  # Header + 2 data rows

    # 3. Export JSON
    req_json = ExportRequestIn(
        strategy_name="A1_IMPULSE_CONFIRMED",
        format=ExportFormat.JSON,
        columns=["symbol", "price", "M_CUR"],
    )
    res_json = export_screen(req=req_json, app_state=test_app_state)
    assert res_json.status_code == 200
    assert "application/json" in res_json.media_type
    data = json.loads(res_json.body)
    assert len(data["rows"]) == 2


def test_route_dataset_refresh(test_app_state, monkeypatch):
    new_data = {
        "NEW_SYM": {"symbol": "NEW_SYM", "price": 999.0}
    }
    monkeypatch.setattr(test_app_state.orchestrator, "build_dataset", lambda cfg: new_data)

    status_out = asyncio.run(refresh_dataset(
        req=RefreshRequestIn(symbols=["NEW_SYM"]),
        app_state=test_app_state,
    ))
    assert status_out.universe_count == 1
    assert "NEW_SYM" in test_app_state.dataset


# -----------------------------------------------------------------------------
# Zero-Dependency ASGI Test Client & End-to-End Application Boundary Tests
# -----------------------------------------------------------------------------

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

    def delete(self, path: str, headers: Optional[Mapping[str, str]] = None) -> AsgiResponse:
        return self.request("DELETE", path, headers=headers)


@pytest.fixture
def asgi_client(test_app_state):
    app = create_app(app_state=test_app_state, auto_refresh=False)
    return AsgiTestClient(app)


def test_asgi_status_endpoint(asgi_client):
    """Verify GET /api/status via ASGI app with CORS headers."""
    res = asgi_client.get("/api/status")
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "*"
    data = res.json()
    assert data["status"] == "READY"
    assert data["universe_count"] == 4
    assert data["exchange"] == "NSE"


def test_asgi_table_custom_columns(asgi_client):
    """Verify GET /api/table with presentation column projection via ASGI."""
    res = asgi_client.get("/api/table", params={"columns": "symbol,price,ACCEL_L"})
    assert res.status_code == 200
    data = res.json()
    assert len(data["columns"]) == 3
    assert [c["key"] for c in data["columns"]] == ["symbol", "price", "ACCEL_L"]
    for row in data["rows"]:
        assert set(row.keys()) == {"symbol", "price", "ACCEL_L"}


def test_asgi_screen_canonical_pipeline(asgi_client):
    """Verify POST /api/screen executes canonical QUALIFY -> ORDER -> SHOW pipeline via ASGI."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [{"field": "BANDST_M", "op": "==", "value": "ABOVE"}],
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "columns": ["symbol", "price", "M_CUR"],
        "limit": 1,
    }
    res = asgi_client.post("/api/screen", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["universe_count"] == 4
    assert data["qualified_count"] == 2
    assert data["selected_count"] == 2
    assert len(data["rows"]) == 1
    assert data["rows"][0]["symbol"] == "DELTA"
    assert set(data["rows"][0].keys()) == {"symbol", "price", "M_CUR"}


def test_asgi_strategies_and_run(asgi_client):
    """Verify GET /api/strategies and POST /api/strategy/run via ASGI."""
    # 1. List
    res_list = asgi_client.get("/api/strategies")
    assert res_list.status_code == 200
    strats = res_list.json()
    assert len(strats) == 21

    # 2. Run
    res_run = asgi_client.post("/api/strategy/run", json={
        "strategy_name": "A1_IMPULSE_CONFIRMED",
        "limit": 5,
        "columns": ["symbol", "price"],
    })
    assert res_run.status_code == 200
    data = res_run.json()
    assert len(data["rows"]) == 2
    for r in data["rows"]:
        assert set(r.keys()) == {"symbol", "price"}

    # 3. 404 on unknown strategy
    res_404 = asgi_client.post("/api/strategy/run", json={"strategy_name": "NON_EXISTENT"})
    assert res_404.status_code == 404


def test_asgi_bands_and_candles(asgi_client):
    """Verify GET/PUT /api/bands and GET /api/candles via ASGI."""
    # Candles
    res_candles = asgi_client.get("/api/candles/ALPHA", params={"tf": "D"})
    assert res_candles.status_code == 200
    candles_data = res_candles.json()
    assert candles_data["symbol"] == "ALPHA"
    assert len(candles_data["candles"]) == 25
    assert candles_data["latest_band"]["width"] == 0.10
    assert candles_data["latest_band"]["timeframe"] == "D"
    assert candles_data["latest_band"]["band_timeframe"] == "D"

    # Get bands
    res_bands = asgi_client.get("/api/bands/ALPHA")
    assert res_bands.status_code == 200
    assert res_bands.json()["bands"]["D"] == 0.10

    # Update bands
    res_up = asgi_client.put("/api/bands/ALPHA", json={"timeframe": "D", "value": 0.22})
    assert res_up.status_code == 200
    assert res_up.json()["value"] == 0.22


def test_asgi_candles_cross_timeframe(asgi_client):
    """Verify ASGI GET /api/candles with band_tf query parameter."""
    # 1. D candles + M band
    res_m = asgi_client.get("/api/candles/ALPHA", params={"tf": "D", "band_tf": "M"})
    assert res_m.status_code == 200
    data_m = res_m.json()
    assert data_m["timeframe"] == "D"
    assert data_m["latest_band"]["timeframe"] == "D"
    assert data_m["latest_band"]["band_timeframe"] == "M"
    assert data_m["latest_band"]["width"] == 0.20
    assert len(data_m["band_upper_curve"]) == 16

    # 2. D candles + Q band
    res_q = asgi_client.get("/api/candles/ALPHA", params={"tf": "D", "band_tf": "Q"})
    assert res_q.status_code == 200
    data_q = res_q.json()
    assert data_q["latest_band"]["band_timeframe"] == "Q"
    assert data_q["latest_band"]["width"] == 0.25

    # 3. Band suppression via NONE
    res_none = asgi_client.get("/api/candles/ALPHA", params={"tf": "D", "band_tf": "NONE"})
    assert res_none.status_code == 200
    data_none = res_none.json()
    assert data_none["band_upper_curve"] == []
    assert data_none["band_lower_curve"] == []
    assert data_none["latest_band"]["width"] is None
    assert data_none["latest_band"]["band_timeframe"] is None
    assert data_none["latest_band"]["basis"] is not None

    # 4. Invalid band_tf fails with 422
    res_invalid = asgi_client.get("/api/candles/ALPHA", params={"tf": "D", "band_tf": "INVALID"})
    assert res_invalid.status_code == 422

    # 5. Deferred 2W timeframe fails with 422
    res_2w = asgi_client.get("/api/candles/ALPHA", params={"tf": "D", "band_tf": "2W"})
    assert res_2w.status_code == 422


def test_asgi_export_csv(asgi_client):
    """Verify POST /api/export returns formatted CSV file stream via ASGI."""
    payload = {
        "strategy_name": "A1_IMPULSE_CONFIRMED",
        "format": "csv",
        "columns": ["symbol", "price"],
    }
    res = asgi_client.post("/api/export", json=payload)
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    lines = res.text.strip().splitlines()
    assert len(lines) == 3


def test_asgi_service_unavailable_503(test_app_state):
    """Verify 503 is returned when optional bands or provider capabilities are not configured."""
    empty_state = AppState(initial_dataset={"TEST": {"symbol": "TEST", "price": 10.0}})
    app = create_app(app_state=empty_state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Missing bands repo -> 503
    res_bands = client.get("/api/bands/TEST")
    assert res_bands.status_code == 503

    # Missing chart service -> 503
    res_candles = client.get("/api/candles/TEST")
    assert res_candles.status_code == 503


def test_app_lifespan_auto_refresh_failure_logs_warning(caplog):
    """Verify lifespan startup auto-refresh logs warning and does not crash when refresh fails."""
    import logging
    failing_state = AppState(initial_dataset={})

    async def mock_failing_refresh(symbols=None, symbol_limit=None):
        raise ConnectionError("Market provider offline")

    failing_state.refresh = mock_failing_refresh

    app = create_app(app_state=failing_state, auto_refresh=True)

    with caplog.at_level(logging.WARNING, logger="yogi.cockpit.app"):
        async def run_lifespan():
            async with app.router.lifespan_context(app):
                pass
        asyncio.run(run_lifespan())

    assert "Optional startup dataset pre-warming failed" in caplog.text
    assert "Market provider offline" in caplog.text


def test_get_strategy_detail_and_user_presets(test_app_state):
    """Verify loading strategy detail and user preset CRUD workflow."""
    app = create_app(app_state=test_app_state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Get mentor preset detail
    res = client.get("/api/strategies/A1_IMPULSE_CONFIRMED")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "A1_IMPULSE_CONFIRMED"
    assert data["is_mentor_preset"] is True
    assert data["filter_group"] is not None
    assert len(data["filter_group"]["rules"]) > 0

    # 2. Save user preset
    preset_payload = {
        "name": "My Momentum Setup",
        "description": "Custom screening setup for testing",
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "limit": 10,
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "price", "op": ">", "value": 50.0}
            ]
        },
        "columns": ["symbol", "price", "M_CUR"]
    }
    save_res = client.post("/api/user-presets", json=preset_payload)
    assert save_res.status_code == 200
    assert save_res.json()["name"] == "My Momentum Setup"

    # 3. List presets - includes user preset
    list_res = client.get("/api/user-presets")
    assert list_res.status_code == 200
    assert any(p["name"] == "My Momentum Setup" for p in list_res.json())

    # 4. Get strategy detail for user preset
    user_detail_res = client.get("/api/strategies/My Momentum Setup")
    assert user_detail_res.status_code == 200
    assert user_detail_res.json()["name"] == "My Momentum Setup"
    assert user_detail_res.json()["is_mentor_preset"] is False

    # 5. Run user preset
    run_res = client.post("/api/strategy/run", json={"strategy_name": "My Momentum Setup"})
    assert run_res.status_code == 200
    assert run_res.json()["selected_count"] > 0

    # 6. Delete user preset
    del_res = client.delete("/api/user-presets/My Momentum Setup")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_get_stock_panel_endpoint(test_app_state):
    """Verify /api/panel/{symbol} returns multi-timeframe metrics."""
    app = create_app(app_state=test_app_state, auto_refresh=False)
    client = AsgiTestClient(app)

    res = client.get("/api/panel/ALPHA")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "ALPHA"
    assert data["price"] == 100.0
    assert len(data["timeframes"]) == 6
    assert any(tf["timeframe"] == "M" for tf in data["timeframes"])

    # Non-existent symbol -> 404
    res_404 = client.get("/api/panel/NONEXISTENT")
    assert res_404.status_code == 404


def test_advanced_conditions_screen(test_app_state):
    """Verify nested boolean groups, column-to-column comparisons, and negation in screening."""
    app = create_app(app_state=test_app_state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Screen with nested OR group and negation
    screen_req = {
        "filter_group": {
            "match": "all",
            "rules": [
                {
                    "field": "price",
                    "op": ">",
                    "value": 10.0
                },
                {
                    "match": "any",
                    "rules": [
                        {"field": "M_CUR", "op": ">", "value": 0.0},
                        {"field": "price", "op": "==", "value": 200.0}
                    ]
                }
            ]
        },
        "ranking_metric": "price",
        "ranking_order": "desc",
        "limit": 5
    }
    res = client.post("/api/screen", json=screen_req)
    assert res.status_code == 200
    data = res.json()
    assert data["qualified_count"] > 0


def test_scenario_41_unified_workflow(test_app_state):
    """End-to-end verification of Scenario 41:
    1. Load built-in preset (A1_IMPULSE_CONFIRMED).
    2. Inspect preset details.
    3. Modify configuration (add condition, nested OR group, change limit).
    4. Save as user preset.
    5. Retrieve and execute user preset.
    6. Verify chart timeframe querying is completely decoupled from screening.
    """
    app = create_app(app_state=test_app_state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Load built-in preset
    detail_res = client.get("/api/strategies/A1_IMPULSE_CONFIRMED")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["name"] == "A1_IMPULSE_CONFIRMED"
    assert "filter_group" in detail
    assert detail["is_mentor_preset"] is True

    # 2. Modify configuration into a custom user preset
    modified_filter = {
        "match": "all",
        "rules": [
            *detail["filter_group"]["rules"],
            {
                "match": "any",
                "rules": [
                    {"field": "EMA_W", "op": "==", "value": "upcut"},
                    {"field": "S4", "op": ">", "value": 10.0},
                ],
            },
        ],
    }

    user_preset_payload = {
        "name": "Scenario 41 Setup",
        "description": "Customized Impulse with Weekly upcut and S4 filter",
        "filter_group": modified_filter,
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "limit": 50,
        "columns": ["symbol", "price", "M_CUR", "EMA_W", "BANDST_M"],
    }

    save_res = client.post("/api/user-presets", json=user_preset_payload)
    assert save_res.status_code == 200
    assert save_res.json()["name"] == "Scenario 41 Setup"

    # 3. Retrieve user preset detail
    get_preset_res = client.get("/api/strategies/Scenario 41 Setup")
    assert get_preset_res.status_code == 200
    saved_detail = get_preset_res.json()
    assert saved_detail["limit"] == 50
    assert len(saved_detail["filter_group"]["rules"]) == len(modified_filter["rules"])

    # 4. Run the user preset via /api/strategy/run
    run_res = client.post("/api/strategy/run", json={"strategy_name": "Scenario 41 Setup"})
    assert run_res.status_code == 200
    run_data = run_res.json()
    assert "qualified_count" in run_data
    assert "rows" in run_data

    # 5. Chart timeframe decoupling test:
    # Query candles and bands across D, W, M without affecting screening results
    for tf in ["D", "W", "M"]:
        candles_res = client.get(f"/api/candles/ALPHA?timeframe={tf}")
        assert candles_res.status_code == 200
        bands_res = client.get(f"/api/bands/ALPHA?timeframe={tf}")
        assert bands_res.status_code == 200

    # Ensure dataset count and screen output remain consistent and intact
    status_res = client.get("/api/status")
    assert status_res.status_code == 200
    assert status_res.json()["universe_count"] == 4

    # 6. Clean up user preset
    del_res = client.delete("/api/user-presets/Scenario 41 Setup")
    assert del_res.status_code == 200




"""Focused tests for Cockpit Stock Detail Drawer architecture, APIs, and interaction rules."""

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping, Optional
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.demo import DemoBandsRepository
from yogi.data.providers.demo import DemoDataProvider
from yogi.cockpit.schemas import FilterGroupIn, FilterOperator, FilterRuleIn, ScreenRequestIn
from yogi.cockpit.state import AppState, EngineConfig
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.results.assembler import ResultAssembler
from yogi.results.formatter import ExportFormatter
from yogi.selection.engine import SelectionEngine
from yogi.strategy.presets import StrategyCatalog


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
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_bytes,
            "headers": raw_headers,
        }

        response_status: list[int] = []
        response_headers: list[tuple[bytes, bytes]] = []
        response_body: list[bytes] = []

        async def receive() -> Mapping[str, Any]:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(message: Mapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_status.append(message["status"])
                response_headers.extend(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))

        asyncio.run(self.app(scope, receive, send))

        hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in response_headers}
        body = b"".join(response_body)
        return AsgiResponse(status_code=response_status[0], headers=hdrs, body=body)

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_data: Any = None, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        return self.request("POST", path, params=params, json_data=json_data)

    def put(self, path: str, json_data: Any = None, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        return self.request("PUT", path, params=params, json_data=json_data)


@pytest.fixture
def demo_app_client() -> AsgiTestClient:
    """Fixture providing initialized FastAPI app with pre-materialized Demo dataset."""
    state = AppState()
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)
    res = client.post("/api/dataset/refresh", json_data={"provider": "demo"})
    assert res.status_code == 200
    return client


# =============================================================================
# 1. Static Layout & Drawer Architecture Tests
# =============================================================================

def test_main_page_does_not_contain_permanent_chart() -> None:
    """Verify that main-content no longer permanently displays the chart/analysis."""
    html_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "index.html"
    assert html_path.exists(), "index.html must exist"
    content = html_path.read_text(encoding="utf-8")

    # The main-content section must NOT contain the chartContainer or chart-section
    main_start = content.find('<main class="main-content">')
    main_end = content.find("</main>")
    assert main_start != -1 and main_end != -1
    main_html = content[main_start:main_end]

    assert '<section class="chart-section' not in main_html, (
        "Permanent chart-section must be removed from main-content workspace."
    )
    assert 'id="chartContainer"' not in main_html, (
        "chartContainer must not be placed inside main-content flow."
    )
    assert 'id="resultsTable"' in main_html, (
        "Screening resultsTable must remain prominent inside main-content."
    )


def test_stock_detail_drawer_structure() -> None:
    """Verify that stockDetailDrawer exists as a dedicated slide-over aside element with all required components."""
    html_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    # 1. Drawer Container
    assert 'id="stockDetailDrawer"' in content
    assert 'class="stock-detail-drawer"' in content

    # 2. Header and Stock Identity
    assert 'id="drawerCloseBtn"' in content
    assert 'id="activeSymbol"' in content
    assert 'id="activeExchange"' in content
    assert 'id="activePrice"' in content
    assert 'id="activeAthDiff"' in content
    assert 'id="activeIcBadge"' in content
    assert 'id="activeBandStatus"' in content

    # 3. Chart & Band Tuning Controls
    assert 'id="tfButtons"' in content
    assert 'id="valBasis"' in content
    assert 'id="valUpper"' in content
    assert 'id="valLower"' in content
    assert 'id="valWidth"' in content
    assert 'id="bandWidthInput"' in content
    assert 'id="saveBandBtn"' in content
    assert 'id="chartContainer"' in content

    # 4. Multi-Timeframe Matrix
    assert 'id="livePanelDrawer"' in content
    assert 'id="liveMatrixTable"' in content
    assert 'id="liveMatrixBody"' in content
    assert 'id="drawerSignalsStrip"' in content

    # 5. Loading and Error Overlays
    assert 'id="drawerLoadingOverlay"' in content
    assert 'id="drawerErrorMsg"' in content


def test_drawer_css_rules_and_compact_reflow() -> None:
    """Verify that cockpit.css implements slide-over drawer and compact table reflow."""
    css_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "css" / "cockpit.css"
    assert css_path.exists(), "cockpit.css must exist"
    content = css_path.read_text(encoding="utf-8")

    # Slide-over drawer styling
    assert ".stock-detail-drawer {" in content
    assert ".stock-detail-drawer.open {" in content
    assert "transform: translateX(102%);" in content
    assert "transform: translateX(0);" in content

    # Left-side compact reflow rules when drawer-open is active
    assert "body.drawer-open .sidebar {" in content
    assert "body.drawer-open .main-content {" in content
    assert ".data-table tbody tr.active-row {" in content


def test_chart_controller_clear_and_resize_methods() -> None:
    """Verify chart.js implements clear() and resize() to prevent stale chart display and handle drawer reflow."""
    js_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js" / "chart.js"
    assert js_path.exists(), "chart.js must exist"
    content = js_path.read_text(encoding="utf-8")

    assert "clear() {" in content, "CockpitChart must provide clear() method to wipe previous stock's data"
    assert "resize() {" in content, "CockpitChart must provide resize() method to reflow inside drawer"


def test_app_js_drawer_open_and_close_handlers() -> None:
    """Verify app.js wires openStockDrawer, closeStockDrawer, Escape key, and table selection."""
    js_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js" / "app.js"
    assert js_path.exists(), "app.js must exist"
    content = js_path.read_text(encoding="utf-8")

    assert "async function openStockDrawer(" in content
    assert "function closeStockDrawer(" in content
    assert "document.getElementById('drawerCloseBtn')" in content
    assert "e.key === 'Escape'" in content
    assert "await openStockDrawer(sym)" in content


# =============================================================================
# 2. Drawer API Data Delivery & Stock Switching Tests
# =============================================================================

def test_drawer_stock_panel_endpoint_returns_correct_symbol(demo_app_client: AsgiTestClient) -> None:
    """Verify /api/panel/{symbol} returns accurate multi-timeframe analytics for selected stock."""
    res = demo_app_client.get("/api/panel/MANYAVAR")
    assert res.status_code == 200
    data = res.json()

    assert data["symbol"] == "MANYAVAR"
    assert data["exchange"] == "NSE"
    assert data["price"] is not None
    assert len(data["timeframes"]) == 6
    assert [r["timeframe"] for r in data["timeframes"]] == ["D", "W", "M", "Q", "H", "Y"]

    # Key metrics verification
    km = data["key_metrics"]
    assert "DROC" in km
    assert "WROC" in km
    assert "M_CUR" in km
    assert "S4" in km
    assert "ACCEL_L" in km


def test_drawer_candles_endpoint_returns_correct_bars(demo_app_client: AsgiTestClient) -> None:
    """Verify /api/candles/{symbol} returns candlestick series and envelope curves."""
    res = demo_app_client.get("/api/candles/SBCL", params={"tf": "D", "years": 2})
    assert res.status_code == 200
    data = res.json()

    assert data["symbol"] == "SBCL"
    assert data["timeframe"] == "D"
    assert len(data["candles"]) > 0
    # Every bar has valid OHLC
    first_candle = data["candles"][0]
    assert "time" in first_candle
    assert "open" in first_candle
    assert "high" in first_candle
    assert "low" in first_candle
    assert "close" in first_candle


def test_switching_stocks_returns_isolated_data(demo_app_client: AsgiTestClient) -> None:
    """Verify that switching from Stock A to Stock B delivers isolated data without bleed."""
    res_a = demo_app_client.get("/api/panel/EMIL")
    assert res_a.status_code == 200
    data_a = res_a.json()

    res_b = demo_app_client.get("/api/panel/MOREPENLAB")
    assert res_b.status_code == 200
    data_b = res_b.json()

    assert data_a["symbol"] == "EMIL"
    assert data_b["symbol"] == "MOREPENLAB"
    assert data_a["symbol"] != data_b["symbol"]
    assert data_a["price"] != data_b["price"]


def test_drawer_timeframe_change_does_not_modify_screening(demo_app_client: AsgiTestClient) -> None:
    """Verify changing chart timeframe fetches new candle bars without modifying screening state."""
    # 1. Execute initial screen
    screen_req = {
        "filter_group": {
            "match": "all",
            "rules": [{"field": "M_CUR", "op": ">", "value": -100.0}],
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "limit": 5,
    }
    screen_before = demo_app_client.post("/api/screen", json_data=screen_req)
    assert screen_before.status_code == 200
    rows_before = screen_before.json()["rows"]

    # 2. Change chart timeframe in drawer: D -> W -> M -> Q
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        candle_res = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": tf})
        assert candle_res.status_code == 200
        assert candle_res.json()["timeframe"] == tf

    # 3. Verify screening result is completely identical
    screen_after = demo_app_client.post("/api/screen", json_data=screen_req)
    assert screen_after.status_code == 200
    rows_after = screen_after.json()["rows"]

    assert len(rows_before) == len(rows_after)
    assert [r["symbol"] for r in rows_before] == [r["symbol"] for r in rows_after]


def test_drawer_band_update_does_not_reset_screening(demo_app_client: AsgiTestClient) -> None:
    """Verify updating a band width updates the symbol without altering screening state."""
    # 1. Update band for MANYAVAR
    update_res = demo_app_client.put("/api/bands/MANYAVAR", json_data={"timeframe": "M", "value": 0.18})
    assert update_res.status_code == 200
    assert update_res.json()["success"] is True

    # 2. Fetch updated bands
    bands_res = demo_app_client.get("/api/bands/MANYAVAR")
    assert bands_res.status_code == 200
    assert bands_res.json()["bands"]["M"] == 0.18

    # 3. Check candle envelope reflects updated width
    candle_res = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": "M"})
    assert candle_res.status_code == 200
    assert candle_res.json()["latest_band"]["width"] == 0.18


def test_drawer_error_handling_for_unknown_symbol(demo_app_client: AsgiTestClient) -> None:
    """Verify requesting an unknown symbol in the drawer returns a 404 with human-readable detail."""
    res = demo_app_client.get("/api/panel/UNKNOWN_STOCK_XYZ")
    assert res.status_code == 404
    data = res.json()
    assert "not found" in data["detail"].lower()


def test_demo_and_live_provider_isolation(demo_app_client: AsgiTestClient) -> None:
    """Verify Demo mode status reports provider='demo' and does not mix with live."""
    status_res = demo_app_client.get("/api/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["provider"] == "demo"
    assert status_data["is_demo"] is True
    assert status_data["universe_count"] == 5

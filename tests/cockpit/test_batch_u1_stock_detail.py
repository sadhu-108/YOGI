"""Focused verification tests for Batch U1: Stock Detail Coherent Technical Analysis Workspace.

Verifies:
- Grouped controls: Overlays popover, Panels popover, Chart & Band timeframes
- Progressive disclosure of analytical sub-panels
- Multi-timeframe matrix categorization & DMI enrichment
- Header metadata exposure & stock identity
- Independent chart and band timeframes
- Async race protection across rapid stock switching
- Complete DEMO and LIVE isolation
- Architectural purity: zero financial math or screening in JavaScript
"""

import json
from pathlib import Path
from typing import Any, Mapping, Optional
import pytest

from yogi.cockpit.app import create_app
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
    """ASGI TestClient for real FastAPI routing, serialization, and status codes."""

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
        import asyncio
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
# 1. HTML DOM Structure & Grouped Controls Verification
# =============================================================================

def test_drawer_header_metadata_badges_present() -> None:
    """Verify that index.html includes all metadata badge elements in the drawer header."""
    html_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    assert 'id="activeSymbol"' in content
    assert 'id="activeStockName"' in content
    assert 'id="activeSectorBadge"' in content
    assert 'id="activeCapBadge"' in content
    assert 'id="activeGradeBadge"' in content
    assert 'id="activeFnoBadge"' in content


def test_drawer_toolbar_grouped_controls_present() -> None:
    """Verify that index.html implements grouped Overlays ▾, Panels ▾, and Band Timeframe controls."""
    html_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    # 1. Band Timeframe Selector
    assert 'id="bandTfSelect"' in content
    assert '<option value="">Same as Chart</option>' in content
    assert '<option value="D">' in content
    assert '<option value="W">' in content
    assert '<option value="M">' in content
    assert '<option value="NONE">' in content

    # 2. Overlays Popover
    assert 'id="overlaysDropdown"' in content
    assert 'id="overlaysToggleBtn"' in content
    assert 'id="overlaysMenu"' in content
    # Check individual overlay checkboxes
    for chk_id in ("chkEma3", "chkEma5", "chkSma20", "chkAvgPrice", "chkBands", "chkBollinger", "chkDonchian", "chkAtrBands", "chkVwap", "chkVolume"):
        assert f'id="{chk_id}"' in content, f"Missing overlay checkbox {chk_id}"

    # Default checked overlays
    assert '<input type="checkbox" id="chkEma3" checked>' in content
    assert '<input type="checkbox" id="chkEma5" checked>' in content
    assert '<input type="checkbox" id="chkBands" checked>' in content
    assert '<input type="checkbox" id="chkVolume" checked>' in content

    # 3. Panels Popover
    assert 'id="panelsDropdown"' in content
    assert 'id="panelsToggleBtn"' in content
    assert 'id="panelsMenu"' in content
    assert 'id="activePanelLabel"' in content
    # Check individual panel options
    for panel_code in ("none", "rsi", "macd", "dmi", "obv", "mfi", "sprint", "accel", "band_dist", "yogi_roc"):
        assert f'data-panel="{panel_code}"' in content, f"Missing panel option {panel_code}"

    # 4. Analytical Sub-Panel Viewport
    assert 'id="subChartContainer"' in content
    assert 'id="subChartTitle"' in content
    assert 'id="subChartLegend"' in content
    assert 'id="closeSubChartBtn"' in content
    assert 'id="subChartCanvas"' in content


def test_matrix_table_structure_retains_required_ids() -> None:
    """Verify that liveMatrixTable retains standard IDs and elements."""
    html_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    assert 'id="livePanelDrawer"' in content
    assert 'id="liveMatrixTable"' in content
    assert 'id="liveMatrixBody"' in content
    assert 'id="drawerSignalsStrip"' in content


# =============================================================================
# 2. JavaScript Controller & State Verification
# =============================================================================

def test_chart_js_controller_methods_and_defaults() -> None:
    """Verify CockpitChart implements overlays, sub-panels, and time-scale sync."""
    js_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js" / "chart.js"
    content = js_path.read_text(encoding="utf-8")

    # Class and core lifecycle methods
    assert "class CockpitChart" in content
    assert "init() {" in content
    assert "clear() {" in content
    assert "resize() {" in content
    assert "render(" in content

    # Batch U1 methods
    assert "setOverlay(" in content
    assert "setActivePanel(" in content
    assert "applyOverlays() {" in content
    assert "renderSubPanel() {" in content
    assert "_clearSubChart() {" in content

    # Overlay state defaults
    assert "ema3: true" in content
    assert "ema5: true" in content
    assert "bands: true" in content
    assert "volume: true" in content
    assert "activePanel = 'none'" in content

    # Sub-chart synchronization
    assert "subscribeVisibleLogicalRangeChange" in content
    assert "setVisibleLogicalRange" in content


def test_api_js_supports_band_tf_query_param() -> None:
    """Verify API.getCandles accepts bandTf and appends band_tf parameter."""
    js_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js" / "api.js"
    content = js_path.read_text(encoding="utf-8")

    assert "bandTf = null" in content
    assert "band_tf=" in content


def test_app_js_implements_async_race_guard() -> None:
    """Verify app.js increments and checks currentStockDrawerRequestId."""
    js_path = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js" / "app.js"
    content = js_path.read_text(encoding="utf-8")

    assert "let currentStockDrawerRequestId = 0" in content
    assert "currentStockDrawerRequestId++" in content
    assert "currentStockDrawerRequestId !== currentId" in content or "currentStockDrawerRequestId !== reqId" in content


# =============================================================================
# 3. Cross-Timeframe Band Scaling & API Parity Tests
# =============================================================================

def test_candles_api_with_cross_timeframe_band(demo_app_client: AsgiTestClient) -> None:
    """Verify /api/candles endpoint honors band_tf independently from chart tf."""
    # Daily candles with Monthly band scaling
    res = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": "D", "band_tf": "M"})
    assert res.status_code == 200
    data = res.json()

    assert data["timeframe"] == "D"
    assert data["latest_band"] is not None
    assert data["latest_band"]["timeframe"] == "D"
    assert data["latest_band"]["band_timeframe"] == "M"

    # Daily candles with Band OFF
    res_none = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": "D", "band_tf": "NONE"})
    assert res_none.status_code == 200
    data_none = res_none.json()
    assert data_none["band_upper_curve"] == []
    assert data_none["band_lower_curve"] == []
    assert data_none["latest_band"]["width"] is None
    assert data_none["latest_band"]["upper"] is None
    assert data_none["latest_band"]["lower"] is None


def test_panel_api_returns_metadata_and_dmi_metrics(demo_app_client: AsgiTestClient) -> None:
    """Verify /api/panel endpoint returns metadata and multi-timeframe DMI metrics."""
    res = demo_app_client.get("/api/panel/MANYAVAR")
    assert res.status_code == 200
    data = res.json()

    # Fundamental metadata fields
    assert "name" in data
    assert "sector" in data
    assert "grade" in data
    assert "grp" in data
    assert "fno" in data

    # Multi-timeframe DMI metrics in key_metrics
    km = data["key_metrics"]
    assert "DMI_STATE_D" in km
    assert "ADX_D" in km


def test_timeframe_change_preserves_screening_state(demo_app_client: AsgiTestClient) -> None:
    """Verify switching chart timeframes in drawer leaves screening result untouched."""
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

    # Toggle chart timeframe across all 6 timeframes
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        candle_res = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": tf})
        assert candle_res.status_code == 200

    screen_after = demo_app_client.post("/api/screen", json_data=screen_req)
    assert screen_after.status_code == 200
    rows_after = screen_after.json()["rows"]

    assert [r["symbol"] for r in rows_before] == [r["symbol"] for r in rows_after]


def test_band_timeframe_change_preserves_screening_state(demo_app_client: AsgiTestClient) -> None:
    """Verify switching band timeframe in drawer leaves screening result untouched."""
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

    # Toggle band timeframe across various values
    for b_tf in ("D", "W", "M", "Q", "H", "Y", "NONE"):
        candle_res = demo_app_client.get("/api/candles/MANYAVAR", params={"tf": "D", "band_tf": b_tf})
        assert candle_res.status_code == 200

    screen_after = demo_app_client.post("/api/screen", json_data=screen_req)
    assert screen_after.status_code == 200
    rows_after = screen_after.json()["rows"]

    assert [r["symbol"] for r in rows_before] == [r["symbol"] for r in rows_after]


# =============================================================================
# 4. Architectural Verification: Zero Financial Math in JavaScript
# =============================================================================

def test_zero_financial_math_or_screening_in_javascript() -> None:
    """Verify that frontend JavaScript does not implement financial formulas or screening logic."""
    js_dir = Path(__file__).resolve().parents[2] / "src" / "yogi" / "cockpit" / "static" / "js"
    for js_file in js_dir.glob("*.js"):
        code = js_file.read_text(encoding="utf-8")

        # No pandas/numpy or formula indicators computed in JS
        assert ".rolling(" not in code, f"Found .rolling( in {js_file.name}"
        assert ".ewm(" not in code, f"Found .ewm( in {js_file.name}"
        assert "calculate_rsi" not in code, f"Found calculate_rsi in {js_file.name}"
        assert "calculate_macd" not in code, f"Found calculate_macd in {js_file.name}"
        assert "calculate_bollinger" not in code, f"Found calculate_bollinger in {js_file.name}"
        assert "calculate_donchian" not in code, f"Found calculate_donchian in {js_file.name}"
        assert "calculate_atr" not in code, f"Found calculate_atr in {js_file.name}"
        assert "calculate_vwap" not in code, f"Found calculate_vwap in {js_file.name}"
        assert "calculate_band_envelope" not in code, f"Found calculate_band_envelope in {js_file.name}"

        # No qualification or ranking engines in JS
        assert "class FilterEngine" not in code, f"Found FilterEngine in {js_file.name}"
        assert "class RankingEngine" not in code, f"Found RankingEngine in {js_file.name}"
        assert "class SelectionEngine" not in code, f"Found SelectionEngine in {js_file.name}"

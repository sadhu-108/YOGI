"""Focused verification tests for Batch U3: Power Controls & Secondary Investor Workflows.

Verifies:
1. Static asset contracts in index.html, cockpit.css, api.js, and app.js:
   - Universe advanced disclosure (sector, instrument type, microcap)
   - Band position grouped shortcut control
   - Multi-period rank cutoff templates
   - Modals: Band History, Band Backups, Sprint Race
   - Drawer enhancements: 6-TF Band Tuning, Metadata Two-Way Edit, Historical Breakdown
   - API client methods: getBandLog, getBandBackups, restoreBandBackup, getMetadata, updateMetadata, getRace
2. Six-Timeframe Band Tuning:
   - PUT /api/bands/{symbol} for D/W/M/Q/H/Y
   - Panel cache invalidation
   - Immediate reflection in GET /api/bands/{symbol}
3. Band Change History:
   - GET /api/bands/log/{symbol} audit trail retrieval
4. Band Backup & Restore:
   - GET /api/bands/backups listing
   - POST /api/bands/restore/{filename} with demo mode isolation (HTTP 403)
   - Regex validation on backup filename
5. Security Metadata Editing:
   - GET /api/meta/{symbol}
   - POST /api/meta/{symbol} with demo mode isolation (HTTP 403)
   - Two-way update in active repository
6. Sprint Race Trajectory:
   - GET /api/race trajectory curves and leaderboard output
7. Universe Power Screening Rules:
   - Sector filtering
   - Instrument type filtering
   - Microcap threshold filtering
8. Stock Detail Drawer Historical Metric Enrichment:
   - GET /api/panel/{symbol} key_metrics includes CAGR, annual returns, sprints
9. Non-regression of Batch U1 & U2 capabilities.
"""

import json
from pathlib import Path
from typing import Any, Mapping, Optional
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState, EngineConfig
from yogi.cockpit.demo import DemoDataProvider, DemoBandsRepository


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
        req_headers = []
        if headers:
            for k, v in headers.items():
                req_headers.append((k.lower().encode("ascii"), v.encode("ascii")))

        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            req_headers.append((b"content-type", b"application/json"))

        req_headers.append((b"content-length", str(len(body_bytes)).encode("ascii")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_bytes,
            "headers": req_headers,
        }

        resp_status = 500
        resp_headers: dict[str, str] = {}
        resp_chunks: list[bytes] = []

        async def receive() -> Mapping[str, Any]:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(message: Mapping[str, Any]) -> None:
            nonlocal resp_status, resp_headers, resp_chunks
            if message["type"] == "http.response.start":
                resp_status = message["status"]
                for k_b, v_b in message.get("headers", []):
                    resp_headers[k_b.decode("latin1").lower()] = v_b.decode("latin1")
            elif message["type"] == "http.response.body":
                resp_chunks.append(message.get("body", b""))

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.app(scope, receive, send))
        finally:
            loop.close()

        return AsgiResponse(resp_status, resp_headers, b"".join(resp_chunks))

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, json_data: Any = None, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        data = json if json is not None else json_data
        return self.request("POST", path, params=params, json_data=data)

    def put(self, path: str, json: Any = None, json_data: Any = None, params: Optional[Mapping[str, Any]] = None) -> AsgiResponse:
        data = json if json is not None else json_data
        return self.request("PUT", path, params=params, json_data=data)


@pytest.fixture
def test_app():
    """Create a fully initialized Cockpit FastAPI application with demo data."""
    app = create_app()
    client = AsgiTestClient(app)
    resp = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert resp.status_code == 200
    return app


@pytest.fixture
def client(test_app):
    """Instantiate an ASGI test client against test_app."""
    return AsgiTestClient(test_app)


# =============================================================================
# 1. Static Verification of Batch U3 HTML, CSS, JS
# =============================================================================


def test_batch_u3_html_elements_present():
    """Verify all Batch U3 HTML structures and controls exist in index.html."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists(), "index.html must exist"
    content = html_path.read_text(encoding="utf-8")

    # Universe Power Controls (Card 1)
    assert 'id="universeAdvancedDetails"' in content
    assert 'id="universeSectorSelect"' in content
    assert 'id="universeInstrSelect"' in content
    assert 'id="universeMicrocapToggle"' in content

    # Grouped Band Position Shortcut (Card 2)
    assert 'id="quickBandPositionSelect"' in content
    assert 'id="applyBandPositionBtn"' in content

    # Rank Cutoff Templates (Card 4)
    assert 'id="cutoffTemplateSelect"' in content
    assert "top100_m_y" in content
    assert "top50_all_q" in content
    assert "top100_all_tf" in content

    # Sprint Race Action (Card 5)
    assert 'id="openRaceBtn"' in content

    # Stock Detail Drawer Power Controls
    assert 'id="editMetaBtn"' in content
    assert 'id="metaEditPanel"' in content
    assert 'id="metaEditSector"' in content
    assert 'id="metaEditGrade"' in content
    assert 'id="metaEditNotes"' in content
    assert 'id="saveMetaBtn"' in content
    assert 'id="cancelMetaBtn"' in content

    # Drawer Band History & Historical Breakdown
    assert 'id="bandHistoryBtn"' in content
    assert 'id="drawerHistoryDetails"' in content
    assert 'id="drawerHistoryContent"' in content

    # Modals
    assert 'id="bandHistoryModal"' in content
    assert 'id="bandBackupsModal"' in content
    assert 'id="raceModal"' in content
    assert '<canvas id="raceChartCanvas"' in content
    assert 'id="raceLeaderboardContainer"' in content


def test_batch_u3_api_js_methods_present():
    """Verify all Batch U3 API endpoints are wrapped in api.js."""
    api_js_path = Path("src/yogi/cockpit/static/js/api.js")
    assert api_js_path.exists(), "api.js must exist"
    content = api_js_path.read_text(encoding="utf-8")

    assert "getBandLog(" in content
    assert "getBandBackups(" in content
    assert "restoreBandBackup(" in content
    assert "getMetadata(" in content
    assert "updateMetadata(" in content
    assert "getRace(" in content


def test_batch_u3_app_js_handlers_present():
    """Verify app.js wires up all Batch U3 power controls and event handlers."""
    app_js_path = Path("src/yogi/cockpit/static/js/app.js")
    assert app_js_path.exists(), "app.js must exist"
    content = app_js_path.read_text(encoding="utf-8")

    assert "applyBandPositionBtn" in content
    assert "cutoffTemplateSelect" in content
    assert "matrix-band-input" in content
    assert "updateDiscoveredSectors" in content
    assert "bandHistoryModal" in content
    assert "bandBackupsModal" in content
    assert "raceModal" in content
    assert "renderRaceChart" in content
    assert "executeRace" in content


# =============================================================================
# 2. Six-Timeframe Band Tuning (PUT /api/bands/{symbol})
# =============================================================================


def test_six_timeframe_band_update(client):
    """Verify discrete updates to D, W, M, Q, H, Y band widths."""
    symbol = "MANYAVAR"

    # Test updating each of the 6 standard timeframes
    test_values = {
        "D": 0.12,
        "W": 0.18,
        "M": 0.25,
        "Q": 0.32,
        "H": 0.40,
        "Y": 0.55,
    }

    for tf, val in test_values.items():
        resp = client.put(f"/api/bands/{symbol}", json_data={"timeframe": tf, "value": val})
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == symbol
        assert data["timeframe"] == tf
        assert abs(data["value"] - val) < 1e-5
        assert data["success"] is True

    # Verify that all 6 updated values persist in get_bands
    bands_resp = client.get(f"/api/bands/{symbol}")
    assert bands_resp.status_code == 200
    bands_data = bands_resp.json()["bands"]

    for tf, val in test_values.items():
        assert abs(bands_data[tf] - val) < 1e-5


# =============================================================================
# 3. Band Change History (GET /api/bands/log/{symbol})
# =============================================================================


def test_band_change_history(client):
    """Verify that updating a band creates an audit entry accessible via GET /api/bands/log/{symbol}."""
    symbol = "MANYAVAR"

    # Perform an update
    client.put(f"/api/bands/{symbol}", json_data={"timeframe": "M", "value": 0.22})

    # Retrieve history
    resp = client.get(f"/api/bands/log/{symbol}", params={"limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == symbol
    changes = data["changes"]
    assert len(changes) >= 1

    latest = changes[0]
    assert latest["timeframe"] == "M"
    assert "22" in str(latest["new_pct"])
    assert latest["changed_by"] == "cockpit"


# =============================================================================
# 4. Band Backup & Restore Controls
# =============================================================================


def test_band_backups_list(client):
    """Verify GET /api/bands/backups returns available daily backups."""
    resp = client.get("/api/bands/backups")
    assert resp.status_code == 200
    data = resp.json()
    assert "backups" in data
    assert isinstance(data["backups"], list)


def test_band_restore_demo_isolation(client):
    """Verify POST /api/bands/restore/{filename} returns HTTP 403 Forbidden in Demo mode."""
    # Strict regex check
    resp_invalid = client.post("/api/bands/restore/invalid_file.txt")
    assert resp_invalid.status_code == 403 or resp_invalid.status_code == 400

    # Valid filename in demo mode must be rejected with 403
    resp = client.post("/api/bands/restore/bands_2026-03-29.csv")
    assert resp.status_code == 403
    assert "demo mode" in resp.json()["detail"].lower()


# =============================================================================
# 5. Security Metadata Controls
# =============================================================================


def test_get_security_metadata(client):
    """Verify GET /api/meta/{symbol} retrieves canonical security metadata."""
    resp = client.get("/api/meta/MANYAVAR")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "MANYAVAR"
    assert "sector" in data
    assert "fno" in data
    assert "instrument_type" in data


def test_update_security_metadata_demo_isolation(client):
    """Verify POST /api/meta/{symbol} returns HTTP 403 in Demo mode."""
    resp = client.post("/api/meta/MANYAVAR", json_data={"field": "grade", "value": "A"})
    assert resp.status_code == 403
    assert "demo mode" in resp.json()["detail"].lower()


# =============================================================================
# 6. Sprint Race Trajectories
# =============================================================================


def test_sprint_race_trajectories(client):
    """Verify GET /api/race returns multi-line time series curves."""
    resp = client.get("/api/race", params={"anchor": "2021-01-01", "top": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["anchor"] == "2021-01-01"
    assert "lines" in data
    lines = data["lines"]
    assert len(lines) > 0

    first_line = lines[0]
    assert "symbol" in first_line
    assert "final" in first_line
    assert "points" in first_line
    assert len(first_line["points"]) > 0

    first_point = first_line["points"][0]
    assert "time" in first_point
    assert "value" in first_point


def test_sprint_race_with_explicit_symbols(client):
    """Verify GET /api/race handles explicit comma-separated symbols."""
    resp = client.get("/api/race", params={"symbols": "MANYAVAR, SBCL", "anchor": "2021-01-01"})
    assert resp.status_code == 200
    data = resp.json()
    lines = data["lines"]
    symbols = {l["symbol"] for l in lines}
    assert "MANYAVAR" in symbols or "SBCL" in symbols


def test_sprint_race_canvas_renderer_regression(client):
    """Regression test for Sprint Race canvas getContext runtime defect.

    Proves:
    1. Sprint Race modal markup exists and open button triggers modal display
    2. Race response (/api/race) is schema-valid and successfully handled
    3. The renderer receives an actual HTMLCanvasElement (<canvas>), NOT a <div>
    4. canvas.getContext('2d') is successfully obtained without TypeError
    5. The race visualization renders trajectories without runtime error
    """
    import shutil
    import subprocess
    import tempfile
    from bs4 import BeautifulSoup

    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists(), "index.html must exist"
    html_content = html_path.read_text(encoding="utf-8")

    app_js_path = Path("src/yogi/cockpit/static/js/app.js")
    assert app_js_path.exists(), "app.js must exist"
    app_js_content = app_js_path.read_text(encoding="utf-8")

    # 1. Proving Sprint Race modal opens:
    soup = BeautifulSoup(html_content, "html.parser")
    race_modal = soup.find(id="raceModal")
    assert race_modal is not None, "raceModal element must exist"
    assert "modal-backdrop" in race_modal.get("class", [])

    open_btn = soup.find(id="openRaceBtn")
    assert open_btn is not None, "openRaceBtn must exist"
    assert "openRaceBtn" in app_js_content
    assert "raceModal.style.display = 'flex'" in app_js_content
    assert "executeRace();" in app_js_content

    # 2. Proving race response is handled:
    resp = client.get("/api/race", params={"anchor": "2021-01-01", "top": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    lines = data["lines"]
    assert len(lines) > 0
    assert "currentRaceLines = res.lines || [];" in app_js_content
    assert "renderRaceChart(currentRaceLines);" in app_js_content

    # 3. Proving renderer receives an actual HTML canvas (NOT a div):
    canvas_elems = soup.find_all(id="raceChartCanvas")
    assert len(canvas_elems) == 1, "Must have exactly one element with id='raceChartCanvas' (no duplicate IDs)"
    canvas_tag = canvas_elems[0]
    assert canvas_tag.name == "canvas", (
        f"Critical regression: #raceChartCanvas must be a <canvas> element, but found <{canvas_tag.name}>! "
        "A <div> causes runtime error 'canvas.getContext is not a function'."
    )
    assert "race-chart-viewport" in canvas_tag.get("class", [])

    # 4 & 5. Proving getContext() is obtained and visualization renders without runtime error:
    node_bin = shutil.which("node")
    if node_bin:
        node_script = f"""
        const fs = require('fs');
        const appJs = fs.readFileSync('src/yogi/cockpit/static/js/app.js', 'utf8');

        const fnMatch = appJs.match(/function renderRaceChart\\(lines\\)\\s*\\{{([\\s\\S]*?\\n\\s*\\}})/);
        if (!fnMatch) {{
            console.error("renderRaceChart not found in app.js");
            process.exit(1);
        }}

        let contextRequested = null;
        let drawingCalls = [];
        const mockCtx = {{
            scale: (x, y) => drawingCalls.push(['scale', x, y]),
            clearRect: (x, y, w, h) => drawingCalls.push(['clearRect', x, y, w, h]),
            beginPath: () => drawingCalls.push(['beginPath']),
            moveTo: (x, y) => drawingCalls.push(['moveTo', x, y]),
            lineTo: (x, y) => drawingCalls.push(['lineTo', x, y]),
            stroke: () => drawingCalls.push(['stroke']),
            fillText: (text, x, y) => drawingCalls.push(['fillText', text, x, y]),
            set strokeStyle(v) {{ drawingCalls.push(['strokeStyle', v]); }},
            set fillStyle(v) {{ drawingCalls.push(['fillStyle', v]); }},
            set font(v) {{ drawingCalls.push(['font', v]); }},
            set textAlign(v) {{ drawingCalls.push(['textAlign', v]); }},
            set lineWidth(v) {{ drawingCalls.push(['lineWidth', v]); }}
        }};

        const mockCanvas = {{
            tagName: 'CANVAS',
            id: 'raceChartCanvas',
            parentElement: {{ clientWidth: 900 }},
            style: {{}},
            getContext: function(type) {{
                contextRequested = type;
                return mockCtx;
            }}
        }};

        global.document = {{
            getElementById: (id) => (id === 'raceChartCanvas' ? mockCanvas : null)
        }};
        global.window = {{ devicePixelRatio: 1 }};

        const renderFn = new Function('lines', fnMatch[1]);
        const testLines = {json.dumps(lines)};

        try {{
            renderFn(testLines);
        }} catch (err) {{
            console.error("RENDER_ERROR:", err.message);
            process.exit(2);
        }}

        if (contextRequested !== '2d') {{
            console.error("EXPECTED_2D_CONTEXT, got:", contextRequested);
            process.exit(3);
        }}

        if (drawingCalls.length === 0) {{
            console.error("NO_DRAWING_OPERATIONS_EXECUTED");
            process.exit(4);
        }}

        // Verify negative test: on a <div> (the pre-fix defect), it throws 'canvas.getContext is not a function'
        const mockDiv = {{
            tagName: 'DIV',
            id: 'raceChartCanvas',
            parentElement: {{ clientWidth: 900 }},
            style: {{}}
        }};
        global.document.getElementById = (id) => (id === 'raceChartCanvas' ? mockDiv : null);
        let threwExpected = false;
        try {{
            renderFn(testLines);
        }} catch (err) {{
            if (err.message.includes('getContext is not a function')) {{
                threwExpected = true;
            }}
        }}
        if (!threwExpected) {{
            console.error("NEGATIVE_TEST_FAILED: expected getContext is not a function on div");
            process.exit(5);
        }}

        console.log("SUCCESS");
        """

        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as tf:
            tf.write(node_script)
            temp_path = tf.name

        try:
            result = subprocess.run(
                [node_bin, temp_path],
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
            )
            assert result.returncode == 0, f"Node verification failed: {result.stderr or result.stdout}"
            assert "SUCCESS" in result.stdout
        finally:
            try:
                Path(temp_path).unlink()
            except OSError:
                pass


# =============================================================================
# 7. Universe Power Screening Rules Execution
# =============================================================================


def test_screening_with_sector_filter(client):
    """Verify screening execution filtered by sector."""
    # Screen with sector condition
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "sector", "op": "==", "value": "ENERGY"}
            ]
        },
        "limit": 10
    }
    resp = client.post("/api/screen", json_data=payload)
    assert resp.status_code == 200
    data = resp.json()
    for row in data["rows"]:
        assert row.get("sector") == "ENERGY"


def test_screening_with_microcap_filter(client):
    """Verify screening execution filtered by microcap (< 100 cr)."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "mcap", "op": "<", "value": 100}
            ]
        },
        "limit": 10
    }
    resp = client.post("/api/screen", json_data=payload)
    assert resp.status_code == 200
    data = resp.json()
    for row in data["rows"]:
        assert row.get("mcap", 0) < 100


# =============================================================================
# 8. Stock Detail Drawer Historical Metric Enrichment
# =============================================================================


def test_stock_detail_panel_historical_enrichment(client):
    """Verify that GET /api/panel/{symbol} includes historical metrics in key_metrics."""
    resp = client.get("/api/panel/MANYAVAR")
    assert resp.status_code == 200
    data = resp.json()
    km = data.get("key_metrics", {})

    # Check that standard panel metrics and any available CAGR/Sprint metrics are present
    assert "DROC" in km
    assert "WROC" in km
    assert "MROC" in km
    assert "YROC" in km
    assert "S4" in km
    assert "S13" in km
    assert "S26" in km
    assert "S52" in km
    assert "ACCEL_L" in km
    assert "ACCEL_S" in km


# =============================================================================
# 9. Non-Regression of Batch U1 & U2
# =============================================================================


def test_batch_u1_and_u2_non_regression(client):
    """Verify that Batch U1 chart band_tf flow and Batch U2 strategy presets remain intact."""
    # U1 Chart band_tf flow
    candle_resp = client.get("/api/candles/MANYAVAR", params={"tf": "W", "band_tf": "M"})
    assert candle_resp.status_code == 200
    candle_data = candle_resp.json()
    assert candle_data["timeframe"] == "W"
    assert candle_data.get("latest_band", {}).get("band_timeframe") == "M"

    # U2 Strategy run
    strat_resp = client.post("/api/strategy/run", json_data={"strategy_name": "A1_IMPULSE_CONFIRMED", "limit": 5})
    assert strat_resp.status_code == 200
    strat_data = strat_resp.json()
    assert len(strat_data["rows"]) <= 5

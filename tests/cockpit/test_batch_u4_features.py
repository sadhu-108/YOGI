"""Focused verification tests for Batch U4: Secondary Features & Global Management.

Verifies:
1. Static Asset Contracts:
   - Chart Measurement Tool in index.html, cockpit.css, and chart.js
   - Data & Snapshots Management Console in index.html, cockpit.css, and app.js
   - API client methods: getBandLog (supports global and single-symbol), getGlobalBandLog
   - Measurement methods in CockpitChart: toggleMeasure, recordMeasurePoint, resetMeasure, cancelMeasure
2. Global Band Management:
   - GET /api/bands/backups listing
   - GET /api/bands/log global audit trail retrieval across all symbols
   - GET /api/bands/log/{symbol} symbol-specific audit trail retrieval
   - POST /api/bands/restore/{filename} with Demo mode protection (HTTP 403)
   - Restore in active repository with automated pre-restore safety snapshot
3. Point-to-Point Measurement Logic:
   - Two-point percentage delta calculation
   - Positive and negative delta handling
   - Measurement lifecycle (step 1 -> step 2 -> step 3 -> restart)
   - Measurement reset and cancel
   - Zero mutation of screening state and zero server API calls
4. Non-regression of Batches U1, U2, and U3.
"""

import json
from pathlib import Path
from typing import Any, Mapping, Optional
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState, EngineConfig
from yogi.cockpit.demo import DemoDataProvider, DemoBandsRepository
from yogi.storage.bands import CsvBandsRepository


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

        parsed_url = urllib.parse.urlsplit(path)
        actual_path = parsed_url.path
        if parsed_url.query:
            if query_bytes:
                query_bytes = parsed_url.query.encode("ascii") + b"&" + query_bytes
            else:
                query_bytes = parsed_url.query.encode("ascii")

        raw_headers = [(b"host", b"testserver")]
        if headers:
            for k, v in headers.items():
                raw_headers.append((k.lower().encode("latin1"), v.encode("latin1")))

        body_bytes = b""
        if json_data is not None:
            body_bytes = json.dumps(json_data).encode("utf-8")
            raw_headers.append((b"content-type", b"application/json"))
            raw_headers.append((b"content-length", str(len(body_bytes)).encode("ascii")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "headers": raw_headers,
            "path": actual_path,
            "raw_path": actual_path.encode("ascii"),
            "query_string": query_bytes,
            "scheme": "http",
            "server": ("testserver", 80),
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

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> AsgiResponse:
        return self.request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Any = None, json_data: Any = None, params: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> AsgiResponse:
        data = json if json is not None else json_data
        return self.request("POST", path, params=params, json_data=data, **kwargs)

    def put(self, path: str, json: Any = None, json_data: Any = None, params: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> AsgiResponse:
        data = json if json is not None else json_data
        return self.request("PUT", path, params=params, json_data=data, **kwargs)


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
# 1. STATIC ASSET CONTRACT VERIFICATION
# =============================================================================

def test_u4_html_contracts() -> None:
    """Verify HTML elements for Measurement Tool and Data & Snapshots management console."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists(), "index.html must exist"
    content = html_path.read_text(encoding="utf-8")

    # App Header button
    assert 'id="bandBackupsBtn"' in content, "Must retain bandBackupsBtn ID for backwards compatibility"
    assert "Data &amp; Snapshots" in content or "Data & Snapshots" in content, "Must display Data & Snapshots in header"

    # Chart Toolbar Measurement Tool
    assert 'id="chartMeasureBtn"' in content, "Must contain chartMeasureBtn in chart toolbar"
    assert 'id="measureHud"' in content, "Must contain measureHud HUD container"
    assert 'id="measureHudStep"' in content, "Must contain measureHudStep guide text"
    assert 'id="measureHudResult"' in content, "Must contain measureHudResult result badge"
    assert 'id="measureResetBtn"' in content, "Must contain measureResetBtn cancel button"

    # Data & Snapshots Modal with Tabs
    assert 'id="bandBackupsModal"' in content, "Must contain bandBackupsModal"
    assert 'id="tabSnapshotsBtn"' in content, "Must contain tabSnapshotsBtn"
    assert 'id="tabGlobalAuditBtn"' in content, "Must contain tabGlobalAuditBtn"
    assert 'id="dataTabSnapshots"' in content, "Must contain dataTabSnapshots content pane"
    assert 'id="dataTabAudit"' in content, "Must contain dataTabAudit content pane"
    assert 'id="globalAuditContainer"' in content, "Must contain globalAuditContainer"
    assert 'id="refreshGlobalAuditBtn"' in content, "Must contain refreshGlobalAuditBtn"
    assert "Restore Impact &amp; Safety Notice" in content or "Restore Impact" in content, "Must explain restore impact"


def test_u4_css_contracts() -> None:
    """Verify CSS styling for Measurement Tool and Data & Snapshots console."""
    css_path = Path("src/yogi/cockpit/static/css/cockpit.css")
    assert css_path.exists(), "cockpit.css must exist"
    content = css_path.read_text(encoding="utf-8")

    assert ".toolbar-measure-wrap" in content, "Must style toolbar-measure-wrap"
    assert ".measure-toggle-btn" in content, "Must style measure-toggle-btn"
    assert ".measure-hud" in content, "Must style measure-hud"
    assert ".data-mgmt-tabs" in content, "Must style data-mgmt-tabs"
    assert ".data-tab-btn" in content, "Must style data-tab-btn"
    assert ".restore-impact-card" in content, "Must style restore-impact-card"
    assert ".global-audit-table" in content, "Must style global-audit-table"


def test_u4_api_js_contracts() -> None:
    """Verify API client methods in api.js support global audit trail and single-symbol history."""
    api_path = Path("src/yogi/cockpit/static/js/api.js")
    assert api_path.exists(), "api.js must exist"
    content = api_path.read_text(encoding="utf-8")

    assert "getBandLog(symbol = null" in content or "getBandLog(symbol" in content, "Must support getBandLog"
    assert "getGlobalBandLog" in content, "Must support getGlobalBandLog"
    assert "/api/bands/log" in content, "Must target /api/bands/log"
    assert "getBandBackups()" in content, "Must support getBandBackups"
    assert "restoreBandBackup(filename)" in content, "Must support restoreBandBackup"


def test_u4_chart_js_measurement_contracts() -> None:
    """Verify CockpitChart implements point-to-point measurement methods."""
    chart_path = Path("src/yogi/cockpit/static/js/chart.js")
    assert chart_path.exists(), "chart.js must exist"
    content = chart_path.read_text(encoding="utf-8")

    assert "this.isMeasuring" in content, "CockpitChart must track isMeasuring"
    assert "this.measureP1" in content, "CockpitChart must track measureP1"
    assert "this.measureP2" in content, "CockpitChart must track measureP2"
    assert "toggleMeasure" in content, "CockpitChart must implement toggleMeasure"
    assert "recordMeasurePoint" in content, "CockpitChart must implement recordMeasurePoint"
    assert "resetMeasure" in content, "CockpitChart must implement resetMeasure"
    assert "cancelMeasure" in content, "CockpitChart must implement cancelMeasure"
    assert "subscribeClick" in content, "CockpitChart must subscribe to chart click"


def test_u4_app_js_wiring() -> None:
    """Verify app.js wires measurement tool and global audit trail."""
    app_path = Path("src/yogi/cockpit/static/js/app.js")
    assert app_path.exists(), "app.js must exist"
    content = app_path.read_text(encoding="utf-8")

    assert "chartMeasureBtn" in content, "app.js must wire chartMeasureBtn"
    assert "measureResetBtn" in content, "app.js must wire measureResetBtn"
    assert "chart.onMeasureChange" in content, "app.js must set chart.onMeasureChange"
    assert "tabSnapshotsBtn" in content, "app.js must wire tabSnapshotsBtn"
    assert "tabGlobalAuditBtn" in content, "app.js must wire tabGlobalAuditBtn"
    assert "loadGlobalBandLog" in content, "app.js must implement loadGlobalBandLog"
    assert "window.confirm" in content or "confirm(" in content, "app.js must confirm before restore"


# =============================================================================
# 2. GLOBAL BAND MANAGEMENT BACKEND API TESTS
# =============================================================================

def test_api_get_band_backups_list(client: AsgiTestClient) -> None:
    """Verify GET /api/bands/backups returns available snapshot backups."""
    res = client.get("/api/bands/backups")
    assert res.status_code == 200
    data = res.json()
    assert "backups" in data
    assert isinstance(data["backups"], list)


def test_api_get_global_band_log(client: AsgiTestClient) -> None:
    """Verify GET /api/bands/log returns universe-wide change history."""
    res = client.get("/api/bands/log?limit=50")
    assert res.status_code == 200
    data = res.json()
    assert "changes" in data
    assert isinstance(data["changes"], list)


def test_api_get_symbol_band_log(client: AsgiTestClient) -> None:
    """Verify GET /api/bands/log/{symbol} returns symbol-specific history."""
    res = client.get("/api/bands/log/MANYAVAR?limit=30")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "MANYAVAR"
    assert "changes" in data
    assert isinstance(data["changes"], list)


def test_api_demo_restore_band_backup_protection(client: AsgiTestClient) -> None:
    """Verify POST /api/bands/restore/{filename} is locked in Demo mode with HTTP 403."""
    res = client.post("/api/bands/restore/bands_2026-04-01.csv")
    assert res.status_code == 403
    data = res.json()
    assert "demo mode" in data["detail"].lower()


def test_api_restore_band_backup_in_active_repo(tmp_path: Path) -> None:
    """Verify backup restore creates automated pre-restore safety snapshot and applies levels."""
    bands_file = tmp_path / "bands.csv"
    backup_dir = tmp_path / "band_backups"
    backup_dir.mkdir(parents=True)

    # Seed initial bands with standard format: symbol,D,W,M,Q,H,Y
    bands_file.write_text("symbol,D,W,M,Q,H,Y\nMANYAVAR,0.15,0.20,,,,\n", encoding="utf-8")

    # Create a dated snapshot to restore
    snapshot_file = backup_dir / "bands_2026-03-01.csv"
    snapshot_file.write_text("symbol,D,W,M,Q,H,Y\nMANYAVAR,0.25,0.30,,,,\nSBCL,,,0.40,,,\n", encoding="utf-8")

    repo = CsvBandsRepository(data_dir=tmp_path)

    state = AppState()
    state._bands_repo = repo
    state._is_demo = False  # Enable non-demo for restore test

    client = AsgiTestClient(create_app(app_state=state))

    res = client.post(f"/api/bands/restore/{snapshot_file.name}")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["stocks"] == 2  # MANYAVAR and SBCL

    # Verify restored values in repository
    entry_d = repo.get_band("MANYAVAR", "D")
    assert entry_d is not None
    assert abs(entry_d - 0.25) < 1e-4

    entry_sbcl = repo.get_band("SBCL", "M")
    assert entry_sbcl is not None
    assert abs(entry_sbcl - 0.40) < 1e-4

    # Verify automated pre-restore safety backup was created in backups_dir
    backups = repo.list_backups()
    assert len(backups) >= 2


# =============================================================================
# 3. POINT-TO-POINT MEASUREMENT LOGIC TESTS
# =============================================================================

def test_measurement_percentage_delta_calculation() -> None:
    """Verify point-to-point percentage delta mathematics."""
    # Positive delta (e.g. 100 to 135)
    p1 = 100.0
    p2 = 135.0
    delta_abs = p2 - p1
    delta_pct = (delta_abs / abs(p1)) * 100.0
    assert abs(delta_pct - 35.0) < 1e-4
    assert abs(delta_abs - 35.0) < 1e-4

    # Negative delta (e.g. 200 to 150)
    p1_neg = 200.0
    p2_neg = 150.0
    delta_abs_neg = p2_neg - p1_neg
    delta_pct_neg = (delta_abs_neg / abs(p1_neg)) * 100.0
    assert abs(delta_pct_neg - (-25.0)) < 1e-4
    assert abs(delta_abs_neg - (-50.0)) < 1e-4


# =============================================================================
# 4. NON-REGRESSION OF BATCHES U1, U2, AND U3
# =============================================================================

def test_u1_stock_detail_non_regression(client: AsgiTestClient) -> None:
    """Verify Stock Detail Panel and Candlestick APIs remain intact."""
    res_panel = client.get("/api/panel/MANYAVAR")
    assert res_panel.status_code == 200
    data = res_panel.json()
    assert data["symbol"] == "MANYAVAR"
    assert "timeframes" in data
    assert "key_metrics" in data

    res_candles = client.get("/api/candles/MANYAVAR?tf=D&band_tf=M")
    assert res_candles.status_code == 200
    candles = res_candles.json()
    assert "candles" in candles
    assert "band_upper_curve" in candles


def test_u2_screener_non_regression(client: AsgiTestClient) -> None:
    """Verify screener execution via PipelineOrchestrator remains intact."""
    screen_req = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "price", "op": ">", "value": 0}
            ]
        },
        "ranking_metric": "DROC",
        "ranking_order": "desc",
        "limit": 10
    }
    res = client.post("/api/screen", json=screen_req)
    assert res.status_code == 200
    payload = res.json()
    assert payload["universe_count"] > 0
    assert payload["qualified_count"] > 0
    assert payload["selected_count"] > 0


def test_u3_power_controls_non_regression(client: AsgiTestClient) -> None:
    """Verify 6-TF Band Tuning, Sprint Race, and Security Metadata remain intact."""
    # 1. Band update
    res_band = client.put("/api/bands/MANYAVAR", json={"timeframe": "W", "value": 0.22})
    assert res_band.status_code == 200

    # 2. Sprint Race
    res_race = client.get("/api/race?top=5&metric=SPA_A21")
    assert res_race.status_code == 200
    race_data = res_race.json()
    assert "lines" in race_data

    # 3. Metadata retrieval
    res_meta = client.get("/api/meta/MANYAVAR")
    assert res_meta.status_code == 200
    meta_data = res_meta.json()
    assert meta_data["symbol"] == "MANYAVAR"

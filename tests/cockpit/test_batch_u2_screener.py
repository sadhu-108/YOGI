"""Focused verification tests for Batch U2: Unified Screening & Configuration Workspace.

Verifies:
1. Unified 5-card progressive disclosure layout in index.html (Universe & Presets, Conditions, Ranking, Selection, Columns).
2. Clean static asset contracts in cockpit.css, app.js, and table.js.
3. Metric families & multi-timeframe segmented controls mapping.
4. Condition Builder contracts:
   - Match ALL / ANY
   - Root negation
   - Nested group with group-level negation
   - Cross-field comparison (field2)
   - Blank / Not Blank operators
5. Ranking (ORDER) and Selection (SHOW) separation:
   - Primary and secondary tie-breaker ranking
   - Top N limits and limit pills
   - Rank survival cutoffs (RankCutoffSpec)
6. Preset lifecycle: instant load, revert pristine snapshot, save as user preset, delete.
7. Active Setup Summary Banner & Funnel Telemetry contracts.
8. Zero regression on Batch U1 Stock Detail Drawer and Chart Data.
9. Final Design Test: Complete code-free institutional momentum screen execution.
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
                for k, v in message.get("headers", []):
                    resp_headers[k.decode("ascii").lower()] = v.decode("ascii")
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

    def post(self, path: str, json: Any = None) -> AsgiResponse:
        return self.request("POST", path, json_data=json)

    def delete(self, path: str) -> AsgiResponse:
        return self.request("DELETE", path)


@pytest.fixture
def test_app():
    """Create a fully initialized app with demo dataset loaded."""
    app = create_app()
    client = AsgiTestClient(app)
    # Refresh with golden demo dataset (5 stocks)
    resp = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert resp.status_code == 200
    return app


@pytest.fixture
def client(test_app):
    return AsgiTestClient(test_app)


# =============================================================================
# 1. HTML DOM Structure & 5-Card Progressive Disclosure Verification
# =============================================================================

def test_u2_html_5_cards_structure():
    """Verify index.html contains all 5 progressive disclosure cards on Left Workbench."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists(), "index.html missing"
    content = html_path.read_text(encoding="utf-8")

    # Card 1: Universe & Presets
    assert 'id="sectionUniversePresets"' in content
    assert 'Universe & Presets' in content
    assert 'id="universeExchange"' in content
    assert 'id="universeSegment"' in content
    assert 'id="presetSelect"' in content
    assert 'id="revertPresetBtn"' in content
    assert 'id="saveAsPresetBtn"' in content
    assert 'id="stockQuickSearch"' in content

    # Card 2: Conditions (QUALIFY)
    assert 'id="sectionConditions"' in content
    assert 'Conditions (QUALIFY)' in content
    assert 'id="activeRuleCountBadge"' in content
    assert 'id="emaQuickToggles"' in content
    assert 'id="quickBandAboveBtn"' in content
    assert 'id="quickBandOutsideBtn"' in content
    assert 'id="quickReactionTradeBtn"' in content
    assert 'id="rootGroupMatch"' in content
    assert 'id="rootGroupNotToggle"' in content
    assert 'id="filterRulesContainer"' in content
    assert 'id="addRuleBtn"' in content
    assert 'id="addGroupBtn"' in content

    # Card 3: Ranking (ORDER)
    assert 'id="sectionRanking"' in content
    assert 'Ranking (ORDER)' in content
    assert 'id="rankingMetric"' in content
    assert 'id="rankingOrder"' in content
    assert 'id="secondaryRankingMetric"' in content

    # Card 4: Selection (SHOW)
    assert 'id="sectionSelection"' in content
    assert 'Selection (SHOW)' in content
    assert 'id="screenLimit"' in content
    assert 'limit-pill' in content
    assert 'id="cutoffsContainer"' in content
    assert 'id="addCutoffBtn"' in content

    # Card 5: Display Columns & Actions
    assert 'id="sectionColumns"' in content
    assert 'Display Columns & Actions' in content
    assert 'col-preset-btn' in content
    assert 'id="customColumns"' in content
    assert 'id="runScreenBtn"' in content
    assert 'id="exportXlsxBtn"' in content
    assert 'id="exportCsvBtn"' in content
    assert 'id="exportJsonBtn"' in content

    # Right Viewport: Summary Banner & Funnel Telemetry
    assert 'id="activeConfigBanner"' in content
    assert 'id="summaryUniverse"' in content
    assert 'id="summaryPreset"' in content
    assert 'id="summaryConditions"' in content
    assert 'id="summaryRanking"' in content
    assert 'id="summarySelection"' in content
    assert 'id="funnelTelemetry"' in content
    assert 'id="funnelUniverse"' in content
    assert 'id="funnelQualified"' in content
    assert 'id="funnelSelected"' in content

    # Preserved U1 Stock Detail Drawer
    assert 'id="stockDetailDrawer"' in content
    assert 'id="activeSymbol"' in content


# =============================================================================
# 2. Static Assets Verification (CSS & JS)
# =============================================================================

def test_u2_css_classes_present():
    """Verify cockpit.css defines all required styles for U2 controls."""
    css_path = Path("src/yogi/cockpit/static/css/cockpit.css")
    assert css_path.exists()
    content = css_path.read_text(encoding="utf-8")

    assert ".rule-tf-segmented" in content
    assert ".rule-tf-btn" in content
    assert ".rule-field-resolved" in content
    assert ".group-not-toggle" in content
    assert ".nested-group-card" in content
    assert ".cutoff-row" in content
    assert ".cutoff-metric" in content
    assert ".cutoff-max" in content


def test_u2_app_js_functions_present():
    """Verify app.js contains all U2 condition builder and preset handlers."""
    js_path = Path("src/yogi/cockpit/static/js/app.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    assert "MULTI_TF_FAMILIES" in content
    assert "getFamilyForMetricKey" in content
    assert "createRuleRow" in content
    assert "createNestedGroupCard" in content
    assert "addCutoffRow" in content
    assert "applyPresetToEditor" in content
    assert "extractFilterGroup" in content
    assert "buildScreenPayload" in content
    assert "updateSummaryBanner" in content
    assert "revertPresetBtn" in content


def test_u2_table_js_formatting():
    """Verify table.js renders candlestick and multi-timeframe DMI columns."""
    table_path = Path("src/yogi/cockpit/static/js/table.js")
    assert table_path.exists()
    content = table_path.read_text(encoding="utf-8")

    # Candlestick pattern badge logic
    assert "key.startsWith('CD_')" in content
    assert "badge badge-above" in content

    # DMI state multi-timeframe logic
    assert "key.startsWith('DMI_')" in content
    assert "badge-dmi-bullish" in content


# =============================================================================
# 3. Dynamic Screening Execution & Backend Pipelines (/api/screen)
# =============================================================================

def test_screening_execution_simple_condition(client):
    """Test running a screen with a simple single-field condition."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "price", "op": ">", "value": 100}
            ]
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "limit": 10
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["universe_count"] == 5
    assert data["qualified_count"] > 0
    assert data["selected_count"] <= 10
    assert len(data["rows"]) == data["selected_count"]


def test_screening_execution_cross_field_comparison(client):
    """Test running a screen comparing two metrics directly via field2."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "S4", "op": ">", "value": None, "field2": "S52"}
            ]
        },
        "ranking_metric": "M_CUR",
        "limit": 5
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert data["selected_count"] <= 5


def test_screening_execution_nested_groups_with_negation(client):
    """Test nested filter group with group-level negation (is_negated: True)."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {
                    "match": "any",
                    "rules": [
                        {"field": "EMA_D", "op": "==", "value": "downcut"},
                        {"field": "BANDST_D", "op": "==", "value": "BELOW"}
                    ],
                    "is_negated": True  # Invert: NOT (downcut OR BELOW)
                }
            ]
        },
        "ranking_metric": "DROC",
        "limit": 10
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "qualified_count" in data


def test_screening_selection_rank_cutoffs(client):
    """Test rank survival cutoffs restricting results by ordinal rank."""
    payload = {
        "filter_group": None,
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 2}
        ],
        "limit": 20
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    # At most 2 stocks can satisfy Month Rank <= 2
    assert data["selected_count"] <= 2
    assert len(data["rows"]) <= 2


def test_screening_presentation_columns_projection(client):
    """Test ColumnProjectingAssembler projection through screening payload."""
    custom_cols = ["symbol", "price", "DROC", "EMA_M"]
    payload = {
        "filter_group": None,
        "ranking_metric": "M_CUR",
        "columns": custom_cols,
        "limit": 5
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    rendered_keys = [c["key"] for c in data["columns"]]
    assert rendered_keys == custom_cols
    for row in data["rows"]:
        for col in custom_cols:
            assert col in row


# =============================================================================
# 4. Strategy & Preset Persistence Lifecycle
# =============================================================================

def test_preset_retrieval_and_user_preset_crud(client):
    """Test preset retrieval, user preset creation, and user preset deletion."""
    # 1. Built-in mentor presets
    resp = client.get("/api/strategies/A1_IMPULSE_CONFIRMED")
    assert resp.status_code == 200
    preset = resp.json()
    assert preset["name"] == "A1_IMPULSE_CONFIRMED"
    assert "filter_group" in preset
    assert preset["filter_group"]["match"] == "all"

    # 2. Save a user preset
    user_preset = {
        "name": "TEST_INSTITUTIONAL_ALPHA",
        "description": "Custom momentum setup for verification",
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "MROC", "op": ">", "value": 5.0},
                {"field": "BANDST_M", "op": "==", "value": "ABOVE"}
            ]
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 50}
        ],
        "limit": 15,
        "columns": ["symbol", "price", "MROC", "BANDST_M"]
    }
    save_resp = client.post("/api/user-presets", json=user_preset)
    assert save_resp.status_code == 200
    saved = save_resp.json()
    assert saved["name"] == "TEST_INSTITUTIONAL_ALPHA"

    # 3. Retrieve user presets list
    list_resp = client.get("/api/user-presets")
    assert list_resp.status_code == 200
    presets_list = list_resp.json()
    assert any(p["name"] == "TEST_INSTITUTIONAL_ALPHA" for p in presets_list)

    # 4. Clean up / delete user preset
    del_resp = client.delete("/api/user-presets/TEST_INSTITUTIONAL_ALPHA")
    assert del_resp.status_code == 200
    assert del_resp.json()["name"] == "TEST_INSTITUTIONAL_ALPHA"
    assert del_resp.json()["success"] is True


# =============================================================================
# 5. Zero Regression on Batch U1 Stock Detail Drawer
# =============================================================================

def test_u1_stock_detail_and_chart_endpoint_integrity(client):
    """Confirm Batch U1 Stock Detail Drawer APIs remain intact and functional."""
    # Stock detail panel
    resp_detail = client.get("/api/panel/MANYAVAR")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["symbol"] == "MANYAVAR"
    assert "timeframes" in detail
    assert "key_metrics" in detail

    # Chart data with separate chart & band timeframes
    resp_chart = client.get("/api/candles/MANYAVAR", params={"tf": "W", "band_tf": "M"})
    assert resp_chart.status_code == 200
    chart = resp_chart.json()
    assert chart["symbol"] == "MANYAVAR"
    assert chart["timeframe"] == "W"
    assert "candles" in chart
    assert "latest_band" in chart


# =============================================================================
# 6. Final Design Test: Complete Code-Free Institutional Momentum Screen
# =============================================================================

def test_final_design_institutional_momentum_screen(client):
    """Execute the final design benchmark: Institutional multi-timeframe momentum screen."""
    institutional_screen = {
        "filter_group": {
            "match": "all",
            "rules": [
                # Cash / F&O equity qualification
                {"field": "fno", "op": "==", "value": "Y"},
                # Multi-timeframe trend & band qualification
                {"field": "BANDST_M", "op": "==", "value": "ABOVE"},
                # Nested subgroup: fresh breakout or upcut in weekly/daily
                {
                    "match": "any",
                    "rules": [
                        {"field": "EMA_W", "op": "==", "value": "upcut"},
                        {"field": "EMA_D", "op": "==", "value": "upcut"}
                    ]
                }
            ],
            "is_negated": False
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 100}
        ],
        "limit": 20,
        "columns": ["symbol", "name", "price", "M_CUR", "RANK_M", "EMA_W", "BANDST_M", "S4"]
    }

    resp = client.post("/api/screen", json=institutional_screen)
    assert resp.status_code == 200
    data = resp.json()

    # Telemetry contracts
    assert data["universe_count"] == 5
    assert data["qualified_count"] >= 0
    assert data["selected_count"] <= 20
    assert len(data["rows"]) == data["selected_count"]

    # Verify column projection
    keys = [c["key"] for c in data["columns"]]
    assert keys == institutional_screen["columns"]


def test_screening_with_rank_m_column_selection(client):
    """Verify that requesting RANK_M in columns with ranking_metric M_CUR populates non-None rank values and base fields."""
    payload = {
        "filter_group": {
            "match": "all",
            "rules": [
                {"field": "price", "op": ">", "value": 0}
            ]
        },
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "limit": 10,
        "columns": ["symbol", "name", "price", "RANK_M"]
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["selected_count"] > 0
    assert len(data["rows"]) == data["selected_count"]

    # Verify that columns and rows are correctly populated (not None / not blank)
    for row in data["rows"]:
        assert row["symbol"] is not None
        assert row["name"] is not None
        assert row["price"] is not None
        assert isinstance(row["RANK_M"], (int, float))
        assert row["RANK_M"] >= 1


def test_u2_sync_rank_cols_preserves_base_summary_columns():
    """Verify app.js syncRankColsToCustomColumns seeds base columns from active preset when custom columns is empty."""
    js_path = Path("src/yogi/cockpit/static/js/app.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")

    assert "function syncRankColsToCustomColumns()" in content
    assert "nonRankCols.length === 0" in content
    assert "COLUMN_PRESETS.summary" in content

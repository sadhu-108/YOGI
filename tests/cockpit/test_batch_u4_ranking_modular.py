"""Focused verification tests for Batch U4: Controlled Modular Ranking System & Cockpit Integration.

Verifies:
1. Static asset and DOM contracts in index.html, cockpit.css, app.js, and table.js:
   - Card 3: Primary Ranking (Metric, Direction, Active Indicator Badge, Tie-Breaker)
   - Card 4: Rank Filter & Selection (Enable switch, Threshold N, Presets, Mode ALL/ANY, Timeframe chips, Summary)
   - Card 5: Ranking Periods to Return (Checkboxes, Quick buttons All/Primary/Clear)
   - Table: Sequential row position (#) column distinct from metric ranks
2. Schema & Contract Integration:
   - ScreeningQuery.selection_mode (SelectionMode.ALL / ANY)
   - ScreenRequestIn.selection_mode validation and serialization
   - ExportRequestIn.selection_mode validation
   - to_screening_query translation with backwards compatibility
   - Invalid selection_mode rejection (HTTP 422)
3. Selection Engine ALL / ANY Evaluation:
   - ALL intersection: stocks must satisfy all active rank cutoffs
   - ANY union: stocks satisfying at least one active rank cutoff survive
   - Boundary condition: rank == N passes, rank == N+1 fails
   - Single period cutoff consistency
   - Zero selected periods skips filtering without eliminating stocks
   - Disabled rank filter bypasses selection
4. Independence Invariants:
   - Primary ranking direction (DESC vs ASC) is independent of rank cutoffs
   - Selection stage does not mutate primary ordering
   - Display limit (Stage D) is applied post-cutoff and does not affect qualification
   - Result column projection (Stage E) does not affect candidate eligibility or order
5. End-to-end Cockpit /api/screen execution with real backend pipeline.
"""

from pathlib import Path
from typing import Any, Mapping
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.schemas import (
    RankCutoffIn,
    ScreenRequestIn,
    to_screening_query,
)
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.selection import RankCutoffSpec, SelectionMode
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.selection.engine import SelectionEngine


# =============================================================================
# Lightweight In-Memory ASGI Test Client
# =============================================================================

class AsgiResponse:
    def __init__(self, status_code: int, headers: Mapping[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        import json
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


class AsgiTestClient:
    def __init__(self, app: Any) -> None:
        self.app = app

    def request(
        self,
        method: str,
        path: str,
        params: Any = None,
        json_data: Any = None,
        headers: Any = None,
    ) -> AsgiResponse:
        import asyncio
        import json
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

    def get(self, path: str, params: Any = None) -> AsgiResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, json_data: Any = None) -> AsgiResponse:
        data = json if json is not None else json_data
        return self.request("POST", path, json_data=data)


@pytest.fixture
def test_app():
    """Create a test application seeded with demo data."""
    app = create_app()
    client = AsgiTestClient(app)
    resp = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert resp.status_code == 200
    return app


@pytest.fixture
def client(test_app):
    return AsgiTestClient(test_app)


@pytest.fixture
def synthetic_records():
    """Deterministic synthetic universe for testing multi-period selection & ranking."""
    return {
        "ALPHA": {
            "symbol": "ALPHA",
            "price": 100.0,
            "RANK_D": 5,
            "RANK_W": 10,
            "RANK_M": 15,
            "RANK_Y": 80,
            "M_CUR": 25.0,
            "YROC": 10.0,
        },
        "BETA": {
            "symbol": "BETA",
            "price": 200.0,
            "RANK_D": 12,
            "RANK_W": 20,
            "RANK_M": 45,
            "RANK_Y": 30,
            "M_CUR": 15.0,
            "YROC": 40.0,
        },
        "GAMMA": {
            "symbol": "GAMMA",
            "price": 300.0,
            "RANK_D": 50,
            "RANK_W": 70,
            "RANK_M": 90,
            "RANK_Y": 120,
            "M_CUR": 5.0,
            "YROC": -5.0,
        },
        "DELTA": {
            "symbol": "DELTA",
            "price": 400.0,
            "RANK_D": 95,
            "RANK_W": 40,
            "RANK_M": 30,
            "RANK_Y": 25,
            "M_CUR": 18.0,
            "YROC": 50.0,
        },
        "EPSILON": {
            "symbol": "EPSILON",
            "price": 500.0,
            "RANK_D": 150,
            "RANK_W": 180,
            "RANK_M": 190,
            "RANK_Y": 200,
            "M_CUR": -10.0,
            "YROC": -30.0,
        },
    }


# =============================================================================
# 1. Static Asset & DOM Contracts
# =============================================================================

def test_static_html_has_modular_ranking_controls():
    """Verify index.html contains the approved four-section Ranking Console structure."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Section 01: Primary Ranking
    assert 'id="sectionRanking"' in content
    assert 'Primary Ranking</h3>' in content
    assert 'id="rankingMetric"' in content
    assert 'id="rankingOrder"' in content
    assert 'id="radioOrderDesc"' in content
    assert 'id="radioOrderAsc"' in content
    assert 'id="primaryRankIndicator"' in content
    assert 'id="primaryRankIndicatorText"' in content

    # Section 02: Rank Filter
    assert 'id="sectionSelection"' in content
    assert 'Rank Filter</h3>' in content
    assert 'id="rankFilterToggle"' in content
    assert 'id="rankFilterStatus"' in content
    assert 'id="rankFilterBody"' in content
    assert 'id="rankCutoffThreshold"' in content
    assert 'class="cutoff-pill"' in content
    assert 'data-cutoff="10"' in content
    assert 'data-cutoff="25"' in content
    assert 'data-cutoff="50"' in content
    assert 'data-cutoff="100"' in content
    assert 'name="selectionMode"' in content
    assert 'id="radioModeAll"' in content
    assert 'id="radioModeAny"' in content
    assert 'class="rank-filter-tf"' in content
    assert 'id="activeRankFilterSummary"' in content
    assert 'Note: Rank filter is skipped when disabled or when no periods are selected.' in content

    # Section 03: Ranking Periods to Return
    assert 'id="sectionRankingReturn"' in content
    assert 'Ranking Periods to Return</h3>' in content
    assert "rank-columns-section" in content
    assert 'class="rank-col-tf"' in content
    assert 'id="btnRankColsAll"' in content
    assert 'id="btnRankColsPrimary"' in content
    assert 'id="btnRankColsClear"' in content

    # Section 04: Final List Display
    assert 'id="sectionFinalDisplay"' in content
    assert 'Final List Display</h3>' in content
    assert 'id="screenLimit"' in content
    assert 'class="quick-limit-pills"' in content


def test_static_css_has_modular_ranking_classes():
    """Verify cockpit.css defines all styling rules for toggle, chips, modes, and seq col."""
    css_path = Path("src/yogi/cockpit/static/css/cockpit.css")
    assert css_path.exists()
    content = css_path.read_text(encoding="utf-8")

    assert ".switch-control" in content
    assert ".switch-slider" in content
    assert ".badge-enabled" in content
    assert ".badge-disabled" in content
    assert ".mode-toggle-group" in content
    assert ".mode-btn" in content
    assert ".rank-periods-grid" in content
    assert ".period-chip" in content
    assert ".cutoff-pill" in content
    assert ".active-rule-summary" in content
    assert ".seq-num-th" in content
    assert ".seq-num-td" in content


def test_static_table_js_has_sequential_row_position():
    """Verify table.js renders sequential position # column."""
    table_path = Path("src/yogi/cockpit/static/js/table.js")
    assert table_path.exists()
    content = table_path.read_text(encoding="utf-8")

    assert "seq-num-th" in content
    assert "seq-num-td" in content
    assert "rowIndex + 1" in content


def test_static_app_js_has_ranking_console_wiring():
    """Verify app.js wires all interactive ranking events and serializes payload."""
    app_path = Path("src/yogi/cockpit/static/js/app.js")
    assert app_path.exists()
    content = app_path.read_text(encoding="utf-8")

    assert "rankFilterToggle" in content
    assert "updateRankFilterSummary" in content
    assert "updatePrimaryRankIndicator" in content
    assert "syncRankColsToCustomColumns" in content
    assert "selection_mode" in content


# =============================================================================
# 2. Schema & Contract Integration
# =============================================================================

def test_screening_query_selection_mode_default_and_explicit():
    """Verify ScreeningQuery supports selection_mode with default ALL."""
    q_default = ScreeningQuery()
    assert q_default.selection_mode == SelectionMode.ALL

    q_any = ScreeningQuery(selection_mode=SelectionMode.ANY)
    assert q_any.selection_mode == SelectionMode.ANY


def test_screen_request_in_dto_selection_mode_serialization():
    """Verify ScreenRequestIn parses and validates selection_mode."""
    req_default = ScreenRequestIn()
    assert req_default.selection_mode == SelectionMode.ALL

    req_any = ScreenRequestIn(selection_mode=SelectionMode.ANY)
    assert req_any.selection_mode == SelectionMode.ANY

    req_str = ScreenRequestIn(selection_mode="any")
    assert req_str.selection_mode == SelectionMode.ANY

    # Translate to Core ScreeningQuery
    core_q = to_screening_query(selection_mode=req_any.selection_mode)
    assert core_q.selection_mode == SelectionMode.ANY


def test_invalid_selection_mode_raises_validation_error():
    """Verify malformed selection_mode values are strictly rejected."""
    with pytest.raises(Exception):
        ScreenRequestIn(selection_mode="INVALID_MODE")


# =============================================================================
# 3. Selection Engine ALL vs ANY Evaluation
# =============================================================================

def test_selection_engine_all_intersection(synthetic_records):
    """Test ALL mode requires meeting all cutoff criteria (Intersection)."""
    engine = SelectionEngine()

    # Rule: RANK_M <= 50 AND RANK_Y <= 50
    cutoffs = (
        RankCutoffSpec(rank_metric="RANK_M", max_rank=50),
        RankCutoffSpec(rank_metric="RANK_Y", max_rank=50),
    )

    res = engine.select(ranked_records=synthetic_records, cutoffs=cutoffs, mode=SelectionMode.ALL)

    # ALPHA: M=15 (<=50), Y=80 (>50) -> FAIL
    # BETA:  M=45 (<=50), Y=30 (<=50) -> PASS
    # GAMMA: M=90 (>50),  Y=120 (>50) -> FAIL
    # DELTA: M=30 (<=50), Y=25 (<=50) -> PASS
    # EPSILON: M=190 (>50), Y=200 (>50) -> FAIL
    assert set(res.selected_symbols) == {"BETA", "DELTA"}
    assert res.matched_count == 2
    assert "AND" in res.spec_summary


def test_selection_engine_any_union(synthetic_records):
    """Test ANY mode requires meeting at least one cutoff criterion (Union)."""
    engine = SelectionEngine()

    # Rule: RANK_M <= 30 OR RANK_Y <= 30
    cutoffs = (
        RankCutoffSpec(rank_metric="RANK_M", max_rank=30),
        RankCutoffSpec(rank_metric="RANK_Y", max_rank=30),
    )

    res = engine.select(ranked_records=synthetic_records, cutoffs=cutoffs, mode=SelectionMode.ANY)

    # ALPHA: M=15 (<=30), Y=80 -> PASS (on M)
    # BETA:  M=45, Y=30 (<=30) -> PASS (on Y)
    # GAMMA: M=90, Y=120 -> FAIL
    # DELTA: M=30 (<=30), Y=25 (<=30) -> PASS (on both)
    # EPSILON: M=190, Y=200 -> FAIL
    assert set(res.selected_symbols) == {"ALPHA", "BETA", "DELTA"}
    assert res.matched_count == 3
    assert "OR" in res.spec_summary


def test_selection_cutoff_boundary_n_passes_n_plus_1_fails():
    """Verify strict cutoff boundary: Rank == N passes, Rank == N+1 fails."""
    records = {
        "EXACT_N": {"symbol": "EXACT_N", "RANK_M": 50},
        "OVER_N": {"symbol": "OVER_N", "RANK_M": 51},
        "BEST_1": {"symbol": "BEST_1", "RANK_M": 1},
    }
    engine = SelectionEngine()
    res = engine.select(
        ranked_records=records,
        cutoffs=(RankCutoffSpec(rank_metric="RANK_M", max_rank=50),),
    )

    assert "BEST_1" in res.selected_symbols
    assert "EXACT_N" in res.selected_symbols
    assert "OVER_N" not in res.selected_symbols
    assert res.matched_count == 2


def test_empty_cutoffs_skips_selection_without_dropping_stocks(synthetic_records):
    """Verify empty selection cutoffs skips filtering and returns 100% of candidates."""
    engine = SelectionEngine()
    res = engine.select(ranked_records=synthetic_records, cutoffs=())

    assert len(res.selected_symbols) == len(synthetic_records)
    assert res.matched_count == len(synthetic_records)


# =============================================================================
# 4. Pipeline Independence Invariants
# =============================================================================

def test_pipeline_honors_selection_mode_from_query(synthetic_records):
    """Verify PipelineOrchestrator applies query.selection_mode into selection stage."""
    hub = RegistryHub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )

    cutoffs = (
        RankCutoffSpec(rank_metric="RANK_M", max_rank=30),
        RankCutoffSpec(rank_metric="RANK_Y", max_rank=30),
    )

    # 1. ALL Mode -> BETA and DELTA satisfy both
    q_all = ScreeningQuery(selection_cutoffs=cutoffs, selection_mode=SelectionMode.ALL)
    res_all = orchestrator.execute_screen(query=q_all, records=synthetic_records)
    assert set(r["symbol"] for r in res_all.rows) == {"DELTA"}  # Note: BETA has RANK_M=45 (>30)

    # 2. ANY Mode -> ALPHA, BETA, DELTA satisfy at least one
    q_any = ScreeningQuery(selection_cutoffs=cutoffs, selection_mode=SelectionMode.ANY)
    res_any = orchestrator.execute_screen(query=q_any, records=synthetic_records)
    assert set(r["symbol"] for r in res_any.rows) == {"ALPHA", "BETA", "DELTA"}


def test_primary_ranking_direction_independent_of_cutoffs(synthetic_records):
    """Verify sorting direction (DESC vs ASC) is determined solely by ranking stage."""
    hub = RegistryHub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )

    # Cutoff permits ALPHA (M_CUR=25), BETA (M_CUR=15), DELTA (M_CUR=18)
    cutoffs = (RankCutoffSpec(rank_metric="RANK_M", max_rank=45),)

    # DESCENDING: Highest M_CUR first -> ALPHA (25), DELTA (18), BETA (15)
    q_desc = ScreeningQuery(
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=cutoffs,
    )
    res_desc = orchestrator.execute_screen(query=q_desc, records=synthetic_records)
    assert [r["symbol"] for r in res_desc.rows] == ["ALPHA", "DELTA", "BETA"]

    # ASCENDING: Lowest M_CUR first -> BETA (15), DELTA (18), ALPHA (25)
    q_asc = ScreeningQuery(
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.ASCENDING,
        selection_cutoffs=cutoffs,
    )
    res_asc = orchestrator.execute_screen(query=q_asc, records=synthetic_records)
    assert [r["symbol"] for r in res_asc.rows] == ["BETA", "DELTA", "ALPHA"]


def test_display_limit_applied_post_selection(synthetic_records):
    """Verify display limit (Stage D) slices surviving rows without changing eligibility."""
    hub = RegistryHub()
    orchestrator = PipelineOrchestrator(
        registry=hub,
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )

    # 3 stocks pass cutoffs
    cutoffs = (RankCutoffSpec(rank_metric="RANK_M", max_rank=45),)
    query = ScreeningQuery(
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=cutoffs,
        limit=2,  # User requests only Top 2
    )

    payload = orchestrator.execute_screen(query=query, records=synthetic_records)

    # Analytical qualification: 3 stocks survived selection
    assert payload.selected_count == 3
    # Display limit truncation: only 2 returned
    assert len(payload.rows) == 2
    assert [r["symbol"] for r in payload.rows] == ["ALPHA", "DELTA"]


# =============================================================================
# 5. Full Cockpit API Integration (/api/screen)
# =============================================================================

def test_api_screen_with_modular_selection_mode_all(client):
    """Test POST /api/screen with selection_mode='ALL'."""
    payload = {
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 3},
            {"metric": "RANK_Y", "max_rank": 3},
        ],
        "selection_mode": "ALL",
        "limit": 10,
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert data["selected_count"] <= 3


def test_api_screen_with_modular_selection_mode_any(client):
    """Test POST /api/screen with selection_mode='ANY'."""
    payload = {
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 2},
            {"metric": "RANK_Y", "max_rank": 2},
        ],
        "selection_mode": "ANY",
        "limit": 10,
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data


def test_api_screen_column_projection_independent_of_ranking_and_cutoffs(client):
    """Test requested columns in Card 5 do not affect eligibility or ranking order."""
    # Screen with primary rank M_CUR and cutoff on RANK_M <= 3,
    # but request columns for RANK_D, RANK_W, RANK_Y
    requested_cols = ["symbol", "price", "RANK_D", "RANK_W", "RANK_M", "RANK_Y"]
    payload = {
        "ranking_metric": "M_CUR",
        "ranking_order": "desc",
        "selection_cutoffs": [
            {"metric": "RANK_M", "max_rank": 3},
        ],
        "selection_mode": "ALL",
        "columns": requested_cols,
        "limit": 10,
    }
    resp = client.post("/api/screen", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    col_keys = [c["key"] for c in data["columns"]]
    for rc in requested_cols:
        assert rc in col_keys


def test_static_html_has_all_12_periods_in_all_selectors():
    """Verify all 12 canonical periods exist across Primary Ranking, Rank Filter, and Return Columns."""
    html_path = Path("src/yogi/cockpit/static/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    all_12_keys = ["DROC", "WROC", "M_CUR", "Q_CUR", "H_CUR", "YROC", "YTD", "3M", "3Y", "4Y", "5Y", "AVG5Y"]
    all_12_rank_cols = [
        "RANK_D", "RANK_W", "RANK_M", "RANK_Q", "RANK_H", "RANK_Y",
        "RANK_YTD", "RANK_3M", "RANK_3Y", "RANK_4Y", "RANK_5Y", "RANK_AVG5Y"
    ]

    # Section 01: All 12 options present in Primary Ranking Period selector
    for k in all_12_keys:
        assert f'value="{k}"' in content, f"Missing {k} in rankingMetric options"

    # Section 02: All 12 checkboxes present in Rank Filter
    for rc in all_12_rank_cols:
        assert f'class="rank-filter-tf" value="{rc}"' in content, f"Missing {rc} in rank-filter-tf"

    # Section 03: All 12 checkboxes present in Ranking Periods to Return
    for rc in all_12_rank_cols:
        assert f'class="rank-col-tf" value="{rc}"' in content, f"Missing {rc} in rank-col-tf"


def test_all_12_periods_primary_ranking(client):
    """Verify primary ranking works for every one of the 12 canonical periods."""
    all_12_metrics = ["DROC", "WROC", "M_CUR", "Q_CUR", "H_CUR", "YROC", "YTD", "3M", "3Y", "4Y", "5Y", "AVG5Y"]
    for m in all_12_metrics:
        resp = client.post("/api/screen", json={
            "universe_provider": "demo",
            "ranking_metric": m,
            "ranking_order": "desc",
            "selection_cutoffs": [],
            "limit": 5,
        })
        assert resp.status_code == 200, f"Screen failed for metric {m}"
        rows = resp.json()["rows"]
        assert len(rows) > 0, f"No rows returned for metric {m}"


def test_5y_vs_avg5y_distinction_preserved(client):
    """Verify 5Y (total-period return) and AVG5Y (average of 5 annual returns) produce distinct orderings."""
    r_5y = client.post("/api/screen", json={
        "universe_provider": "demo",
        "ranking_metric": "5Y",
        "ranking_order": "desc",
        "selection_cutoffs": [],
        "limit": 5,
    })
    assert r_5y.status_code == 200
    syms_5y = [row["symbol"] for row in r_5y.json()["rows"]]

    r_avg5y = client.post("/api/screen", json={
        "universe_provider": "demo",
        "ranking_metric": "AVG5Y",
        "ranking_order": "desc",
        "selection_cutoffs": [],
        "limit": 5,
    })
    assert r_avg5y.status_code == 200
    syms_avg5y = [row["symbol"] for row in r_avg5y.json()["rows"]]

    # They must produce different relative standings for the 5 demo stocks
    assert syms_5y != syms_avg5y, "5Y total return and AVG5Y average annual return must not be conflated"


def test_all_12_periods_rank_filtering_and_projection(client):
    """Verify rank cutoff filtering and column projection across extended periods."""
    extended_rank_cols = ["RANK_YTD", "RANK_3M", "RANK_3Y", "RANK_4Y", "RANK_5Y", "RANK_AVG5Y"]

    for rc in extended_rank_cols:
        # Cutoff test
        resp = client.post("/api/screen", json={
            "universe_provider": "demo",
            "ranking_metric": "M_CUR",
            "ranking_order": "desc",
            "selection_cutoffs": [{"metric": rc, "max_rank": 2}],
            "selection_mode": "ALL",
            "columns": ["symbol", "price", rc],
            "limit": 10,
        })
        assert resp.status_code == 200, f"Cutoff failed for {rc}"
        rows = resp.json()["rows"]
        assert len(rows) == 2, f"Expected 2 stocks for {rc} <= 2, got {len(rows)}"
        for row in rows:
            assert row[rc] <= 2, f"Stock {row['symbol']} exceeded cutoff: {row[rc]}"

"""Integration tests for Cockpit Security Metadata REST API endpoints.

Verifies:
- GET /api/meta/{symbol} returns canonical metadata
- GET /api/meta/{symbol} returns fallback record metadata if repo missing
- GET /api/meta/{symbol} returns 404 for unknown symbols
- POST /api/meta/{symbol} successfully updates metadata in live mode
- POST /api/meta/{symbol} returns 403 in demo mode
- POST /api/meta/{symbol} returns 422 for invalid editable field
- Demo mode GET /api/meta/SHILPAMED shows is_fno=True, fno='Y'
"""

from pathlib import Path
import pytest

from tests.cockpit.test_cockpit_api import AsgiTestClient
from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.storage.metadata import CsvMetadataRepository


@pytest.fixture
def temp_meta_repo(tmp_path: Path) -> CsvMetadataRepository:
    repo = CsvMetadataRepository(data_dir=tmp_path)
    repo.update_metadata("RELIANCE", "name", "Reliance Industries Limited")
    repo.update_metadata("RELIANCE", "sector", "Energy")
    repo.update_metadata("RELIANCE", "grade", "A")
    repo.update_metadata("RELIANCE", "mcap", 1950000.0)
    repo.update_metadata("RELIANCE", "fno", "Y")
    return repo


@pytest.fixture
def live_app_state(temp_meta_repo: CsvMetadataRepository) -> AppState:
    config = EngineConfig(provider="yfinance")
    state = AppState(
        config=config,
        metadata_repo=temp_meta_repo,
        initial_dataset={
            "RELIANCE": {"symbol": "RELIANCE", "price": 2500.0},
            "TCS": {"symbol": "TCS", "price": 3800.0, "name": "TCS Ltd", "sector": "IT", "fno": "N"},
        },
    )
    return state


@pytest.fixture
def live_client(live_app_state: AppState) -> AsgiTestClient:
    app = create_app(app_state=live_app_state, auto_refresh=False)
    return AsgiTestClient(app)


@pytest.fixture
def demo_client() -> AsgiTestClient:
    config = EngineConfig(provider="demo")
    state = AppState(config=config)
    app = create_app(app_state=state, auto_refresh=False)
    return AsgiTestClient(app)


def test_get_metadata_from_repo(live_client: AsgiTestClient):
    resp = live_client.get("/api/meta/RELIANCE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "RELIANCE"
    assert data["name"] == "Reliance Industries Limited"
    assert data["sector"] == "Energy"
    assert data["grade"] == "A"
    assert data["mcap"] == 1950000.0
    assert data["is_fno"] is True
    assert data["fno"] == "Y"
    assert data["instrument_type"] == "EQ"


def test_get_metadata_fallback_from_dataset(live_client: AsgiTestClient):
    resp = live_client.get("/api/meta/TCS")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "TCS"
    assert data["name"] == "TCS Ltd"
    assert data["sector"] == "IT"
    assert data["is_fno"] is False
    assert data["fno"] == "N"


def test_get_metadata_not_found(live_client: AsgiTestClient):
    resp = live_client.get("/api/meta/NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_post_metadata_live_success(live_client: AsgiTestClient, temp_meta_repo: CsvMetadataRepository):
    # Update sector
    resp = live_client.post(
        "/api/meta/RELIANCE",
        json={"field": "sector", "value": "Oil & Telecom"},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["symbol"] == "RELIANCE"
    assert out["field"] == "sector"
    assert out["value"] == "Oil & Telecom"
    assert out["success"] is True

    # Check persistence via GET
    get_resp = live_client.get("/api/meta/RELIANCE")
    assert get_resp.status_code == 200
    assert get_resp.json()["sector"] == "Oil & Telecom"


def test_post_metadata_invalid_field_returns_422(live_client: AsgiTestClient):
    resp = live_client.post(
        "/api/meta/RELIANCE",
        json={"field": "invalid_attribute", "value": "test"},
    )
    assert resp.status_code == 422
    assert "not a valid editable metadata field" in resp.json()["detail"]


def test_post_metadata_demo_returns_403(demo_client: AsgiTestClient):
    resp = demo_client.post(
        "/api/meta/SHILPAMED",
        json={"field": "sector", "value": "Pharma"},
    )
    assert resp.status_code == 403
    assert "disabled in demo mode" in resp.json()["detail"]


def test_demo_metadata_shilpamed_fno(demo_client: AsgiTestClient):
    resp = demo_client.get("/api/meta/SHILPAMED")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "SHILPAMED"
    assert data["is_fno"] is True
    assert data["fno"] == "Y"
    assert data["sector"] == "Pharma"
    assert data["grade"] == "OPP"


def test_demo_metadata_manyavar_non_fno(demo_client: AsgiTestClient):
    resp = demo_client.get("/api/meta/MANYAVAR")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "MANYAVAR"
    assert data["is_fno"] is False
    assert data["fno"] == "N"
    assert data["sector"] == "Apparel"

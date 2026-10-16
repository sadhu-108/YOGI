"""Tests for Cockpit System Settings API and Persistence."""

import json
from pathlib import Path
import pytest
from fastapi import status

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.cockpit.schemas import SystemSettingsOut, SystemSettingsUpdateIn
from yogi.storage.cache import DatasetCache, MarketBarsCache
from tests.cockpit.test_cockpit_api import AsgiTestClient


@pytest.fixture
def clean_settings_app(tmp_path):
    """Create a test AppState and FastAPI application using a temporary data directory."""
    settings_file = tmp_path / "settings.json"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    state = AppState(
        dataset_cache=DatasetCache(cache_dir=cache_dir),
        bars_cache=MarketBarsCache(cache_dir=cache_dir),
    )
    # Inject isolated settings file
    state._settings_file = settings_file
    state._load_settings()
    app = create_app(app_state=state, auto_refresh=False)
    yield app
    # Cleanup
    if settings_file.exists():
        settings_file.unlink(missing_ok=True)


def test_get_settings_default(clean_settings_app):
    """GET /api/settings returns prototype policy by default."""
    client = AsgiTestClient(clean_settings_app)
    res = client.get("/api/settings")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data.get("half_year_policy") == "prototype"


def test_update_settings_valid(clean_settings_app):
    """POST /api/settings updates half_year_policy and persists to storage."""
    client = AsgiTestClient(clean_settings_app)
    res = client.post("/api/settings", json={"half_year_policy": "calendar"})
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data.get("half_year_policy") == "calendar"

    # Verify AppState synchronization
    yogi_state = clean_settings_app.state.yogi_state
    assert yogi_state.half_year_policy == "calendar"
    assert yogi_state.orchestrator.timeframe_engine.half_year_policy == "calendar"

    # Verify persistence file on disk
    assert yogi_state._settings_file.is_file()
    disk_data = json.loads(yogi_state._settings_file.read_text(encoding="utf-8"))
    assert disk_data.get("half_year_policy") == "calendar"

    # Verify subsequent GET returns updated policy
    get_res = client.get("/api/settings")
    assert get_res.json().get("half_year_policy") == "calendar"

    # Revert back to prototype
    revert_res = client.post("/api/settings", json={"half_year_policy": "prototype"})
    assert revert_res.status_code == status.HTTP_200_OK
    assert revert_res.json().get("half_year_policy") == "prototype"
    assert yogi_state.half_year_policy == "prototype"


def test_update_settings_invalid_policy(clean_settings_app):
    """POST /api/settings with an unsupported policy returns HTTP 400 Bad Request."""
    client = AsgiTestClient(clean_settings_app)
    res = client.post("/api/settings", json={"half_year_policy": "unsupported_rule"})
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid half_year_policy" in res.json().get("detail", "")


def test_system_status_reports_half_year_policy(clean_settings_app):
    """GET /api/status includes the active half_year_policy."""
    client = AsgiTestClient(clean_settings_app)
    res = client.get("/api/status")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "half_year_policy" in data
    assert data["half_year_policy"] == "prototype"

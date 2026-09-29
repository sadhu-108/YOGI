"""Integration tests for Cockpit Band Audit, Backups, and Restore REST API endpoints.

Verifies:
- GET /api/bands/log/{symbol} returns per-symbol change history with correct DTO fields
- GET /api/bands/log returns global change history respecting limit parameter
- GET /api/bands/backups returns available snapshots with safe metadata
- POST and GET /api/bands/restore/{filename} successfully restores bands
- Restore returns 404 for missing backup file
- Restore returns 400 for path traversal attempt or invalid filename regex
- Restore returns 422 for malformed / invalid backup CSV
- Restore returns 403 when operating in demo mode
- Panel cache is cleared upon band update and backup restore
- End-to-end roundtrip: update band -> view audit -> snapshot -> update again -> restore -> verify
"""

from pathlib import Path
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.schemas import (
    BandBackupsResponseOut,
    BandGlobalLogResponseOut,
    BandLogResponseOut,
    BandRestoreResponseOut,
    BandUpdateIn,
    StockDetailPanelOut,
)
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.bands import BAND_TIMEFRAMES
from yogi.storage.bands import CsvBandsRepository


class SimpleAsgiResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json_data = json_data

    def json(self) -> dict:
        return self._json_data


@pytest.fixture
def persistent_repo(tmp_path: Path) -> CsvBandsRepository:
    return CsvBandsRepository(data_dir=tmp_path)


@pytest.fixture
def app_state_with_csv(persistent_repo: CsvBandsRepository) -> AppState:
    config = EngineConfig(provider="yfinance", bands_repository="csv")
    state = AppState(
        bands_repo=persistent_repo,
        config=config,
        initial_dataset={"ALPHA": {"symbol": "ALPHA", "price": 100.0}},
    )
    return state



def test_api_bands_log_per_symbol(app_state_with_csv: AppState, persistent_repo: CsvBandsRepository):
    """Verify GET /api/bands/log/{symbol} returns symbol change history."""
    from yogi.cockpit.router import get_band_log_symbol

    persistent_repo.set_band("ALPHA", "D", 0.05, who="trader_bob", source="chart")
    persistent_repo.set_band("ALPHA", "D", 0.09, who="trader_alice", source="slider")
    persistent_repo.set_band("BETA", "M", 0.15)

    res = get_band_log_symbol(symbol="ALPHA", limit=60, app_state=app_state_with_csv)
    assert isinstance(res, BandLogResponseOut)
    assert res.symbol == "ALPHA"
    assert len(res.changes) == 2

    assert res.changes[0].old_pct == "5.0"
    assert res.changes[0].new_pct == "9.0"
    assert res.changes[0].changed_by == "trader_alice"
    assert res.changes[0].source == "slider"


def test_api_bands_log_global(app_state_with_csv: AppState, persistent_repo: CsvBandsRepository):
    """Verify GET /api/bands/log returns global change history across all symbols."""
    from yogi.cockpit.router import get_band_log_all

    persistent_repo.set_band("ALPHA", "D", 0.05)
    persistent_repo.set_band("BETA", "W", 0.10)
    persistent_repo.set_band("GAMMA", "M", 0.15)

    res = get_band_log_all(limit=2, app_state=app_state_with_csv)
    assert isinstance(res, BandGlobalLogResponseOut)
    assert len(res.changes) == 2
    # Reverse chronological: GAMMA, BETA
    assert res.changes[0].symbol == "GAMMA"
    assert res.changes[1].symbol == "BETA"


def test_api_bands_backups_list(app_state_with_csv: AppState, persistent_repo: CsvBandsRepository, tmp_path: Path):
    """Verify GET /api/bands/backups lists available snapshots."""
    from yogi.cockpit.router import get_band_backups

    persistent_repo.set_band("ALPHA", "D", 0.05)

    res = get_band_backups(app_state=app_state_with_csv)
    assert isinstance(res, BandBackupsResponseOut)
    assert len(res.backups) >= 1
    assert res.backups[0].file.startswith("bands_")
    assert res.backups[0].file.endswith(".csv")
    assert res.backups[0].stocks is not None
    assert res.backups[0].size_kb >= 0.0


def test_api_bands_restore_success(app_state_with_csv: AppState, persistent_repo: CsvBandsRepository, tmp_path: Path):
    """Verify restoring a backup replaces bands and clears panel cache."""
    from yogi.cockpit.router import restore_band_backup

    # Create dummy entry in panel cache
    with app_state_with_csv._panel_cache_lock:
        app_state_with_csv._panel_cache["ALPHA"] = StockDetailPanelOut(
            symbol="ALPHA",
            name="Alpha Ltd",
            exchange="NSE",
            price=100.0,
            as_of="2026-09-25",
            timeframe_rows=[],
            chips=[],
        )
    assert len(app_state_with_csv.panel_cache) == 1

    # Prepare backup file
    backup_file = tmp_path / "band_backups" / "bands_2026-06-15.csv"
    header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
    backup_file.write_text(header + "RESTORED_SYM,0.11,0.12,0.13,0.14,0.15,0.16\n", encoding="utf-8")

    res = restore_band_backup("bands_2026-06-15.csv", app_state=app_state_with_csv)
    assert isinstance(res, BandRestoreResponseOut)
    assert res.ok is True
    assert res.filename == "bands_2026-06-15.csv"
    assert "RESTORED_SYM" in persistent_repo._bands

    # Panel cache was cleared
    assert len(app_state_with_csv.panel_cache) == 0


def test_api_bands_restore_path_traversal_returns_400(app_state_with_csv: AppState):
    """Verify path traversal attempt in restore filename raises HTTP 400."""
    from fastapi import HTTPException
    from yogi.cockpit.router import restore_band_backup

    with pytest.raises(HTTPException) as excinfo:
        restore_band_backup("../../etc/passwd", app_state=app_state_with_csv)
    assert excinfo.value.status_code == 400
    assert "Invalid backup filename" in excinfo.value.detail


def test_api_bands_restore_missing_file_returns_404(app_state_with_csv: AppState):
    """Verify restoring a non-existent backup raises HTTP 404."""
    from fastapi import HTTPException
    from yogi.cockpit.router import restore_band_backup

    with pytest.raises(HTTPException) as excinfo:
        restore_band_backup("bands_2025-01-01.csv", app_state=app_state_with_csv)
    assert excinfo.value.status_code == 404


def test_api_bands_restore_malformed_csv_returns_422(app_state_with_csv: AppState, tmp_path: Path):
    """Verify restoring a corrupted backup raises HTTP 422."""
    from fastapi import HTTPException
    from yogi.cockpit.router import restore_band_backup

    bad_file = tmp_path / "band_backups" / "bands_2026-04-04.csv"
    bad_file.write_text("corrupted,file,no,timeframes\n1,2,3,4\n", encoding="utf-8")

    with pytest.raises(HTTPException) as excinfo:
        restore_band_backup("bands_2026-04-04.csv", app_state=app_state_with_csv)
    assert excinfo.value.status_code == 422


def test_api_update_band_clears_panel_cache(app_state_with_csv: AppState):
    """Verify PUT /api/bands/{symbol} clears the on-demand panel cache."""
    from yogi.cockpit.router import update_band

    with app_state_with_csv._panel_cache_lock:
        app_state_with_csv._panel_cache["ALPHA"] = StockDetailPanelOut(
            symbol="ALPHA",
            name="Alpha Ltd",
            exchange="NSE",
            price=100.0,
            as_of="2026-09-25",
            timeframe_rows=[],
            chips=[],
        )
    assert len(app_state_with_csv.panel_cache) == 1

    req = BandUpdateIn(timeframe="D", value=0.08)
    res = update_band("ALPHA", req, app_state=app_state_with_csv)
    assert res.success is True
    assert res.value == 0.08

    # Cache must be evicted
    assert len(app_state_with_csv.panel_cache) == 0


def test_full_roundtrip_audit_backup_restore(app_state_with_csv: AppState, persistent_repo: CsvBandsRepository, tmp_path: Path):
    """Verify full operational lifecycle: edit -> audit log -> snapshot -> edit -> restore original."""
    from yogi.cockpit.router import get_band_backups, get_band_log_symbol, restore_band_backup, update_band

    # 1. Update band to 0.05
    update_band("ROUNDTRIP_SYM", BandUpdateIn(timeframe="M", value=0.05), app_state=app_state_with_csv)
    assert persistent_repo.get_band("ROUNDTRIP_SYM", "M") == 0.05

    # 2. Check audit log
    log1 = get_band_log_symbol("ROUNDTRIP_SYM", app_state=app_state_with_csv)
    assert len(log1.changes) == 1
    assert log1.changes[0].new_pct == "5.0"

    # 3. Create a distinct historical backup with date 2026-07-20
    backup_file = tmp_path / "band_backups" / "bands_2026-07-20.csv"
    persistent_repo._atomic_write_bands_file(persistent_repo._bands, backup_file)

    # Verify backup is discoverable
    backups = get_band_backups(app_state=app_state_with_csv)
    assert any(b.file == "bands_2026-07-20.csv" for b in backups.backups)

    # 4. Update band to 0.25 (drift)
    update_band("ROUNDTRIP_SYM", BandUpdateIn(timeframe="M", value=0.25), app_state=app_state_with_csv)
    assert persistent_repo.get_band("ROUNDTRIP_SYM", "M") == 0.25

    # 5. Restore from 2026-07-20 backup
    restore_res = restore_band_backup("bands_2026-07-20.csv", app_state=app_state_with_csv)
    assert restore_res.ok is True

    # 6. Verify original 0.05 restored
    assert persistent_repo.get_band("ROUNDTRIP_SYM", "M") == 0.05


def test_api_bands_restore_in_demo_mode_returns_403(persistent_repo: CsvBandsRepository):
    """Verify band restore is rejected with HTTP 403 when application is running in demo mode."""
    from fastapi import HTTPException
    from yogi.cockpit.router import restore_band_backup

    demo_state = AppState(
        bands_repo=persistent_repo,
        config=EngineConfig(provider="demo", bands_repository="csv"),
        initial_dataset={"ALPHA": {"symbol": "ALPHA", "price": 100.0}},
    )
    with pytest.raises(HTTPException) as excinfo:
        restore_band_backup("bands_2026-01-01.csv", app_state=demo_state)
    assert excinfo.value.status_code == 403
    assert "demo mode" in excinfo.value.detail


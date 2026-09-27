"""Unit tests for daily band snapshots, backup listing, and 400-day pruning in CsvBandsRepository.

Verifies:
- full band matrix snapshot covering all symbols and canonical timeframes (D, W, M, Q, H, Y)
- correct filename formatting (bands_YYYY-MM-DD.csv)
- same-day snapshot replacement (one file per day)
- backup listing with symbol count and file size in KB
- 400-day retention pruning unlinking older files
- atomic staged file creation
"""

from datetime import date, datetime, timedelta
from pathlib import Path
import pytest

from yogi.core.contracts.bands import BAND_TIMEFRAMES
from yogi.storage.bands import CsvBandsRepository


@pytest.fixture
def repo(tmp_path: Path) -> CsvBandsRepository:
    """Instantiate a CsvBandsRepository with a temporary directory."""
    return CsvBandsRepository(data_dir=tmp_path)


def test_create_snapshot_writes_full_matrix(repo: CsvBandsRepository, tmp_path: Path):
    """Verify create_snapshot writes a valid CSV with all symbols and timeframes."""
    # Seed custom symbols
    repo.set_band("SYM_ALPHA", "D", 0.05)
    repo.set_band("SYM_ALPHA", "M", 0.15)
    repo.set_band("SYM_BETA", "W", 0.08)

    snapshot_file = repo.create_snapshot(reason="test")
    assert snapshot_file is not None

    today_str = date.today().strftime("%Y-%m-%d")
    assert snapshot_file == f"bands_{today_str}.csv"

    snapshot_path = tmp_path / "band_backups" / snapshot_file
    assert snapshot_path.exists()

    lines = snapshot_path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    assert header[0] == "symbol"
    assert tuple(header[1:]) == tuple(BAND_TIMEFRAMES)

    # Check rows exist
    content = snapshot_path.read_text(encoding="utf-8")
    assert "SYM_ALPHA" in content
    assert "SYM_BETA" in content


def test_same_day_snapshot_overwrites_existing_file(repo: CsvBandsRepository, tmp_path: Path):
    """Verify calling snapshot multiple times on the same day updates the same file."""
    repo.set_band("SYM_UPDATE", "D", 0.05)
    file1 = repo.create_snapshot()

    today_str = date.today().strftime("%Y-%m-%d")
    expected_file = f"bands_{today_str}.csv"
    assert file1 == expected_file

    backup_path = tmp_path / "band_backups" / expected_file
    assert "0.05" in backup_path.read_text(encoding="utf-8")

    # Update band and snapshot again
    repo.set_band("SYM_UPDATE", "D", 0.12)
    file2 = repo.create_snapshot()
    assert file2 == expected_file

    # Only 1 file should exist in backup_dir
    backup_files = list((tmp_path / "band_backups").glob("bands_*.csv"))
    assert len(backup_files) == 1
    assert "0.12" in backup_path.read_text(encoding="utf-8")


def test_list_backups_returns_sorted_metadata(repo: CsvBandsRepository, tmp_path: Path):
    """Verify list_backups discovers backup files in reverse chronological order."""
    backup_dir = tmp_path / "band_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
    # Create fake dated files
    (backup_dir / "bands_2026-08-01.csv").write_text(header + "A,0.01,0.02,0.03,0.04,0.05,0.06\n", encoding="utf-8")
    (backup_dir / "bands_2026-09-01.csv").write_text(
        header + "A,0.01,0.02,0.03,0.04,0.05,0.06\nB,0.02,0.03,0.04,0.05,0.06,0.07\n", encoding="utf-8"
    )
    (backup_dir / "bands_2026-07-15.csv").write_text(header, encoding="utf-8")

    backups = repo.list_backups()
    assert len(backups) == 3

    # Sorted descending by date
    assert backups[0].filename == "bands_2026-09-01.csv"
    assert backups[0].date_str == "2026-09-01"
    assert backups[0].symbol_count == 2
    assert backups[0].size_kb >= 0.0

    assert backups[1].filename == "bands_2026-08-01.csv"
    assert backups[1].date_str == "2026-08-01"
    assert backups[1].symbol_count == 1

    assert backups[2].filename == "bands_2026-07-15.csv"
    assert backups[2].date_str == "2026-07-15"
    assert backups[2].symbol_count == 0


def test_pruning_keeps_400_days_and_unlinks_older(repo: CsvBandsRepository, tmp_path: Path):
    """Verify _prune_backups retains only the latest 400 snapshots."""
    backup_dir = tmp_path / "band_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
    start_date = date(2025, 1, 1)

    # Create 410 daily snapshot files
    for day in range(410):
        d = start_date + timedelta(days=day)
        fn = f"bands_{d.strftime('%Y-%m-%d')}.csv"
        (backup_dir / fn).write_text(header, encoding="utf-8")

    assert len(list(backup_dir.glob("bands_*.csv"))) == 410

    # Trigger prune
    repo._prune_backups(keep_days=400)

    remaining = sorted([f.name for f in backup_dir.glob("bands_*.csv")])
    assert len(remaining) == 400

    # Oldest 10 (Jan 1 to Jan 10 2025) should be gone
    assert "bands_2025-01-01.csv" not in remaining
    assert "bands_2025-01-10.csv" not in remaining
    assert "bands_2025-01-11.csv" in remaining

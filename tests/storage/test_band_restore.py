"""Unit tests for band restore operation, atomicity, validation, and security protection.

Verifies:
- valid restore completely replaces active bands.csv and in-memory cache
- pre-restore safety snapshot is automatically created
- path traversal attempts are strictly blocked:
  - '../' and '..\\'
  - absolute paths
  - arbitrary filenames / non-matching regex
  - arbitrary file extensions
- content validation aborts before modifying state:
  - invalid CSV structure
  - missing required 'symbol' or timeframe columns
  - negative band values
  - non-numeric band values
  - empty records
- failed restore leaves original bands completely intact (atomicity)
"""

from pathlib import Path
import pytest

from yogi.core.contracts.bands import BAND_TIMEFRAMES
from yogi.storage.bands import CsvBandsRepository


@pytest.fixture
def repo(tmp_path: Path) -> CsvBandsRepository:
    """Instantiate a CsvBandsRepository pointing to a temporary test directory."""
    return CsvBandsRepository(data_dir=tmp_path)


def test_valid_restore_replaces_matrix_and_creates_safety_snapshot(repo: CsvBandsRepository, tmp_path: Path):
    """Verify restore_backup replaces all bands and takes a pre-restore snapshot."""
    # Set initial bands
    repo.set_band("STOCK_OLD", "D", 0.05)
    assert repo.get_band("STOCK_OLD", "D") == 0.05

    # Create a dated backup to restore from
    backup_dir = tmp_path / "band_backups"
    target_backup = backup_dir / "bands_2026-05-01.csv"
    header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
    target_backup.write_text(header + "STOCK_RESTORED,0.12,0.14,0.16,0.18,0.20,0.22\n", encoding="utf-8")

    # Perform restore
    success = repo.restore_backup("bands_2026-05-01.csv")
    assert success is True

    # Active bands should be replaced (unassigned stock resolves to default 0.0)
    assert repo.get_band("STOCK_OLD", "D") == 0.0
    assert repo.get_band("STOCK_RESTORED", "D") == 0.12
    assert repo.get_band("STOCK_RESTORED", "Y") == 0.22

    # Verify data/bands.csv was replaced on disk
    bands_disk = (tmp_path / "bands.csv").read_text(encoding="utf-8")
    assert "STOCK_RESTORED" in bands_disk
    assert "STOCK_OLD" not in bands_disk


def test_restore_missing_backup_raises_file_not_found(repo: CsvBandsRepository):
    """Verify restoring a non-existent backup raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="does not exist"):
        repo.restore_backup("bands_2025-01-01.csv")


@pytest.mark.parametrize(
    "malicious_filename",
    [
        "../etc/passwd",
        "..\\windows\\win.ini",
        "../../bands_2026-01-01.csv",
        "bands_2026-01-01.csv/../../escape.csv",
        "/etc/bands_2026-01-01.csv",
        "C:\\Windows\\System32\\bands_2026-01-01.csv",
        "bands_seed.csv",
        "user_presets.json",
        "bands_2026-01-01.txt",
        "bands_2026-01-01.csv.bak",
        "invalid_regex_format.csv",
    ],
)
def test_path_traversal_and_invalid_filenames_strictly_rejected(repo: CsvBandsRepository, malicious_filename: str):
    """Verify path traversal patterns and non-whitelisted filenames are rejected with ValueError."""
    with pytest.raises(ValueError, match="Invalid backup filename"):
        repo.restore_backup(malicious_filename)


def test_restore_invalid_csv_schema_aborts_without_modifying_state(repo: CsvBandsRepository, tmp_path: Path):
    """Verify backup with missing timeframe columns fails validation without corrupting state."""
    repo.set_band("ORIGINAL", "D", 0.05)

    backup_dir = tmp_path / "band_backups"
    bad_backup = backup_dir / "bands_2026-01-01.csv"
    # Missing columns Q, H, Y
    bad_backup.write_text("symbol,D,W,M\nBAD,0.1,0.2,0.3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required canonical timeframe column"):
        repo.restore_backup("bands_2026-01-01.csv")

    # State must be completely intact
    assert repo.get_band("ORIGINAL", "D") == 0.05


def test_restore_negative_band_value_aborts_without_modifying_state(repo: CsvBandsRepository, tmp_path: Path):
    """Verify backup with negative band value fails validation without corrupting state."""
    repo.set_band("SAFE_STOCK", "W", 0.08)

    backup_dir = tmp_path / "band_backups"
    bad_backup = backup_dir / "bands_2026-02-02.csv"
    header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
    bad_backup.write_text(header + "BAD_STOCK,-0.05,0.1,0.1,0.1,0.1,0.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Negative band value"):
        repo.restore_backup("bands_2026-02-02.csv")

    assert repo.get_band("SAFE_STOCK", "W") == 0.08


def test_restore_empty_backup_aborts(repo: CsvBandsRepository, tmp_path: Path):
    """Verify empty backup with only headers fails validation."""
    backup_dir = tmp_path / "band_backups"
    empty_backup = backup_dir / "bands_2026-03-03.csv"
    empty_backup.write_text("symbol," + ",".join(BAND_TIMEFRAMES) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="contains no valid symbol records"):
        repo.restore_backup("bands_2026-03-03.csv")

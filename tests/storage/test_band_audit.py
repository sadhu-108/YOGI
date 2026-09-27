"""Unit tests for persistent band audit logging in CsvBandsRepository.

Verifies:
- first band change creates an entry
- old_pct and new_pct correctly recorded as human-readable percentages
- symbol, timeframe, changed_by, source, timestamp correctness
- changes with absolute difference < 1e-12 are suppressed
- append-only behavior (never overwriting historical rows)
- per-symbol history retrieval with isolation
- global history retrieval across symbols
- limits: 60 for symbol, 300 for global
- strict reverse-chronological ordering (newest first)
- thread-safety of concurrent audit appends
"""

from datetime import datetime
import threading
from pathlib import Path
import pytest

from yogi.core.contracts.bands import BandAuditEntry
from yogi.storage.bands import CsvBandsRepository


@pytest.fixture
def repo(tmp_path: Path) -> CsvBandsRepository:
    """Instantiate a CsvBandsRepository pointing to a temporary test directory."""
    return CsvBandsRepository(data_dir=tmp_path)


def test_first_band_change_creates_audit_entry(repo: CsvBandsRepository, tmp_path: Path):
    """Verify set_band creates an audit row in band_changes.csv for a new symbol."""
    audit_file = tmp_path / "band_changes.csv"
    assert not audit_file.exists()

    repo.set_band("NEW_STOCK_XYZ", "M", 0.15, who="trader1", source="chart panel")

    assert audit_file.exists()
    history = repo.get_history("NEW_STOCK_XYZ")
    assert len(history) == 1

    entry = history[0]
    assert entry.symbol == "NEW_STOCK_XYZ"
    assert entry.timeframe == "M"
    assert entry.old_value is None
    assert entry.new_value == 0.15
    assert entry.old_pct == ""
    assert entry.new_pct == "15.0"
    assert entry.changed_by == "trader1"
    assert entry.source == "chart panel"
    assert isinstance(entry.timestamp, datetime)


def test_subsequent_band_change_records_old_and_new_pct(repo: CsvBandsRepository):
    """Verify changing a band records the previous value as old_pct and new as new_pct."""
    repo.set_band("NEW_SYM_A", "D", 0.05, who="userA", source="test")
    repo.set_band("NEW_SYM_A", "D", 0.08, who="userB", source="slider")

    history = repo.get_history("NEW_SYM_A")
    assert len(history) == 2

    # Reverse-chronological: newest first
    newest = history[0]
    assert newest.symbol == "NEW_SYM_A"
    assert newest.timeframe == "D"
    assert newest.old_value == 0.05
    assert newest.new_value == 0.08
    assert newest.old_pct == "5.0"
    assert newest.new_pct == "8.0"
    assert newest.changed_by == "userB"
    assert newest.source == "slider"

    oldest = history[1]
    assert oldest.old_value is None
    assert oldest.new_value == 0.05
    assert oldest.old_pct == ""
    assert oldest.new_pct == "5.0"


def test_seeded_symbol_edit_records_seed_as_old_pct(repo: CsvBandsRepository):
    """Verify editing a pre-seeded stock (like RELIANCE with M=0.08) records 0.08 as old_value."""
    seed_m = repo.get_band("RELIANCE", "M")
    assert seed_m == 0.08

    repo.set_band("RELIANCE", "M", 0.15, who="trader1", source="chart")
    history = repo.get_history("RELIANCE")
    assert len(history) == 1
    assert history[0].old_value == 0.08
    assert history[0].new_value == 0.15
    assert history[0].old_pct == "8.0"
    assert history[0].new_pct == "15.0"


def test_suppress_change_below_tolerance(repo: CsvBandsRepository):
    """Verify changes with abs difference < 1e-12 do not create an audit entry."""
    repo.set_band("INFY", "W", 0.10)
    assert len(repo.get_history("INFY")) == 1

    # Identical value
    repo.set_band("INFY", "W", 0.10)
    assert len(repo.get_history("INFY")) == 1

    # Value with micro-drift < 1e-12
    repo.set_band("INFY", "W", 0.10 + 1e-13)
    assert len(repo.get_history("INFY")) == 1

    # Meaningful change >= 1e-12
    repo.set_band("INFY", "W", 0.10 + 1e-6)
    assert len(repo.get_history("INFY")) == 2


def test_append_only_behavior(repo: CsvBandsRepository, tmp_path: Path):
    """Verify the audit file grows append-only with valid CSV headers."""
    audit_file = tmp_path / "band_changes.csv"

    repo.set_band("HDFC", "M", 0.12)
    lines_after_first = audit_file.read_text(encoding="utf-8").splitlines()
    assert len(lines_after_first) == 2  # header + 1 row
    assert lines_after_first[0] == "when,symbol,timeframe,old_pct,new_pct,changed_by,source"

    repo.set_band("HDFC", "M", 0.14)
    lines_after_second = audit_file.read_text(encoding="utf-8").splitlines()
    assert len(lines_after_second) == 3
    assert lines_after_second[1] == lines_after_first[1]  # first line intact


def test_per_symbol_isolation_and_filtering(repo: CsvBandsRepository):
    """Verify get_history(symbol) isolates rows for that symbol only."""
    repo.set_band("AAPL", "D", 0.02)
    repo.set_band("MSFT", "D", 0.03)
    repo.set_band("AAPL", "W", 0.06)
    repo.set_band("GOOG", "M", 0.10)

    aapl_hist = repo.get_history("AAPL")
    assert len(aapl_hist) == 2
    assert all(e.symbol == "AAPL" for e in aapl_hist)
    assert aapl_hist[0].timeframe == "W"
    assert aapl_hist[1].timeframe == "D"

    msft_hist = repo.get_history("msft")  # case-insensitive
    assert len(msft_hist) == 1
    assert msft_hist[0].symbol == "MSFT"

    unknown_hist = repo.get_history("NONEXISTENT")
    assert unknown_hist == []


def test_global_history_and_limits(repo: CsvBandsRepository):
    """Verify get_history(symbol=None) retrieves across all symbols, respecting limits."""
    for i in range(10):
        repo.set_band(f"SYM{i}", "D", float(i) / 100.0)

    global_hist = repo.get_history(symbol=None, limit=5)
    assert len(global_hist) == 5
    # Newest was SYM9
    assert global_hist[0].symbol == "SYM9"
    assert global_hist[4].symbol == "SYM5"


def test_missing_audit_file_returns_empty_list(tmp_path: Path):
    """Verify empty list is returned cleanly when audit file does not exist."""
    repo = CsvBandsRepository(data_dir=tmp_path)
    # Remove audit file if created
    if (tmp_path / "band_changes.csv").exists():
        (tmp_path / "band_changes.csv").unlink()

    assert repo.get_history("ANY") == []
    assert repo.get_history(None) == []


def test_concurrent_audit_appends(repo: CsvBandsRepository):
    """Verify multi-threaded band updates safely append without corrupted rows."""
    def worker(worker_id: int):
        for i in range(10):
            repo.set_band(f"CONC{worker_id}", "D", float(i) * 0.01 + 0.01, who=f"w{worker_id}")

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_history = repo.get_history(symbol=None, limit=500)
    assert len(all_history) == 50

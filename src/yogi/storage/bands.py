"""Persistent Bands Storage — CsvBandsRepository, Audit Trail, Daily Snapshots & Atomic Restore.

Implements authoritative disk-backed storage for trader discretionary band configurations:
1. Authoritative active band state: `data/bands.csv`
2. Append-only change audit trail: `data/band_changes.csv`
3. Daily historical snapshots: `data/band_backups/bands_YYYY-MM-DD.csv`
4. Atomic restoration with pre-restore safety snapshot and strict path containment.
"""

from csv import DictReader, DictWriter
from datetime import date, datetime
import logging
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Mapping, Optional, Sequence

from yogi.core.contracts.bands import (
    BAND_TIMEFRAMES,
    BandAuditEntry,
    BandBackupInfo,
    IBandAuditRepository,
    IBandBackupService,
    IBandsRepository,
)
from yogi.storage.paths import get_data_dir

logger = logging.getLogger(__name__)

AUDIT_FIELDS = ["when", "symbol", "timeframe", "old_pct", "new_pct", "changed_by", "source"]
BACKUP_FILENAME_PATTERN = re.compile(r"^bands_\d{4}-\d{2}-\d{2}\.csv$")
KEEP_SNAPSHOT_DAYS = 400


class CsvBandsRepository(IBandsRepository, IBandAuditRepository, IBandBackupService):
    """Thread-safe, CSV-backed discretionary bands repository with audit logging and backups."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        fixtures_dir: Optional[Path] = None,
    ) -> None:
        self.data_dir = get_data_dir(data_dir)
        self.backup_dir = self.data_dir / "band_backups"
        self.bands_file = self.data_dir / "bands.csv"
        self.audit_file = self.data_dir / "band_changes.csv"
        self._fixtures_dir = Path(fixtures_dir).resolve() if fixtures_dir is not None else None

        self._lock = threading.RLock()
        self._bands: dict[str, dict[str, float]] = {}

        self._ensure_storage_initialized()

    def _ensure_storage_initialized(self) -> None:
        """Create directories and initialize authoritative bands.csv from fixture seed if missing."""
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            if not self.bands_file.exists():
                seed_path = self._resolve_seed_fixture()
                if seed_path and seed_path.exists():
                    try:
                        shutil.copy(seed_path, self.bands_file)
                        logger.info("Initialized authoritative bands from seed fixture: %s", seed_path)
                    except Exception as exc:
                        logger.warning("Failed to copy seed fixture to %s: %s", self.bands_file, exc)
                        self._create_empty_bands_file()
                else:
                    self._create_empty_bands_file()

            self._load_from_disk()

    def _resolve_seed_fixture(self) -> Optional[Path]:
        """Locate bands_seed.csv from configured fixture directory, storage-owned data, or legacy fallback."""
        if self._fixtures_dir and (self._fixtures_dir / "bands_seed.csv").exists():
            return self._fixtures_dir / "bands_seed.csv"

        # Canonical storage-owned asset
        storage_seed = Path(__file__).resolve().parent / "data" / "bands_seed.csv"
        if storage_seed.exists():
            return storage_seed

        # Legacy fallback if cockpit asset exists
        legacy_cockpit_seed = Path(__file__).resolve().parent.parent / "cockpit" / "data" / "bands_seed.csv"
        if legacy_cockpit_seed.exists():
            return legacy_cockpit_seed

        return None

    def _create_empty_bands_file(self) -> None:
        """Create an empty bands.csv with standard headers."""
        header = "symbol," + ",".join(BAND_TIMEFRAMES) + "\n"
        self.bands_file.write_text(header, encoding="utf-8")

    def _load_from_disk(self) -> None:
        """Load bands from bands.csv into in-memory dictionary."""
        new_bands: dict[str, dict[str, float]] = {}
        if self.bands_file.exists():
            try:
                with open(self.bands_file, mode="r", newline="", encoding="utf-8") as f:
                    reader = DictReader(f)
                    for row in reader:
                        sym_raw = row.get("symbol")
                        if not sym_raw:
                            continue
                        sym = str(sym_raw).strip().upper()
                        new_bands[sym] = {}
                        for tf in BAND_TIMEFRAMES:
                            val_str = row.get(tf)
                            if val_str is not None and val_str.strip() != "":
                                try:
                                    new_bands[sym][tf] = float(val_str)
                                except ValueError:
                                    pass
            except Exception as exc:
                logger.error("Error loading bands from %s: %s", self.bands_file, exc)
        self._bands = new_bands

    def _atomic_write_bands_file(self, bands_data: Mapping[str, Mapping[str, float]], target_path: Path) -> None:
        """Atomically write bands dictionary to a target CSV path via staged temporary rename."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target_path.with_name(
            f"{target_path.name}.tmp_{os.getpid()}_{threading.get_ident()}"
        )
        try:
            with open(tmp_file, mode="w", newline="", encoding="utf-8") as f:
                writer = DictWriter(f, fieldnames=["symbol"] + list(BAND_TIMEFRAMES))
                writer.writeheader()
                for sym in sorted(bands_data.keys()):
                    row: dict[str, str] = {"symbol": sym}
                    sym_bands = bands_data[sym]
                    for tf in BAND_TIMEFRAMES:
                        val = sym_bands.get(tf)
                        row[tf] = f"{val:g}" if val is not None else ""
                    writer.writerow(row)
            os.replace(tmp_file, target_path)
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    # -------------------------------------------------------------------------
    # IBandsRepository
    # -------------------------------------------------------------------------

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        """Return the band width fraction for a symbol and timeframe."""
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        with self._lock:
            return self._bands.get(sym, {}).get(tf)

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        """Return band width fractions across all standard timeframes."""
        sym = symbol.strip().upper()
        with self._lock:
            sym_bands = self._bands.get(sym, {})
            return {tf: sym_bands.get(tf) for tf in BAND_TIMEFRAMES}

    def set_band(
        self,
        symbol: str,
        timeframe: str,
        value: float,
        who: str = "app",
        source: str = "app",
    ) -> float:
        """Update a band width fraction, atomically persist to disk, record audit entry, and snapshot."""
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        new_val = float(value)

        with self._lock:
            old_val = self._bands.get(sym, {}).get(tf)

            # Update in-memory dict
            if sym not in self._bands:
                self._bands[sym] = {}
            self._bands[sym][tf] = new_val

            # Atomic persist to data/bands.csv
            self._atomic_write_bands_file(self._bands, self.bands_file)

            # Audit logging & daily snapshot only if numerical change >= 1e-12
            if old_val is None or abs(old_val - new_val) >= 1e-12:
                entry = BandAuditEntry(
                    timestamp=datetime.now(),
                    symbol=sym,
                    timeframe=tf,
                    old_value=old_val,
                    new_value=new_val,
                    changed_by=who,
                    source=source,
                )
                self.record_change(entry)
                self.create_snapshot(reason="auto")

            return new_val

    # -------------------------------------------------------------------------
    # IBandAuditRepository
    # -------------------------------------------------------------------------

    def record_change(self, entry: BandAuditEntry) -> bool:
        """Append an audit record to data/band_changes.csv. Suppresses zero-diff changes."""
        old = entry.old_value
        new = entry.new_value
        if old is not None and new is not None and abs(float(old) - float(new)) < 1e-12:
            return False

        with self._lock:
            try:
                self.audit_file.parent.mkdir(parents=True, exist_ok=True)
                newfile = not self.audit_file.exists()
                with open(self.audit_file, mode="a", newline="", encoding="utf-8") as f:
                    writer = DictWriter(f, fieldnames=AUDIT_FIELDS)
                    if newfile:
                        writer.writeheader()
                    writer.writerow({
                        "when": entry.when,
                        "symbol": entry.symbol.strip().upper(),
                        "timeframe": entry.timeframe.strip().upper(),
                        "old_pct": entry.old_pct,
                        "new_pct": entry.new_pct,
                        "changed_by": entry.changed_by,
                        "source": entry.source,
                    })
                return True
            except Exception as exc:
                logger.error("Failed to write band audit entry to %s: %s", self.audit_file, exc)
                return False

    def get_history(self, symbol: Optional[str] = None, limit: int = 500) -> Sequence[BandAuditEntry]:
        """Retrieve audit history in reverse chronological order."""
        if not self.audit_file.exists():
            return []

        target_sym = symbol.strip().upper() if symbol is not None else None
        rows: list[dict[str, str]] = []

        with self._lock:
            try:
                with open(self.audit_file, mode="r", newline="", encoding="utf-8") as f:
                    reader = DictReader(f)
                    for row in reader:
                        sym = str(row.get("symbol", "")).strip().upper()
                        if target_sym is None or sym == target_sym:
                            rows.append(row)
            except Exception as exc:
                logger.error("Failed to read band audit history from %s: %s", self.audit_file, exc)
                return []

        # Prototype semantics: tail(limit) then reverse (newest first)
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            limit_val = 500

        selected_rows = rows[-limit_val:] if len(rows) > limit_val else rows
        selected_rows.reverse()

        entries: list[BandAuditEntry] = []
        for r in selected_rows:
            try:
                when_str = r.get("when", "")
                try:
                    dt = datetime.strptime(when_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = datetime.now()

                old_str = r.get("old_pct", "")
                old_val = float(old_str) / 100.0 if old_str and old_str.strip() != "" else None

                new_str = r.get("new_pct", "")
                new_val = float(new_str) / 100.0 if new_str and new_str.strip() != "" else None

                entries.append(
                    BandAuditEntry(
                        timestamp=dt,
                        symbol=str(r.get("symbol", "")).strip().upper(),
                        timeframe=str(r.get("timeframe", "")).strip().upper(),
                        old_value=old_val,
                        new_value=new_val,
                        changed_by=str(r.get("changed_by", "app")),
                        source=str(r.get("source", "app")),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed audit row %s: %s", r, exc)

        return entries

    # -------------------------------------------------------------------------
    # IBandBackupService
    # -------------------------------------------------------------------------

    def create_snapshot(self, reason: str = "auto") -> Optional[str]:
        """Create a daily snapshot of all bands, replacing same-day file, and prune older than 400 days."""
        with self._lock:
            try:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = date.today().strftime("%Y-%m-%d")
                filename = f"bands_{stamp}.csv"
                target_path = self.backup_dir / filename

                # Atomic write of full current matrix
                self._atomic_write_bands_file(self._bands, target_path)

                # Prune older than 400 days
                self._prune_backups(keep_days=KEEP_SNAPSHOT_DAYS)

                return filename
            except Exception as exc:
                logger.error("Failed to create band backup snapshot: %s", exc)
                return None

    def _prune_backups(self, keep_days: int = 400) -> None:
        """Keep the most recent daily snapshots and unlink older files."""
        files = sorted(
            [f for f in self.backup_dir.glob("bands_*.csv") if BACKUP_FILENAME_PATTERN.match(f.name)]
        )
        if len(files) > keep_days:
            for old_file in files[:-keep_days]:
                try:
                    old_file.unlink()
                except OSError as exc:
                    logger.warning("Failed to prune old backup %s: %s", old_file, exc)

    def list_backups(self) -> Sequence[BandBackupInfo]:
        """List all valid backups in descending chronological order."""
        if not self.backup_dir.exists():
            return []

        out: list[BandBackupInfo] = []
        with self._lock:
            files = sorted(
                [f for f in self.backup_dir.glob("bands_*.csv") if BACKUP_FILENAME_PATTERN.match(f.name)],
                reverse=True,
            )
            for f in files:
                try:
                    date_str = f.stem.replace("bands_", "")
                    # Count non-empty symbol rows
                    stocks = 0
                    with open(f, mode="r", newline="", encoding="utf-8") as csv_f:
                        reader = DictReader(csv_f)
                        for _ in reader:
                            stocks += 1
                    size_kb = round(f.stat().st_size / 1024.0, 1)
                    out.append(
                        BandBackupInfo(
                            filename=f.name,
                            date_str=date_str,
                            symbol_count=stocks,
                            size_kb=size_kb,
                        )
                    )
                except Exception as exc:
                    logger.warning("Error reading backup metadata for %s: %s", f, exc)

        return out

    def restore_backup(self, filename: str) -> bool:
        """Safely and atomically restore bands from a validated dated snapshot."""
        # 1. Security check: strict filename validation against regex
        if not BACKUP_FILENAME_PATTERN.match(filename):
            raise ValueError(f"Invalid backup filename '{filename}'. Format must match 'bands_YYYY-MM-DD.csv'.")

        with self._lock:
            # 2. Security check: path containment verification
            resolved_backup_dir = self.backup_dir.resolve()
            src = (self.backup_dir / filename).resolve()
            if src.parent != resolved_backup_dir or not src.is_file():
                raise FileNotFoundError(f"Backup file '{filename}' does not exist in backup directory.")

            # 3. Content validation of backup CSV before touching active state
            candidate_bands: dict[str, dict[str, float]] = {}
            try:
                with open(src, mode="r", newline="", encoding="utf-8") as f:
                    reader = DictReader(f)
                    fieldnames = reader.fieldnames or []
                    if "symbol" not in fieldnames:
                        raise ValueError("Backup CSV missing required 'symbol' column.")
                    for tf in BAND_TIMEFRAMES:
                        if tf not in fieldnames:
                            raise ValueError(f"Backup CSV missing required canonical timeframe column '{tf}'.")

                    row_count = 0
                    for row in reader:
                        sym_raw = row.get("symbol")
                        if not sym_raw:
                            continue
                        sym = str(sym_raw).strip().upper()
                        if not sym:
                            continue
                        row_count += 1
                        candidate_bands[sym] = {}
                        for tf in BAND_TIMEFRAMES:
                            val_str = row.get(tf)
                            if val_str is not None and val_str.strip() != "":
                                try:
                                    val = float(val_str)
                                    if val < 0.0:
                                        raise ValueError(f"Negative band value {val} for {sym}:{tf}")
                                    candidate_bands[sym][tf] = val
                                except ValueError as val_err:
                                    raise ValueError(f"Invalid numeric band value in {sym}:{tf}: {val_err}") from val_err

                    if row_count == 0 or not candidate_bands:
                        raise ValueError("Backup CSV contains no valid symbol records.")
            except Exception as exc:
                if isinstance(exc, (ValueError, FileNotFoundError)):
                    raise
                raise ValueError(f"Corrupted or unparseable backup file: {exc}") from exc

            # 4. Create pre-restore safety snapshot of active data
            self.create_snapshot(reason="before-restore")

            # 5. Atomically replace authoritative data/bands.csv
            self._atomic_write_bands_file(candidate_bands, self.bands_file)

            # 6. Update in-memory cache
            self._bands = candidate_bands
            logger.info("Successfully restored bands from %s (%d symbols).", filename, len(candidate_bands))
            return True

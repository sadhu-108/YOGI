"""Persistent CSV Security Metadata Repository — thread-safe atomic storage.

Implements ISecurityMetadataRepository managing metadata.csv and fno_list.csv.
Follows the atomic write safety pattern established in Batch 4 CsvBandsRepository.
"""

import csv
import io
import logging
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping, Optional, Sequence, Set

from yogi.core.contracts.security import (
    ISecurityMetadataRepository,
    InstrumentType,
    ListingStatus,
    SecurityMetadata,
)
from yogi.storage.paths import get_data_dir

logger = logging.getLogger(__name__)

METADATA_HEADER = [
    "symbol",
    "exchange",
    "name",
    "isin",
    "sector",
    "grade",
    "is_fno",
    "mcap",
    "instrument_type",
    "listing_status",
    "series_or_group",
    "notes",
]


class CsvMetadataRepository(ISecurityMetadataRepository):
    """Thread-safe, atomic CSV-backed security metadata and F&O repository."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        seed_meta_csv: Optional[Path] = None,
        seed_fno_csv: Optional[Path] = None,
    ) -> None:
        self._dir = get_data_dir(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._meta_file = self._dir / "metadata.csv"
        self._fno_file = self._dir / "fno_list.csv"
        self._lock = threading.Lock()

        self._metadata: dict[tuple[str, str], SecurityMetadata] = {}
        self._fno_symbols: set[str] = set()

        self._initialize(seed_meta_csv=seed_meta_csv, seed_fno_csv=seed_fno_csv)

    def _initialize(
        self,
        seed_meta_csv: Optional[Path] = None,
        seed_fno_csv: Optional[Path] = None,
    ) -> None:
        with self._lock:
            # 1. Load F&O symbols
            if self._fno_file.exists():
                self._load_fno_file(self._fno_file)
            elif seed_fno_csv and seed_fno_csv.exists():
                self._load_fno_file(seed_fno_csv)
                self._save_fno_file_atomic()

            # 2. Load Metadata
            if self._meta_file.exists():
                self._load_meta_file(self._meta_file)
            else:
                seed = seed_meta_csv if seed_meta_csv and seed_meta_csv.exists() else (self._dir / "his_meta.csv")
                if seed and seed.exists():
                    self._load_legacy_or_meta_file(seed)
                    self._save_meta_file_atomic()

    def _load_fno_file(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
            reader = csv.DictReader(io.StringIO(content.strip()))
            if not reader.fieldnames:
                return
            sym_col = next((c for c in reader.fieldnames if "SYMBOL" in str(c).strip().upper()), None)
            if not sym_col:
                return
            for row in reader:
                val = row.get(sym_col)
                if val:
                    sym = str(val).strip().upper()
                    if sym and sym not in ("", "NAN", "NULL", "NONE"):
                        self._fno_symbols.add(sym)
        except Exception as exc:
            logger.warning("Could not load F&O list from %s: %s", path, exc)

    def _load_meta_file(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
            reader = csv.DictReader(io.StringIO(content.strip()))
            if not reader.fieldnames:
                return
            for row in reader:
                sym = str(row.get("symbol", "")).strip().upper()
                ex = str(row.get("exchange", "NSE")).strip().upper()
                if not sym:
                    continue

                raw_fno = str(row.get("is_fno", "")).strip().upper()
                is_fno = raw_fno in ("Y", "YES", "TRUE", "1") or sym in self._fno_symbols

                raw_mcap = row.get("mcap")
                mcap = float(raw_mcap) if raw_mcap and raw_mcap not in ("", "None", "nan") else None

                raw_instr = str(row.get("instrument_type", "EQ")).strip().upper()
                try:
                    instr = InstrumentType(raw_instr)
                except ValueError:
                    instr = InstrumentType.EQ

                raw_status = str(row.get("listing_status", "ACTIVE")).strip().upper()
                try:
                    status = ListingStatus(raw_status)
                except ValueError:
                    status = ListingStatus.ACTIVE

                sec = SecurityMetadata(
                    symbol=sym,
                    exchange=ex,
                    name=row.get("name") or None,
                    isin=row.get("isin") or None,
                    sector=row.get("sector") or None,
                    grade=row.get("grade") or None,
                    is_fno=is_fno,
                    mcap=mcap,
                    instrument_type=instr,
                    listing_status=status,
                    series_or_group=row.get("series_or_group") or None,
                    notes=row.get("notes") or None,
                )
                self._metadata[(sym, ex)] = sec
        except Exception as exc:
            logger.warning("Could not load metadata from %s: %s", path, exc)

    def _load_legacy_or_meta_file(self, path: Path) -> None:
        """Load either canonical metadata.csv or prototype his_meta.csv."""
        try:
            content = path.read_text(encoding="utf-8")
            reader = csv.DictReader(io.StringIO(content.strip()))
            if not reader.fieldnames:
                return

            cols = [str(c).strip().lower() for c in reader.fieldnames]
            is_legacy = "fno" in cols and "is_fno" not in cols

            for row in reader:
                sym = str(row.get("symbol", "")).strip().upper()
                if not sym:
                    continue
                ex = str(row.get("exchange", "NSE")).strip().upper()

                if is_legacy:
                    raw_fno = str(row.get("fno", "")).strip().upper()
                    is_fno = raw_fno in ("Y", "FNO", "YES", "TRUE") or sym in self._fno_symbols
                else:
                    raw_fno = str(row.get("is_fno", "")).strip().upper()
                    is_fno = raw_fno in ("Y", "YES", "TRUE", "1") or sym in self._fno_symbols

                raw_mcap = row.get("mcap")
                mcap = float(raw_mcap) if raw_mcap and raw_mcap not in ("", "None", "nan") else None

                raw_instr = str(row.get("instrument_type", "EQ")).strip().upper()
                try:
                    instr = InstrumentType(raw_instr)
                except ValueError:
                    instr = InstrumentType.EQ

                sec = SecurityMetadata(
                    symbol=sym,
                    exchange=ex,
                    name=row.get("name") or None,
                    isin=row.get("isin") or None,
                    sector=row.get("sector") or None,
                    grade=row.get("grade") or None,
                    is_fno=is_fno,
                    mcap=mcap,
                    instrument_type=instr,
                    listing_status=ListingStatus.ACTIVE,
                    series_or_group=row.get("series_or_group") or None,
                    notes=row.get("notes") or None,
                )
                self._metadata[(sym, ex)] = sec
        except Exception as exc:
            logger.warning("Could not seed metadata from %s: %s", path, exc)

    def _save_meta_file_atomic(self) -> None:
        """Atomically persist self._metadata to metadata.csv."""
        tmp_file = self._dir / "metadata.csv.tmp"
        rows: list[dict[str, Any]] = []
        for (sym, ex), sec in sorted(self._metadata.items()):
            rows.append({
                "symbol": sec.symbol,
                "exchange": sec.exchange,
                "name": sec.name or "",
                "isin": sec.isin or "",
                "sector": sec.sector or "",
                "grade": sec.grade or "",
                "is_fno": "Y" if sec.is_fno else "N",
                "mcap": sec.mcap if sec.mcap is not None else "",
                "instrument_type": sec.instrument_type.value,
                "listing_status": sec.listing_status.value,
                "series_or_group": sec.series_or_group or "",
                "notes": sec.notes or "",
            })

        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=METADATA_HEADER)
        writer.writeheader()
        writer.writerows(rows)

        tmp_file.write_text(out.getvalue(), encoding="utf-8")
        tmp_file.replace(self._meta_file)

    def _save_fno_file_atomic(self) -> None:
        """Atomically persist self._fno_symbols to fno_list.csv."""
        tmp_file = self._dir / "fno_list.csv.tmp"
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["symbol"])
        writer.writeheader()
        for sym in sorted(self._fno_symbols):
            writer.writerow({"symbol": sym})

        tmp_file.write_text(out.getvalue(), encoding="utf-8")
        tmp_file.replace(self._fno_file)

    def get_metadata(self, symbol: str, exchange: str = "NSE") -> Optional[SecurityMetadata]:
        sym_u = symbol.strip().upper()
        ex_u = (exchange or "NSE").strip().upper()
        with self._lock:
            sec = self._metadata.get((sym_u, ex_u))
            if sec:
                return sec
            # Fallback to symbol-only match across exchanges
            for (s, e), m in self._metadata.items():
                if s == sym_u:
                    return m
            return None

    def get_all_metadata(self, exchange: str = "NSE") -> Mapping[str, SecurityMetadata]:
        ex_u = (exchange or "NSE").strip().upper()
        with self._lock:
            return {
                sym: sec
                for (sym, ex), sec in self._metadata.items()
                if ex == ex_u
            }

    def get_fno_symbols(self) -> Set[str]:
        with self._lock:
            return set(self._fno_symbols)

    def is_fno(self, symbol: str) -> bool:
        sym_u = symbol.strip().upper()
        with self._lock:
            if sym_u in self._fno_symbols:
                return True
            for (s, _), sec in self._metadata.items():
                if s == sym_u and sec.is_fno:
                    return True
            return False

    def update_metadata(
        self,
        symbol: str,
        field: str,
        value: Any,
        exchange: str = "NSE",
    ) -> Optional[SecurityMetadata]:
        sym_u = symbol.strip().upper()
        ex_u = (exchange or "NSE").strip().upper()
        fld = field.strip().lower()

        allowed_fields = {
            "name",
            "isin",
            "sector",
            "grade",
            "fno",
            "is_fno",
            "mcap",
            "instrument_type",
            "listing_status",
            "series_or_group",
            "notes",
        }
        if fld not in allowed_fields:
            raise ValueError(f"Field '{field}' is not a valid editable metadata field.")

        with self._lock:
            existing = self._metadata.get((sym_u, ex_u))
            if existing is None:
                # Default baseline for newly introduced symbol
                is_fno_init = sym_u in self._fno_symbols
                existing = SecurityMetadata(
                    symbol=sym_u,
                    exchange=ex_u,
                    is_fno=is_fno_init,
                    instrument_type=InstrumentType.EQ,
                    listing_status=ListingStatus.ACTIVE,
                )

            # Apply field update with appropriate type coercion
            kwargs: dict[str, Any] = {
                "symbol": existing.symbol,
                "exchange": existing.exchange,
                "name": existing.name,
                "isin": existing.isin,
                "sector": existing.sector,
                "grade": existing.grade,
                "is_fno": existing.is_fno,
                "mcap": existing.mcap,
                "instrument_type": existing.instrument_type,
                "listing_status": existing.listing_status,
                "series_or_group": existing.series_or_group,
                "notes": existing.notes,
            }

            if fld in ("fno", "is_fno"):
                if isinstance(value, str):
                    kwargs["is_fno"] = value.strip().upper() in ("Y", "YES", "TRUE", "1")
                else:
                    kwargs["is_fno"] = bool(value)
                if kwargs["is_fno"]:
                    self._fno_symbols.add(sym_u)
                else:
                    self._fno_symbols.discard(sym_u)
            elif fld == "mcap":
                if value is None or str(value).strip() in ("", "None", "nan"):
                    kwargs["mcap"] = None
                else:
                    kwargs["mcap"] = float(value)
            elif fld == "instrument_type":
                kwargs["instrument_type"] = (
                    value if isinstance(value, InstrumentType) else InstrumentType(str(value).strip().upper())
                )
            elif fld == "listing_status":
                kwargs["listing_status"] = (
                    value if isinstance(value, ListingStatus) else ListingStatus(str(value).strip().upper())
                )
            else:
                kwargs[fld] = str(value).strip() if value is not None and str(value).strip() else None

            updated = SecurityMetadata(**kwargs)
            self._metadata[(sym_u, ex_u)] = updated

            # Atomic persist
            self._save_meta_file_atomic()
            if fld in ("fno", "is_fno"):
                self._save_fno_file_atomic()

            return updated

    def set_fno_symbols(self, symbols: Iterable[str]) -> None:
        """Replace the F&O universe and sync is_fno flags across known securities."""
        sym_set = {str(s).strip().upper() for s in symbols if str(s).strip()}
        with self._lock:
            self._fno_symbols = sym_set

            # Sync is_fno flag on all loaded securities
            updated_meta: dict[tuple[str, str], SecurityMetadata] = {}
            for (sym, ex), sec in self._metadata.items():
                should_fno = sym in self._fno_symbols
                if sec.is_fno != should_fno:
                    sec = SecurityMetadata(
                        symbol=sec.symbol,
                        exchange=sec.exchange,
                        name=sec.name,
                        isin=sec.isin,
                        sector=sec.sector,
                        grade=sec.grade,
                        is_fno=should_fno,
                        mcap=sec.mcap,
                        instrument_type=sec.instrument_type,
                        listing_status=sec.listing_status,
                        series_or_group=sec.series_or_group,
                        notes=sec.notes,
                    )
                updated_meta[(sym, ex)] = sec
            self._metadata = updated_meta

            self._save_fno_file_atomic()
            self._save_meta_file_atomic()

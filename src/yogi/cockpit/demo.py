"""Demo Data Provider and Discretionary Bands Repository for Cockpit MVP Demonstration.

Loads verified offline golden fixtures (prices.csv and bands_seed.csv) so the Cockpit
can be fully demonstrated without external internet access or live broker credentials.
Satisfies the frozen IDataProvider and IBandsRepository Core contracts.
"""

from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
import pandas as pd

from datetime import datetime
from yogi.core.contracts.bands import (
    BAND_TIMEFRAMES,
    BandAuditEntry,
    BandBackupInfo,
    IBandAuditRepository,
    IBandBackupService,
    IBandsRepository,
)
from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.security import (
    ISecurityMetadataRepository,
    InstrumentType,
    ListingStatus,
    SecurityMetadata,
)


def _resolve_fixtures_dir(explicit_dir: Optional[Path] = None) -> Path:
    """Resolve the test fixtures directory containing golden price and band datasets."""
    if explicit_dir is not None:
        p = Path(explicit_dir)
        if p.exists() and (p / "prices.csv").exists():
            return p

    # Strategy 1: Bundled package data directory (src/yogi/cockpit/data)
    pkg_data = Path(__file__).resolve().parent / "data"
    if pkg_data.exists() and (pkg_data / "prices.csv").exists():
        return pkg_data

    # Strategy 2: Walk upwards from __file__ to find tests/fixtures or data
    curr = Path(__file__).resolve().parent
    for _ in range(6):
        c1 = curr / "tests" / "fixtures"
        if c1.exists() and (c1 / "prices.csv").exists():
            return c1
        c2 = curr / "data"
        if c2.exists() and (c2 / "prices.csv").exists():
            return c2
        curr = curr.parent

    # Strategy 3: Walk upwards from current working directory
    curr = Path.cwd()
    for _ in range(6):
        c1 = curr / "tests" / "fixtures"
        if c1.exists() and (c1 / "prices.csv").exists():
            return c1
        c2 = curr / "data"
        if c2.exists() and (c2 / "prices.csv").exists():
            return c2
        curr = curr.parent

    raise FileNotFoundError(
        "Unable to locate demo fixture dataset (prices.csv and bands_seed.csv) in package data or tests/fixtures."
    )


# Re-exported from replaceable provider layer under YOGI-F02 module placement
from yogi.data.providers.demo import DemoDataProvider


class DemoBandsRepository(IBandsRepository, IBandAuditRepository, IBandBackupService):
    """In-memory bands repository seeded from the verified bands_seed.csv fixture.
    
    Permits runtime interactive adjustment of band widths (set_band) while persisting
    in memory for the session, with in-memory audit tracking.
    """

    def __init__(self, fixtures_dir: Optional[Path] = None) -> None:
        fixtures_path = _resolve_fixtures_dir(fixtures_dir)
        bands_file = fixtures_path / "bands_seed.csv"
        if not bands_file.exists():
            raise FileNotFoundError(f"Bands fixture not found at {bands_file}")

        df = pd.read_csv(bands_file)
        self._bands: dict[str, dict[str, float]] = {}
        self._audit_log: list[BandAuditEntry] = []
        for _, row in df.iterrows():
            sym = str(row["symbol"]).strip().upper()
            self._bands[sym] = {}
            for tf in BAND_TIMEFRAMES:
                val = row.get(tf)
                if pd.notna(val):
                    self._bands[sym][tf] = float(val)

    def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        return self._bands.get(sym, {}).get(tf)

    def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
        sym = symbol.strip().upper()
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
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        old = self.get_band(sym, tf)
        if sym not in self._bands:
            self._bands[sym] = {}
        self._bands[sym][tf] = float(value)

        # Audit logging in memory if value actually changed
        if old is None or abs(old - float(value)) >= 1e-12:
            entry = BandAuditEntry(
                timestamp=datetime.now(),
                symbol=sym,
                timeframe=tf,
                old_value=old,
                new_value=float(value),
                changed_by=who,
                source=source,
            )
            self.record_change(entry)

        return float(value)

    # -------------------------------------------------------------------------
    # IBandAuditRepository
    # -------------------------------------------------------------------------

    def record_change(self, entry: BandAuditEntry) -> bool:
        old = entry.old_value
        new = entry.new_value
        if old is not None and new is not None and abs(float(old) - float(new)) < 1e-12:
            return False
        self._audit_log.append(entry)
        return True

    def get_history(self, symbol: Optional[str] = None, limit: int = 500) -> Sequence[BandAuditEntry]:
        target = symbol.strip().upper() if symbol is not None else None
        matches = [e for e in self._audit_log if target is None or e.symbol == target]
        selected = matches[-limit:] if len(matches) > limit else matches
        return list(reversed(selected))

    # -------------------------------------------------------------------------
    # IBandBackupService
    # -------------------------------------------------------------------------

    def create_snapshot(self, reason: str = "auto") -> Optional[str]:
        return None

    def list_backups(self) -> Sequence[BandBackupInfo]:
        return []

    def restore_backup(self, filename: str) -> bool:
        raise PermissionError("Band restore operation is disabled in demo mode.")


class DemoMetadataRepository(ISecurityMetadataRepository):
    """In-memory security metadata repository seeded from the offline demo_metadata.csv fixture.

    Guarantees 100% offline determinism:
    - Zero external network requests
    - Populates canonical metadata for the 5 golden demo symbols
    - In-memory updates during interactive demonstrations without filesystem persistence
    """

    def __init__(self, fixtures_dir: Optional[Path] = None) -> None:
        fixtures_path = _resolve_fixtures_dir(fixtures_dir)
        meta_file = fixtures_path / "demo_metadata.csv"
        if not meta_file.exists():
            raise FileNotFoundError(f"Demo metadata fixture not found at {meta_file}")

        df = pd.read_csv(meta_file)
        self._metadata: dict[tuple[str, str], SecurityMetadata] = {}
        self._fno_symbols: set[str] = set()

        for _, row in df.iterrows():
            sym = str(row["symbol"]).strip().upper()
            ex = str(row.get("exchange", "NSE")).strip().upper()
            raw_fno = str(row.get("is_fno", "")).strip().upper()
            is_fno = raw_fno in ("Y", "YES", "TRUE", "1")
            if is_fno:
                self._fno_symbols.add(sym)

            raw_mcap = row.get("mcap")
            mcap = float(raw_mcap) if pd.notna(raw_mcap) else None

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
                name=str(row["name"]).strip() if pd.notna(row.get("name")) else None,
                isin=str(row["isin"]).strip() if pd.notna(row.get("isin")) else None,
                sector=str(row["sector"]).strip() if pd.notna(row.get("sector")) else None,
                grade=str(row["grade"]).strip() if pd.notna(row.get("grade")) else None,
                is_fno=is_fno,
                mcap=mcap,
                instrument_type=instr,
                listing_status=status,
                series_or_group=str(row["series_or_group"]).strip() if pd.notna(row.get("series_or_group")) else None,
                notes=str(row["notes"]).strip() if pd.notna(row.get("notes")) else None,
            )
            self._metadata[(sym, ex)] = sec

    def get_metadata(self, symbol: str, exchange: str = "NSE") -> Optional[SecurityMetadata]:
        sym_u = symbol.strip().upper()
        ex_u = (exchange or "NSE").strip().upper()
        sec = self._metadata.get((sym_u, ex_u))
        if sec:
            return sec
        for (s, _), m in self._metadata.items():
            if s == sym_u:
                return m
        return None

    def get_all_metadata(self, exchange: str = "NSE") -> Mapping[str, SecurityMetadata]:
        ex_u = (exchange or "NSE").strip().upper()
        return {sym: sec for (sym, ex), sec in self._metadata.items() if ex == ex_u}

    def get_fno_symbols(self) -> Set[str]:
        return set(self._fno_symbols)

    def is_fno(self, symbol: str) -> bool:
        sym_u = symbol.strip().upper()
        if sym_u in self._fno_symbols:
            return True
        sec = self.get_metadata(sym_u)
        return sec.is_fno if sec else False

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

        existing = self.get_metadata(sym_u, ex_u)
        if existing is None:
            existing = SecurityMetadata(
                symbol=sym_u,
                exchange=ex_u,
                is_fno=sym_u in self._fno_symbols,
                instrument_type=InstrumentType.EQ,
                listing_status=ListingStatus.ACTIVE,
            )

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
            kwargs["mcap"] = float(value) if value is not None and str(value).strip() not in ("", "None", "nan") else None
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
        return updated



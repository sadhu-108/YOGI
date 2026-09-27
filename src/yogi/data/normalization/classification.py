"""Instrument classification normalizer — deterministic mapping of exchange listings to InstrumentType.

Migrated and adapted from prototype yogi.security_master.classify per BATCH_5_AUDIT_REPORT.md.
Pure normalizer: zero filesystem, HTTP, or framework dependencies.
"""

import csv
import io
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Set

from yogi.core.contracts.security import InstrumentType

NAME_HINTS: dict[str, tuple[str, ...]] = {
    "ETF": (
        "ETF",
        "BEES",
        "IETF",
        "GOLDSHARE",
        "SILVER",
        "LIQUID CASE",
        "GSEC",
        "NIFTYBEES",
        "BANKBEES",
        "JUNIORBEES",
    ),
    "REIT_INVIT": ("REIT", "INVIT", "INVITS"),
}


@dataclass(frozen=True)
class ClassificationMaps:
    """Pre-built lookup collections for instrument classification."""
    etf_symbols: frozenset[str] = frozenset()
    sme_symbols: frozenset[str] = frozenset()
    series_map: Mapping[str, str] = MappingProxyType({})
    bse_group_map: Mapping[str, str] = MappingProxyType({})


def parse_nse_etf_csv(csv_text: str) -> frozenset[str]:
    """Extract set of uppercase ETF symbols from NSE eq_etfseclist.csv content."""
    if not csv_text or not csv_text.strip():
        return frozenset()

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return frozenset()

    sym_col = next((c for c in reader.fieldnames if "SYMBOL" in c.upper()), None)
    if not sym_col:
        return frozenset()

    symbols: set[str] = set()
    for row in reader:
        raw = str(row.get(sym_col, "")).strip().upper()
        if raw and raw not in ("", "NAN", "NULL", "NONE"):
            symbols.add(raw)
    return frozenset(symbols)


def parse_nse_sme_csv(csv_text: str) -> frozenset[str]:
    """Extract set of uppercase SME symbols from NSE SME_EQUITY_L.csv content."""
    if not csv_text or not csv_text.strip():
        return frozenset()

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return frozenset()

    sym_col = next((c for c in reader.fieldnames if "SYMBOL" in c.upper()), None)
    if not sym_col:
        return frozenset()

    symbols: set[str] = set()
    for row in reader:
        raw = str(row.get(sym_col, "")).strip().upper()
        if raw and raw not in ("", "NAN", "NULL", "NONE"):
            symbols.add(raw)
    return frozenset(symbols)


def parse_nse_series_csv(csv_text: str) -> Mapping[str, str]:
    """Extract symbol -> series mapping from NSE EQUITY_L.csv content."""
    if not csv_text or not csv_text.strip():
        return MappingProxyType({})

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return MappingProxyType({})

    sym_col = next((c for c in reader.fieldnames if "SYMBOL" in c.upper()), None)
    ser_col = next((c for c in reader.fieldnames if c.strip().upper() == "SERIES" or "SERIES" in c.upper()), None)
    if not sym_col or not ser_col:
        return MappingProxyType({})

    series_map: dict[str, str] = {}
    for row in reader:
        sym = str(row.get(sym_col, "")).strip().upper()
        ser = str(row.get(ser_col, "")).strip().upper()
        if sym and ser and sym not in ("", "NAN", "NULL", "NONE"):
            series_map[sym] = ser
    return MappingProxyType(series_map)


def parse_bse_universe_csv(csv_text: str) -> Mapping[str, str]:
    """Extract symbol/scrip code -> group mapping from BSE universe CSV content."""
    if not csv_text or not csv_text.strip():
        return MappingProxyType({})

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return MappingProxyType({})

    grp_col = next((c for c in reader.fieldnames if c.strip().lower() in ("group", "grp", "group_name")), None)
    if not grp_col:
        return MappingProxyType({})

    sym_cols = [c for c in reader.fieldnames if c.strip().lower() in ("symbol", "scrip_cd", "scrip_code")]
    if not sym_cols:
        return MappingProxyType({})

    group_map: dict[str, str] = {}
    for row in reader:
        grp = str(row.get(grp_col, "")).strip().upper()
        if not grp:
            continue
        for scol in sym_cols:
            sym = str(row.get(scol, "")).strip().upper()
            if sym and sym not in ("", "NAN", "NULL", "NONE"):
                group_map[sym] = grp
    return MappingProxyType(group_map)


def classify_instrument(
    symbol: str,
    name: Optional[str] = None,
    exchange: str = "NSE",
    maps: Optional[ClassificationMaps] = None,
) -> tuple[InstrumentType, str]:
    """Work out InstrumentType and series/group for a single security.

    Pure function adhering strictly to prototype decision rules:
    - NSE: Checks ETF list, SME list, REIT/InvIT name hints, ETF name hints, trade-to-trade series (BE/BZ),
      defaulting to EQ.
    - BSE: Checks SME groups (M, MT, MS), illiquid groups (T, TS, XT, Z), name hints, defaulting to EQ.
    """
    sym = str(symbol).strip().upper()
    nm = (str(name) if name else "").strip().upper()
    ex = str(exchange or "NSE").strip().upper()
    m = maps if maps is not None else ClassificationMaps()

    if ex == "NSE":
        series = m.series_map.get(sym, "")

        # 1. Official NSE ETF list
        if sym in m.etf_symbols:
            return InstrumentType.ETF, series or "EQ"

        # 2. Official NSE SME (Emerge) list or SME series
        if sym in m.sme_symbols or series in ("SM", "ST"):
            return InstrumentType.SME, series or "SM"

        # 3. REIT / InvIT name or symbol hints
        for hint in NAME_HINTS["REIT_INVIT"]:
            if hint in nm or hint in sym:
                return InstrumentType.REIT_INVIT, series or "EQ"

        # 4. ETF name or symbol hints
        for hint in NAME_HINTS["ETF"]:
            if hint in sym or hint in nm:
                return InstrumentType.ETF, series or "EQ"

        # 5. Trade-to-trade surveillance
        if series in ("BE", "BZ"):
            return InstrumentType.BE, series

        return InstrumentType.EQ, series or "EQ"

    if ex == "BSE":
        grp = m.bse_group_map.get(sym, "")

        # 1. BSE SME groups
        if grp in ("M", "MT", "MS"):
            return InstrumentType.SME, grp

        # 2. BSE illiquid groups
        if grp in ("T", "TS", "XT", "Z"):
            return InstrumentType.ILLIQUID, grp

        # 3. ETF hints
        for hint in NAME_HINTS["ETF"]:
            if hint in nm or hint in sym:
                return InstrumentType.ETF, grp

        # 4. REIT / InvIT hints
        for hint in NAME_HINTS["REIT_INVIT"]:
            if hint in nm or hint in sym:
                return InstrumentType.REIT_INVIT, grp

        return InstrumentType.EQ, grp

    return InstrumentType.UNKNOWN, ""

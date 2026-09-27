"""NSE F&O Underlying Universe Normalizer — pure extraction of derivative-eligible equities.

Migrated and adapted from prototype yogi.security_master.fno_list per BATCH_5_AUDIT_REPORT.md.
Pure normalizer: zero filesystem, HTTP, or framework dependencies.
"""

import csv
import io
from typing import Optional, Set


def parse_fno_lots_csv(csv_text: str, min_symbols: int = 50) -> frozenset[str]:
    """Parse official NSE fo_mktlots.csv content and extract underlying equity symbols.

    Adheres strictly to prototype parsing rules:
    - Identifies column matching 'SYMBOL'
    - Sanitizes uppercase, stripped ASCII symbols
    - Rejects headers, non-ASCII characters, and symbols longer than 20 chars
    - Enforces min_symbols threshold to reject truncated or error responses
    """
    if not csv_text or not csv_text.strip():
        return frozenset()

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return frozenset()

    sym_col = next((c for c in reader.fieldnames if "SYMBOL" in str(c).strip().upper()), None)
    if not sym_col:
        return frozenset()

    symbols: set[str] = set()
    for row in reader:
        val = row.get(sym_col)
        if not val:
            continue
        sym = str(val).strip().upper()
        if (
            sym
            and sym.isascii()
            and len(sym) <= 20
            and not sym.startswith("SYMBOL")
            and sym not in ("", "NAN", "NULL", "NONE")
        ):
            symbols.add(sym)

    if min_symbols > 0 and len(symbols) < min_symbols:
        # File is truncated or malformed
        return frozenset()

    return frozenset(symbols)


def parse_fno_list_csv(csv_text: str) -> frozenset[str]:
    """Parse cached fno_list.csv (single column 'symbol')."""
    if not csv_text or not csv_text.strip():
        return frozenset()

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return frozenset()

    sym_col = next((c for c in reader.fieldnames if "SYMBOL" in str(c).strip().upper()), None)
    if not sym_col:
        return frozenset()

    symbols: set[str] = set()
    for row in reader:
        val = row.get(sym_col)
        if not val:
            continue
        sym = str(val).strip().upper()
        if sym and sym not in ("", "NAN", "NULL", "NONE"):
            symbols.add(sym)

    return frozenset(symbols)

"""Universe discovery and normalization for NSE and BSE equities.

Provides deterministic parsing of exchange security master files and APIs,
with offline fallback capabilities.
"""

import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import requests

NSE_EQUITY_URLS = [
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
]

BSE_SCRIP_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}

DEFAULT_NSE_FALLBACK: Sequence[str] = (
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "BHARTIARTL",
    "ITC",
    "KOTAKBANK",
    "LT",
)


def parse_nse_equity_csv(csv_text: str) -> Sequence[str]:
    """Parse NSE EQUITY_L.csv content, filtering strictly for SERIES == 'EQ'.

    Returns sorted unique uppercase symbols.
    """
    if not csv_text or not csv_text.strip():
        return ()

    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return ()

    col_map = {str(c).strip().upper(): c for c in reader.fieldnames}
    sym_col = col_map.get("SYMBOL")
    series_col = col_map.get("SERIES")

    if not sym_col:
        return ()

    symbols: set[str] = set()
    for row in reader:
        # Filter series if series column is present
        if series_col:
            series_val = str(row.get(series_col, "")).strip().upper()
            if series_val != "EQ":
                continue

        raw_sym = str(row.get(sym_col, "")).strip().upper()
        if raw_sym and raw_sym not in ("", "NAN", "NULL", "NONE"):
            symbols.add(raw_sym)

    return tuple(sorted(symbols))


def parse_bse_scrip_json(json_data: Union[str, Mapping[str, Any], Sequence[Any]]) -> Sequence[str]:
    """Parse BSE ListofScripData response, extracting active numeric equity scrip codes."""
    if isinstance(json_data, str):
        if not json_data.strip():
            return ()
        try:
            parsed = json.loads(json_data)
        except json.JSONDecodeError:
            return ()
    else:
        parsed = json_data

    rows: Sequence[Any]
    if isinstance(parsed, dict):
        rows = parsed.get("Table", [])
    elif isinstance(parsed, list):
        rows = parsed
    else:
        return ()

    codes: list[str] = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        code = str(it.get("SCRIP_CD") or it.get("Scrip_Cd") or it.get("symbol") or "").strip()
        if code.isdigit():
            codes.append(code)

    return tuple(sorted(set(codes)))


def fetch_nse_universe(
    session: Optional[requests.Session] = None,
    fallback_csv_path: Optional[Union[str, Path]] = None,
    static_fallback: Optional[Sequence[str]] = None,
    timeout: float = 15.0,
    use_network: bool = True,
) -> Sequence[str]:
    """Fetch the live NSE tradable equity universe with automatic offline fallback."""
    # Check local fallback file first if specified and existing
    if fallback_csv_path:
        p = Path(fallback_csv_path)
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                symbols = parse_nse_equity_csv(content)
                if symbols:
                    return symbols
            except Exception:
                pass

    if use_network:
        s = session or requests.Session()
        s.headers.update(HTTP_HEADERS)

        for url in NSE_EQUITY_URLS:
            try:
                resp = s.get(url, timeout=timeout)
                resp.raise_for_status()
                symbols = parse_nse_equity_csv(resp.text)
                if len(symbols) >= 50:
                    return symbols
            except Exception:
                continue

    return static_fallback or DEFAULT_NSE_FALLBACK


def fetch_bse_universe(
    session: Optional[requests.Session] = None,
    cache_path: Optional[Union[str, Path]] = None,
    static_fallback: Optional[Sequence[str]] = None,
    timeout: float = 20.0,
    use_network: bool = True,
) -> Sequence[str]:
    """Fetch the live BSE equity universe with offline cache fallback."""
    if cache_path:
        p = Path(cache_path)
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                codes = parse_bse_scrip_json(content)
                if codes:
                    return codes
            except Exception:
                pass

    if use_network:
        s = session or requests.Session()
        s.headers.update(HTTP_HEADERS)

        try:
            resp = s.get(BSE_SCRIP_URL, timeout=timeout)
            resp.raise_for_status()
            codes = parse_bse_scrip_json(resp.text)
            if codes:
                if cache_path:
                    try:
                        Path(cache_path).write_text(resp.text, encoding="utf-8")
                    except Exception:
                        pass
                return codes
        except Exception:
            pass

    return static_fallback or ()

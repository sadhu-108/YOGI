"""Canonical market data normalization for YOGI.

Converts raw external provider responses (DataFrames, dicts, MultiIndex tables)
into YOGI's frozen contractual data structures (MarketBar, TickData).
"""

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from yogi.core.contracts.market_data import MarketBar, TickData


def _to_naive_datetime(ts: Any) -> Optional[datetime]:
    """Convert a timestamp/date object to a timezone-naive datetime instance."""
    if ts is None:
        return None
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    if isinstance(ts, (int, float)):
        # Epoch seconds or milliseconds
        if ts > 1e11:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts)
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
            return dt.replace(tzinfo=None)
        except ValueError:
            pdt = pd.to_datetime(ts)
            return pdt.to_pydatetime().replace(tzinfo=None)
    return None


def normalize_yfinance_bars(df: Any) -> Sequence[MarketBar]:
    """Normalize a single-symbol DataFrame or slice from yfinance into a sequence of MarketBar.

    Preserves:
    - Naive datetime timestamps
    - Open, High, Low, Close (split/dividend adjusted when auto_adjust=True was used)
    - Volume as float when available, or None
    - Strict chronological ascending ordering
    - Deduplication by timestamp
    """
    if df is None:
        return ()
    if not isinstance(df, pd.DataFrame):
        return ()
    if df.empty:
        return ()

    # Handle MultiIndex columns (if single-ticker slice retained MultiIndex)
    if isinstance(df.columns, pd.MultiIndex):
        # Flatten MultiIndex to lowest level or first level
        df = df.copy()
        df.columns = df.columns.get_level_values(-1)

    # Standardize column names to lowercase
    col_map: dict[str, str] = {}
    for col in df.columns:
        c_str = str(col).strip().lower()
        col_map[c_str] = col

    # Identify primary columns
    c_close = col_map.get("close") or col_map.get("adj close")
    if not c_close:
        return ()

    c_open = col_map.get("open")
    c_high = col_map.get("high")
    c_low = col_map.get("low")
    c_vol = col_map.get("volume")

    bars_by_ts: dict[datetime, MarketBar] = {}

    # Extract Series arrays for rapid iteration
    indices = df.index
    closes = df[c_close].values
    opens = df[c_open].values if c_open else closes
    highs = df[c_high].values if c_high else closes
    lows = df[c_low].values if c_low else closes
    volumes = df[c_vol].values if c_vol else None

    for i in range(len(df)):
        ts = _to_naive_datetime(indices[i])
        if ts is None:
            continue

        c_val = closes[i]
        if pd.isna(c_val):
            continue

        o_val = opens[i]
        h_val = highs[i]
        l_val = lows[i]

        o_val = c_val if pd.isna(o_val) else o_val
        h_val = c_val if pd.isna(h_val) else h_val
        l_val = c_val if pd.isna(l_val) else l_val

        v_val: Optional[float] = None
        if volumes is not None:
            vol_raw = volumes[i]
            if pd.notna(vol_raw):
                try:
                    v_val = float(vol_raw)
                except (ValueError, TypeError):
                    v_val = None

        bar = MarketBar(
            timestamp=ts,
            open=float(o_val),
            high=float(h_val),
            low=float(l_val),
            close=float(c_val),
            volume=v_val,
        )
        bars_by_ts[ts] = bar

    # Return sorted chronologically ascending
    return tuple(sorted(bars_by_ts.values(), key=lambda b: b.timestamp))


def normalize_yfinance_batch(
    df: Any,
    symbols: Sequence[str],
    exchange: str = "NSE",
    ticker_map: Optional[Mapping[str, str]] = None,
) -> Mapping[str, Sequence[MarketBar]]:
    """Extract and normalize individual symbol OHLCV sequences from a yfinance batch download DataFrame.

    Handles MultiIndex variations:
    - Level 0: Metric ("Open", "Close", ...), Level 1: Ticker ("RELIANCE.NS", ...)
    - Level 0: Ticker ("RELIANCE.NS", ...), Level 1: Metric ("Open", "Close", ...)
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {s: () for s in symbols}

    out: dict[str, Sequence[MarketBar]] = {}

    if not isinstance(df.columns, pd.MultiIndex):
        # Single symbol response in flat DataFrame
        if len(symbols) == 1:
            sym = symbols[0]
            out[sym] = normalize_yfinance_bars(df)
            return out
        # If columns match a known symbol, normalize directly
        return {s: () for s in symbols}

    lv0 = [str(c).strip() for c in df.columns.get_level_values(0).unique()]
    lv1 = [str(c).strip() for c in df.columns.get_level_values(1).unique()]

    known_fields = {"open", "high", "low", "close", "adj close", "volume"}
    lv0_is_field = any(f in known_fields for f in [c.lower() for c in lv0])
    lv1_is_field = any(f in known_fields for f in [c.lower() for c in lv1])

    for sym in symbols:
        # Candidate ticker strings to match
        candidates = [sym, sym.upper(), sym.lower()]
        if ticker_map and sym in ticker_map:
            candidates.insert(0, ticker_map[sym])
        if exchange.upper() == "NSE":
            candidates.extend([f"{sym}.NS", f"{sym}.ns"])
        elif exchange.upper() == "BSE":
            candidates.extend([f"{sym}.BO", f"{sym}.bo"])

        matched_tk: Optional[str] = None
        matched_slice: Optional[pd.DataFrame] = None

        if lv0_is_field:
            # Level 0 is Metric, Level 1 is Ticker
            for cand in candidates:
                if cand in lv1:
                    matched_tk = cand
                    break
            if matched_tk:
                col_dict: dict[str, Any] = {}
                for field_name in lv0:
                    try:
                        col_dict[field_name] = df[(field_name, matched_tk)]
                    except KeyError:
                        pass
                if col_dict:
                    matched_slice = pd.DataFrame(col_dict, index=df.index)
        elif lv1_is_field:
            # Level 0 is Ticker, Level 1 is Metric
            for cand in candidates:
                if cand in lv0:
                    matched_tk = cand
                    break
            if matched_tk:
                try:
                    matched_slice = df[matched_tk]
                except KeyError:
                    pass

        if matched_slice is not None and not matched_slice.empty:
            out[sym] = normalize_yfinance_bars(matched_slice)
        else:
            out[sym] = ()

    return out


def normalize_zerodha_history(records: Sequence[Mapping[str, Any]]) -> Sequence[MarketBar]:
    """Normalize Zerodha Kite historical records (list of dicts) into a sequence of MarketBar."""
    if not records:
        return ()

    bars_by_ts: dict[datetime, MarketBar] = {}

    for r in records:
        raw_date = r.get("date")
        ts = _to_naive_datetime(raw_date)
        if ts is None:
            continue

        try:
            c_val = float(r["close"])
        except (KeyError, ValueError, TypeError):
            continue

        o_val = float(r.get("open", c_val))
        h_val = float(r.get("high", c_val))
        l_val = float(r.get("low", c_val))

        vol_raw = r.get("volume")
        v_val: Optional[float] = None
        if vol_raw is not None:
            try:
                v_val = float(vol_raw)
            except (ValueError, TypeError):
                v_val = None

        bar = MarketBar(
            timestamp=ts,
            open=o_val,
            high=h_val,
            low=l_val,
            close=c_val,
            volume=v_val,
        )
        bars_by_ts[ts] = bar

    return tuple(sorted(bars_by_ts.values(), key=lambda b: b.timestamp))


def normalize_zerodha_tick(
    symbol: str,
    tick: Mapping[str, Any],
    timestamp: Optional[datetime] = None,
) -> TickData:
    """Normalize a Zerodha KiteTicker packet into a YOGI canonical TickData DTO."""
    raw_price = tick.get("last_price", 0.0)
    try:
        last_price = float(raw_price) if raw_price is not None else 0.0
    except (ValueError, TypeError):
        last_price = 0.0

    raw_qty = tick.get("last_traded_quantity") or tick.get("last_quantity") or 0
    try:
        last_qty = int(raw_qty) if raw_qty is not None else 0
    except (ValueError, TypeError):
        last_qty = 0

    raw_time = tick.get("timestamp") or tick.get("exchange_timestamp")
    ts = _to_naive_datetime(raw_time) or timestamp or datetime.now()

    return TickData(
        symbol=symbol.upper(),
        timestamp=ts,
        last_price=last_price,
        last_quantity=last_qty,
    )


def normalize_twelve_data_bars(
    payload: Union[Mapping[str, Any], Sequence[Mapping[str, Any]], None],
) -> Sequence[MarketBar]:
    """Normalize a Twelve Data time_series response or values array into a sequence of MarketBar.

    Handles:
    - Dict with "values" key: {"meta": {...}, "values": [...], "status": "ok"}
    - Direct sequence of value dicts: [{"datetime": "...", "open": "...", ...}, ...]
    - Timestamp conversion to naive datetime
    - Numeric string conversion to float
    - Volume parsing (None if omitted or empty)
    - Strict chronological ascending ordering (Twelve Data returns newest first)
    - Deduplication by timestamp
    """
    if payload is None:
        return ()

    raw_values: Sequence[Mapping[str, Any]]
    if isinstance(payload, Mapping):
        # Check error status
        if payload.get("status") == "error":
            return ()
        raw_values = payload.get("values", ())
    elif isinstance(payload, Sequence):
        raw_values = payload
    else:
        return ()

    if not raw_values:
        return ()

    bars_by_ts: dict[datetime, MarketBar] = {}

    for row in raw_values:
        if not isinstance(row, Mapping):
            continue

        raw_dt = row.get("datetime")
        ts = _to_naive_datetime(raw_dt)
        if ts is None:
            continue

        try:
            c_val = float(row["close"])
        except (KeyError, ValueError, TypeError):
            continue

        try:
            o_val = float(row.get("open", c_val))
        except (ValueError, TypeError):
            o_val = c_val

        try:
            h_val = float(row.get("high", c_val))
        except (ValueError, TypeError):
            h_val = c_val

        try:
            l_val = float(row.get("low", c_val))
        except (ValueError, TypeError):
            l_val = c_val

        vol_raw = row.get("volume")
        v_val: Optional[float] = None
        if vol_raw is not None and str(vol_raw).strip() != "":
            try:
                v_val = float(vol_raw)
            except (ValueError, TypeError):
                v_val = None

        bar = MarketBar(
            timestamp=ts,
            open=o_val,
            high=h_val,
            low=l_val,
            close=c_val,
            volume=v_val,
        )
        bars_by_ts[ts] = bar

    return tuple(sorted(bars_by_ts.values(), key=lambda b: b.timestamp))


def normalize_twelve_data_batch(
    payload: Any,
    symbols: Sequence[str],
) -> Mapping[str, Sequence[MarketBar]]:
    """Normalize a multi-symbol Twelve Data response into a mapping of symbol -> Sequence[MarketBar].

    Handles:
    - Multi-symbol dict: {"RELIANCE": {"values": [...]}, "TCS": {"values": [...]}}
    - Single-symbol dict if batch had 1 symbol: {"meta": {"symbol": "RELIANCE"}, "values": [...]}
    """
    if not symbols:
        return {}
    if not isinstance(payload, Mapping) or not payload:
        return {s: () for s in symbols}

    out: dict[str, Sequence[MarketBar]] = {}

    # Case 1: Single symbol response format returned for a 1-item batch
    if "values" in payload and len(symbols) == 1:
        out[symbols[0]] = normalize_twelve_data_bars(payload)
        return out

    # Case 2: Multi-symbol dictionary keyed by symbol
    norm_payload = {str(k).strip().upper(): v for k, v in payload.items()}

    for sym in symbols:
        sym_u = sym.strip().upper()
        matched_data = norm_payload.get(sym_u)
        if matched_data is None:
            # Try finding key that starts with sym_u (e.g. "RELIANCE:NSE" or "RELIANCE.NS")
            for k, v in norm_payload.items():
                if k == sym_u or k.startswith(f"{sym_u}:") or k.startswith(f"{sym_u}."):
                    matched_data = v
                    break

        if matched_data is not None and isinstance(matched_data, Mapping):
            out[sym] = normalize_twelve_data_bars(matched_data)
        else:
            out[sym] = ()

    return out


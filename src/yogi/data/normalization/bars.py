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

    # Handle MultiIndex columns by identifying the level containing OHLCV price fields
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        best_level = None
        max_matches = 0
        known_fields = {"close", "adj close", "open", "high", "low", "volume"}
        for lvl in range(df.columns.nlevels):
            vals = {str(c).strip().lower() for c in df.columns.get_level_values(lvl)}
            matches = len(vals.intersection(known_fields))
            if matches > max_matches:
                max_matches = matches
                best_level = lvl

        if best_level is not None and max_matches > 0:
            df.columns = df.columns.get_level_values(best_level)
        else:
            # Fallback to last level if no known price fields detected
            df.columns = df.columns.get_level_values(-1)

    # Standardize column names to lowercase
    col_map: dict[str, Any] = {}
    for col in df.columns:
        c_str = str(col).strip().lower()
        if c_str not in col_map:
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

    def _extract_series(col_key: Any) -> Optional[Any]:
        if col_key is None:
            return None
        series_or_df = df[col_key]
        if isinstance(series_or_df, pd.DataFrame):
            return series_or_df.iloc[:, 0].values
        return series_or_df.values

    # Extract Series arrays for rapid iteration
    indices = df.index
    closes = _extract_series(c_close)
    if closes is None:
        return ()
    opens = _extract_series(c_open) if c_open is not None else closes
    highs = _extract_series(c_high) if c_high is not None else closes
    lows = _extract_series(c_low) if c_low is not None else closes
    volumes = _extract_series(c_vol) if c_vol is not None else None

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



"""YOGI Timeframe Engine — Multi-Timeframe Candle Synthesis.

Authoritatively synthesizes higher-order trading timeframes (W, M, Q, H, Y)
from canonical daily MarketBar sequences using verified financial OHLCV aggregation.
"""

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from yogi.core.contracts.market_data import MarketBar, MarketContext, Timeframe
from yogi.core.contracts.timeframe import ITimeframeEngine

# Authoritative resampling frequency mapping preserved from verified prototype
# config.py and core_math/formulas.py
TIMEFRAME_RULES: Mapping[str, Optional[str]] = {
    "D": None,
    "W": "W",       # Week-ending Sunday (W-SUN)
    "M": "ME",      # Calendar month-end
    "Q": "QE",      # Calendar quarter-end (Mar, Jun, Sep, Dec)
    "H": "2QE",     # Calendar half-year (2 quarters ending Mar, Sep)
    "Y": "YE",      # Calendar year-end (Dec 31)
}


def _normalize_timeframe_key(tf: Union[str, Timeframe]) -> str:
    """Normalize a timeframe identifier to its canonical uppercase string key."""
    if isinstance(tf, Timeframe):
        return tf.value
    return str(tf).strip().upper()


def _to_naive_datetime(ts: Any) -> datetime:
    """Convert any timestamp or date representation into a timezone-naive datetime."""
    if isinstance(ts, pd.Timestamp):
        return ts.to_pydatetime().replace(tzinfo=None)
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None)
    pdt = pd.to_datetime(ts)
    return pdt.to_pydatetime().replace(tzinfo=None)


def resample_bars(
    bars: Sequence[MarketBar],
    timeframe: Union[str, Timeframe],
) -> tuple[MarketBar, ...]:
    """Resample a sequence of daily MarketBar objects into a target timeframe.

    Preserves verified prototype OHLCV aggregation rules:
    - open: first bar's open
    - high: max of all highs
    - low: min of all lows
    - close: last bar's close
    - volume: sum of all volumes (retaining None if no volume data is present)

    Parameters:
        bars: Daily MarketBar objects (will be sorted chronologically before synthesis).
        timeframe: Target timeframe string or Timeframe enum ("D", "W", "M", "Q", "H", "Y").

    Returns:
        Immutable tuple of synthesized MarketBar objects sorted chronologically.
    """
    tf_key = _normalize_timeframe_key(timeframe)
    if tf_key not in TIMEFRAME_RULES:
        raise ValueError(
            f"Unsupported timeframe '{tf_key}'. Supported timeframes: {tuple(TIMEFRAME_RULES.keys())}"
        )

    if not bars:
        return ()

    # 1. Enforce chronological ordering and deterministic deduplication by timestamp
    sorted_bars = sorted(bars, key=lambda b: b.timestamp)
    deduped: dict[datetime, MarketBar] = {}
    for b in sorted_bars:
        deduped[b.timestamp] = b
    clean_bars = list(deduped.values())

    if not clean_bars:
        return ()

    # Daily timeframe returns the canonical sorted/deduplicated daily bars directly
    rule = TIMEFRAME_RULES[tf_key]
    if rule is None:
        return tuple(clean_bars)

    # 2. Extract column arrays
    timestamps = [b.timestamp for b in clean_bars]
    opens = [b.open for b in clean_bars]
    highs = [b.high for b in clean_bars]
    lows = [b.low for b in clean_bars]
    closes = [b.close for b in clean_bars]
    volumes = [b.volume for b in clean_bars]

    has_volume = any(v is not None for v in volumes)

    data: dict[str, Any] = {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    }
    if has_volume:
        data["volume"] = [
            float(v) if (v is not None and not pd.isna(v)) else float("nan")
            for v in volumes
        ]

    df = pd.DataFrame(data, index=pd.DatetimeIndex(timestamps))

    # 3. Apply standard OHLCV aggregation
    agg: dict[str, Any] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if has_volume:
        agg["volume"] = lambda s: s.sum(min_count=1)

    # Resample and drop empty periods (no trading days in period)
    res = df.resample(rule).agg(agg).dropna(subset=["close"])

    if res.empty:
        return ()

    # 4. Vectorized conversion back to frozen MarketBar DTOs
    res_index = res.index
    res_opens = res["open"].values
    res_highs = res["high"].values
    res_lows = res["low"].values
    res_closes = res["close"].values
    res_volumes = res["volume"].values if has_volume else None

    result: list[MarketBar] = []
    n = len(res)
    for i in range(n):
        bar_ts = _to_naive_datetime(res_index[i])
        vol: Optional[float] = None
        if res_volumes is not None:
            v_val = res_volumes[i]
            if not pd.isna(v_val):
                vol = float(v_val)

        result.append(
            MarketBar(
                timestamp=bar_ts,
                open=float(res_opens[i]),
                high=float(res_highs[i]),
                low=float(res_lows[i]),
                close=float(res_closes[i]),
                volume=vol,
            )
        )

    return tuple(result)


def build_market_context(
    symbol: str,
    exchange: str,
    daily_bars: Sequence[MarketBar],
    timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
    as_of: Optional[datetime] = None,
) -> MarketContext:
    """Build an immutable MarketContext populated across all requested timeframes."""
    if timeframes is None:
        target_tfs: Sequence[Union[str, Timeframe]] = tuple(TIMEFRAME_RULES.keys())
    else:
        target_tfs = timeframes

    bars_by_tf: dict[str, Sequence[MarketBar]] = {}
    for tf in target_tfs:
        tf_key = _normalize_timeframe_key(tf)
        bars_by_tf[tf_key] = resample_bars(daily_bars, tf_key)

    latest_ts: Optional[datetime] = None
    if as_of is not None:
        latest_ts = as_of
    elif daily_bars:
        # Determine latest timestamp from sorted daily bars
        latest_ts = max(b.timestamp for b in daily_bars)

    return MarketContext(
        symbol=symbol,
        exchange=exchange,
        bars_by_timeframe=bars_by_tf,
        as_of=latest_ts,
    )


class TimeframeEngine(ITimeframeEngine):
    """Authoritative engine coordinating multi-timeframe candle synthesis."""

    def resample(
        self,
        bars: Sequence[MarketBar],
        timeframe: Union[str, Timeframe],
    ) -> tuple[MarketBar, ...]:
        """Resample daily bars into the specified target timeframe."""
        return resample_bars(bars=bars, timeframe=timeframe)

    def build_context(
        self,
        symbol: str,
        exchange: str,
        daily_bars: Sequence[MarketBar],
        timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
        as_of: Optional[datetime] = None,
    ) -> MarketContext:
        """Construct an immutable MarketContext across requested timeframes."""
        return build_market_context(
            symbol=symbol,
            exchange=exchange,
            daily_bars=daily_bars,
            timeframes=timeframes,
            as_of=as_of,
        )

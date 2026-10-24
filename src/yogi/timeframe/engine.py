"""YOGI Timeframe Engine — Multi-Timeframe Candle Synthesis.

Authoritatively synthesizes higher-order trading timeframes (W, M, Q, H, Y)
from canonical daily MarketBar sequences using verified financial OHLCV aggregation.
"""

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from yogi.core.contracts.market_data import MarketBar, MarketContext, Timeframe
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.timeframe.cache import TimeframeCache

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


def _resample_calendar_half(df: pd.DataFrame, agg: dict[str, Any]) -> pd.DataFrame:
    """Resample daily OHLCV bars into Calendar Half-Years:
    - H1: Jan 1 to Jun 30 (labeled YYYY-06-30)
    - H2: Jul 1 to Dec 31 (labeled YYYY-12-31)
    """
    if df.empty:
        return df

    def _to_half_end(ts: Any) -> pd.Timestamp:
        pdt = pd.to_datetime(ts)
        return (
            pd.Timestamp(year=pdt.year, month=6, day=30)
            if pdt.month <= 6
            else pd.Timestamp(year=pdt.year, month=12, day=31)
        )

    half_ends = df.index.map(_to_half_end)
    res = df.groupby(half_ends).agg(agg).dropna(subset=["close"])
    return res.sort_index()


def resample_bars(
    bars: Sequence[MarketBar],
    timeframe: Union[str, Timeframe],
    half_year_policy: str = "prototype",
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
        half_year_policy: "prototype" (2QE boundaries ending Mar/Sep) or "calendar" (H1: Jun 30, H2: Dec 31).

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

    # Inspect volume values to optimize aggregation:
    # - If all values are None/NaN, volume column is omitted and result volumes remain None.
    # - If any values are missing (None or NaN), track valid volume counts (_vol_valid)
    #   so built-in Cython "sum" can be used while strictly preserving min_count=1 semantics
    #   (groups with only missing values yield None, not 0.0, and 0.0 is preserved).
    # - If all values are valid numeric floats, built-in Cython "sum" is used directly.
    has_volume = False
    has_missing_volume = False
    clean_volumes: list[float] = []

    for v in volumes:
        if v is None:
            has_missing_volume = True
            clean_volumes.append(float("nan"))
        else:
            vf = float(v)
            if vf != vf:  # math.isnan check
                has_missing_volume = True
                clean_volumes.append(vf)
            else:
                has_volume = True
                clean_volumes.append(vf)

    data: dict[str, Any] = {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
    }
    agg: dict[str, Any] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }

    if has_volume:
        data["volume"] = clean_volumes
        agg["volume"] = "sum"
        if has_missing_volume:
            data["_vol_valid"] = [0 if (v != v) else 1 for v in clean_volumes]
            agg["_vol_valid"] = "sum"

    df = pd.DataFrame(data, index=pd.DatetimeIndex(timestamps))

    # Resample and drop empty periods (no trading days in period)
    if tf_key == "H" and half_year_policy == "calendar":
        res = _resample_calendar_half(df, agg)
    else:
        rule = TIMEFRAME_RULES[tf_key]
        if rule is None:
            return tuple(clean_bars)
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
    res_vol_valid = (
        res["_vol_valid"].values if (has_volume and has_missing_volume) else None
    )

    result: list[MarketBar] = []
    n = len(res)
    for i in range(n):
        bar_ts = _to_naive_datetime(res_index[i])
        vol: Optional[float] = None
        if res_volumes is not None:
            if res_vol_valid is not None and res_vol_valid[i] == 0:
                vol = None
            else:
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


def _is_normalized_daily_tuple(bars: Sequence[MarketBar]) -> bool:
    """Determine whether a sequence of MarketBar objects is already an immutable, strictly chronological tuple with no duplicates."""
    if not isinstance(bars, tuple):
        return False
    n = len(bars)
    if n <= 1:
        return True
    if bars[0].timestamp >= bars[-1].timestamp:
        return False
    it = iter(bars)
    prev_ts = next(it).timestamp
    for b in it:
        curr_ts = b.timestamp
        if prev_ts >= curr_ts:
            return False
        prev_ts = curr_ts
    return True


def _resolve_daily_bars(
    bars: Sequence[MarketBar],
    half_year_policy: str = "prototype",
) -> tuple[MarketBar, ...]:
    """Resolve canonical daily MarketBar sequence directly when proven safe, falling back to resample_bars."""
    if not bars:
        return ()
    if _is_normalized_daily_tuple(bars):
        return bars  # type: ignore[return-value]
    return resample_bars(bars, "D", half_year_policy=half_year_policy)


def build_market_context(
    symbol: str,
    exchange: str,
    daily_bars: Sequence[MarketBar],
    timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
    as_of: Optional[datetime] = None,
    half_year_policy: str = "prototype",
) -> MarketContext:
    """Build an immutable MarketContext populated across all requested timeframes."""
    if timeframes is None:
        target_tfs: Sequence[Union[str, Timeframe]] = tuple(TIMEFRAME_RULES.keys())
    else:
        target_tfs = timeframes

    bars_by_tf: dict[str, Sequence[MarketBar]] = {}
    for tf in target_tfs:
        tf_key = _normalize_timeframe_key(tf)
        if tf_key == "D":
            bars_by_tf[tf_key] = _resolve_daily_bars(
                daily_bars, half_year_policy=half_year_policy
            )
        else:
            bars_by_tf[tf_key] = resample_bars(
                daily_bars, tf_key, half_year_policy=half_year_policy
            )

    latest_ts: Optional[datetime] = None
    if as_of is not None:
        latest_ts = as_of
    elif daily_bars:
        d_bars = bars_by_tf.get("D")
        if d_bars:
            latest_ts = d_bars[-1].timestamp
        else:
            latest_ts = max(b.timestamp for b in daily_bars)

    return MarketContext(
        symbol=symbol,
        exchange=exchange,
        bars_by_timeframe=bars_by_tf,
        as_of=latest_ts,
    )


class TimeframeEngine(ITimeframeEngine):
    """Authoritative engine coordinating multi-timeframe candle synthesis."""

    def __init__(
        self,
        half_year_policy: str = "prototype",
        cache: Optional[TimeframeCache] = None,
        enable_cache: bool = True,
        max_cache_entries: int = 10000,
    ) -> None:
        self.half_year_policy = half_year_policy
        if cache is not None:
            self._cache: Optional[TimeframeCache] = cache
        elif enable_cache:
            self._cache = TimeframeCache(max_entries=max_cache_entries)
        else:
            self._cache = None

    @property
    def cache(self) -> Optional[TimeframeCache]:
        """Return the underlying TimeframeCache instance if caching is enabled."""
        return self._cache

    @property
    def cache_stats(self) -> Optional[dict[str, Any]]:
        """Return operational cache metrics if caching is enabled."""
        return self._cache.stats() if self._cache is not None else None

    def invalidate_cache(
        self,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> int:
        """Invalidate cached derived timeframe data for a symbol, exchange, or all entries."""
        if self._cache is not None:
            return self._cache.invalidate(symbol=symbol, exchange=exchange)
        return 0

    def clear_cache(self) -> None:
        """Clear all cached derived timeframe data."""
        if self._cache is not None:
            self._cache.clear()

    def resample(
        self,
        bars: Sequence[MarketBar],
        timeframe: Union[str, Timeframe],
        half_year_policy: Optional[str] = None,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> tuple[MarketBar, ...]:
        """Resample daily bars into the specified target timeframe."""
        policy = half_year_policy if half_year_policy is not None else self.half_year_policy
        tf_key = _normalize_timeframe_key(timeframe)
        ex = (exchange or "NSE").strip().upper()
        sym = (symbol or "").strip().upper()

        if tf_key == "D":
            return _resolve_daily_bars(bars, half_year_policy=policy)

        if self._cache is not None and sym and bars:
            cached = self._cache.get(ex, sym, tf_key, bars, half_year_policy=policy)
            if cached is not None:
                return cached

        resampled = resample_bars(bars=bars, timeframe=tf_key, half_year_policy=policy)

        if self._cache is not None and sym and bars:
            self._cache.put(ex, sym, tf_key, bars, resampled, half_year_policy=policy)

        return resampled

    def build_context(
        self,
        symbol: str,
        exchange: str,
        daily_bars: Sequence[MarketBar],
        timeframes: Optional[Sequence[Union[str, Timeframe]]] = None,
        as_of: Optional[datetime] = None,
        half_year_policy: Optional[str] = None,
    ) -> MarketContext:
        """Construct an immutable MarketContext across requested timeframes with caching."""
        policy = half_year_policy if half_year_policy is not None else self.half_year_policy
        if timeframes is None:
            target_tfs: Sequence[Union[str, Timeframe]] = tuple(TIMEFRAME_RULES.keys())
        else:
            target_tfs = timeframes

        ex = (exchange or "NSE").strip().upper()
        sym = (symbol or "").strip().upper()

        bars_by_tf: dict[str, Sequence[MarketBar]] = {}
        for tf in target_tfs:
            tf_key = _normalize_timeframe_key(tf)
            if tf_key == "D":
                # Daily timeframe returns canonical sorted/deduplicated bars directly, bypassing resample_bars when safe
                bars_by_tf[tf_key] = _resolve_daily_bars(daily_bars, half_year_policy=policy)
                continue

            if self._cache is not None and daily_bars:
                cached = self._cache.get(ex, sym, tf_key, daily_bars, half_year_policy=policy)
                if cached is not None:
                    bars_by_tf[tf_key] = cached
                    continue

            resampled = resample_bars(daily_bars, tf_key, half_year_policy=policy)
            if self._cache is not None and daily_bars:
                self._cache.put(ex, sym, tf_key, daily_bars, resampled, half_year_policy=policy)
            bars_by_tf[tf_key] = resampled

        latest_ts: Optional[datetime] = None
        if as_of is not None:
            latest_ts = as_of
        elif daily_bars:
            d_bars = bars_by_tf.get("D")
            if d_bars:
                latest_ts = d_bars[-1].timestamp
            else:
                latest_ts = max(b.timestamp for b in daily_bars)

        return MarketContext(
            symbol=symbol,
            exchange=exchange,
            bars_by_timeframe=bars_by_tf,
            as_of=latest_ts,
        )

"""YOGI Timeframe Cache — In-Memory Bounded LRU Cache for Derived Timeframe Bars.

Authoritatively caches synthesized higher-order MarketBar sequences (W, M, Q, H, Y)
and deduplicated daily bars to eliminate redundant resampling passes during dataset
construction, screening, and chart operations.

Design Philosophy:
- Stable Core: Keeps timeframe caching strictly within src/yogi/timeframe/ without
  coupling storage to calculation or calculation to storage.
- Contract-First: Preserves ITimeframeEngine and MarketContext contracts completely.
- Bounded Memory: Enforces an explicit LRU eviction limit to prevent unbounded memory growth.
- Revision Safety: Uses a fast, deterministic fingerprint detecting bar count changes,
  appended bars, real-time candle price revisions, date shifts, and historical revisions.
"""

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import logging
import math
import struct
import threading
import time
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from yogi.core.contracts.market_data import MarketBar, Timeframe

logger = logging.getLogger(__name__)

# Fixed 8-byte byte sentinels for non-finite and missing values
_NONE_BYTES = b"__NONE__"
_NAN_BYTES = b"__NAN___"
_POS_INF_BYTES = b"+__INF__"
_NEG_INF_BYTES = b"-__INF__"
_ZERO_BYTES = b"\x00\x00\x00\x00\x00\x00\x00\x00"


def _encode_numeric(v: Any) -> bytes:
    """Deterministically encode a numeric bar field into a fixed 8-byte representation.

    Distinguishes:
    - None (missing value, e.g. volume=None): _NONE_BYTES
    - NaN (IEEE 754 NaN): _NAN_BYTES
    - Positive infinity: _POS_INF_BYTES
    - Negative infinity: _NEG_INF_BYTES
    - +0.0 and -0.0: normalized to _ZERO_BYTES
    - Finite floats: exact IEEE 754 big-endian 8-byte packing
    """
    if v is None:
        return _NONE_BYTES
    if pd.isna(v):
        return _NAN_BYTES
    try:
        f = float(v)
    except (ValueError, TypeError):
        return b"__ERR___"
    if math.isnan(f):
        return _NAN_BYTES
    if math.isinf(f):
        return _POS_INF_BYTES if f > 0 else _NEG_INF_BYTES
    if f == 0.0:
        return _ZERO_BYTES
    return struct.pack(">d", f)


def normalize_timeframe_key(tf: Union[str, Timeframe]) -> str:
    """Normalize a timeframe identifier to its canonical uppercase string key."""
    if isinstance(tf, Timeframe):
        return tf.value
    return str(tf).strip().upper()


def compute_bars_fingerprint(bars: Sequence[MarketBar]) -> tuple[int, str]:
    """Compute a deterministic, complete revision fingerprint of a MarketBar sequence.

    Encodes every source-bar field that affects derived timeframe synthesis:
    - timestamp (with microsecond precision, safe on Windows and pre-epoch dates)
    - open, high, low, close
    - volume (distinguishing None from NaN from finite values)

    Uses SHA-256 to ensure non-lossy revision detection and stable comparison
    across non-finite (NaN, +/-Inf) and missing values.
    """
    if not bars:
        return (0, "")
    hasher = hashlib.sha256()
    for b in bars:
        ts = b.timestamp
        if ts is None:
            ts_bytes = b"__NONE__;"
        elif hasattr(ts, "isoformat"):
            ts_bytes = ts.isoformat().encode("ascii") + b";"
        else:
            ts_bytes = str(ts).encode("utf-8") + b";"
        hasher.update(ts_bytes)
        hasher.update(_encode_numeric(b.open))
        hasher.update(_encode_numeric(b.high))
        hasher.update(_encode_numeric(b.low))
        hasher.update(_encode_numeric(b.close))
        hasher.update(_encode_numeric(b.volume))
    return (len(bars), hasher.hexdigest())


@dataclass
class TimeframeCacheEntry:
    """Entry holding cached synthesized MarketBar sequence and source version metadata."""

    bars: tuple[MarketBar, ...]
    source_version: tuple[Any, ...]
    source_obj_id: int
    created_at: float
    hits: int = 0
    source_ref: Optional[tuple[MarketBar, ...]] = None


class TimeframeCache:
    """Thread-safe, bounded LRU cache for multi-timeframe synthesized bars.

    Cache Key: (exchange, symbol, timeframe, half_year_policy)
    """

    def __init__(self, max_entries: int = 10000) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be positive integer >= 1 (got {max_entries})")
        self.max_entries = max_entries
        self._cache: OrderedDict[tuple[str, str, str, str], TimeframeCacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0
        self._invalidations: int = 0

    def _make_key(
        self,
        exchange: str,
        symbol: str,
        timeframe: Union[str, Timeframe],
        half_year_policy: Optional[str] = None,
    ) -> tuple[str, str, str, str]:
        ex = (exchange or "NSE").strip().upper()
        sym = (symbol or "").strip().upper()
        tf = normalize_timeframe_key(timeframe)
        policy = (half_year_policy or "prototype").strip().lower()
        return ex, sym, tf, policy

    def get(
        self,
        exchange: str,
        symbol: str,
        timeframe: Union[str, Timeframe],
        daily_bars: Sequence[MarketBar],
        half_year_policy: Optional[str] = None,
    ) -> Optional[tuple[MarketBar, ...]]:
        """Retrieve cached synthesized bars if entry exists and source bars match current revision."""
        if not daily_bars:
            return None

        key = self._make_key(exchange, symbol, timeframe, half_year_policy)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            # Fast path 1: Provably immutable sequence identity match
            # Only valid when daily_bars is a tuple of immutable MarketBar objects AND the entry
            # holds an active reference to that exact tuple instance (preventing memory address reuse).
            is_immutable = isinstance(daily_bars, tuple)
            if is_immutable and (entry.source_ref is daily_bars or (entry.source_ref is None and id(daily_bars) == entry.source_obj_id)):
                if entry.source_ref is None:
                    entry.source_ref = daily_bars
                self._cache.move_to_end(key)
                entry.hits += 1
                self._hits += 1
                return entry.bars

            # Safe path 2: Check deterministic version fingerprint
            current_fp = compute_bars_fingerprint(daily_bars)
            if current_fp == entry.source_version:
                # Valid cache hit across different object instances or mutable sequences
                if is_immutable:
                    entry.source_ref = daily_bars
                    entry.source_obj_id = id(daily_bars)
                self._cache.move_to_end(key)
                entry.hits += 1
                self._hits += 1
                return entry.bars

            # Source data changed! Discard stale entry
            del self._cache[key]
            self._invalidations += 1
            self._misses += 1
            return None

    def put(
        self,
        exchange: str,
        symbol: str,
        timeframe: Union[str, Timeframe],
        daily_bars: Sequence[MarketBar],
        derived_bars: Sequence[MarketBar],
        half_year_policy: Optional[str] = None,
    ) -> None:
        """Store synthesized bars in cache with LRU eviction."""
        if not daily_bars or derived_bars is None:
            return

        key = self._make_key(exchange, symbol, timeframe, half_year_policy)
        fp = compute_bars_fingerprint(daily_bars)
        is_immutable = isinstance(daily_bars, tuple)
        entry = TimeframeCacheEntry(
            bars=tuple(derived_bars),
            source_version=fp,
            source_obj_id=id(daily_bars) if is_immutable else 0,
            source_ref=daily_bars if is_immutable else None,
            created_at=time.time(),
        )

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = entry

            # Enforce LRU capacity limit
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
                self._evictions += 1

    def invalidate(
        self,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> int:
        """Invalidate cached entries for a symbol, an exchange, or all entries."""
        sym_norm = symbol.strip().upper() if symbol else None
        ex_norm = exchange.strip().upper() if exchange else None

        with self._lock:
            if sym_norm is None and ex_norm is None:
                count = len(self._cache)
                self._cache.clear()
                self._invalidations += count
                return count

            keys_to_remove = [
                k
                for k in self._cache
                if (sym_norm is None or k[1] == sym_norm)
                and (ex_norm is None or k[0] == ex_norm)
            ]
            for k in keys_to_remove:
                del self._cache[k]
            count = len(keys_to_remove)
            self._invalidations += count
            return count

    def clear(self) -> None:
        """Clear all entries and reset stats."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._invalidations = 0

    def stats(self) -> dict[str, Any]:
        """Return operational cache metrics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_ratio = (self._hits / total_requests) if total_requests > 0 else 0.0
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "invalidations": self._invalidations,
                "hit_ratio": hit_ratio,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, key: Any) -> bool:
        with self._lock:
            return key in self._cache

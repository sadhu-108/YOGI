"""Persistent Local Cache — Dataset & Historical Market Bars Storage.

Implements high-performance local disk-backed persistence for:
1. Computed feature datasets (`data/cache/dataset_{exchange}_{provider}.pkl`)
2. Historical daily market bars (`data/cache/bars_{exchange}_{provider}.pkl`)

Provides fast startup (<100ms), schema/policy validation, and atomic updates.
Follows YOGI architecture: Replaceable Modules with strict validation.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import pickle
import re
import threading
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from yogi.core.contracts.filter import ScreeningCancelledError
from yogi.core.contracts.market_data import MarketBar
from yogi.storage.paths import get_cache_dir

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
DEFAULT_CACHE_DIR = get_cache_dir()


class IngestionCohort(str, Enum):
    """Classification cohort for market data ingestion planning."""
    UP_TO_DATE = "UP_TO_DATE"
    INCREMENTAL_UPDATE = "INCREMENTAL_UPDATE"
    FULL_BACKFILL = "FULL_BACKFILL"


@dataclass(frozen=True)
class SymbolIngestionPlan:
    """Ingestion recommendation and date boundaries for a single symbol."""
    symbol: str
    cohort: IngestionCohort
    cached_bars_count: int
    latest_bar_date: Optional[date] = None
    start_date: Optional[date] = None
    reason: str = ""

    @property
    def start_date_str(self) -> Optional[str]:
        return self.start_date.strftime("%Y-%m-%d") if self.start_date else None


@dataclass(frozen=True)
class IngestionPlan:
    """Deterministic, structured ingestion plan across a requested universe."""
    target_date: date
    expected_fresh_date: date
    overlap_days: int
    min_bars: int
    plans: Mapping[str, SymbolIngestionPlan]
    up_to_date: tuple[str, ...]
    incremental: tuple[str, ...]
    full_backfill: tuple[str, ...]
    start_dates: Mapping[str, date]

    def for_symbol(self, symbol: str) -> Optional[SymbolIngestionPlan]:
        return self.plans.get(str(symbol).strip().upper())


class DatasetCache:
    """Thread-safe persistent cache for materialized YOGI feature datasets."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = get_cache_dir(cache_dir)
        self._lock = threading.Lock()

    def _cache_path(self, exchange: str, provider: str) -> Path:
        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()
        return self.cache_dir / f"dataset_{ex}_{pv}.pkl"

    def save(
        self,
        dataset: Mapping[str, Mapping[str, Any]],
        exchange: str = "NSE",
        provider: str = "yfinance",
        half_year_policy: str = "prototype",
        historical_years: int = 10,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Optional[Path]:
        """Atomically persist a computed dataset to disk with schema and policy envelope."""
        if not dataset:
            logger.warning("DatasetCache.save: Refusing to cache empty dataset.")
            return None

        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()

        # Do not persist ephemeral demo data to live cache
        if pv == "demo":
            logger.debug("DatasetCache.save: Skipping persistence for demo provider.")
            return None

        with self._lock:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                target_path = self._cache_path(ex, pv)
                temp_path = self.cache_dir / f"{target_path.name}.tmp"

                payload: dict[str, Any] = {
                    "version": CACHE_VERSION,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "exchange": ex,
                    "provider": pv,
                    "half_year_policy": str(half_year_policy),
                    "historical_years": int(historical_years),
                    "symbols_count": len(dataset),
                    "metadata": dict(metadata) if metadata else {},
                    "dataset": {str(k): dict(v) for k, v in dataset.items()},
                }

                with open(temp_path, "wb") as fh:
                    pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    fh.flush()
                    os.fsync(fh.fileno())

                os.replace(temp_path, target_path)
                logger.info(
                    "DatasetCache: Persisted %d symbols to '%s' (policy: %s)",
                    len(dataset),
                    target_path,
                    half_year_policy,
                )
                return target_path
            except Exception as exc:
                logger.error("DatasetCache: Failed to persist dataset: %s", exc)
                return None

    def validate(
        self,
        payload: Any,
        exchange: str = "NSE",
        provider: str = "yfinance",
        half_year_policy: Optional[str] = None,
    ) -> bool:
        """Validate payload structure, version compatibility, and policy consistency."""
        if not isinstance(payload, dict):
            return False

        if payload.get("version") != CACHE_VERSION:
            return False

        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()

        if payload.get("exchange") != ex:
            return False

        if payload.get("provider") != pv:
            return False

        if half_year_policy is not None and payload.get("half_year_policy") != str(half_year_policy):
            logger.info(
                "DatasetCache: Policy mismatch (cached: '%s', requested: '%s'). Cache invalid.",
                payload.get("half_year_policy"),
                half_year_policy,
            )
            return False

        dataset = payload.get("dataset")
        if not isinstance(dataset, dict) or len(dataset) == 0:
            return False

        # Validate sample record integrity
        sample_sym, sample_row = next(iter(dataset.items()))
        if not isinstance(sample_row, dict) or "symbol" not in sample_row:
            return False

        return True

    def load(
        self,
        exchange: str = "NSE",
        provider: str = "yfinance",
        half_year_policy: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Load and validate persisted dataset. Returns None if invalid or missing."""
        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()

        if pv == "demo":
            return None

        target_path = self._cache_path(ex, pv)
        if not target_path.is_file():
            return None

        with self._lock:
            try:
                with open(target_path, "rb") as fh:
                    payload = pickle.load(fh)

                if not self.validate(payload, exchange=ex, provider=pv, half_year_policy=half_year_policy):
                    logger.warning("DatasetCache: Cache file '%s' failed validation.", target_path)
                    return None

                logger.info(
                    "DatasetCache: Loaded %d symbols from '%s' (saved: %s, policy: %s)",
                    payload["symbols_count"],
                    target_path,
                    payload.get("saved_at"),
                    payload.get("half_year_policy"),
                )
                return payload
            except Exception as exc:
                logger.warning("DatasetCache: Could not load cache from '%s': %s", target_path, exc)
                return None

    def clear(self, exchange: str = "NSE", provider: str = "yfinance") -> bool:
        """Remove cached dataset file if present."""
        target_path = self._cache_path(exchange, provider)
        with self._lock:
            try:
                if target_path.is_file():
                    target_path.unlink()
                    logger.info("DatasetCache: Cleared '%s'", target_path)
                return True
            except Exception as exc:
                logger.warning("DatasetCache: Failed to clear '%s': %s", target_path, exc)
                return False


def _normalize_bar_ts(ts: Any) -> Any:
    """Normalize a timestamp to timezone-naive datetime for uniform comparison and sorting."""
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            return ts.astimezone(timezone.utc).replace(tzinfo=None)
        return ts
    if hasattr(ts, "year") and hasattr(ts, "month") and hasattr(ts, "day"):
        return datetime(ts.year, ts.month, ts.day)
    return ts


def merge_market_bars(
    prior_bars: Optional[Sequence[MarketBar]],
    new_bars: Optional[Sequence[MarketBar]],
) -> tuple[MarketBar, ...]:
    """Deterministically merge and deduplicate two MarketBar sequences by timestamp.

    Overlapping timestamps in new_bars replace matching timestamps in prior_bars.
    Resulting sequence is strictly sorted in ascending chronological order.
    """
    merged_by_ts: dict[Any, MarketBar] = {}
    if isinstance(prior_bars, (list, tuple)):
        for b in prior_bars:
            if hasattr(b, "timestamp") and b.timestamp is not None:
                merged_by_ts[_normalize_bar_ts(b.timestamp)] = b

    if isinstance(new_bars, (list, tuple)):
        for b in new_bars:
            if hasattr(b, "timestamp") and b.timestamp is not None:
                merged_by_ts[_normalize_bar_ts(b.timestamp)] = b

    if not merged_by_ts:
        return ()

    return tuple(
        sorted(merged_by_ts.values(), key=lambda b: _normalize_bar_ts(b.timestamp))
    )


def _safe_symbol_filename(symbol: str) -> str:
    """Deterministically map a market symbol to a safe, valid filesystem filename.

    Preserves uppercase symbol name for standard symbols (e.g. 'RELIANCE' -> 'RELIANCE.pkl').
    Replaces filesystem-reserved characters (: * ? " < > | / \\) safely.
    """
    clean = str(symbol).strip().upper()
    return re.sub(r'[\\/:*?"<>|]', lambda m: f"%{ord(m.group(0)):02X}", clean)



def _safe_clean_staging_dir(staging_dir: Path) -> None:
    """Safely remove a temporary staging directory and its files."""
    if not staging_dir.exists():
        return
    try:
        if staging_dir.is_dir():
            for f in staging_dir.iterdir():
                try:
                    if f.is_file():
                        f.unlink()
                except Exception:
                    pass
            try:
                staging_dir.rmdir()
            except Exception:
                pass
    except Exception:
        pass


class MarketBarsCache:
    """Thread-safe persistent cache for historical daily MarketBar sequences.

    Supports both symbol-partitioned storage (fast O(1) single-symbol chart retrieval)
    and consolidated monolithic files (legacy backward compatibility).
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = get_cache_dir(cache_dir)
        self._write_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._lock = self._write_lock  # Backward compatibility alias
        # Namespace key: (ex, pv) -> Mapping[str, tuple[MarketBar, ...]]
        self._snapshots: dict[tuple[str, str], Mapping[str, tuple[MarketBar, ...]]] = {}
        # Symbol snapshot cache: (ex, pv, sym) -> tuple[MarketBar, ...]
        self._symbol_snapshots: dict[tuple[str, str, str], tuple[MarketBar, ...]] = {}
        self._uncertain_namespaces: set[tuple[str, str]] = set()

    def _ns_key(self, exchange: str, provider: str) -> tuple[str, str]:
        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()
        return ex, pv

    def _bars_path(self, exchange: str, provider: str) -> Path:
        ex, pv = self._ns_key(exchange, provider)
        return self.cache_dir / f"bars_{ex}_{pv}.pkl"

    def _partition_dir(self, exchange: str, provider: str) -> Path:
        ex, pv = self._ns_key(exchange, provider)
        return self.cache_dir / "bars" / f"{ex}_{pv}"

    def _partition_path(self, exchange: str, provider: str, symbol: str) -> Path:
        pdir = self._partition_dir(exchange, provider)
        safe_name = _safe_symbol_filename(symbol)
        return pdir / f"{safe_name}.pkl"

    def save_bars(
        self,
        bars_map: Mapping[str, Sequence[MarketBar]],
        exchange: str = "NSE",
        provider: str = "yfinance",
    ) -> Optional[Path]:
        """Atomically merge and persist daily market bars across symbols.

        Writes symbol-partitioned files and updates the consolidated monolithic
        cache file for full backward compatibility.
        """
        if not bars_map:
            return None

        ex, pv = self._ns_key(exchange, provider)
        ns_key = (ex, pv)

        if pv == "demo":
            return None

        with self._write_lock:
            temp_path: Optional[Path] = None
            written_partition_tmps: list[Path] = []
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                part_dir = self._partition_dir(ex, pv)
                part_dir.mkdir(parents=True, exist_ok=True)
                target_path = self._bars_path(ex, pv)
                temp_path = self.cache_dir / f"{target_path.name}.tmp"

                # 1. Obtain baseline store for full universe
                with self._snapshot_lock:
                    cached_snapshot = self._snapshots.get(ns_key)

                existing_bars: dict[str, Sequence[MarketBar]] = {}
                if cached_snapshot is not None:
                    existing_bars = dict(cached_snapshot)
                else:
                    if target_path.is_file():
                        try:
                            with open(target_path, "rb") as fh:
                                data = pickle.load(fh)
                                if isinstance(data, dict):
                                    for sym, bars in data.items():
                                        if isinstance(bars, (list, tuple)) and len(bars) > 0 and isinstance(bars[0], MarketBar):
                                            existing_bars[str(sym).strip().upper()] = tuple(bars)
                        except Exception:
                            existing_bars = {}
                    if part_dir.is_dir():
                        for pfile in part_dir.glob("*.pkl"):
                            try:
                                with open(pfile, "rb") as pfh:
                                    pdata = pickle.load(pfh)
                                if isinstance(pdata, (list, tuple)) and len(pdata) > 0 and isinstance(pdata[0], MarketBar):
                                    existing_bars[pfile.stem.strip().upper()] = tuple(pdata)
                            except Exception:
                                pass

                # 2. Merge incoming bars for each symbol
                updated_partitions: dict[str, tuple[MarketBar, ...]] = {}
                for sym, bars in bars_map.items():
                    if not bars:
                        continue
                    sym_key = str(sym).strip().upper()
                    if not sym_key:
                        continue

                    prior_bars = existing_bars.pop(sym_key, None)
                    if prior_bars is None and sym_key.lower() in existing_bars:
                        prior_bars = existing_bars.pop(sym_key.lower(), None)

                    merged = merge_market_bars(prior_bars, bars)
                    if merged:
                        existing_bars[sym_key] = merged
                        updated_partitions[sym_key] = merged

                # 3. Store immutable tuples in resident store
                working_snapshot: dict[str, tuple[MarketBar, ...]] = {
                    k: tuple(v) for k, v in existing_bars.items()
                }

                # 4. Atomically write each symbol partition file
                for sym_key, pbars in updated_partitions.items():
                    p_target = self._partition_path(ex, pv, sym_key)
                    p_tmp = part_dir / f"{p_target.name}.tmp"
                    written_partition_tmps.append(p_tmp)
                    with open(p_tmp, "wb") as pfh:
                        pickle.dump(pbars, pfh, protocol=pickle.HIGHEST_PROTOCOL)
                        pfh.flush()
                        os.fsync(pfh.fileno())
                    os.replace(p_tmp, p_target)

                # 5. Atomically write consolidated monolithic file
                with open(temp_path, "wb") as fh:
                    pickle.dump(working_snapshot, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    fh.flush()
                    os.fsync(fh.fileno())

                os.replace(temp_path, target_path)

                # 6. Post-commit publication under _snapshot_lock
                with self._snapshot_lock:
                    self._snapshots[ns_key] = working_snapshot
                    for sym_key, pbars in updated_partitions.items():
                        self._symbol_snapshots[(ex, pv, sym_key)] = pbars
                    self._uncertain_namespaces.discard(ns_key)

                logger.info(
                    "MarketBarsCache: Persisted bars for %d symbols to '%s' and %d partitions in '%s'",
                    len(working_snapshot),
                    target_path,
                    len(updated_partitions),
                    part_dir,
                )
                return target_path
            except Exception as exc:
                logger.error("MarketBarsCache: Failed to persist bars: %s", exc)
                # Cleanup monolithic temp file
                if temp_path and temp_path.is_file():
                    try:
                        temp_path.unlink()
                    except Exception as clean_exc:
                        logger.warning(
                            "MarketBarsCache: Failed to clean temporary file '%s': %s",
                            temp_path,
                            clean_exc,
                        )
                # Cleanup partition temp files
                for p_tmp in written_partition_tmps:
                    if p_tmp.is_file():
                        try:
                            p_tmp.unlink()
                        except Exception as p_clean_exc:
                            logger.warning(
                                "MarketBarsCache: Failed to clean temporary file '%s': %s",
                                p_tmp,
                                p_clean_exc,
                            )
                return None

    def load_bars(
        self,
        exchange: str = "NSE",
        provider: str = "yfinance",
    ) -> dict[str, Sequence[MarketBar]]:
        """Load all cached MarketBar sequences for the given exchange/provider.

        Uses resident in-memory snapshot for sub-millisecond warm reads.
        Loads from symbol partitions if present, falling back to legacy monolithic file.
        """
        ex, pv = self._ns_key(exchange, provider)
        ns_key = (ex, pv)

        if pv == "demo":
            return {}

        # 1. Warm hit check: acquire _snapshot_lock briefly, copy reference, release
        with self._snapshot_lock:
            if ns_key in self._uncertain_namespaces:
                return {}
            snapshot = self._snapshots.get(ns_key)

        if snapshot is not None:
            return dict(snapshot)

        # 2. Cold miss: acquire _write_lock to serialize disk load
        with self._write_lock:
            # Double-check under _snapshot_lock
            with self._snapshot_lock:
                if ns_key in self._uncertain_namespaces:
                    return {}
                snapshot = self._snapshots.get(ns_key)

            if snapshot is not None:
                return dict(snapshot)

            valid_store: dict[str, tuple[MarketBar, ...]] = {}
            part_dir = self._partition_dir(ex, pv)
            target_path = self._bars_path(ex, pv)

            target_mtime = 0.0
            # 1. Baseline: Load legacy monolithic file if present
            if target_path.is_file():
                try:
                    target_mtime = target_path.stat().st_mtime
                    with open(target_path, "rb") as fh:
                        data = pickle.load(fh)
                    if isinstance(data, dict):
                        for sym, bars in data.items():
                            if isinstance(bars, (list, tuple)) and len(bars) > 0 and isinstance(bars[0], MarketBar):
                                sym_key = str(sym).strip().upper()
                                valid_store[sym_key] = tuple(bars)
                except Exception as exc:
                    logger.warning("MarketBarsCache: Failed to load legacy bars from '%s': %s", target_path, exc)

            # 2. Overlay: Symbol partitions take precedence if not in legacy or if newer
            if part_dir.is_dir():
                for pfile in part_dir.glob("*.pkl"):
                    sym_key = pfile.stem.strip().upper()
                    try:
                        p_mtime = pfile.stat().st_mtime
                    except Exception:
                        p_mtime = 0.0

                    if sym_key not in valid_store or p_mtime > target_mtime:
                        try:
                            with open(pfile, "rb") as pfh:
                                pdata = pickle.load(pfh)
                            if isinstance(pdata, (list, tuple)) and len(pdata) > 0 and isinstance(pdata[0], MarketBar):
                                valid_store[sym_key] = tuple(pdata)
                        except Exception as p_exc:
                            logger.warning("MarketBarsCache: Failed reading partition '%s': %s", pfile, p_exc)

            if not valid_store and not target_path.is_file() and not part_dir.is_dir():
                return {}

            with self._snapshot_lock:
                self._snapshots[ns_key] = valid_store
                for sym, bars in valid_store.items():
                    self._symbol_snapshots[(ex, pv, sym)] = bars

            return dict(valid_store)

    def get_bars_for_symbols(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        provider: str = "yfinance",
        min_bars: int = 60,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[dict[str, Sequence[MarketBar]], list[str]]:
        """Partition requested symbols into usable cached bars and symbols needing download.

        Loads requested symbols from partitioned symbol storage without deserializing
        unrequested symbols or the full universe.
        """
        ex, pv = self._ns_key(exchange, provider)
        ns_key = (ex, pv)

        if pv == "demo":
            return {}, [str(s).strip().upper() for s in symbols if str(s).strip()]

        found: dict[str, Sequence[MarketBar]] = {}
        missing: list[str] = []

        # Deduplicate and normalize requested symbols preserving order
        clean_symbols: list[str] = []
        seen = set()
        for s in symbols:
            c = str(s).strip().upper()
            if c and c not in seen:
                seen.add(c)
                clean_symbols.append(c)

        total_symbols = len(clean_symbols)
        for idx, sym in enumerate(clean_symbols):
            if cancel_check is not None and (idx % 20 == 0 or idx == total_symbols - 1):
                if cancel_check():
                    raise ScreeningCancelledError("Screening cancelled during bar retrieval.")

            if progress_callback is not None and (idx % 25 == 0 or idx == total_symbols - 1):
                progress_callback(idx + 1, total_symbols)

            # 1. Warm in-memory check
            with self._snapshot_lock:
                if ns_key in self._uncertain_namespaces:
                    missing.append(sym)
                    continue
                bars = self._symbol_snapshots.get((ex, pv, sym))
                if bars is None:
                    universe_snap = self._snapshots.get(ns_key)
                    if universe_snap is not None:
                        bars = universe_snap.get(sym)

            if bars is not None:
                if len(bars) >= min_bars:
                    found[sym] = bars
                else:
                    missing.append(sym)
                continue

            # 2. Cold check for this specific symbol's partition file
            part_path = self._partition_path(ex, pv, sym)
            if part_path.is_file():
                try:
                    with open(part_path, "rb") as pfh:
                        pdata = pickle.load(pfh)
                    if isinstance(pdata, (list, tuple)) and len(pdata) > 0 and isinstance(pdata[0], MarketBar):
                        bars_tuple = tuple(pdata)
                        with self._snapshot_lock:
                            self._symbol_snapshots[(ex, pv, sym)] = bars_tuple
                        if len(bars_tuple) >= min_bars:
                            found[sym] = bars_tuple
                        else:
                            missing.append(sym)
                    else:
                        missing.append(sym)
                except Exception as exc:
                    logger.warning("MarketBarsCache: Failed to load partition for '%s': %s", sym, exc)
                    missing.append(sym)
                continue

            # 3. Partition absent: check legacy monolithic cache
            legacy_path = self._bars_path(ex, pv)
            if legacy_path.is_file():
                with self._snapshot_lock:
                    if ns_key in self._uncertain_namespaces:
                        missing.append(sym)
                        continue
                    universe_snap = self._snapshots.get(ns_key)

                if universe_snap is None:
                    logger.warning(
                        "MarketBarsCache: Partition for '%s' absent. Falling back to legacy monolithic cache '%s' (expensive whole-universe deserialization).",
                        sym,
                        legacy_path,
                    )
                    all_bars = self.load_bars(exchange=exchange, provider=provider)
                else:
                    all_bars = universe_snap

                legacy_bars = all_bars.get(sym)
                if legacy_bars and len(legacy_bars) >= min_bars:
                    found[sym] = legacy_bars
                    with self._snapshot_lock:
                        self._symbol_snapshots[(ex, pv, sym)] = legacy_bars
                else:
                    missing.append(sym)
                continue

            # 4. Neither partition nor legacy exists
            missing.append(sym)

        return found, missing

    def clear(self, exchange: str = "NSE", provider: str = "yfinance") -> bool:
        """Remove cached bars file, delete symbol partitions, and evict in-memory snapshots."""
        ex, pv = self._ns_key(exchange, provider)
        ns_key = (ex, pv)
        target_path = self._bars_path(ex, pv)
        part_dir = self._partition_dir(ex, pv)

        with self._write_lock:
            try:
                # 1. Unlink monolithic file if present
                if target_path.is_file():
                    target_path.unlink()
                    logger.info("MarketBarsCache: Cleared '%s'", target_path)

                # 2. Delete partition directory and files if present
                if part_dir.is_dir():
                    for pfile in part_dir.glob("*.pkl"):
                        try:
                            pfile.unlink()
                        except Exception:
                            pass
                    for pfile_tmp in part_dir.glob("*.tmp"):
                        try:
                            pfile_tmp.unlink()
                        except Exception:
                            pass
                    try:
                        part_dir.rmdir()
                    except Exception:
                        pass

                # 3. Evict snapshots under _snapshot_lock
                with self._snapshot_lock:
                    self._snapshots.pop(ns_key, None)
                    keys_to_del = [k for k in self._symbol_snapshots if k[0] == ex and k[1] == pv]
                    for k in keys_to_del:
                        self._symbol_snapshots.pop(k, None)
                    self._uncertain_namespaces.discard(ns_key)
                return True
            except Exception as exc:
                logger.warning("MarketBarsCache: Failed to clear '%s': %s", target_path, exc)
                try:
                    file_still_exists = target_path.exists() or (part_dir.is_dir() and any(part_dir.glob("*.pkl")))
                except Exception:
                    file_still_exists = True

                with self._snapshot_lock:
                    if file_still_exists:
                        self._uncertain_namespaces.add(ns_key)
                        self._snapshots[ns_key] = {}
                        keys_to_del = [k for k in self._symbol_snapshots if k[0] == ex and k[1] == pv]
                        for k in keys_to_del:
                            self._symbol_snapshots.pop(k, None)
                    else:
                        self._snapshots.pop(ns_key, None)
                        keys_to_del = [k for k in self._symbol_snapshots if k[0] == ex and k[1] == pv]
                        for k in keys_to_del:
                            self._symbol_snapshots.pop(k, None)
                        self._uncertain_namespaces.discard(ns_key)
                return False

    def migrate_legacy_bars(
        self,
        exchange: str = "NSE",
        provider: str = "yfinance",
        overwrite: bool = False,
    ) -> int:
        """Explicit migration utility: partition legacy monolithic bars cache into symbol files.

        Uses staged migration with validation before atomic directory publication.
        Leaves original legacy monolithic cache file intact.
        Returns count of migrated symbols.
        """
        ex, pv = self._ns_key(exchange, provider)
        legacy_path = self._bars_path(ex, pv)
        if not legacy_path.is_file():
            return 0

        with self._write_lock:
            part_dir = self._partition_dir(ex, pv)
            staging_dir = part_dir.parent / f"{part_dir.name}.staging"

            try:
                # 1. Read legacy cache without modifying, deleting, or truncating it
                with open(legacy_path, "rb") as fh:
                    data = pickle.load(fh)
                if not isinstance(data, dict):
                    return 0

                # 2. Extract and validate expected symbols
                expected_map: dict[str, tuple[MarketBar, ...]] = {}
                for sym, bars in data.items():
                    if not isinstance(bars, (list, tuple)) or len(bars) == 0 or not isinstance(bars[0], MarketBar):
                        continue
                    sym_key = str(sym).strip().upper()
                    if not sym_key:
                        continue
                    expected_map[sym_key] = tuple(bars)

                if not expected_map:
                    return 0

                # 3. Check existing final destination
                if part_dir.exists():
                    if part_dir.is_dir():
                        # Validate whether existing destination is already a complete, valid publication
                        is_complete = True
                        for sym_key, exp_bars in expected_map.items():
                            p_path = part_dir / f"{_safe_symbol_filename(sym_key)}.pkl"
                            if not p_path.is_file():
                                is_complete = False
                                break
                            try:
                                with open(p_path, "rb") as pfh:
                                    pdata = pickle.load(pfh)
                                if not isinstance(pdata, (list, tuple)) or len(pdata) != len(exp_bars):
                                    is_complete = False
                                    break
                            except Exception:
                                is_complete = False
                                break

                        if is_complete:
                            logger.info(
                                "MarketBarsCache: Destination '%s' already contains complete valid publication (%d symbols). Skipping.",
                                part_dir,
                                len(expected_map),
                            )
                            return len(expected_map)

                    # Destination exists but is not a verified complete publication; refuse destructive alteration
                    logger.warning(
                        "MarketBarsCache: Destination '%s' already exists but is not a verified complete publication. Refusing destructive alteration.",
                        part_dir,
                    )
                    return 0

                # 4. Clean up any stale staging artifacts from prior attempts
                _safe_clean_staging_dir(staging_dir)
                staging_dir.mkdir(parents=True, exist_ok=True)

                # 5. Write each symbol partition into staging directory
                for sym_key, bars_tuple in expected_map.items():
                    safe_name = _safe_symbol_filename(sym_key)
                    p_target = staging_dir / f"{safe_name}.pkl"
                    p_tmp = staging_dir / f"{safe_name}.pkl.tmp"

                    with open(p_tmp, "wb") as pfh:
                        pickle.dump(bars_tuple, pfh, protocol=pickle.HIGHEST_PROTOCOL)
                        pfh.flush()
                        os.fsync(pfh.fileno())
                    os.replace(p_tmp, p_target)

                # 6. Validate staged output before publication
                # Check A: No temporary files remain
                if any(staging_dir.glob("*.tmp")):
                    raise RuntimeError("Staging directory contains leftover temporary files")

                # Check B: File count matches expected symbol count
                staged_files = list(staging_dir.glob("*.pkl"))
                if len(staged_files) != len(expected_map):
                    raise RuntimeError(
                        f"Staged file count ({len(staged_files)}) does not match expected symbol count ({len(expected_map)})"
                    )

                # Check C: Deep validation of each expected partition file
                for sym_key, exp_bars in expected_map.items():
                    safe_name = _safe_symbol_filename(sym_key)
                    p_path = staging_dir / f"{safe_name}.pkl"
                    if not p_path.is_file() or p_path.stat().st_size == 0:
                        raise RuntimeError(f"Missing or empty partition for '{sym_key}' at '{p_path}'")

                    with open(p_path, "rb") as pfh:
                        pdata = pickle.load(pfh)

                    if not isinstance(pdata, (list, tuple)) or len(pdata) != len(exp_bars):
                        raise RuntimeError(
                            f"Corrupted or mismatched bar count for '{sym_key}': expected {len(exp_bars)}, got {len(pdata) if isinstance(pdata, (list, tuple)) else 'invalid'}"
                        )
                    if not isinstance(pdata[0], MarketBar):
                        raise RuntimeError(f"Partition record for '{sym_key}' is not MarketBar instance")

                # 7. Atomic publication to final destination
                os.replace(staging_dir, part_dir)

                logger.info(
                    "MarketBarsCache: Successfully published %d symbol partitions from '%s' to '%s'",
                    len(expected_map),
                    legacy_path,
                    part_dir,
                )
                return len(expected_map)

            except Exception as exc:
                logger.error("MarketBarsCache: Failed migrating legacy bars: %s", exc)
                _safe_clean_staging_dir(staging_dir)
                return 0

    def plan_ingestion(
        self,
        symbols: Sequence[str],
        target_date: Union[datetime, date, str],
        exchange: str = "NSE",
        provider: str = "yfinance",
        overlap_days: int = 5,
        min_bars: int = 60,
        holidays: Optional[Sequence[Union[date, str]]] = None,
        session_completed: bool = False,
    ) -> IngestionPlan:
        """Deterministically plan ingestion for requested symbols against this cache."""
        return plan_ingestion(
            symbols=symbols,
            target_date=target_date,
            cache=self,
            exchange=exchange,
            provider=provider,
            overlap_days=overlap_days,
            min_bars=min_bars,
            holidays=holidays,
            session_completed=session_completed,
        )


def _resolve_trading_holidays(
    holidays: Optional[Sequence[Union[date, str]]] = None,
) -> set[date]:
    """Resolve trading holiday date objects from explicit sequence or default calendar."""
    resolved: set[date] = set()
    if holidays is not None:
        for h in holidays:
            if isinstance(h, datetime):
                resolved.add(h.date())
            elif isinstance(h, date):
                resolved.add(h)
            elif isinstance(h, str):
                s = h.strip()
                if s:
                    try:
                        resolved.add(date.fromisoformat(s))
                    except ValueError:
                        pass
        return resolved

    try:
        from yogi.market.calendar import INDIAN_TRADING_HOLIDAYS
        for year_hols in INDIAN_TRADING_HOLIDAYS.values():
            for s in year_hols:
                try:
                    resolved.add(date.fromisoformat(s))
                except ValueError:
                    pass
    except ImportError:
        pass

    return resolved


def get_latest_completed_trading_day(
    target_date: Union[datetime, date, str],
    holidays: Optional[Sequence[Union[date, str]]] = None,
    session_completed: bool = False,
) -> date:
    """Deterministically find the latest completed market trading day on or before target_date.

    Rules:
    - Monday through Friday are market days (weekday < 5).
    - Saturday and Sunday are weekends.
    - Days present in `holidays` (or Indian market holidays by default) are exchange holidays.
    - If session_completed is False (default): the session on target_date is not assumed
      complete, so the latest completed session is the preceding market trading day.
    - If session_completed is True: target_date itself is evaluated as completed if it is a trading day.
    """
    if isinstance(target_date, datetime):
        t_date = target_date.date()
    elif isinstance(target_date, date):
        t_date = target_date
    elif isinstance(target_date, str):
        s = target_date.strip()
        try:
            t_date = date.fromisoformat(s)
        except ValueError:
            t_date = datetime.fromisoformat(s).date()
    else:
        raise ValueError(
            f"Unsupported type for target_date: expected datetime, date, or str, got {type(target_date).__name__}"
        )

    hol_set = _resolve_trading_holidays(holidays)
    curr = t_date if session_completed else t_date - timedelta(days=1)

    for _ in range(30):
        if curr.weekday() < 5 and curr not in hol_set:
            return curr
        curr -= timedelta(days=1)

    return curr


def plan_ingestion(
    symbols: Sequence[str],
    target_date: Union[datetime, date, str],
    cached_bars: Optional[Mapping[str, Sequence[MarketBar]]] = None,
    cache: Optional[MarketBarsCache] = None,
    exchange: str = "NSE",
    provider: str = "yfinance",
    overlap_days: int = 5,
    min_bars: int = 60,
    holidays: Optional[Sequence[Union[date, str]]] = None,
    session_completed: bool = False,
) -> IngestionPlan:
    """Deterministically classify requested symbols into UP_TO_DATE, INCREMENTAL_UPDATE, or FULL_BACKFILL.

    Classification rules:
    - FULL_BACKFILL: No usable cached history exists, or the symbol has fewer bars than min_bars.
      A symbol with insufficient history is never considered up to date even if its latest bar is recent.
    - INCREMENTAL_UPDATE: Sufficient history exists (>= min_bars), but its latest valid daily bar is
      strictly earlier than the expected fresh trading day.
    - UP_TO_DATE: Sufficient history exists (>= min_bars) and its latest bar is on or after the expected
      fresh trading day.

    For INCREMENTAL_UPDATE symbols, start_date is calculated as:
    `start_date = latest_cached_bar_date - timedelta(days=overlap_days)`

    Parameters:
        symbols: Requested symbols to plan ingestion for.
        target_date: Explicit reference date for freshness evaluation (never machine clock).
        cached_bars: Optional pre-loaded mapping of symbol -> Sequence[MarketBar].
        cache: Optional MarketBarsCache instance to load bars from if cached_bars is omitted.
        exchange: Exchange code (e.g. 'NSE').
        provider: Provider code (e.g. 'yfinance').
        overlap_days: Number of calendar days to subtract for incremental updates (>= 0).
        min_bars: Minimum number of unique daily bars required for sufficient history (>= 1).
        holidays: Optional sequence of holiday date strings or date objects.
        session_completed: Whether the session on target_date is already completed.

    Returns:
        IngestionPlan: Structured plan with deterministic classifications and start dates.
    """
    if overlap_days < 0:
        raise ValueError(f"overlap_days must be non-negative (>= 0), got {overlap_days}")
    if min_bars < 1:
        raise ValueError(f"min_bars must be positive (>= 1), got {min_bars}")

    expected_fresh = get_latest_completed_trading_day(
        target_date=target_date,
        holidays=holidays,
        session_completed=session_completed,
    )

    if isinstance(target_date, datetime):
        t_date = target_date.date()
    elif isinstance(target_date, date):
        t_date = target_date
    elif isinstance(target_date, str):
        s = target_date.strip()
        try:
            t_date = date.fromisoformat(s)
        except ValueError:
            t_date = datetime.fromisoformat(s).date()
    else:
        raise ValueError(
            f"Unsupported type for target_date: expected datetime, date, or str, got {type(target_date).__name__}"
        )

    # Resolve bars without modifying cache or making network calls
    bars_source: Mapping[str, Sequence[MarketBar]] = {}
    if cached_bars is not None:
        bars_source = cached_bars
    elif cache is not None:
        bars_source = cache.load_bars(exchange=exchange, provider=provider)

    # Normalize symbols: deduplicated, upper-cased, stripped
    unique_symbols: list[str] = []
    seen = set()
    for s in symbols:
        clean = str(s).strip().upper()
        if clean and clean not in seen:
            seen.add(clean)
            unique_symbols.append(clean)

    plans: dict[str, SymbolIngestionPlan] = {}
    up_to_date_list: list[str] = []
    incremental_list: list[str] = []
    full_backfill_list: list[str] = []
    start_dates: dict[str, date] = {}

    for sym in unique_symbols:
        raw_bars = bars_source.get(sym, ())
        valid_bars_by_date: dict[date, MarketBar] = {}

        if isinstance(raw_bars, (list, tuple)):
            for b in raw_bars:
                if hasattr(b, "timestamp") and b.timestamp is not None:
                    norm_ts = _normalize_bar_ts(b.timestamp)
                    if hasattr(norm_ts, "date"):
                        valid_bars_by_date[norm_ts.date()] = b

        valid_count = len(valid_bars_by_date)

        # Rule 1: Insufficient history -> FULL_BACKFILL
        if valid_count < min_bars:
            reason = (
                "Missing history (0 bars)"
                if valid_count == 0
                else f"Insufficient history: {valid_count} unique bars, {min_bars} required"
            )
            latest_d = max(valid_bars_by_date.keys()) if valid_bars_by_date else None
            plan = SymbolIngestionPlan(
                symbol=sym,
                cohort=IngestionCohort.FULL_BACKFILL,
                cached_bars_count=valid_count,
                latest_bar_date=latest_d,
                start_date=None,
                reason=reason,
            )
            plans[sym] = plan
            full_backfill_list.append(sym)
            continue

        # Sufficient history: determine latest bar date
        latest_d = max(valid_bars_by_date.keys())

        # Rule 2: Freshness evaluation
        if latest_d >= expected_fresh:
            reason = f"Up to date: latest bar ({latest_d}) >= expected fresh date ({expected_fresh})"
            plan = SymbolIngestionPlan(
                symbol=sym,
                cohort=IngestionCohort.UP_TO_DATE,
                cached_bars_count=valid_count,
                latest_bar_date=latest_d,
                start_date=None,
                reason=reason,
            )
            plans[sym] = plan
            up_to_date_list.append(sym)
        else:
            calc_start = latest_d - timedelta(days=overlap_days)
            reason = f"Stale: latest bar ({latest_d}) < expected fresh date ({expected_fresh})"
            plan = SymbolIngestionPlan(
                symbol=sym,
                cohort=IngestionCohort.INCREMENTAL_UPDATE,
                cached_bars_count=valid_count,
                latest_bar_date=latest_d,
                start_date=calc_start,
                reason=reason,
            )
            plans[sym] = plan
            incremental_list.append(sym)
            start_dates[sym] = calc_start

    return IngestionPlan(
        target_date=t_date,
        expected_fresh_date=expected_fresh,
        overlap_days=overlap_days,
        min_bars=min_bars,
        plans=plans,
        up_to_date=tuple(up_to_date_list),
        incremental=tuple(incremental_list),
        full_backfill=tuple(full_backfill_list),
        start_dates=start_dates,
    )

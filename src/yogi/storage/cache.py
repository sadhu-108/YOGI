"""Persistent Local Cache — Dataset & Historical Market Bars Storage.

Implements high-performance local disk-backed persistence for:
1. Computed feature datasets (`data/cache/dataset_{exchange}_{provider}.pkl`)
2. Historical daily market bars (`data/cache/bars_{exchange}_{provider}.pkl`)

Provides fast startup (<100ms), schema/policy validation, and atomic updates.
Follows YOGI architecture: Replaceable Modules with strict validation.
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import pickle
import threading
from typing import Any, Mapping, Optional, Sequence

from yogi.core.contracts.market_data import MarketBar
from yogi.storage.paths import get_cache_dir

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
DEFAULT_CACHE_DIR = get_cache_dir()


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


class MarketBarsCache:
    """Thread-safe persistent cache for historical daily MarketBar sequences."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = get_cache_dir(cache_dir)
        self._lock = threading.Lock()

    def _bars_path(self, exchange: str, provider: str) -> Path:
        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()
        return self.cache_dir / f"bars_{ex}_{pv}.pkl"

    def save_bars(
        self,
        bars_map: Mapping[str, Sequence[MarketBar]],
        exchange: str = "NSE",
        provider: str = "yfinance",
    ) -> Optional[Path]:
        """Atomically merge and persist daily market bars across symbols."""
        if not bars_map:
            return None

        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()

        if pv == "demo":
            return None

        with self._lock:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                target_path = self._bars_path(ex, pv)
                temp_path = self.cache_dir / f"{target_path.name}.tmp"

                # Load existing bars to merge
                existing_bars: dict[str, Sequence[MarketBar]] = {}
                if target_path.is_file():
                    try:
                        with open(target_path, "rb") as fh:
                            data = pickle.load(fh)
                            if isinstance(data, dict):
                                existing_bars = data
                    except Exception:
                        existing_bars = {}

                # Merge new bars
                for sym, bars in bars_map.items():
                    if bars:
                        existing_bars[str(sym).strip().upper()] = tuple(bars)

                with open(temp_path, "wb") as fh:
                    pickle.dump(existing_bars, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    fh.flush()
                    os.fsync(fh.fileno())

                os.replace(temp_path, target_path)
                logger.info(
                    "MarketBarsCache: Persisted bars for %d symbols to '%s'",
                    len(existing_bars),
                    target_path,
                )
                return target_path
            except Exception as exc:
                logger.error("MarketBarsCache: Failed to persist bars: %s", exc)
                return None

    def load_bars(
        self,
        exchange: str = "NSE",
        provider: str = "yfinance",
    ) -> dict[str, Sequence[MarketBar]]:
        """Load all cached MarketBar sequences for the given exchange/provider."""
        ex = (exchange or "NSE").strip().upper()
        pv = (provider or "yfinance").strip().lower()

        if pv == "demo":
            return {}

        target_path = self._bars_path(ex, pv)
        if not target_path.is_file():
            return {}

        with self._lock:
            try:
                with open(target_path, "rb") as fh:
                    data = pickle.load(fh)
                if not isinstance(data, dict):
                    return {}

                # Validate elements
                valid_store: dict[str, Sequence[MarketBar]] = {}
                for sym, bars in data.items():
                    if isinstance(bars, (list, tuple)) and len(bars) > 0 and isinstance(bars[0], MarketBar):
                        valid_store[sym] = bars

                return valid_store
            except Exception as exc:
                logger.warning("MarketBarsCache: Failed to load bars from '%s': %s", target_path, exc)
                return {}

    def get_bars_for_symbols(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        provider: str = "yfinance",
        min_bars: int = 60,
    ) -> tuple[dict[str, Sequence[MarketBar]], list[str]]:
        """Partition requested symbols into usable cached bars and symbols needing download."""
        all_bars = self.load_bars(exchange=exchange, provider=provider)
        found: dict[str, Sequence[MarketBar]] = {}
        missing: list[str] = []

        for sym in symbols:
            s_clean = str(sym).strip().upper()
            bars = all_bars.get(s_clean)
            if bars and len(bars) >= min_bars:
                found[s_clean] = bars
            else:
                missing.append(s_clean)

        return found, missing

    def clear(self, exchange: str = "NSE", provider: str = "yfinance") -> bool:
        """Remove cached bars file if present."""
        target_path = self._bars_path(exchange, provider)
        with self._lock:
            try:
                if target_path.is_file():
                    target_path.unlink()
                    logger.info("MarketBarsCache: Cleared '%s'", target_path)
                return True
            except Exception as exc:
                logger.warning("MarketBarsCache: Failed to clear '%s': %s", target_path, exc)
                return False

"""Cockpit Race Service — Sprint Race multi-stock curve presentation service.

Coordinates candidate leader selection from dataset, historical bar fetching from IDataProvider,
and mathematical curve calculation via calculate_anchored_curve.
Decouples presentation-layer multi-line charting from HTTP transport controllers.
"""

from collections import OrderedDict
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Callable, Mapping, Optional, Sequence
import pandas as pd

from yogi.calculation.velocity import calculate_anchored_curve
from yogi.cockpit.schemas import RaceLineOut, RacePointOut, RaceResponseOut
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.storage import IBarsCache
from yogi.core.contracts.timeframe import ITimeframeEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RaceCacheEntry:
    """Bounded cache entry storing calculated race response and timestamp."""
    response: RaceResponseOut
    created_at: float


def _is_strictly_before(ts: Any, anchor_str: str) -> bool:
    """Check if a timestamp or date string is strictly prior to an anchor date."""
    try:
        t = pd.to_datetime(ts)
        a = pd.to_datetime(anchor_str)
        if t.tz is not None and a.tz is None:
            a = a.tz_localize(t.tz)
        elif t.tz is None and a.tz is not None:
            t = t.tz_localize(a.tz)
        return bool(t < a)
    except Exception:
        return False


class RaceDataService:
    """Application presentation service building multi-line sprint race curve payloads."""

    def __init__(
        self,
        provider: IDataProvider,
        dataset_provider: Optional[Callable[[], Mapping[str, Mapping[str, Any]]]] = None,
        max_entries: int = 50,
        ttl_seconds: Optional[float] = 300.0,
        bars_cache: Optional[IBarsCache] = None,
        timeframe_engine: Optional[ITimeframeEngine] = None,
    ) -> None:
        self.provider = provider
        self.dataset_provider = dataset_provider or (lambda: {})
        self.max_entries: int = max_entries
        self.ttl_seconds: Optional[float] = ttl_seconds
        self.bars_cache: Optional[IBarsCache] = bars_cache
        self.timeframe_engine: Optional[ITimeframeEngine] = timeframe_engine
        self._cache: OrderedDict[tuple[Any, ...], _RaceCacheEntry] = OrderedDict()
        self._cache_lock: threading.Lock = threading.Lock()
        self._provider_earliest_date: dict[tuple[str, str], Any] = {}
        self._memory_bars: dict[str, Sequence[MarketBar]] = {}

    def _get_cached(self, key: tuple[Any, ...]) -> Optional[RaceResponseOut]:
        """Retrieve response from bounded LRU cache if entry is unexpired."""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if self.ttl_seconds is not None and (time.monotonic() - entry.created_at) > self.ttl_seconds:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return entry.response

    def _put_cached(self, key: tuple[Any, ...], response: RaceResponseOut) -> None:
        """Store response into bounded LRU cache, evicting oldest if capacity reached."""
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = _RaceCacheEntry(response=response, created_at=time.monotonic())
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        """Clear all cached race curve entries and reset provider history tracking."""
        with self._cache_lock:
            self._cache.clear()
            self._provider_earliest_date.clear()
            self._memory_bars.clear()

    async def get_race(
        self,
        symbols: Optional[str] = None,
        anchor: str = "2021-01-01",
        top: int = 10,
        metric: Optional[str] = None,
        exchange: str = "NSE",
        timeframe: str = "W",
    ) -> RaceResponseOut:
        """Calculate sprint race curves for explicit symbols or auto-picked leaders."""
        tf_key = str(timeframe).strip().upper() if timeframe else "W"
        pv_name = getattr(self.provider, "name", "")
        clean_metric = metric.strip().upper() if metric else ""

        # Fix C: Normalize and deduplicate manual symbols, preserving first occurrence order
        is_manual = False
        syms: list[str] = []
        if symbols and symbols.strip():
            raw_tokens = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            syms = list(dict.fromkeys(raw_tokens))
            is_manual = bool(syms)

        # Fix A: Effective requested count
        if is_manual:
            effective_asked = len(syms)
            want = len(syms)
        else:
            effective_asked = max(1, min(int(top), 50))
            want = effective_asked

        clean_symbols = ",".join(syms) if is_manual else ""
        cache_key = (
            clean_symbols,
            anchor,
            effective_asked,
            clean_metric,
            exchange,
            tf_key,
            pv_name,
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        dataset = self.dataset_provider()

        if not is_manual:
            if not dataset:
                empty_res = RaceResponseOut(
                    anchor=anchor,
                    lines=[],
                    asked=effective_asked,
                    note="No dataset available",
                    timeframe=tf_key,
                )
                return empty_res

            # Automatic ranking: determine ranking metric bound to anchor year
            resolved_metric = clean_metric
            if not resolved_metric:
                try:
                    anchor_yr = pd.Timestamp(anchor).year
                    resolved_metric = f"SPA_A{str(anchor_yr)[-2:]}"
                except Exception:
                    resolved_metric = "SPA_A21"

            all_cols = set()
            for rec in dataset.values():
                all_cols.update(rec.keys())
                break

            if resolved_metric not in all_cols:
                spa_cols = sorted([c for c in all_cols if c.startswith("SPA_A")])
                resolved_metric = spa_cols[-1] if spa_cols else "M_CUR"

            candidates = []
            for sym, rec in dataset.items():
                if rec.get("SUSPECT") == "Y":
                    continue
                val = rec.get(resolved_metric)
                if val is not None:
                    try:
                        fval = float(val)
                        if abs(fval) < 3000:
                            candidates.append((sym, fval))
                    except (ValueError, TypeError):
                        continue

            candidates.sort(key=lambda x: x[1], reverse=True)
            # Pick up to want * 4 candidates (extras allow for stocks with no pre-anchor history)
            syms = [c[0] for c in candidates[: want * 4]]

        # Check persistent bars cache if available
        cached_bars_map: dict[str, Sequence[MarketBar]] = {}
        if self.bars_cache is not None and syms:
            try:
                found, _ = self.bars_cache.get_bars_for_symbols(
                    symbols=syms,
                    exchange=exchange,
                    provider=pv_name,
                    min_bars=3,
                )
                cached_bars_map = found
            except Exception as cache_err:
                logger.debug("RaceDataService: cache batch lookup failed: %s", cache_err)
                cached_bars_map = {}

        lines: list[RaceLineOut] = []
        for s in syms:
            try:
                rec = dataset.get(s, {})
                listing_val = rec.get("listing_date") or rec.get("ipo_date") or rec.get("date_of_listing")
                is_known_post_anchor_ipo = False
                if listing_val:
                    is_known_post_anchor_ipo = not _is_strictly_before(listing_val, anchor)

                provider_key = (s, pv_name)
                provider_earliest = self._provider_earliest_date.get(provider_key)
                is_provider_post_anchor_ipo = bool(
                    provider_earliest is not None and not _is_strictly_before(provider_earliest, anchor)
                )

                bars = cached_bars_map.get(s) or self._memory_bars.get(s)
                has_baseline = bool(bars and len(bars) >= 3 and any(_is_strictly_before(b.timestamp, anchor) for b in bars))

                # Case 2 & 3: If cached bars lack baseline and stock is NOT known to be post-anchor IPO, attempt provider fallback
                if not has_baseline and not is_known_post_anchor_ipo and not is_provider_post_anchor_ipo:
                    try:
                        fetched = self.provider.daily_history(symbol=s, exchange=exchange, years=10)
                        if fetched and len(fetched) >= 3:
                            earliest = min(b.timestamp for b in fetched)
                            self._provider_earliest_date[provider_key] = earliest
                            self._memory_bars[s] = fetched
                            bars = fetched
                            if self.bars_cache is not None:
                                try:
                                    self.bars_cache.save_bars(
                                        {s: fetched},
                                        exchange=exchange,
                                        provider=pv_name,
                                    )
                                except Exception as save_err:
                                    logger.debug("RaceDataService: cache save failed for %s: %s", s, save_err)
                        else:
                            self._provider_earliest_date[provider_key] = pd.Timestamp.max
                    except Exception as fetch_err:
                        logger.debug("RaceDataService: provider fetch failed for %s: %s", s, fetch_err)

                if not bars or len(bars) < 3:
                    continue

                close_series = pd.Series(
                    [b.close for b in bars],
                    index=[b.timestamp for b in bars],
                )
                pts_raw = calculate_anchored_curve(
                    close_series,
                    anchor,
                    weekly=(tf_key == "W"),
                    timeframe=tf_key,
                )
                if len(pts_raw) > 2 and abs(pts_raw[-1]["value"]) < 3000:
                    raw_name = rec.get("name")
                    label = (
                        str(raw_name)
                        if raw_name and str(raw_name).strip().lower() not in ("nan", "none", "") and str(raw_name) != s
                        else s
                    )
                    points = [RacePointOut(time=pt["time"], value=pt["value"]) for pt in pts_raw]
                    lines.append(
                        RaceLineOut(
                            symbol=s,
                            label=label,
                            points=points,
                            final=pts_raw[-1]["value"],
                        )
                    )
                    if len(lines) >= want:
                        break
            except Exception as exc:
                logger.debug("Could not calculate race curve for %s: %s", s, exc)
                continue

        lines.sort(key=lambda x: x.final, reverse=True)
        note = (
            f"showing {len(lines)} of {effective_asked} asked - the rest have no price history before {anchor}"
            if len(lines) < effective_asked
            else ""
        )
        response = RaceResponseOut(
            anchor=anchor,
            lines=lines,
            asked=effective_asked,
            note=note,
            timeframe=tf_key,
        )
        self._put_cached(cache_key, response)
        return response

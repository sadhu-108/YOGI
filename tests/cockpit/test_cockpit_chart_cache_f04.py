"""Focused tests for YOGI-F04: Bounded Chart Data Cache.

Verifies:
1. Cache hits return correct data without re-fetching from provider.
2. Cache entries are evicted when configured maximum is exceeded (LRU eviction).
3. Cache cannot grow beyond its bound.
4. Repeated chart requests behave correctly after eviction.
5. Existing cache invalidation behavior (clear_cache) remains correct.
6. Demo/Live separation is preserved without cross-contamination.
7. Chart numerical results are unchanged between cache hit and fresh calculation.
8. Safe under concurrent access from multiple threads.
9. TTL expiration evicts stale entries and triggers fresh fetches.
10. Failed / empty provider results are never cached.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import time
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.charting import ChartDataService, _ChartCacheEntry
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth


class TrackingMockProvider(IDataProvider):
    """Mock provider tracking every daily_history call."""

    def __init__(self, name: str = "mock_provider") -> None:
        self._name = name
        self.call_history: list[tuple[str, str, int]] = []
        self.bars_by_symbol: dict[str, list[MarketBar]] = {}

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, val: str) -> None:
        self._name = val

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return list(self.bars_by_symbol.keys())

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 2
    ) -> Sequence[MarketBar]:
        self.call_history.append((symbol, exchange, years))
        return self.bars_by_symbol.get(symbol, [])

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.bars_by_symbol.get(symbol)
        return bars[-1].close if bars else None

    def intraday(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self._name, ok=True)


def create_sample_bars(n: int = 25, base_price: float = 100.0) -> list[MarketBar]:
    base_date = datetime(2025, 1, 1)
    bars = []
    for i in range(n):
        dt = base_date + timedelta(days=i)
        p = base_price + i * 1.5
        bars.append(
            MarketBar(
                timestamp=dt,
                open=p - 0.5,
                high=p + 1.0,
                low=p - 1.0,
                close=p,
                volume=1000.0,
            )
        )
    return bars


def test_f04_cache_hit_returns_correct_data_without_provider_call():
    provider = TrackingMockProvider("test_prov")
    provider.bars_by_symbol["INFY"] = create_sample_bars(25, 100.0)

    service = ChartDataService(provider=provider, max_entries=10)

    # First call - cache miss
    res1 = service.get_candles("INFY", timeframe="D", exchange="NSE", years=2)
    assert len(provider.call_history) == 1
    assert len(res1.candles) == 25
    assert service.cache_size == 1

    # Second call - cache hit
    res2 = service.get_candles("INFY", timeframe="D", exchange="NSE", years=2)
    assert len(provider.call_history) == 1  # Provider NOT called again
    assert len(res2.candles) == 25
    assert service.cache_size == 1

    # Compare payload parity
    assert [c.close for c in res1.candles] == [c.close for c in res2.candles]
    assert [p.value for p in res1.band_upper_curve] == [p.value for p in res2.band_upper_curve]
    if res1.latest_band and res2.latest_band:
        assert res1.latest_band.basis == res2.latest_band.basis


def test_f04_bounded_capacity_and_lru_eviction():
    provider = TrackingMockProvider("test_prov")
    for i in range(1, 6):
        provider.bars_by_symbol[f"SYM{i}"] = create_sample_bars(10, 100.0 * i)

    # Set capacity = 3
    service = ChartDataService(provider=provider, max_entries=3)

    # Insert SYM1, SYM2, SYM3
    service.get_candles("SYM1")
    service.get_candles("SYM2")
    service.get_candles("SYM3")

    assert service.cache_size == 3
    assert list(service._cache.keys()) == [
        ("SYM1", "NSE", 2),
        ("SYM2", "NSE", 2),
        ("SYM3", "NSE", 2),
    ]

    # Access SYM1 -> moves to end (most recently used)
    service.get_candles("SYM1")
    assert list(service._cache.keys()) == [
        ("SYM2", "NSE", 2),
        ("SYM3", "NSE", 2),
        ("SYM1", "NSE", 2),
    ]

    # Add SYM4 -> SYM2 (least recently used) must be evicted
    service.get_candles("SYM4")
    assert service.cache_size == 3
    assert ("SYM2", "NSE", 2) not in service._cache
    assert list(service._cache.keys()) == [
        ("SYM3", "NSE", 2),
        ("SYM1", "NSE", 2),
        ("SYM4", "NSE", 2),
    ]


def test_f04_cache_cannot_grow_beyond_bound():
    provider = TrackingMockProvider("test_prov")
    for i in range(50):
        provider.bars_by_symbol[f"TICKER_{i}"] = create_sample_bars(5, 50.0 + i)

    service = ChartDataService(provider=provider, max_entries=5)

    for i in range(50):
        service.get_candles(f"TICKER_{i}")
        assert service.cache_size <= 5

    assert service.cache_size == 5


def test_f04_repeated_requests_after_eviction():
    provider = TrackingMockProvider("test_prov")
    provider.bars_by_symbol["A"] = create_sample_bars(10, 100.0)
    provider.bars_by_symbol["B"] = create_sample_bars(10, 200.0)
    provider.bars_by_symbol["C"] = create_sample_bars(10, 300.0)
    provider.bars_by_symbol["D"] = create_sample_bars(10, 400.0)

    service = ChartDataService(provider=provider, max_entries=2)

    # Populate A and B
    service.get_candles("A")
    service.get_candles("B")
    assert len(provider.call_history) == 2

    # Add C -> A is evicted
    service.get_candles("C")
    assert ("A", "NSE", 2) not in service._cache
    assert len(provider.call_history) == 3

    # Request A again -> provider called for A again, B is evicted
    res_a = service.get_candles("A")
    assert len(provider.call_history) == 4
    assert len(res_a.candles) == 10
    assert ("A", "NSE", 2) in service._cache
    assert ("B", "NSE", 2) not in service._cache


def test_f04_clear_cache_invalidation():
    provider = TrackingMockProvider("test_prov")
    provider.bars_by_symbol["TCS"] = create_sample_bars(15, 3000.0)

    service = ChartDataService(provider=provider, max_entries=10)
    service.get_candles("TCS")
    assert service.cache_size == 1
    assert len(provider.call_history) == 1

    # Invalidate cache
    service.clear_cache()
    assert service.cache_size == 0

    # Next call must query provider
    service.get_candles("TCS")
    assert service.cache_size == 1
    assert len(provider.call_history) == 2


def test_f04_demo_live_provider_isolation():
    demo_provider = TrackingMockProvider("demo")
    demo_provider.bars_by_symbol["STOCK"] = create_sample_bars(10, 100.0)

    service = ChartDataService(provider=demo_provider, max_entries=10)
    service.get_candles("STOCK")
    assert service.cache_size == 1

    # Switch provider instance / name on the service
    live_provider = TrackingMockProvider("yfinance")
    live_provider.bars_by_symbol["STOCK"] = create_sample_bars(10, 999.0)
    service.provider = live_provider

    # Next call detects provider change, invalidates demo cache, and queries live provider
    res_live = service.get_candles("STOCK")
    assert len(live_provider.call_history) == 1
    assert res_live.candles[-1].close == 999.0 + 9 * 1.5


def test_f04_ttl_expiration():
    provider = TrackingMockProvider("test_prov")
    provider.bars_by_symbol["QUICK"] = create_sample_bars(10, 100.0)

    # Set 0.2s (200ms) TTL
    service = ChartDataService(provider=provider, max_entries=10, ttl_seconds=0.2)

    service.get_candles("QUICK")
    assert len(provider.call_history) == 1

    # Immediate call hits cache
    service.get_candles("QUICK")
    assert len(provider.call_history) == 1

    # Wait past TTL
    time.sleep(0.25)

    # Expired entry triggers re-fetch from provider
    service.get_candles("QUICK")
    assert len(provider.call_history) == 2


def test_f04_failed_empty_results_never_cached():
    provider = TrackingMockProvider("test_prov")
    # UNKNOWN has no bars
    service = ChartDataService(provider=provider, max_entries=10)

    res = service.get_candles("UNKNOWN")
    assert res.candles == []
    assert service.cache_size == 0
    assert ("UNKNOWN", "NSE", 2) not in service._cache


def test_f04_concurrent_thread_safety():
    provider = TrackingMockProvider("test_prov")
    for i in range(20):
        provider.bars_by_symbol[f"CONC_{i}"] = create_sample_bars(10, float(i))

    service = ChartDataService(provider=provider, max_entries=5)

    def worker(sym: str):
        for _ in range(5):
            res = service.get_candles(sym)
            assert len(res.candles) == 10

    symbols = [f"CONC_{i % 20}" for i in range(100)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, symbols))

    assert service.cache_size <= 5

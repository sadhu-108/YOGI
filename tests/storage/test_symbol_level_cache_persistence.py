"""Focused tests for symbol-level partition cache persistence (surgical performance fix).

Verifies that single-symbol chart updates persist only the affected symbol partition,
leaving historical bars intact, ensuring subsequent reads return the latest data,
preserving monolithic cache consistency without synchronous whole-universe disk I/O,
and maintaining thread-safety and error cleanup guarantees.
"""

from datetime import datetime, timezone, timedelta
import logging
from pathlib import Path
import pickle
import threading
import pytest

from yogi.core.contracts.market_data import MarketBar
from yogi.storage.cache import MarketBarsCache


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_test_bars(symbol: str, count: int = 10, start_day: int = 1, price_base: float = 100.0) -> tuple[MarketBar, ...]:
    base_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=start_day + i),
            open=price_base + i,
            high=price_base + i + 5.0,
            low=price_base + i - 5.0,
            close=price_base + i + 2.0,
            volume=1000.0 * (i + 1),
        )
        for i in range(count)
    )


def test_single_symbol_save_with_sync_monolith_false_persists_partition_only(temp_cache_dir: Path):
    """Verify single-symbol update persists partition file without creating/rewriting monolith."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_infy = _make_test_bars("INFY", 20)
    bars_tcs = _make_test_bars("TCS", 20)

    # Pre-populate TCS partition directly
    tcs_part = temp_cache_dir / "bars" / "NSE_yfinance" / "TCS.pkl"
    tcs_part.parent.mkdir(parents=True, exist_ok=True)
    with open(tcs_part, "wb") as pfh:
        pickle.dump(bars_tcs, pfh)
    initial_tcs_mtime = tcs_part.stat().st_mtime_ns

    # Save INFY with sync_monolith=False
    saved_path = cache.save_bars({"INFY": bars_infy}, exchange="NSE", provider="yfinance", sync_monolith=False)

    infy_part = temp_cache_dir / "bars" / "NSE_yfinance" / "INFY.pkl"
    mono_path = temp_cache_dir / "bars_NSE_yfinance.pkl"

    assert saved_path == infy_part
    assert infy_part.is_file()
    assert not mono_path.exists(), "Monolithic universe file must NOT be written when sync_monolith=False"

    # Other symbol partitions must remain completely untouched
    assert tcs_part.stat().st_mtime_ns == initial_tcs_mtime


def test_subsequent_reads_return_updated_candles_after_partition_only_save(temp_cache_dir: Path):
    """Verify warm and cold subsequent reads return the latest updated candles."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    initial_bars = _make_test_bars("RELIANCE", 30, start_day=1)
    cache.save_bars({"RELIANCE": initial_bars}, exchange="NSE", provider="yfinance", sync_monolith=False)

    # 1. Incremental update with 5 newer bars
    inc_bars = _make_test_bars("RELIANCE", 5, start_day=31)
    cache.save_bars({"RELIANCE": inc_bars}, exchange="NSE", provider="yfinance", sync_monolith=False)

    # 2. Warm in-memory read
    found_warm, missing_warm = cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)
    assert missing_warm == []
    assert len(found_warm["RELIANCE"]) == 35
    assert found_warm["RELIANCE"][-1].timestamp == inc_bars[-1].timestamp

    # 3. Cold read via a fresh MarketBarsCache instance (simulating restart / new worker)
    cold_cache = MarketBarsCache(cache_dir=temp_cache_dir)
    found_cold, missing_cold = cold_cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)
    assert missing_cold == []
    assert len(found_cold["RELIANCE"]) == 35
    assert found_cold["RELIANCE"][-1].timestamp == inc_bars[-1].timestamp


def test_historical_candles_preserved_and_merged_correctly(temp_cache_dir: Path):
    """Verify historical candles are not overwritten or truncated, and new candles merge chronologically."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_1 = _make_test_bars("WIPRO", 50, start_day=1)
    cache.save_bars({"WIPRO": bars_1}, exchange="NSE", provider="yfinance", sync_monolith=False)

    # Incremental fetch
    bars_2 = _make_test_bars("WIPRO", 10, start_day=45)  # 5 overlapping bars, 5 new bars
    cache.save_bars({"WIPRO": bars_2}, exchange="NSE", provider="yfinance", sync_monolith=False)

    found, _ = cache.get_bars_for_symbols(["WIPRO"], min_bars=10)
    merged = found["WIPRO"]
    assert len(merged) == 54  # 50 days (1..50) + 10 days (45..54, 6 overlapping) = 54 total days
    # Verify strictly monotonic timestamps
    timestamps = [b.timestamp for b in merged]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))


def test_single_symbol_save_does_not_open_or_dump_monolith(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that pickle.load and pickle.dump never touch the 300MB monolithic file during partition save."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("HDFCBANK", 20)

    # Create dummy monolithic file
    mono_path = temp_cache_dir / "bars_NSE_yfinance.pkl"
    with open(mono_path, "wb") as fh:
        pickle.dump({"OLD": _make_test_bars("OLD", 5)}, fh)

    opened_files: list[str] = []
    orig_load = pickle.load
    orig_dump = pickle.dump

    def spy_load(fh, *args, **kwargs):
        name = Path(getattr(fh, "name", str(fh))).name
        opened_files.append(f"load:{name}")
        return orig_load(fh, *args, **kwargs)

    def spy_dump(obj, fh, *args, **kwargs):
        name = Path(getattr(fh, "name", str(fh))).name
        opened_files.append(f"dump:{name}")
        return orig_dump(obj, fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", spy_load)
    monkeypatch.setattr(pickle, "dump", spy_dump)

    cache.save_bars({"HDFCBANK": bars}, exchange="NSE", provider="yfinance", sync_monolith=False)

    assert "load:bars_NSE_yfinance.pkl" not in opened_files
    assert "dump:bars_NSE_yfinance.pkl" not in opened_files
    assert "dump:bars_NSE_yfinance.pkl.tmp" not in opened_files
    # Only the partition temp file was dumped
    dumped = [f for f in opened_files if f.startswith("dump:")]
    assert dumped == ["dump:HDFCBANK.pkl.tmp"]


def test_monolithic_load_bars_overlays_partition_only_save(temp_cache_dir: Path):
    """Verify load_bars() overlays newer symbol partitions over baseline monolithic cache."""
    # 1. Monolithic file created with older mtime
    mono_path = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_old = _make_test_bars("INFY", 20, start_day=1)
    with open(mono_path, "wb") as fh:
        pickle.dump({"INFY": bars_old, "TCS": _make_test_bars("TCS", 20)}, fh)

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    # 2. Update INFY partition only (newer mtime)
    bars_new = _make_test_bars("INFY", 30, start_day=1)
    cache.save_bars({"INFY": bars_new}, exchange="NSE", provider="yfinance", sync_monolith=False)

    # 3. Fresh instance calls load_bars()
    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)
    all_bars = fresh_cache.load_bars(exchange="NSE", provider="yfinance")

    assert len(all_bars["INFY"]) == 30  # Partition override took precedence
    assert len(all_bars["TCS"]) == 20   # Monolithic baseline preserved


def test_failure_safety_cleans_temporary_partition_files(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that disk write failures clean up temporary partition files and return None."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("FAIL_TEST", 10)

    def failing_dump(*args, **kwargs):
        raise OSError("Disk write failed during partition serialization")

    monkeypatch.setattr(pickle, "dump", failing_dump)

    result = cache.save_bars({"FAIL_TEST": bars}, exchange="NSE", provider="yfinance", sync_monolith=False)
    assert result is None

    # No leftover .tmp files
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    if part_dir.exists():
        tmp_files = list(part_dir.glob("*.tmp"))
        assert tmp_files == []


def test_concurrency_safety_multi_thread_partition_writes(temp_cache_dir: Path):
    """Verify thread-safety when multiple threads concurrently write separate symbol partitions."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    symbols = [f"SYM_{i}" for i in range(10)]
    errors: list[Exception] = []

    def worker(sym: str):
        try:
            bars = _make_test_bars(sym, 15)
            res = cache.save_bars({sym: bars}, exchange="NSE", provider="yfinance", sync_monolith=False)
            if res is None or not res.is_file():
                errors.append(RuntimeError(f"Save failed for {sym}"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in symbols]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Verify all 10 partitions exist and have 15 bars
    found, missing = cache.get_bars_for_symbols(symbols, min_bars=10)
    assert missing == []
    assert len(found) == 10
    for s in symbols:
        assert len(found[s]) == 15


def test_chart_data_service_persists_partition_only_without_monolith_rewrite(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that ChartDataService triggers partition-only persistence without touching monolith."""
    from yogi.cockpit.charting import ChartDataService
    from tests.cockpit.test_chart_cache_freshness import MockChartingProvider, DummyBandsRepo

    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    # 50 old bars ending before target
    initial_bars = _make_test_bars("CHART_SYM", 50, start_day=1)
    cache.save_bars({"CHART_SYM": initial_bars}, exchange="NSE", provider="mock_charting", sync_monolith=False)

    # Provider with 5 new bars
    all_provider_bars = _make_test_bars("CHART_SYM", 55, start_day=1)
    provider = MockChartingProvider(data={"CHART_SYM": all_provider_bars})
    bands_repo = DummyBandsRepo()

    service = ChartDataService(
        provider=provider,
        bands_repo=bands_repo,
        bars_cache=cache,
    )

    opened_files: list[str] = []
    orig_dump = pickle.dump

    def spy_dump(obj, fh, *args, **kwargs):
        name = Path(getattr(fh, "name", str(fh))).name
        opened_files.append(name)
        return orig_dump(obj, fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "dump", spy_dump)

    # Trigger chart request
    result = service.get_candles("CHART_SYM", timeframe="D", years=2)
    assert result.symbol == "CHART_SYM"
    assert len(result.candles) == 55

    # Monolithic file was NEVER dumped
    assert "bars_NSE_mock_charting.pkl.tmp" not in opened_files
    assert not (temp_cache_dir / "bars_NSE_mock_charting.pkl").exists()

    # The partition file was updated
    assert "CHART_SYM.pkl.tmp" in opened_files
    part_path = temp_cache_dir / "bars" / "NSE_mock_charting" / "CHART_SYM.pkl"
    assert part_path.is_file()


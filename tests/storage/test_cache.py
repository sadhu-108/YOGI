"""Tests for persistent DatasetCache and MarketBarsCache storage."""

from datetime import datetime, timezone, timedelta
import pickle
import pytest
from pathlib import Path

from yogi.core.contracts.market_data import MarketBar
from yogi.storage.cache import DatasetCache, MarketBarsCache, CACHE_VERSION


@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_dataset_cache_save_and_load(temp_cache_dir: Path):
    cache = DatasetCache(cache_dir=temp_cache_dir)
    test_data = {
        "RELIANCE": {"symbol": "RELIANCE", "close": 2950.0, "DROC": 1.5, "price": 2950.0},
        "TCS": {"symbol": "TCS", "close": 4200.0, "DROC": -0.8, "price": 4200.0},
    }

    path = cache.save(
        dataset=test_data,
        exchange="NSE",
        provider="yfinance",
        half_year_policy="prototype",
        historical_years=10,
    )
    assert path is not None
    assert path.is_file()

    loaded = cache.load(exchange="NSE", provider="yfinance", half_year_policy="prototype")
    assert loaded is not None
    assert loaded["version"] == CACHE_VERSION
    assert loaded["exchange"] == "NSE"
    assert loaded["provider"] == "yfinance"
    assert loaded["half_year_policy"] == "prototype"
    assert loaded["symbols_count"] == 2
    assert "RELIANCE" in loaded["dataset"]
    assert loaded["dataset"]["RELIANCE"]["close"] == 2950.0
    assert loaded["dataset"]["TCS"]["close"] == 4200.0


def test_dataset_cache_policy_mismatch_rejected(temp_cache_dir: Path):
    cache = DatasetCache(cache_dir=temp_cache_dir)
    test_data = {"INFY": {"symbol": "INFY", "close": 1800.0, "price": 1800.0}}

    cache.save(
        dataset=test_data,
        exchange="NSE",
        provider="yfinance",
        half_year_policy="prototype",
    )

    # Requesting with different policy should reject cache as stale/incompatible
    loaded = cache.load(exchange="NSE", provider="yfinance", half_year_policy="calendar")
    assert loaded is None


def test_dataset_cache_corrupted_file_recovery(temp_cache_dir: Path):
    cache = DatasetCache(cache_dir=temp_cache_dir)
    cache_file = temp_cache_dir / "dataset_NSE_yfinance.pkl"
    cache_file.write_bytes(b"corrupted garbage bytes that are not valid pickle")

    loaded = cache.load(exchange="NSE", provider="yfinance")
    assert loaded is None


def test_dataset_cache_refuses_empty_and_demo(temp_cache_dir: Path):
    cache = DatasetCache(cache_dir=temp_cache_dir)

    # Empty dataset
    assert cache.save({}, exchange="NSE", provider="yfinance") is None

    # Demo provider should not be persisted
    assert cache.save({"RELIANCE": {"symbol": "RELIANCE"}}, exchange="NSE", provider="demo") is None
    assert cache.load(exchange="NSE", provider="demo") is None


def test_dataset_cache_clear(temp_cache_dir: Path):
    cache = DatasetCache(cache_dir=temp_cache_dir)
    cache.save({"RELIANCE": {"symbol": "RELIANCE", "close": 2900.0}}, exchange="NSE", provider="yfinance")
    assert (temp_cache_dir / "dataset_NSE_yfinance.pkl").is_file()

    assert cache.clear(exchange="NSE", provider="yfinance") is True
    assert not (temp_cache_dir / "dataset_NSE_yfinance.pkl").exists()


def test_market_bars_cache_save_load_merge(temp_cache_dir: Path):
    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars_rel = tuple(
        MarketBar(
            timestamp=start_dt + timedelta(days=i),
            open=100.0 + i,
            high=105.0 + i,
            low=99.0 + i,
            close=102.0 + i,
            volume=1000.0,
        )
        for i in range(70)
    )

    bars_tcs = tuple(
        MarketBar(
            timestamp=start_dt + timedelta(days=i),
            open=200.0 + i,
            high=205.0 + i,
            low=199.0 + i,
            close=202.0 + i,
            volume=500.0,
        )
        for i in range(30)
    )

    # Save first batch
    path = cache.save_bars({"RELIANCE": bars_rel}, exchange="NSE", provider="yfinance")
    assert path is not None
    assert path.is_file()

    # Merge second batch
    cache.save_bars({"TCS": bars_tcs}, exchange="NSE", provider="yfinance")

    # Load all bars
    all_bars = cache.load_bars(exchange="NSE", provider="yfinance")
    assert "RELIANCE" in all_bars
    assert "TCS" in all_bars
    assert len(all_bars["RELIANCE"]) == 70
    assert len(all_bars["TCS"]) == 30

    # Partition: RELIANCE has 70 bars (>=60), TCS has 30 (<60), INFY missing
    found, missing = cache.get_bars_for_symbols(
        ["RELIANCE", "TCS", "INFY"],
        exchange="NSE",
        provider="yfinance",
        min_bars=60,
    )
    assert "RELIANCE" in found
    assert "TCS" in missing
    assert "INFY" in missing

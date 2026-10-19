"""Tests for persistent DatasetCache and MarketBarsCache storage."""

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone, timedelta
import hashlib
import logging
import os
from pathlib import Path
import pickle
import threading
import pytest

from yogi.core.contracts.market_data import MarketBar
from yogi.storage.cache import (
    DatasetCache,
    MarketBarsCache,
    CACHE_VERSION,
    IngestionCohort,
    IngestionPlan,
    SymbolIngestionPlan,
    plan_ingestion,
    get_latest_completed_trading_day,
)


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


def test_market_bars_cache_historical_preservation(temp_cache_dir: Path):
    """Test A: 1,000 historical bars + 5 later bars = 1,005 sorted bars (no truncation)."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    base_dt = datetime(2020, 1, 1)

    initial_bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=i),
            open=100.0 + (i % 50),
            high=105.0 + (i % 50),
            low=95.0 + (i % 50),
            close=102.0 + (i % 50),
            volume=10000.0,
        )
        for i in range(1000)
    )

    path = cache.save_bars({"INFY": initial_bars}, exchange="NSE", provider="yfinance")
    assert path is not None
    loaded = cache.load_bars(exchange="NSE", provider="yfinance")
    assert len(loaded["INFY"]) == 1000

    # Incremental update with 5 newer bars
    incremental_bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=1000 + i),
            open=200.0 + i,
            high=205.0 + i,
            low=195.0 + i,
            close=202.0 + i,
            volume=12000.0,
        )
        for i in range(5)
    )

    cache.save_bars({"INFY": incremental_bars}, exchange="NSE", provider="yfinance")
    updated = cache.load_bars(exchange="NSE", provider="yfinance")

    # Verify history was preserved, not overwritten
    assert len(updated["INFY"]) == 1005
    # Verify strictly monotonic ascending order
    for idx in range(len(updated["INFY"]) - 1):
        assert updated["INFY"][idx].timestamp < updated["INFY"][idx + 1].timestamp
    # Verify boundaries
    assert updated["INFY"][0].timestamp == base_dt
    assert updated["INFY"][-1].timestamp == base_dt + timedelta(days=1004)


def test_market_bars_cache_revision_handling(temp_cache_dir: Path):
    """Test B: Incoming bar with identical timestamp replaces older candle (candle revision)."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    base_dt = datetime(2026, 1, 1)

    bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=i),
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=1000.0,
        )
        for i in range(10)
    )
    cache.save_bars({"RELIANCE": bars}, exchange="NSE", provider="yfinance")

    # Revised bar at day 5 with adjusted close
    revised_bar = MarketBar(
        timestamp=base_dt + timedelta(days=5),
        open=999.0,
        high=1005.0,
        low=990.0,
        close=1000.0,
        volume=50000.0,
    )
    cache.save_bars({"RELIANCE": (revised_bar,)}, exchange="NSE", provider="yfinance")

    loaded = cache.load_bars(exchange="NSE", provider="yfinance")
    rel_bars = loaded["RELIANCE"]

    # Count must remain 10 (no duplicate at day 5)
    assert len(rel_bars) == 10
    # Day 5 bar must have updated values
    assert rel_bars[5].close == 1000.0
    assert rel_bars[5].open == 999.0
    assert rel_bars[5].volume == 50000.0
    # Surrounding bars remain untouched
    assert rel_bars[4].close == 106.0
    assert rel_bars[6].close == 108.0


def test_market_bars_cache_duplicate_timestamps(temp_cache_dir: Path):
    """Test C: Duplicate incoming timestamps within batch are deterministically deduplicated."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    target_dt = datetime(2026, 3, 15)

    duplicate_bars = (
        MarketBar(timestamp=target_dt, open=100.0, high=105.0, low=95.0, close=101.0, volume=100.0),
        MarketBar(timestamp=target_dt, open=100.0, high=105.0, low=95.0, close=102.0, volume=200.0),
        MarketBar(timestamp=target_dt, open=100.0, high=105.0, low=95.0, close=103.0, volume=300.0),
    )

    cache.save_bars({"HDFCBANK": duplicate_bars}, exchange="NSE", provider="yfinance")
    loaded = cache.load_bars(exchange="NSE", provider="yfinance")

    assert len(loaded["HDFCBANK"]) == 1
    # Last seen bar wins
    assert loaded["HDFCBANK"][0].close == 103.0
    assert loaded["HDFCBANK"][0].volume == 300.0


def test_market_bars_cache_empty_update_safety(temp_cache_dir: Path):
    """Test D: Empty updates (() or []) do NOT erase or alter existing history."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    base_dt = datetime(2026, 1, 1)

    initial_bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0,
        )
        for i in range(50)
    )
    cache.save_bars({"INFY": initial_bars}, exchange="NSE", provider="yfinance")

    # Saving empty tuple or list for INFY must leave 50 bars intact
    cache.save_bars({"INFY": ()}, exchange="NSE", provider="yfinance")
    assert len(cache.load_bars(exchange="NSE", provider="yfinance")["INFY"]) == 50

    cache.save_bars({"INFY": []}, exchange="NSE", provider="yfinance")
    assert len(cache.load_bars(exchange="NSE", provider="yfinance")["INFY"]) == 50

    # Empty dictionary returns None and does not affect cache
    assert cache.save_bars({}, exchange="NSE", provider="yfinance") is None
    assert len(cache.load_bars(exchange="NSE", provider="yfinance")["INFY"]) == 50


def test_market_bars_cache_out_of_order_bars(temp_cache_dir: Path):
    """Test E: Out-of-order incoming bars are sorted ascending chronologically in cache."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    base_dt = datetime(2026, 2, 1)

    scrambled_days = [15, 2, 28, 8, 1, 20]
    bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=d),
            open=100.0 + d,
            high=105.0 + d,
            low=95.0 + d,
            close=102.0 + d,
            volume=500.0,
        )
        for d in scrambled_days
    )

    cache.save_bars({"WIPRO": bars}, exchange="NSE", provider="yfinance")
    loaded = cache.load_bars(exchange="NSE", provider="yfinance")
    wipro_bars = loaded["WIPRO"]

    assert len(wipro_bars) == len(scrambled_days)
    # Check strictly ascending order
    for idx in range(len(wipro_bars) - 1):
        assert wipro_bars[idx].timestamp < wipro_bars[idx + 1].timestamp
    assert wipro_bars[0].timestamp == base_dt + timedelta(days=1)
    assert wipro_bars[-1].timestamp == base_dt + timedelta(days=28)


def test_market_bars_cache_provider_isolation_and_demo_block(temp_cache_dir: Path):
    """Test F: Provider isolation and demo block regression check."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    sample_bar = (
        MarketBar(
            timestamp=datetime(2026, 1, 1),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0,
        ),
    )

    # Demo provider should never write to disk or return loaded bars
    assert cache.save_bars({"SBIN": sample_bar}, exchange="NSE", provider="demo") is None
    assert not (temp_cache_dir / "bars_NSE_demo.pkl").exists()
    assert cache.load_bars(exchange="NSE", provider="demo") == {}

    # Separate provider/exchange combinations must not collide
    cache.save_bars({"SBIN": sample_bar}, exchange="NSE", provider="yfinance")
    cache.save_bars({"SBIN": sample_bar}, exchange="NSE", provider="zerodha")
    cache.save_bars({"SBIN": sample_bar}, exchange="BSE", provider="yfinance")

    assert (temp_cache_dir / "bars_NSE_yfinance.pkl").is_file()
    assert (temp_cache_dir / "bars_NSE_zerodha.pkl").is_file()
    assert (temp_cache_dir / "bars_BSE_yfinance.pkl").is_file()


def test_market_bars_cache_failure_safety(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Test G: Failure during serialization leaves previous cache file intact and cleans .tmp."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    base_dt = datetime(2026, 1, 1)

    initial_bars = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=i),
            open=500.0 + i,
            high=505.0 + i,
            low=495.0 + i,
            close=502.0 + i,
            volume=2000.0,
        )
        for i in range(20)
    )
    cache.save_bars({"TCS": initial_bars}, exchange="NSE", provider="yfinance")
    target_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    assert target_file.is_file()

    # Simulate an I/O error during pickle.dump
    def mock_pickle_dump(*args, **kwargs):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(pickle, "dump", mock_pickle_dump)

    new_bars = (
        MarketBar(
            timestamp=base_dt + timedelta(days=25),
            open=600.0,
            high=605.0,
            low=595.0,
            close=602.0,
            volume=3000.0,
        ),
    )
    result = cache.save_bars({"TCS": new_bars}, exchange="NSE", provider="yfinance")
    assert result is None

    # Verify no temp file left behind
    temp_file = temp_cache_dir / "bars_NSE_yfinance.pkl.tmp"
    assert not temp_file.exists()

    # Verify original file was not corrupted or modified
    monkeypatch.undo()
    loaded = cache.load_bars(exchange="NSE", provider="yfinance")
    assert len(loaded["TCS"]) == 20
    assert loaded["TCS"][-1].timestamp == base_dt + timedelta(days=19)


def test_market_bars_cache_mixed_tz_resilience(temp_cache_dir: Path):
    """Test mixed naive and timezone-aware timestamps merge and sort without TypeError."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bar_naive = MarketBar(
        timestamp=datetime(2026, 1, 1, 0, 0),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
    )
    bar_aware = MarketBar(
        timestamp=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        open=105.0,
        high=110.0,
        low=100.0,
        close=107.0,
    )

    cache.save_bars({"MIXED": (bar_naive,)}, exchange="NSE", provider="yfinance")
    cache.save_bars({"MIXED": (bar_aware,)}, exchange="NSE", provider="yfinance")

    loaded = cache.load_bars(exchange="NSE", provider="yfinance")
    assert len(loaded["MIXED"]) == 2
    # Verify first is Jan 1, second is Jan 2
    assert loaded["MIXED"][0].close == 102.0
    assert loaded["MIXED"][1].close == 107.0


def test_get_latest_completed_trading_day_calendar_logic():
    """Verify deterministic resolution of latest completed trading day across sessions, weekends, and holidays."""
    # Scenario 1a: Wednesday 2026-04-22 (session not completed) -> expected Tuesday 2026-04-21 (regular day)
    d_reg = get_latest_completed_trading_day("2026-04-22", session_completed=False)
    assert d_reg == date(2026, 4, 21)

    # Scenario 1b: Wednesday 2026-04-15 -> Tuesday 2026-04-14 is Ambedkar Jayanti holiday, so steps to Monday 2026-04-13
    d1 = get_latest_completed_trading_day("2026-04-15", session_completed=False)
    assert d1 == date(2026, 4, 13)

    # Scenario 2: Wednesday 2026-04-15 (session completed) -> expected Wednesday 2026-04-15
    d2 = get_latest_completed_trading_day("2026-04-15", session_completed=True)
    assert d2 == date(2026, 4, 15)

    # Scenario 3: Weekend (Sunday 2026-04-19) -> expected Friday 2026-04-17
    d3 = get_latest_completed_trading_day(date(2026, 4, 19), session_completed=False)
    assert d3 == date(2026, 4, 17)

    # Scenario 4: Monday 2026-04-13 (session not completed) -> expected prior Friday 2026-04-10
    d4 = get_latest_completed_trading_day(date(2026, 4, 13), session_completed=False)
    assert d4 == date(2026, 4, 10)

    # Scenario 5: Friday 2026-04-10 is a holiday -> steps back to Thursday 2026-04-09
    d5 = get_latest_completed_trading_day(
        date(2026, 4, 13),
        holidays=["2026-04-10"],
        session_completed=False,
    )
    assert d5 == date(2026, 4, 9)


def test_plan_ingestion_missing_and_empty_history(temp_cache_dir: Path):
    """Test 1: Missing and empty history correctly classified as FULL_BACKFILL."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    # Cache has no data at all
    plan = cache.plan_ingestion(
        symbols=["NONEXISTENT", "EMPTY_SYM"],
        target_date="2026-04-15",
    )

    assert len(plan.full_backfill) == 2
    assert "NONEXISTENT" in plan.full_backfill
    assert "EMPTY_SYM" in plan.full_backfill
    assert len(plan.up_to_date) == 0
    assert len(plan.incremental) == 0

    p_non = plan.for_symbol("NONEXISTENT")
    assert p_non is not None
    assert p_non.cohort == IngestionCohort.FULL_BACKFILL
    assert p_non.cached_bars_count == 0
    assert p_non.start_date is None


def test_plan_ingestion_fewer_than_min_bars():
    """Test 2: Fewer than min_bars is ALWAYS FULL_BACKFILL even if latest candle is fresh."""
    base_dt = datetime(2026, 1, 1)
    # 59 bars ending on 2026-04-15 (recent, but 1 short of 60)
    bars_59 = tuple(
        MarketBar(
            timestamp=base_dt + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
        )
        for i in range(59)
    )

    plan = plan_ingestion(
        symbols=["RECENT_SHORT"],
        target_date="2026-04-15",
        cached_bars={"RECENT_SHORT": bars_59},
        min_bars=60,
    )

    assert plan.full_backfill == ("RECENT_SHORT",)
    assert len(plan.up_to_date) == 0
    assert len(plan.incremental) == 0
    assert "Insufficient history" in plan.plans["RECENT_SHORT"].reason


def test_plan_ingestion_fresh_vs_stale_symbols():
    """Test 3: Symbols with sufficient history are correctly partitioned into UP_TO_DATE vs INCREMENTAL_UPDATE."""
    # Target date: Wednesday 2026-04-15 (expected latest completed session: Tuesday 2026-04-14)
    # 1. Fresh symbol ending on 2026-04-14 (>= 60 bars)
    bars_fresh = tuple(
        MarketBar(
            timestamp=datetime(2026, 1, 1) + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
        )
        for i in range(104)  # ends on 2026-04-14
    )

    # 2. Stale symbol ending on 2026-04-05 (missing last 9 days)
    bars_stale = tuple(
        MarketBar(
            timestamp=datetime(2026, 1, 1) + timedelta(days=i),
            open=200.0,
            high=205.0,
            low=195.0,
            close=202.0,
        )
        for i in range(95)  # ends on 2026-04-05
    )

    plan = plan_ingestion(
        symbols=["FRESH_CO", "STALE_CO"],
        target_date=date(2026, 4, 15),
        cached_bars={"FRESH_CO": bars_fresh, "STALE_CO": bars_stale},
        min_bars=60,
        overlap_days=5,
    )

    assert plan.up_to_date == ("FRESH_CO",)
    assert plan.incremental == ("STALE_CO",)
    assert len(plan.full_backfill) == 0

    p_fresh = plan.plans["FRESH_CO"]
    assert p_fresh.cohort == IngestionCohort.UP_TO_DATE
    assert p_fresh.start_date is None

    p_stale = plan.plans["STALE_CO"]
    assert p_stale.cohort == IngestionCohort.INCREMENTAL_UPDATE
    assert p_stale.latest_bar_date == date(2026, 4, 5)
    # Overlap subtraction: 2026-04-05 - 5 days = 2026-03-31
    assert p_stale.start_date == date(2026, 3, 31)
    assert p_stale.start_date_str == "2026-03-31"


def test_plan_ingestion_overlap_calculation():
    """Test 4: Correct calendar-day overlap subtraction, including zero overlap."""
    bars = tuple(
        MarketBar(
            timestamp=datetime(2026, 1, 1) + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
        )
        for i in range(70)  # ends on 2026-03-11
    )

    # Overlap = 7 days
    plan_7 = plan_ingestion(
        symbols=["TCS"],
        target_date="2026-04-15",
        cached_bars={"TCS": bars},
        overlap_days=7,
    )
    assert plan_7.plans["TCS"].start_date == date(2026, 3, 11) - timedelta(days=7)
    assert plan_7.plans["TCS"].start_date == date(2026, 3, 4)

    # Overlap = 0 days
    plan_0 = plan_ingestion(
        symbols=["TCS"],
        target_date="2026-04-15",
        cached_bars={"TCS": bars},
        overlap_days=0,
    )
    assert plan_0.plans["TCS"].start_date == date(2026, 3, 11)


def test_plan_ingestion_invalid_overlap_and_min_bars():
    """Test 5: Negative overlap_days or non-positive min_bars raises ValueError."""
    with pytest.raises(ValueError, match="overlap_days must be non-negative"):
        plan_ingestion(symbols=["INFY"], target_date="2026-04-15", overlap_days=-1)

    with pytest.raises(ValueError, match="min_bars must be positive"):
        plan_ingestion(symbols=["INFY"], target_date="2026-04-15", min_bars=0)


def test_plan_ingestion_multiple_symbols_different_cohorts():
    """Test 6: Multiple symbols correctly partitioned into distinct, mutually exclusive cohorts."""
    # S1: Fresh (100 bars up to 2026-04-14)
    s1_bars = tuple(MarketBar(timestamp=datetime(2026, 1, 1) + timedelta(days=i), open=10, high=11, low=9, close=10) for i in range(104))
    # S2: Stale (100 bars up to 2026-03-01)
    s2_bars = tuple(MarketBar(timestamp=datetime(2025, 11, 20) + timedelta(days=i), open=10, high=11, low=9, close=10) for i in range(100))
    # S3: Short (20 bars)
    s3_bars = tuple(MarketBar(timestamp=datetime(2026, 3, 1) + timedelta(days=i), open=10, high=11, low=9, close=10) for i in range(20))
    # S4: Missing (not in map)

    plan = plan_ingestion(
        symbols=["S1", "S2", "S3", "S4"],
        target_date="2026-04-15",
        cached_bars={"S1": s1_bars, "S2": s2_bars, "S3": s3_bars},
        min_bars=60,
    )

    assert plan.up_to_date == ("S1",)
    assert plan.incremental == ("S2",)
    assert set(plan.full_backfill) == {"S3", "S4"}

    # Mutually exclusive: no symbol in more than one cohort
    all_assigned = list(plan.up_to_date) + list(plan.incremental) + list(plan.full_backfill)
    assert len(all_assigned) == len(set(all_assigned)) == 4


def test_plan_ingestion_unsorted_and_duplicate_timestamps():
    """Test 7: Unsorted bars and duplicate timestamps are handled robustly without corrupting counts."""
    # 1. Duplicate timestamps: 100 bars but only 50 distinct calendar dates
    dup_bars = []
    base_dt = datetime(2026, 1, 1)
    for i in range(50):
        # 2 bars per day
        dup_bars.append(MarketBar(timestamp=base_dt + timedelta(days=i), open=10, high=11, low=9, close=10))
        dup_bars.append(MarketBar(timestamp=base_dt + timedelta(days=i), open=10, high=12, low=9, close=11))

    plan = plan_ingestion(
        symbols=["DUP_SYM"],
        target_date="2026-04-15",
        cached_bars={"DUP_SYM": tuple(dup_bars)},
        min_bars=60,  # 50 unique dates < 60
    )
    # Must be FULL_BACKFILL because unique dates < 60
    assert plan.full_backfill == ("DUP_SYM",)
    assert plan.plans["DUP_SYM"].cached_bars_count == 50

    # 2. Scrambled timestamps with 70 unique dates
    scrambled_bars = list(MarketBar(timestamp=base_dt + timedelta(days=i), open=10, high=11, low=9, close=10) for i in range(70))
    import random
    rng = random.Random(42)
    rng.shuffle(scrambled_bars)

    plan_scrambled = plan_ingestion(
        symbols=["SCRAMBLED"],
        target_date="2026-04-15",
        cached_bars={"SCRAMBLED": tuple(scrambled_bars)},
        min_bars=60,
    )
    # Latest bar is properly detected as base_dt + 69 days (2026-03-11)
    assert plan_scrambled.plans["SCRAMBLED"].latest_bar_date == date(2026, 3, 11)
    assert plan_scrambled.incremental == ("SCRAMBLED",)


def test_plan_ingestion_malformed_history_not_up_to_date():
    """Test 8: Malformed objects without timestamp or non-datetime timestamps are ignored safely."""
    # 70 items, but 30 have invalid timestamps
    bars = []
    base_dt = datetime(2026, 1, 1)
    for i in range(40):
        bars.append(MarketBar(timestamp=base_dt + timedelta(days=i), open=10, high=11, low=9, close=10))
    for i in range(30):
        # Malformed bar with None timestamp
        bars.append(MarketBar(timestamp=None, open=10, high=11, low=9, close=10))  # type: ignore

    plan = plan_ingestion(
        symbols=["MALFORMED"],
        target_date="2026-04-15",
        cached_bars={"MALFORMED": tuple(bars)},
        min_bars=60,
    )
    # Valid count is only 40 (< 60), must be FULL_BACKFILL
    assert plan.full_backfill == ("MALFORMED",)
    assert plan.plans["MALFORMED"].cached_bars_count == 40


def test_plan_ingestion_deterministic_reproducibility():
    """Test 9: Identical inputs produce bit-identical plans regardless of invocation time."""
    bars = tuple(
        MarketBar(timestamp=datetime(2026, 1, 1) + timedelta(days=i), open=10, high=11, low=9, close=10)
        for i in range(100)
    )
    target = "2026-04-15"

    plans = [
        plan_ingestion(
            symbols=["A", "B"],
            target_date=target,
            cached_bars={"A": bars},
            overlap_days=5,
            min_bars=60,
        )
        for _ in range(5)
    ]

    for p in plans[1:]:
        assert p == plans[0]


def test_plan_ingestion_no_cache_mutation_or_network_calls(temp_cache_dir: Path):
    """Test 10: Ingestion planning performs ZERO cache mutations and ZERO disk modifications."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    sample_bars = tuple(
        MarketBar(timestamp=datetime(2026, 1, 1) + timedelta(days=i), open=10, high=11, low=9, close=10)
        for i in range(70)
    )
    cache.save_bars({"MUT_TEST": sample_bars}, exchange="NSE", provider="yfinance")

    target_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    assert target_file.is_file()
    initial_bytes = target_file.read_bytes()
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()
    initial_mtime = target_file.stat().st_mtime_ns

    # Plan ingestion
    plan = cache.plan_ingestion(
        symbols=["MUT_TEST", "UNCACHED"],
        target_date="2026-04-15",
        exchange="NSE",
        provider="yfinance",
    )

    assert plan.plans["MUT_TEST"].cohort == IngestionCohort.INCREMENTAL_UPDATE
    assert plan.plans["UNCACHED"].cohort == IngestionCohort.FULL_BACKFILL

    # Confirm zero file mutation
    assert target_file.read_bytes() == initial_bytes
    assert hashlib.sha256(target_file.read_bytes()).hexdigest() == initial_hash
    assert target_file.stat().st_mtime_ns == initial_mtime


def test_plan_ingestion_symbol_normalization_and_deduplication():
    """Test symbol normalization: casing, whitespace, and deduplication handled cleanly."""
    plan = plan_ingestion(
        symbols=["infy", "  INFY  ", "tcs", "TCS", " "],
        target_date="2026-04-15",
        cached_bars={},
    )

    assert set(plan.plans.keys()) == {"INFY", "TCS"}
    assert len(plan.full_backfill) == 2
    assert "INFY" in plan.full_backfill
    assert "TCS" in plan.full_backfill


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


def test_warm_reads_avoid_deserialization(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 1: After initial load, repeated warm reads do NOT call pickle.load()."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("RELIANCE", 20)
    cache.save_bars({"RELIANCE": bars})

    # Fresh instance starts cold
    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)
    initial_load = fresh_cache.load_bars()
    assert "RELIANCE" in initial_load
    assert len(initial_load["RELIANCE"]) == 20

    # Hook pickle.load to ensure zero calls on warm reads
    load_count = 0
    orig_load = pickle.load

    def counting_load(*args, **kwargs):
        nonlocal load_count
        load_count += 1
        return orig_load(*args, **kwargs)

    monkeypatch.setattr(pickle, "load", counting_load)

    # Perform multiple warm reads and get_bars_for_symbols
    warm_1 = fresh_cache.load_bars()
    warm_2 = fresh_cache.load_bars()
    found, missing = fresh_cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)

    assert load_count == 0, f"Expected 0 pickle.load calls on warm reads, got {load_count}"
    assert warm_1["RELIANCE"] == initial_load["RELIANCE"]
    assert warm_2["RELIANCE"] == initial_load["RELIANCE"]
    assert found["RELIANCE"] == initial_load["RELIANCE"]
    assert missing == []


def test_concurrent_cold_loads(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 2: Concurrent requests for same namespace cause only one cold deserialization."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("TCS", 30)
    cache.save_bars({"TCS": bars})

    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    load_count = 0
    load_lock = threading.Lock()
    orig_load = pickle.load

    def counting_load(*args, **kwargs):
        nonlocal load_count
        with load_lock:
            load_count += 1
        return orig_load(*args, **kwargs)

    monkeypatch.setattr(pickle, "load", counting_load)

    results: list[dict] = [{} for _ in range(5)]
    errors: list[Exception] = []
    barrier = threading.Barrier(5)

    def worker(idx: int):
        try:
            barrier.wait(timeout=5.0)
            results[idx] = fresh_cache.load_bars()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors, f"Errors in worker threads: {errors}"
    assert load_count == 1, f"Expected exactly 1 cold deserialization, got {load_count}"
    for idx, r in enumerate(results):
        assert "TCS" in r, f"Thread {idx} result missing TCS"
        assert len(r["TCS"]) == 30


def test_warm_read_during_blocked_fsync(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 3: Warm reader finishes and observes complete previous snapshot while writer is blocked in fsync."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_a = _make_test_bars("INFY", 10, start_day=1, price_base=100.0)
    cache.save_bars({"INFY": bars_a})
    # Warm up cache
    warm_init = cache.load_bars()
    assert len(warm_init["INFY"]) == 10

    fsync_reached = threading.Event()
    allow_fsync = threading.Event()
    orig_fsync = os.fsync

    def blocking_fsync(fd):
        fsync_reached.set()
        if not allow_fsync.wait(timeout=5.0):
            raise TimeoutError("Test timed out waiting for allow_fsync")
        return orig_fsync(fd)

    monkeypatch.setattr(os, "fsync", blocking_fsync)

    bars_b = _make_test_bars("INFY", 5, start_day=11, price_base=200.0)
    writer_errors: list[Exception] = []

    def writer():
        try:
            res = cache.save_bars({"INFY": bars_b})
            if res is None:
                writer_errors.append(RuntimeError("save_bars returned None"))
        except Exception as exc:
            writer_errors.append(exc)

    t_writer = threading.Thread(target=writer)
    t_writer.start()

    try:
        assert fsync_reached.wait(timeout=5.0), "Writer failed to reach fsync within timeout"
        # While writer is blocked inside fsync under _write_lock, warm read acquires _snapshot_lock briefly
        warm_read = cache.load_bars()
        # Must observe complete previous snapshot A without blocking
        assert "INFY" in warm_read
        assert len(warm_read["INFY"]) == 10
        assert warm_read["INFY"][-1].close == bars_a[-1].close
    finally:
        allow_fsync.set()
        t_writer.join(timeout=5.0)
        assert not t_writer.is_alive()

    assert not writer_errors, f"Writer thread failed: {writer_errors}"

    # Once writer finishes and commits, subsequent load observes updated snapshot
    after_load = cache.load_bars()
    assert len(after_load["INFY"]) == 15


def test_publication_after_commit(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 4: New data is NOT visible before successful replacement, and becomes visible immediately after."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_a = _make_test_bars("HDFC", 10, start_day=1)
    cache.save_bars({"HDFC": bars_a})
    cache.load_bars()

    replace_reached = threading.Event()
    allow_replace = threading.Event()
    orig_replace = os.replace

    def hooked_replace(src, dst):
        replace_reached.set()
        if not allow_replace.wait(timeout=5.0):
            raise TimeoutError("Test timed out waiting for allow_replace")
        return orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", hooked_replace)

    bars_b = _make_test_bars("HDFC", 5, start_day=11)
    writer_errors: list[Exception] = []

    def writer():
        try:
            cache.save_bars({"HDFC": bars_b})
        except Exception as exc:
            writer_errors.append(exc)

    t_writer = threading.Thread(target=writer)
    t_writer.start()

    try:
        assert replace_reached.wait(timeout=5.0), "Writer failed to reach replace within timeout"
        # Before atomic replacement commits, reader sees prior snapshot
        res_before = cache.load_bars()
        assert len(res_before["HDFC"]) == 10
    finally:
        allow_replace.set()
        t_writer.join(timeout=5.0)
        assert not t_writer.is_alive()

    assert not writer_errors
    res_after = cache.load_bars()
    assert len(res_after["HDFC"]) == 15


def test_pickle_write_flush_fsync_failures(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 5: Failures during pickle dump or fsync do not publish uncommitted snapshot; prior state remains valid."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_a = _make_test_bars("WIPRO", 10)
    cache.save_bars({"WIPRO": bars_a})
    cache.load_bars()

    def failing_dump(*args, **kwargs):
        raise OSError("Simulated disk write failure during dump")

    monkeypatch.setattr(pickle, "dump", failing_dump)

    bars_b = _make_test_bars("WIPRO", 5, start_day=11)
    result = cache.save_bars({"WIPRO": bars_b})
    assert result is None

    # Resident cache still has previous snapshot A
    resident = cache.load_bars()
    assert len(resident["WIPRO"]) == 10

    # Temp file was cleaned up
    temp_file = temp_cache_dir / "bars_NSE_yfinance.pkl.tmp"
    assert not temp_file.exists()


def test_replacement_failure(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 6: Failure during os.replace leaves prior destination and resident state intact, and attempts cleanup."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_a = _make_test_bars("BHARTIARTL", 10)
    cache.save_bars({"BHARTIARTL": bars_a})
    cache.load_bars()

    def failing_replace(src, dst):
        raise OSError("Simulated atomic replacement failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    bars_b = _make_test_bars("BHARTIARTL", 5, start_day=11)
    result = cache.save_bars({"BHARTIARTL": bars_b})
    assert result is None

    # Resident cache untouched
    assert len(cache.load_bars()["BHARTIARTL"]) == 10

    # Destination on disk untouched
    monkeypatch.undo()
    disk_data = pickle.loads((temp_cache_dir / "bars_NSE_yfinance.pkl").read_bytes())
    assert len(disk_data["BHARTIARTL"]) == 10

    # Temp file cleaned up
    temp_file = temp_cache_dir / "bars_NSE_yfinance.pkl.tmp"
    assert not temp_file.exists()


def test_cleanup_failure(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    """Behavior 7: Original failure remains visible, cleanup failure is logged separately, returns None."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("ICICIBANK", 5)

    def failing_dump(*args, **kwargs):
        raise OSError("Primary disk serialization failure")

    def failing_unlink(self):
        raise PermissionError("Secondary cleanup permission failure")

    monkeypatch.setattr(pickle, "dump", failing_dump)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with caplog.at_level(logging.WARNING):
        result = cache.save_bars({"ICICIBANK": bars})

    assert result is None
    assert "Failed to persist bars" in caplog.text
    assert "Failed to clean temporary file" in caplog.text


def test_successful_save_matches_persisted_merged_data(temp_cache_dir: Path):
    """Behavior 8: Resident snapshot exactly matches the persisted merged data with immutable tuples."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_rel = _make_test_bars("RELIANCE", 10, start_day=1)
    bars_tcs = _make_test_bars("TCS", 15, start_day=1)
    cache.save_bars({"RELIANCE": bars_rel, "TCS": bars_tcs})

    # Save additional incremental bars for RELIANCE
    bars_rel_new = _make_test_bars("RELIANCE", 5, start_day=11)
    cache.save_bars({"RELIANCE": bars_rel_new})

    resident = cache.load_bars()
    target_path = temp_cache_dir / "bars_NSE_yfinance.pkl"
    disk_data = pickle.loads(target_path.read_bytes())

    assert len(resident) == len(disk_data)
    for sym in ("RELIANCE", "TCS"):
        assert sym in resident and sym in disk_data
        assert resident[sym] == disk_data[sym]
        assert isinstance(resident[sym], tuple)


def test_clear_success(temp_cache_dir: Path):
    """Behavior 9: Successful clear evicts resident snapshot and deletes file; subsequent loads return empty."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("ITC", 10)
    cache.save_bars({"ITC": bars})
    assert len(cache.load_bars()["ITC"]) == 10

    res = cache.clear()
    assert res is True

    # File on disk gone
    target_path = temp_cache_dir / "bars_NSE_yfinance.pkl"
    assert not target_path.exists()

    # In-memory snapshot evicted
    assert ("NSE", "yfinance") not in cache._snapshots

    # Subsequent loads return empty
    assert cache.load_bars() == {}
    found, missing = cache.get_bars_for_symbols(["ITC"])
    assert found == {}
    assert missing == ["ITC"]


def test_clear_failure_fails_closed(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Behavior 10: Clear failure fails closed; does not silently reload stale disk contents."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("MARUTI", 10)
    cache.save_bars({"MARUTI": bars})
    cache.load_bars()

    target_path = temp_cache_dir / "bars_NSE_yfinance.pkl"
    assert target_path.is_file()

    def failing_unlink(self):
        raise PermissionError("Simulated locked file on delete")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    res = cache.clear()
    assert res is False

    # File still exists on disk
    assert target_path.is_file()

    # Implementation must fail closed for this namespace
    assert ("NSE", "yfinance") in cache._uncertain_namespaces
    assert cache.load_bars() == {}

    found, missing = cache.get_bars_for_symbols(["MARUTI"])
    assert found == {}
    assert missing == ["MARUTI"]

    # When a subsequent save succeeds, certainty is restored
    monkeypatch.undo()
    new_bars = _make_test_bars("MARUTI", 5, start_day=1)
    save_res = cache.save_bars({"MARUTI": new_bars})
    assert save_res is not None
    assert ("NSE", "yfinance") not in cache._uncertain_namespaces
    assert len(cache.load_bars()["MARUTI"]) == 5


def test_save_clear_race(temp_cache_dir: Path):
    """Behavior 11: Saves and clears serialize cleanly under _write_lock without deadlocks or corrupt state."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("AXISBANK", 10)
    cache.save_bars({"AXISBANK": bars})

    barrier = threading.Barrier(2)
    thread_errors: list[Exception] = []

    def saver():
        try:
            barrier.wait(timeout=5.0)
            cache.save_bars({"AXISBANK": _make_test_bars("AXISBANK", 5, start_day=11)})
        except Exception as exc:
            thread_errors.append(exc)

    def clearer():
        try:
            barrier.wait(timeout=5.0)
            cache.clear()
        except Exception as exc:
            thread_errors.append(exc)

    t1 = threading.Thread(target=saver)
    t2 = threading.Thread(target=clearer)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert not thread_errors

    # State must be consistent: either cleared (empty) or save ran after clear
    loaded = cache.load_bars()
    assert isinstance(loaded, dict)
    if "AXISBANK" in loaded:
        assert len(loaded["AXISBANK"]) in (5, 15)


def test_concurrent_saves_no_lost_updates(temp_cache_dir: Path):
    """Behavior 12: Concurrent saves serialize and preserve all symbol batches without lost updates."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    barrier = threading.Barrier(3)
    thread_errors: list[Exception] = []

    symbols = ["SYM_ALPHA", "SYM_BETA", "SYM_GAMMA"]

    def worker(sym: str):
        try:
            barrier.wait(timeout=5.0)
            bars = _make_test_bars(sym, 10)
            res = cache.save_bars({sym: bars})
            if res is None:
                thread_errors.append(RuntimeError(f"save_bars failed for {sym}"))
        except Exception as exc:
            thread_errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in symbols]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not thread_errors
    loaded = cache.load_bars()
    for s in symbols:
        assert s in loaded, f"Symbol {s} was lost in concurrent saves"
        assert len(loaded[s]) == 10


def test_namespace_isolation(temp_cache_dir: Path):
    """Behavior 13: Separate (exchange, provider) namespaces remain independent in memory and on disk."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("KOTAKBANK", 10)

    cache.save_bars({"KOTAKBANK": bars}, exchange="NSE", provider="yfinance")
    cache.save_bars({"KOTAKBANK": bars}, exchange="BSE", provider="yfinance")
    cache.save_bars({"KOTAKBANK": bars}, exchange="NSE", provider="zerodha")

    # Clear NSE yfinance
    assert cache.clear(exchange="NSE", provider="yfinance") is True

    # NSE yfinance must be empty
    assert cache.load_bars(exchange="NSE", provider="yfinance") == {}
    assert not (temp_cache_dir / "bars_NSE_yfinance.pkl").exists()

    # BSE yfinance and NSE zerodha must remain intact
    bse_yf = cache.load_bars(exchange="BSE", provider="yfinance")
    assert "KOTAKBANK" in bse_yf
    assert len(bse_yf["KOTAKBANK"]) == 10
    assert (temp_cache_dir / "bars_BSE_yfinance.pkl").is_file()

    nse_zd = cache.load_bars(exchange="NSE", provider="zerodha")
    assert "KOTAKBANK" in nse_zd
    assert len(nse_zd["KOTAKBANK"]) == 10
    assert (temp_cache_dir / "bars_NSE_zerodha.pkl").is_file()


def test_mutation_isolation(temp_cache_dir: Path):
    """Behavior 14: Modifying returned dictionary does not mutate resident state; bars and tuples are immutable."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("LT", 10)
    cache.save_bars({"LT": bars})

    loaded = cache.load_bars()

    # 1. Caller mutates returned dictionary
    loaded["MUTATED_KEY"] = ()
    loaded["LT"] = ()
    del loaded["LT"]

    # Subsequent load must be unaffected
    fresh_loaded = cache.load_bars()
    assert "MUTATED_KEY" not in fresh_loaded
    assert "LT" in fresh_loaded
    assert len(fresh_loaded["LT"]) == 10

    # 2. Sequence inside cache is immutable tuple
    assert isinstance(fresh_loaded["LT"], tuple)

    # 3. MarketBar fields are immutable (frozen dataclass)
    bar = fresh_loaded["LT"][0]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        bar.close = 99999.0  # type: ignore


# ===========================================================================
# Stage 5F: Symbol-Partitioned Historical Bars Cache Tests
# ===========================================================================

def test_partition_cold_read_single_symbol_isolation(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5F: Loading one symbol's historical bars deserializes ONLY that symbol's partition file."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_rel = _make_test_bars("RELIANCE", 25)
    bars_tcs = _make_test_bars("TCS", 30)
    bars_infy = _make_test_bars("INFY", 20)
    cache.save_bars({"RELIANCE": bars_rel, "TCS": bars_tcs, "INFY": bars_infy})

    # Verify partition files exist on disk
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert (part_dir / "RELIANCE.pkl").is_file()
    assert (part_dir / "TCS.pkl").is_file()
    assert (part_dir / "INFY.pkl").is_file()

    # Fresh instance starts cold with empty in-memory snapshots
    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    opened_files: list[str] = []
    orig_load = pickle.load

    def spy_pickle_load(fh, *args, **kwargs):
        name = getattr(fh, "name", str(fh))
        opened_files.append(Path(name).name)
        return orig_load(fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", spy_pickle_load)

    # Request ONLY RELIANCE
    found, missing = fresh_cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)

    # 1. Correct data returned
    assert "RELIANCE" in found
    assert len(found["RELIANCE"]) == 25
    assert missing == []

    # 2. Deserialization isolation: ONLY RELIANCE.pkl was loaded!
    assert len(opened_files) == 1, f"Expected 1 deserialization, got: {opened_files}"
    assert opened_files[0] == "RELIANCE.pkl"
    assert "TCS.pkl" not in opened_files
    assert "INFY.pkl" not in opened_files
    assert "bars_NSE_yfinance.pkl" not in opened_files


def test_partition_legacy_fallback_with_explicit_cost_warning(temp_cache_dir: Path, caplog: pytest.LogCaptureFixture):
    """Stage 5F: If partition is absent but legacy monolithic cache exists, falls back safely with explicit warning."""
    # Create synthetic legacy monolithic cache file directly
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars = _make_test_bars("LEGACY_CO", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"LEGACY_CO": bars}, fh)

    # Ensure no partition directory exists
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert not part_dir.exists()

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    with caplog.at_level(logging.WARNING):
        found, missing = cache.get_bars_for_symbols(["LEGACY_CO"], min_bars=10)

    assert "LEGACY_CO" in found
    assert len(found["LEGACY_CO"]) == 15
    assert missing == []

    # Verify explicit cost warning is logged
    assert "Partition for 'LEGACY_CO' absent" in caplog.text
    assert "Falling back to legacy monolithic cache" in caplog.text
    assert "expensive whole-universe deserialization" in caplog.text

    # Verify no silent empty partition was created
    assert not (part_dir / "LEGACY_CO.pkl").exists()


def test_partition_explicit_migration_utility(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5F: Explicit migration splits legacy monolithic file into symbol partitions without altering legacy file."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_1 = _make_test_bars("SYM_ONE", 20)
    bars_2 = _make_test_bars("SYM_TWO", 15)
    payload = {"SYM_ONE": bars_1, "SYM_TWO": bars_2}
    with open(legacy_file, "wb") as fh:
        pickle.dump(payload, fh)

    initial_legacy_bytes = legacy_file.read_bytes()
    initial_legacy_hash = hashlib.sha256(initial_legacy_bytes).hexdigest()

    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    migrated_count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")

    assert migrated_count == 2

    # Verify original legacy monolithic cache is 100% untouched
    assert legacy_file.read_bytes() == initial_legacy_bytes
    assert hashlib.sha256(legacy_file.read_bytes()).hexdigest() == initial_legacy_hash

    # Verify partition files now exist
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert (part_dir / "SYM_ONE.pkl").is_file()
    assert (part_dir / "SYM_TWO.pkl").is_file()

    # Now verify cold load of SYM_ONE uses the partition without opening the legacy file
    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)
    opened: list[str] = []
    orig_load = pickle.load

    def spy_load(fh, *args, **kwargs):
        opened.append(Path(getattr(fh, "name", str(fh))).name)
        return orig_load(fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", spy_load)

    found, missing = fresh_cache.get_bars_for_symbols(["SYM_ONE"], min_bars=10)
    assert "SYM_ONE" in found
    assert len(found["SYM_ONE"]) == 20
    assert opened == ["SYM_ONE.pkl"]
    assert "bars_NSE_yfinance.pkl" not in opened


def test_partition_concurrent_cold_reads(temp_cache_dir: Path):
    """Stage 5F: Concurrent cold requests for the same partitioned symbol execute safely without race conditions."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("CONCURRENT_SYM", 25)
    cache.save_bars({"CONCURRENT_SYM": bars})

    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    results: list[dict] = [{} for _ in range(6)]
    errors: list[Exception] = []
    barrier = threading.Barrier(6)

    def worker(idx: int):
        try:
            barrier.wait(timeout=5.0)
            f, m = fresh_cache.get_bars_for_symbols(["CONCURRENT_SYM"], min_bars=10)
            results[idx] = f
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors
    for r in results:
        assert "CONCURRENT_SYM" in r
        assert len(r["CONCURRENT_SYM"]) == 25


def test_partition_empty_update_safety(temp_cache_dir: Path):
    """Stage 5F: Empty updates to a symbol do not erase or corrupt existing partitioned history."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("SAFE_SYM", 20)
    cache.save_bars({"SAFE_SYM": bars})

    # Empty update via ()
    cache.save_bars({"SAFE_SYM": ()})
    found, _ = cache.get_bars_for_symbols(["SAFE_SYM"], min_bars=10)
    assert len(found["SAFE_SYM"]) == 20

    # Empty update via []
    cache.save_bars({"SAFE_SYM": []})
    found, _ = cache.get_bars_for_symbols(["SAFE_SYM"], min_bars=10)
    assert len(found["SAFE_SYM"]) == 20

    # Empty dict
    assert cache.save_bars({}) is None
    found, _ = cache.get_bars_for_symbols(["SAFE_SYM"], min_bars=10)
    assert len(found["SAFE_SYM"]) == 20


def test_partition_atomic_failure_cleanup(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5F: Failure during partition replacement leaves prior partition intact and cleans .tmp."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_initial = _make_test_bars("FAIL_SAFE", 10)
    cache.save_bars({"FAIL_SAFE": bars_initial})

    part_file = temp_cache_dir / "bars" / "NSE_yfinance" / "FAIL_SAFE.pkl"
    assert part_file.is_file()
    initial_bytes = part_file.read_bytes()

    # Simulate replacement failure
    def failing_replace(src, dst):
        raise OSError("Simulated replacement failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    bars_new = _make_test_bars("FAIL_SAFE", 5, start_day=11)
    res = cache.save_bars({"FAIL_SAFE": bars_new})
    assert res is None

    # Verify no .tmp file left behind in partition directory
    tmp_files = list((temp_cache_dir / "bars" / "NSE_yfinance").glob("*.tmp"))
    assert not tmp_files

    # Verify prior partition file was not corrupted
    monkeypatch.undo()
    assert part_file.read_bytes() == initial_bytes


def test_partition_clear_deletes_partitions_and_monolithic(temp_cache_dir: Path):
    """Stage 5F: clear() deletes both the monolithic file and all partition files in the directory."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars = _make_test_bars("CLEAR_SYM", 10)
    cache.save_bars({"CLEAR_SYM": bars})

    mono_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    part_file = temp_cache_dir / "bars" / "NSE_yfinance" / "CLEAR_SYM.pkl"
    assert mono_file.is_file()
    assert part_file.is_file()

    assert cache.clear() is True

    assert not mono_file.exists()
    assert not part_file.exists()
    assert not (temp_cache_dir / "bars" / "NSE_yfinance").exists()

    found, missing = cache.get_bars_for_symbols(["CLEAR_SYM"])
    assert found == {}
    assert missing == ["CLEAR_SYM"]


def test_partition_special_character_symbol_handling(temp_cache_dir: Path):
    """Stage 5F: Symbols with reserved filesystem characters are safely encoded and retrievable."""
    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    bars_mm = _make_test_bars("M&M", 15)
    bars_slash = _make_test_bars("TICK/B", 12)
    cache.save_bars({"M&M": bars_mm, "TICK/B": bars_slash})

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert (part_dir / "M&M.pkl").is_file()
    # / encoded as %2F
    assert (part_dir / "TICK%2FB.pkl").is_file()

    found, missing = cache.get_bars_for_symbols(["M&M", "TICK/B"], min_bars=10)
    assert len(found["M&M"]) == 15
    assert len(found["TICK/B"]) == 12
    assert missing == []


def test_partial_partition_directory_preserves_legacy_symbols(temp_cache_dir: Path):
    """Stage 5G-B: The presence of partition files does not hide unmigrated legacy symbols from load_bars or get_bars_for_symbols."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    bars_b = _make_test_bars("SYM_B", 20)
    bars_c = _make_test_bars("SYM_C", 25)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a, "SYM_B": bars_b, "SYM_C": bars_c}, fh)

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    part_dir.mkdir(parents=True, exist_ok=True)
    bars_a_updated = _make_test_bars("SYM_A", 18)
    with open(part_dir / "SYM_A.pkl", "wb") as pfh:
        pickle.dump(bars_a_updated, pfh)

    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    all_bars = fresh_cache.load_bars()
    assert "SYM_A" in all_bars
    assert "SYM_B" in all_bars
    assert "SYM_C" in all_bars
    assert len(all_bars["SYM_A"]) == 18  # partition override
    assert len(all_bars["SYM_B"]) == 20  # preserved from legacy
    assert len(all_bars["SYM_C"]) == 25  # preserved from legacy

    found, missing = fresh_cache.get_bars_for_symbols(["SYM_A", "SYM_B", "SYM_C", "SYM_MISSING"], min_bars=10)
    assert "SYM_A" in found and len(found["SYM_A"]) == 18
    assert "SYM_B" in found and len(found["SYM_B"]) == 20
    assert "SYM_C" in found and len(found["SYM_C"]) == 25
    assert missing == ["SYM_MISSING"]


def test_partition_hit_does_not_deserialize_legacy_cache(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5G-B: A chart/symbol request for a partitioned symbol loads only its partition and never touches legacy cache."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_legacy = _make_test_bars("SYM_LEGACY", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_LEGACY": bars_legacy}, fh)

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    part_dir.mkdir(parents=True, exist_ok=True)
    bars_reliance = _make_test_bars("RELIANCE", 30)
    with open(part_dir / "RELIANCE.pkl", "wb") as pfh:
        pickle.dump(bars_reliance, pfh)

    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    opened_files: list[str] = []
    orig_load = pickle.load

    def spy_load(fh, *args, **kwargs):
        name = Path(getattr(fh, "name", str(fh))).name
        opened_files.append(name)
        return orig_load(fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", spy_load)

    # Cold read for RELIANCE
    found, missing = fresh_cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)
    assert "RELIANCE" in found
    assert len(found["RELIANCE"]) == 30
    assert missing == []
    assert opened_files == ["RELIANCE.pkl"]
    assert "bars_NSE_yfinance.pkl" not in opened_files

    # Warm read for RELIANCE
    opened_files.clear()
    found_warm, _ = fresh_cache.get_bars_for_symbols(["RELIANCE"], min_bars=10)
    assert "RELIANCE" in found_warm
    assert opened_files == []  # 0 deserializations on warm read


def test_missing_partition_does_not_cause_repeated_full_market_reloads(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5G-B: When requested symbol has no partition, fallback loads legacy once and does not reload on subsequent misses."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a}, fh)

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    part_dir.mkdir(parents=True, exist_ok=True)
    with open(part_dir / "SYM_PART.pkl", "wb") as pfh:
        pickle.dump(_make_test_bars("SYM_PART", 20), pfh)

    fresh_cache = MarketBarsCache(cache_dir=temp_cache_dir)

    monolithic_loads = 0
    orig_load = pickle.load

    def spy_load(fh, *args, **kwargs):
        nonlocal monolithic_loads
        name = Path(getattr(fh, "name", str(fh))).name
        if name == "bars_NSE_yfinance.pkl":
            monolithic_loads += 1
        return orig_load(fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", spy_load)

    # 1. Request SYM_A (no partition, present in legacy)
    found, missing = fresh_cache.get_bars_for_symbols(["SYM_A"], min_bars=10)
    assert "SYM_A" in found
    assert monolithic_loads == 1

    # 2. Request SYM_UNKNOWN_1 (no partition, not in legacy)
    found2, missing2 = fresh_cache.get_bars_for_symbols(["SYM_UNKNOWN_1"], min_bars=10)
    assert "SYM_UNKNOWN_1" in missing2
    assert monolithic_loads == 1  # Did NOT reload monolithic file!

    # 3. Request SYM_UNKNOWN_2 (another missing symbol)
    found3, missing3 = fresh_cache.get_bars_for_symbols(["SYM_UNKNOWN_2"], min_bars=10)
    assert "SYM_UNKNOWN_2" in missing3
    assert monolithic_loads == 1  # Still 1, no reload!


def test_staged_migration_success_and_preservation(temp_cache_dir: Path):
    """Stage 5G-C: migrate_legacy_bars stages partitions, validates them, and atomically publishes to destination."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    bars_b = _make_test_bars("SYM_B", 20)
    bars_c = _make_test_bars("SYM_C", 25)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a, "SYM_B": bars_b, "SYM_C": bars_c}, fh)

    initial_bytes = legacy_file.read_bytes()
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    cache = MarketBarsCache(cache_dir=temp_cache_dir)
    count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count == 3

    # Legacy file is byte-identical
    assert legacy_file.read_bytes() == initial_bytes
    assert hashlib.sha256(legacy_file.read_bytes()).hexdigest() == initial_hash

    # Staging directory was cleaned up upon successful publication
    staging_dir = temp_cache_dir / "bars" / "NSE_yfinance.staging"
    assert not staging_dir.exists()

    # Destination exists and has all 3 symbols
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert part_dir.is_dir()
    assert (part_dir / "SYM_A.pkl").is_file()
    assert (part_dir / "SYM_B.pkl").is_file()
    assert (part_dir / "SYM_C.pkl").is_file()

    # Deserialized bar counts and timestamps match
    for sym, exp_bars in [("SYM_A", bars_a), ("SYM_B", bars_b), ("SYM_C", bars_c)]:
        with open(part_dir / f"{sym}.pkl", "rb") as pfh:
            loaded = pickle.load(pfh)
        assert len(loaded) == len(exp_bars)
        assert loaded[0].timestamp == exp_bars[0].timestamp


def test_staged_migration_failure_during_partition_writing(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5G-C: Failure while writing to staging cleans staging artifacts and leaves destination absent and legacy intact."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    bars_b = _make_test_bars("SYM_B", 20)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a, "SYM_B": bars_b}, fh)

    initial_bytes = legacy_file.read_bytes()
    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    orig_dump = pickle.dump
    dump_count = 0

    def failing_dump(obj, file, *args, **kwargs):
        nonlocal dump_count
        dump_count += 1
        if dump_count >= 2:
            raise OSError("Simulated disk full during partition writing")
        return orig_dump(obj, file, *args, **kwargs)

    monkeypatch.setattr(pickle, "dump", failing_dump)

    count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count == 0

    # Destination was never created
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert not part_dir.exists()

    # Staging directory was cleaned up
    staging_dir = temp_cache_dir / "bars" / "NSE_yfinance.staging"
    assert not staging_dir.exists()

    # Legacy file is untouched
    monkeypatch.undo()
    assert legacy_file.read_bytes() == initial_bytes

    # Readers still function cleanly and find symbols in legacy cache
    found, missing = cache.get_bars_for_symbols(["SYM_A", "SYM_B"], min_bars=10)
    assert "SYM_A" in found and "SYM_B" in found
    assert missing == []


def test_staged_migration_failure_during_validation(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5G-C: If staged output fails validation, publication is aborted and staging cleaned."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a}, fh)

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    orig_load = pickle.load

    def corrupting_load(fh, *args, **kwargs):
        name = Path(getattr(fh, "name", str(fh))).name
        # During validation step (loading SYM_A.pkl from staging), return corrupted payload
        if name == "SYM_A.pkl":
            return ("not_a_market_bar",)
        return orig_load(fh, *args, **kwargs)

    monkeypatch.setattr(pickle, "load", corrupting_load)

    count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count == 0

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert not part_dir.exists()
    staging_dir = temp_cache_dir / "bars" / "NSE_yfinance.staging"
    assert not staging_dir.exists()


def test_staged_migration_publication_failure(temp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Stage 5G-C: If directory publication fails, staging is cleaned and destination is not left corrupted."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a}, fh)

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    def failing_replace(src, dst):
        raise PermissionError("Simulated publication lock failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count == 0

    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert not part_dir.exists()
    staging_dir = temp_cache_dir / "bars" / "NSE_yfinance.staging"
    assert not staging_dir.exists()


def test_staged_migration_existing_destination_handling(temp_cache_dir: Path):
    """Stage 5G-C: Existing complete destination is recognized without re-work; incomplete destination is not altered."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    bars_b = _make_test_bars("SYM_B", 20)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a, "SYM_B": bars_b}, fh)

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    # 1. First migration succeeds
    count1 = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count1 == 2

    # 2. Second migration on complete destination recognizes complete publication and skips safely
    count2 = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance", overwrite=False)
    assert count2 == 2

    # 3. Simulate existing incomplete destination (e.g. only SYM_A present for a 2-symbol legacy dataset)
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    (part_dir / "SYM_B.pkl").unlink()
    assert (part_dir / "SYM_A.pkl").is_file()
    assert not (part_dir / "SYM_B.pkl").exists()

    count3 = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance", overwrite=False)
    assert count3 == 0  # Safely refuses destructive alteration
    # SYM_A remains untouched
    assert (part_dir / "SYM_A.pkl").is_file()


def test_staged_migration_stale_staging_cleaned_and_ignored(temp_cache_dir: Path):
    """Stage 5G-C: Stale staging directory is cleaned before migration, and readers never read from staging."""
    legacy_file = temp_cache_dir / "bars_NSE_yfinance.pkl"
    bars_a = _make_test_bars("SYM_A", 15)
    with open(legacy_file, "wb") as fh:
        pickle.dump({"SYM_A": bars_a}, fh)

    cache = MarketBarsCache(cache_dir=temp_cache_dir)

    # Create leftover stale staging artifacts
    staging_dir = temp_cache_dir / "bars" / "NSE_yfinance.staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "CORRUPTED.pkl").write_bytes(b"garbage")
    (staging_dir / "LEFTOVER.tmp").write_bytes(b"garbage")

    # Verify normal readers do NOT read from staging
    found, missing = cache.get_bars_for_symbols(["CORRUPTED"], min_bars=5)
    assert "CORRUPTED" in missing

    # Migration cleans stale staging and publishes complete partition
    count = cache.migrate_legacy_bars(exchange="NSE", provider="yfinance")
    assert count == 1

    assert not staging_dir.exists()
    part_dir = temp_cache_dir / "bars" / "NSE_yfinance"
    assert (part_dir / "SYM_A.pkl").is_file()
    assert not (part_dir / "CORRUPTED.pkl").exists()





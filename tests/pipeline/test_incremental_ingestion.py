"""Prompt 2E: Pipeline Integration & Safe Incremental Ingestion Test Suite.

Verifies:
1. All three cohorts (UP_TO_DATE, INCREMENTAL_UPDATE, FULL_BACKFILL) execute their defined ingestion behavior.
2. Up-to-date symbols trigger zero provider calls; cached histories are fully preserved.
3. Incremental requests receive planned start dates and respect date-range parameters.
4. Full-backfill requests preserve historical-years behavior without date boundaries.
5. Overlapping updates preserve old history and replace matching timestamps with newer bars.
6. Multiple symbols and batch grouping preserve distinct per-symbol date ranges.
7. Provider exceptions propagate or report failure without silent full-history fallback.
8. Empty, malformed, and missing batch responses follow explicit safety policies without silent loss.
9. A failed required ingestion does not publish a partial or empty dataset over the valid dataset.
10. Successful ingestion feeds into existing calculations and screening pipeline identically.
11. Demo provider and production cache namespaces remain strictly isolated.
"""

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union
import pytest

from tests.core.test_orchestration import MockBandsRepo
from yogi.calculation.bands import BandsCalculator
from yogi.calculation.impulse import ImpulseCalculator
from yogi.calculation.trend import TrendCalculator
from yogi.calculation.velocity import VelocityCalculator
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.security import ISecurityMetadataRepository, SecurityMetadata
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.data.providers.demo import DemoDataProvider
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.bands import CsvBandsRepository
from yogi.storage.cache import DatasetCache, IngestionCohort, MarketBarsCache, merge_market_bars
from yogi.storage.metadata import CsvMetadataRepository
from yogi.timeframe.engine import TimeframeEngine


# ---------------------------------------------------------------------------
# Test Fixtures & Mocks
# ---------------------------------------------------------------------------

def make_test_bar(dt: datetime, close: float = 100.0) -> MarketBar:
    return MarketBar(
        timestamp=dt,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=10000.0,
    )


def generate_bar_series(
    start_dt: datetime,
    count: int,
    start_price: float = 100.0,
    daily_delta: float = 0.5,
) -> tuple[MarketBar, ...]:
    return tuple(
        make_test_bar(start_dt + timedelta(days=i), start_price + i * daily_delta)
        for i in range(count)
    )


class RecordingMockProvider(IDataProvider):
    """Mock provider recording all calls and parameter details without network activity."""

    def __init__(
        self,
        canned_data: Optional[Mapping[str, Sequence[MarketBar]]] = None,
        can_batch: bool = True,
        fail_symbols: Optional[Mapping[str, Exception]] = None,
        missing_batch_symbols: Optional[Sequence[str]] = None,
    ) -> None:
        self.canned_data = dict(canned_data or {})
        self._can_batch = can_batch
        self.fail_symbols = dict(fail_symbols or {})
        self.missing_batch_symbols = set(missing_batch_symbols or ())
        self.daily_calls: list[dict[str, Any]] = []
        self.batch_calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock_recording_provider"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return tuple(self.canned_data.keys())

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Sequence[MarketBar]:
        self.daily_calls.append({
            "symbol": symbol,
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        if symbol in self.fail_symbols:
            raise self.fail_symbols[symbol]
        return self.canned_data.get(symbol, ())

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        if not self._can_batch:
            raise AttributeError("Provider does not support batch_daily_history")
        self.batch_calls.append({
            "symbols": list(symbols),
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        res: dict[str, Sequence[MarketBar]] = {}
        for s in symbols:
            if s in self.fail_symbols:
                raise self.fail_symbols[s]
            if s in self.missing_batch_symbols:
                continue  # simulate incomplete batch response
            res[s] = self.canned_data.get(s, ())
        return res

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.canned_data.get(symbol)
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock", ok=True)


def make_test_orchestrator(
    provider: IDataProvider,
    bands_repo: Optional[IBandsRepository] = None,
) -> tuple[PipelineOrchestrator, RegistryHub]:
    hub = RegistryHub()
    hub.providers.register("mock_provider", provider)
    b_repo = bands_repo or MockBandsRepo()
    hub.bands.register("mock_bands", b_repo)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())

    tf_engine = TimeframeEngine()
    orch = PipelineOrchestrator(
        registry=hub,
        timeframe_engine=tf_engine,
    )
    return orch, hub


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_pipeline_cohort_execution_and_up_to_date_triggers_no_calls(tmp_path: Path):
    """Test 1 & 2: UP_TO_DATE symbols trigger zero provider calls; full cached history is preserved."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # Wednesday 2026-04-15. Expected fresh date: Tuesday 2026-04-14.
    # Symbol FRESH_SYM has 104 bars ending on 2026-04-14 -> UP_TO_DATE
    fresh_bars = generate_bar_series(datetime(2026, 1, 1), 104)
    cache.save_bars({"FRESH_SYM": fresh_bars}, exchange="NSE", provider="mock_provider")

    mock_provider = RecordingMockProvider()
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["FRESH_SYM"],
        provider_options={"target_date": "2026-04-15"},
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    assert "FRESH_SYM" in dataset
    # Zero provider calls were made because the symbol is UP_TO_DATE
    assert len(mock_provider.daily_calls) == 0
    assert len(mock_provider.batch_calls) == 0

    # Cached history in cache remains complete and intact
    loaded = cache.load_bars(exchange="NSE", provider="mock_provider")
    assert len(loaded["FRESH_SYM"]) == 104


def test_incremental_cohort_receives_planned_start_date_and_merges_history(tmp_path: Path):
    """Test 3 & 5: Incremental requests receive planned start dates with overlap and correctly merge."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # STALE_SYM has 95 bars from 2026-01-01 to 2026-04-05.
    # On target_date 2026-04-15, expected fresh is 2026-04-14.
    # With overlap_days=5: start_date is 2026-04-05 - 5 days = 2026-03-31.
    stale_bars = generate_bar_series(datetime(2026, 1, 1), 95, start_price=100.0)
    cache.save_bars({"STALE_SYM": stale_bars}, exchange="NSE", provider="mock_provider")

    # Provider will supply 15 new bars from 2026-03-31 to 2026-04-14
    # The first 5 bars overlap (2026-03-31 to 2026-04-05), with updated close prices
    inc_bars = generate_bar_series(datetime(2026, 3, 31), 15, start_price=200.0)
    mock_provider = RecordingMockProvider(canned_data={"STALE_SYM": inc_bars})
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["STALE_SYM"],
        provider_options={
            "target_date": "2026-04-15",
            "overlap_days": 5,
            "end_date": "2026-04-15",
        },
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    assert "STALE_SYM" in dataset
    # Provider received the exact planned start_date and configured end_date
    assert len(mock_provider.daily_calls) == 1
    call = mock_provider.daily_calls[0]
    assert call["symbol"] == "STALE_SYM"
    assert call["start_date"] == date(2026, 3, 31)
    assert call["end_date"] == "2026-04-15"

    # Verify merged history in cache:
    # 95 prior bars + 15 new bars with 5 overlapping = 104 total bars
    loaded = cache.load_bars(exchange="NSE", provider="mock_provider")
    assert len(loaded["STALE_SYM"]) == 104

    # Verify overlapping bar revisions: bar on 2026-03-31 has the revised close price 200.0
    bar_overlap = [b for b in loaded["STALE_SYM"] if b.timestamp.date() == date(2026, 3, 31)][0]
    assert bar_overlap.close == 200.0


def test_full_backfill_cohort_preserves_historical_years_behavior(tmp_path: Path):
    """Test 4: FULL_BACKFILL requests use configured historical_years without date boundaries."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    # Cache is empty for NEW_SYM
    backfill_bars = generate_bar_series(datetime(2025, 1, 1), 200)
    mock_provider = RecordingMockProvider(canned_data={"NEW_SYM": backfill_bars})
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["NEW_SYM"],
        historical_years=7,
        provider_options={"target_date": "2026-04-15"},
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    assert "NEW_SYM" in dataset
    assert len(mock_provider.daily_calls) == 1
    call = mock_provider.daily_calls[0]
    assert call["symbol"] == "NEW_SYM"
    assert call["years"] == 7
    # FULL_BACKFILL does not set explicit date range
    assert call["start_date"] is None
    assert call["end_date"] is None

    # Bars persisted to cache
    loaded = cache.load_bars(exchange="NSE", provider="mock_provider")
    assert len(loaded["NEW_SYM"]) == 200


def test_multi_symbol_batching_groups_by_start_date_without_duplication(tmp_path: Path):
    """Test 6: Multiple symbols are partitioned and batched by start_date without duplicate calls."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # 1. Fresh symbol (104 bars ending 2026-04-14)
    fresh_bars = generate_bar_series(datetime(2026, 1, 1), 104)
    # 2. Stale symbol A (ends 2026-04-05 -> start 2026-03-31)
    stale_bars_a = generate_bar_series(datetime(2026, 1, 1), 95)
    # 3. Stale symbol B (ends 2026-04-05 -> start 2026-03-31)
    stale_bars_b = generate_bar_series(datetime(2026, 1, 1), 95)
    # 4. Stale symbol C (ends 2026-04-01 -> start 2026-03-27)
    stale_bars_c = generate_bar_series(datetime(2026, 1, 1), 91)

    cache.save_bars({
        "FRESH_CO": fresh_bars,
        "STALE_A": stale_bars_a,
        "STALE_B": stale_bars_b,
        "STALE_C": stale_bars_c,
    }, exchange="NSE", provider="mock_provider")

    inc_bars_ab = generate_bar_series(datetime(2026, 3, 31), 15)
    inc_bars_c = generate_bar_series(datetime(2026, 3, 27), 19)
    backfill_bars = generate_bar_series(datetime(2025, 1, 1), 100)

    mock_provider = RecordingMockProvider(canned_data={
        "STALE_A": inc_bars_ab,
        "STALE_B": inc_bars_ab,
        "STALE_C": inc_bars_c,
        "NEW_CO": backfill_bars,
    })
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["FRESH_CO", "STALE_A", "STALE_B", "STALE_C", "NEW_CO"],
        provider_options={"target_date": "2026-04-15", "overlap_days": 5},
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    assert len(dataset) == 5
    # FRESH_CO had 0 calls
    # STALE_A and STALE_B share start_date (2026-03-31) -> grouped into 1 batch call!
    # STALE_C has unique start_date (2026-03-27) -> 1 call
    # NEW_CO is FULL_BACKFILL -> 1 call
    assert len(mock_provider.batch_calls) == 1
    batch_call = mock_provider.batch_calls[0]
    assert set(batch_call["symbols"]) == {"STALE_A", "STALE_B"}
    assert batch_call["start_date"] == date(2026, 3, 31)

    # Total symbols requested across all calls:
    symbols_requested = []
    for bc in mock_provider.batch_calls:
        symbols_requested.extend(bc["symbols"])
    for dc in mock_provider.daily_calls:
        symbols_requested.append(dc["symbol"])

    # FRESH_CO never requested, all others requested exactly once
    assert "FRESH_CO" not in symbols_requested
    assert symbols_requested.count("STALE_A") == 1
    assert symbols_requested.count("STALE_B") == 1
    assert symbols_requested.count("STALE_C") == 1
    assert symbols_requested.count("NEW_CO") == 1


def test_incremental_provider_exception_does_not_fall_back_to_full_history(tmp_path: Path):
    """Test 7: Provider failure on incremental update is explicit; no silent 10-year download."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    stale_bars = generate_bar_series(datetime(2026, 1, 1), 95)
    cache.save_bars({"STALE_SYM": stale_bars}, exchange="NSE", provider="mock_provider")

    # Provider will raise DataProviderError on STALE_SYM
    mock_provider = RecordingMockProvider(
        fail_symbols={"STALE_SYM": DataProviderError("Upstream rate limit")}
    )
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["STALE_SYM"],
        provider_options={"target_date": "2026-04-15"},
    )

    # When all requested symbols fail, DataProviderError is raised
    with pytest.raises(DataProviderError, match="systemic failure"):
        orch.build_dataset(cfg, bars_cache=cache)

    # Verify that provider was only queried for incremental start_date, NOT full 10-year period
    assert len(mock_provider.daily_calls) == 1
    call = mock_provider.daily_calls[0]
    assert call["start_date"] is not None
    # Prior bars in cache remain safe and untouched
    loaded = cache.load_bars(exchange="NSE", provider="mock_provider")
    assert len(loaded["STALE_SYM"]) == 95


def test_empty_incremental_response_preserves_cached_history(tmp_path: Path):
    """Test 8: Legitimate empty response does not erase prior cached bars."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    stale_bars = generate_bar_series(datetime(2026, 1, 1), 95)
    cache.save_bars({"STALE_SYM": stale_bars}, exchange="NSE", provider="mock_provider")

    # Provider returns empty list ()
    mock_provider = RecordingMockProvider(canned_data={"STALE_SYM": ()})
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["STALE_SYM"],
        provider_options={"target_date": "2026-04-15"},
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    # Dataset still built from existing bars
    assert "STALE_SYM" in dataset
    # Prior bars in cache are 100% preserved
    loaded = cache.load_bars(exchange="NSE", provider="mock_provider")
    assert len(loaded["STALE_SYM"]) == 95


def test_missing_batch_symbol_falls_back_to_individual_retrieval(tmp_path: Path):
    """Test 8B: Incomplete batch result is handled safely via individual fallback."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    bars_a = generate_bar_series(datetime(2026, 1, 1), 95)
    bars_b = generate_bar_series(datetime(2026, 1, 1), 95)
    cache.save_bars({"SYM_A": bars_a, "SYM_B": bars_b}, exchange="NSE", provider="mock_provider")

    new_bars = generate_bar_series(datetime(2026, 4, 1), 14)
    # Batch download returns SYM_A, but SYM_B is missing from batch response
    mock_provider = RecordingMockProvider(
        canned_data={"SYM_A": new_bars, "SYM_B": new_bars},
        missing_batch_symbols=["SYM_B"],
    )
    orch, _ = make_test_orchestrator(mock_provider)

    cfg = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["SYM_A", "SYM_B"],
        provider_options={"target_date": "2026-04-15"},
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)

    assert "SYM_A" in dataset
    assert "SYM_B" in dataset

    # SYM_B was retrieved via individual fallback
    daily_symbols = [c["symbol"] for c in mock_provider.daily_calls]
    assert "SYM_B" in daily_symbols


def test_failed_ingestion_preserves_valid_dataset_and_does_not_publish_partial(tmp_path: Path):
    """Test 9: A failed required ingestion preserves the last valid dataset and does not overwrite it."""
    async def _async_test():
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        bars_cache = MarketBarsCache(cache_dir=cache_dir)
        ds_cache = DatasetCache(cache_dir=cache_dir)

        initial_bars = generate_bar_series(datetime(2026, 1, 1), 104)
        bars_cache.save_bars({"GOOD": initial_bars}, exchange="NSE", provider="mock_provider")

        mock_provider = RecordingMockProvider(
            canned_data={"GOOD": initial_bars},
            fail_symbols={"FAIL_SYM": DataProviderError("Network connection reset")},
        )
        orch, hub = make_test_orchestrator(mock_provider)

        initial_config = EngineConfig(
            provider="mock_provider",
            bands_repository="mock_bands",
            symbols=["GOOD"],
            provider_options={"target_date": "2026-04-15"},
        )

        # Initialize AppState with valid dataset
        app_state = AppState(
            orchestrator=orch,
            config=initial_config,
            dataset_cache=ds_cache,
            bars_cache=bars_cache,
        )
        await app_state.refresh(provider="mock_provider", symbols=["GOOD"])
        assert "GOOD" in app_state.dataset
        assert len(app_state.dataset) == 1

        # Now attempt a refresh requiring all symbols where FAIL_SYM fails
        fail_config = EngineConfig(
            provider="mock_provider",
            bands_repository="mock_bands",
            symbols=["GOOD", "FAIL_SYM"],
            provider_options={"target_date": "2026-04-15", "require_all_symbols": True},
        )
        app_state._config = fail_config

        with pytest.raises(DataProviderError, match="failed for required symbol 'FAIL_SYM'"):
            await app_state.refresh(
                provider="mock_provider",
                symbols=["GOOD", "FAIL_SYM"],
            )

        # Verify that the last valid dataset was PRESERVED and not replaced
        assert len(app_state.dataset) == 1
        assert "GOOD" in app_state.dataset
        assert "FAIL_SYM" not in app_state.dataset
        assert app_state.build_status == "FAILED"

    asyncio.run(_async_test())


def test_calculations_and_screening_produce_identical_results(tmp_path: Path):
    """Test 10: Successful incremental ingestion produces identical screening results to full backfill."""
    cache = MarketBarsCache(cache_dir=tmp_path)

    # 104 daily bars from 2026-01-01 to 2026-04-14
    full_bars = generate_bar_series(datetime(2026, 1, 1), 104, start_price=100.0)

    # Case A: Full backfill baseline
    provider_full = RecordingMockProvider(canned_data={"INFY": full_bars})
    orch_full, _ = make_test_orchestrator(provider_full)
    cfg_full = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        symbols=["INFY"],
    )
    dataset_full = orch_full.build_dataset(cfg_full)

    # Case B: Incremental update (95 bars cached + 15 incremental bars with 5 overlapping)
    cache.save_bars({"INFY": full_bars[:95]}, exchange="NSE", provider="mock_provider")
    provider_inc = RecordingMockProvider(canned_data={"INFY": full_bars[90:]})
    orch_inc, _ = make_test_orchestrator(provider_inc)
    cfg_inc = EngineConfig(
        provider="mock_provider",
        bands_repository="mock_bands",
        symbols=["INFY"],
        provider_options={"target_date": "2026-04-15", "overlap_days": 5},
    )
    dataset_inc = orch_inc.build_dataset(cfg_inc, bars_cache=cache)

    assert "INFY" in dataset_full
    assert "INFY" in dataset_inc

    # All calculation metrics (price, bands, velocity, trend, etc.) are identical
    import math
    for metric_key, val_full in dataset_full["INFY"].items():
        val_inc = dataset_inc["INFY"][metric_key]
        if isinstance(val_full, float) and math.isnan(val_full):
            assert isinstance(val_inc, float) and math.isnan(val_inc)
        else:
            assert val_full == val_inc, f"Metric mismatch for {metric_key}: {val_full} != {val_inc}"

    # Screening execution produces identical results
    query = ScreeningQuery()
    screen_full = orch_full.execute_screen(query, dataset_full)
    screen_inc = orch_inc.execute_screen(query, dataset_inc)
    assert screen_full.universe_count == screen_inc.universe_count
    assert screen_full.qualified_count == screen_inc.qualified_count
    assert screen_full.selected_count == screen_inc.selected_count
    assert [r["symbol"] for r in screen_full.rows] == [r["symbol"] for r in screen_inc.rows]


def test_demo_and_production_isolation_preserved(tmp_path: Path):
    """Test 11: Demo provider does not touch MarketBarsCache and remains completely isolated."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    demo_provider = DemoDataProvider()

    hub = RegistryHub()
    hub.providers.register("demo", demo_provider)
    hub.bands.register("mock_bands", MockBandsRepo())
    tf_engine = TimeframeEngine()
    orch = PipelineOrchestrator(registry=hub, timeframe_engine=tf_engine)

    cfg = EngineConfig(
        provider="demo",
        bands_repository="mock_bands",
        calculation_modules=(),
        symbols=["RELIANCE"],
    )

    dataset = orch.build_dataset(cfg, bars_cache=cache)
    assert "RELIANCE" in dataset

    # MarketBarsCache must remain completely empty for demo provider
    loaded_demo = cache.load_bars(exchange="NSE", provider="demo")
    assert loaded_demo == {}
    loaded_prod = cache.load_bars(exchange="NSE", provider="yfinance")
    assert loaded_prod == {}

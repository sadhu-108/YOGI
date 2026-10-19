"""Integration tests for Fast Startup, Persistent Cache, and Non-Blocking Background Rebuild."""

from datetime import datetime, timedelta
from pathlib import Path
import time
from typing import Mapping, Optional, Sequence
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.bands import CsvBandsRepository
from yogi.storage.cache import DatasetCache, MarketBarsCache
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class CountingMockProvider(IDataProvider):
    """Deterministic mock provider that tracks requested symbols for caching assertions."""
    name = "yfinance"

    def __init__(
        self,
        symbols: Optional[Sequence[str]] = None,
        should_fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.should_fail = should_fail
        self.delay = delay
        self._universe = list(symbols) if symbols is not None else ["RELIANCE", "TCS", "INFY"]
        self.downloaded_symbols: list[str] = []
        self._bars = [
            MarketBar(
                timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                open=2500.0 + i,
                high=2520.0 + i,
                low=2490.0 + i,
                close=2510.0 + i,
                volume=50000.0,
            )
            for i in range(70)
        ]

    @property
    def supports_intraday(self) -> bool:
        return True

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        if self.should_fail:
            raise DataProviderError("Provider universe failure.")
        return tuple(self._universe)

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 10
    ) -> Sequence[MarketBar]:
        if self.should_fail:
            raise DataProviderError(f"Download failed for {symbol}")
        if self.delay > 0:
            time.sleep(self.delay)
        self.downloaded_symbols.append(symbol)
        return self._bars

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 10
    ) -> Mapping[str, Sequence[MarketBar]]:
        if self.should_fail:
            raise DataProviderError("Batch download failed.")
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return self._bars[-1].close if self._bars else None

    def intraday(
        self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: any, exchange: str = "NSE") -> any:
        raise NotImplementedError

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self, symbol: Optional[str] = None, exchange: Optional[str] = None) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=not self.should_fail, sample_price=2510.0)


def _setup_test_state(
    tmp_path: Path,
    mock_provider: CountingMockProvider,
    autoload_cache: bool = False,
) -> AppState:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache = DatasetCache(cache_dir=cache_dir)
    bars_cache = MarketBarsCache(cache_dir=cache_dir)
    bands_repo = CsvBandsRepository(data_dir=tmp_path / "bands")

    state = AppState(
        bands_repo=bands_repo,
        autoload_cache=autoload_cache,
        dataset_cache=dataset_cache,
        bars_cache=bars_cache,
    )
    state.orchestrator.registry.providers._instances["yfinance"] = mock_provider
    state.orchestrator.registry.providers._factories.pop("yfinance", None)
    return state


def test_fast_startup_loads_cached_dataset_instantly(tmp_path: Path):
    """Validate fast startup loads a pre-existing cache file in under 100ms."""
    cache_dir = tmp_path / "cache"
    dataset_cache = DatasetCache(cache_dir=cache_dir)

    # 1. Pre-populate cache with 100 mock symbols
    mock_data = {
        f"SYM_{i}": {
            "symbol": f"SYM_{i}",
            "close": 100.0 + i,
            "DROC": 2.0,
            "price": 100.0 + i,
            "pct_b": 0.5,
        }
        for i in range(100)
    }
    dataset_cache.save(mock_data, exchange="NSE", provider="yfinance", half_year_policy="prototype")

    # 2. Benchmark cache load into AppState
    mock_p = CountingMockProvider()
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=False)
    
    t0 = time.perf_counter()
    loaded_ok = state.load_persisted_cache()
    load_time_ms = (time.perf_counter() - t0) * 1000

    # Must load in < 100ms
    assert load_time_ms < 100.0, f"Cache load took {load_time_ms:.2f}ms (must be <100ms)"
    assert loaded_ok is True
    assert len(state.dataset) == 100
    assert state.is_cached is True
    assert state.is_demo is False

    # 3. Verify /api/status reports cached state
    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "READY"
    assert data["universe_count"] == 100
    assert data["is_cached"] is True
    assert data["is_demo"] is False


def test_bars_cache_reuse_avoids_re_download(tmp_path: Path):
    """Verify that cached daily market bars are reused, downloading only missing symbols."""
    cache_dir = tmp_path / "cache"
    bars_cache = MarketBarsCache(cache_dir=cache_dir)

    # 1. Pre-populate MarketBarsCache with RELIANCE and TCS (70 bars >= min_bars 60)
    start_dt = datetime(2024, 1, 1)
    mock_bars = tuple(
        MarketBar(
            timestamp=start_dt + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0,
            volume=1000.0,
        )
        for i in range(70)
    )
    bars_cache.save_bars({"RELIANCE": mock_bars, "TCS": mock_bars}, exchange="NSE", provider="yfinance")

    # 2. Rebuild universe of [RELIANCE, TCS, INFY]
    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS", "INFY"])
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=False)

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # Run synchronous refresh
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance"})
    assert res.status_code == 200
    status = res.json()
    assert status["universe_count"] == 3

    # Assert that only INFY was downloaded, since RELIANCE and TCS were cached
    assert mock_p.downloaded_symbols == ["INFY"], f"Expected only INFY to be downloaded, got {mock_p.downloaded_symbols}"

    # Verify that MarketBarsCache now contains all 3
    cached_all = state.bars_cache.load_bars(exchange="NSE", provider="yfinance")
    assert "RELIANCE" in cached_all
    assert "TCS" in cached_all
    assert "INFY" in cached_all


def test_force_refresh_bars_bypasses_bars_cache(tmp_path: Path):
    """Verify that force_refresh_bars=True bypasses the bars cache and downloads all symbols."""
    cache_dir = tmp_path / "cache"
    bars_cache = MarketBarsCache(cache_dir=cache_dir)

    start_dt = datetime(2024, 1, 1)
    mock_bars = tuple(
        MarketBar(
            timestamp=start_dt + timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0,
            volume=1000.0,
        )
        for i in range(70)
    )
    bars_cache.save_bars({"RELIANCE": mock_bars}, exchange="NSE", provider="yfinance")

    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS"])
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=False)

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # Refresh with force_refresh_bars=True
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "force_refresh_bars": True})
    assert res.status_code == 200

    # Both symbols must be downloaded
    assert set(mock_p.downloaded_symbols) == {"RELIANCE", "TCS"}


def test_background_rebuild_lifecycle_and_non_blocking_progress(tmp_path: Path):
    """Verify non-blocking background rebuild returns immediately, reports progress, and performs atomic swap."""
    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS"], delay=0.01)
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=False)

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Trigger background rebuild
    t0 = time.perf_counter()
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "background": True})
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert res.status_code == 200
    res_data = res.json()
    assert res_data["build_status"] == "BUILDING"
    # HTTP request must return promptly without waiting for completion
    assert elapsed_ms < 500.0

    # 2. Wait for background thread to complete
    if state.build_thread:
        state.build_thread.join(timeout=5.0)

    res = client.get("/api/status")
    status_data = res.json()
    assert status_data["build_status"] == "READY"
    assert status_data["universe_count"] == 2
    assert status_data["progress"] == 1.0

    # 3. Check table data is immediately queryable
    res = client.get("/api/table")
    assert res.status_code == 200
    table_data = res.json()
    assert table_data["universe_count"] == 2


def test_duplicate_rebuild_request_returns_current_job_status(tmp_path: Path):
    """Verify triggering rebuild while a rebuild is in flight safely returns existing job status."""
    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS"], delay=0.05)
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=False)

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # Trigger first
    res1 = client.post("/api/dataset/refresh", json={"provider": "yfinance", "background": True})
    assert res1.status_code == 200
    assert res1.json()["build_status"] == "BUILDING"

    # Trigger second immediately
    res2 = client.post("/api/dataset/refresh", json={"provider": "yfinance", "background": True})
    assert res2.status_code == 200
    assert res2.json()["build_status"] == "BUILDING"

    # Wait for completion
    if state.build_thread:
        state.build_thread.join(timeout=5.0)


def test_failed_background_rebuild_preserves_previous_dataset(tmp_path: Path):
    """Verify that a rebuild failure does not clear or corrupt the active dataset."""
    # 1. Pre-load valid dataset
    cache_dir = tmp_path / "cache"
    dataset_cache = DatasetCache(cache_dir=cache_dir)
    mock_data = {
        "RELIANCE": {"symbol": "RELIANCE", "close": 2900.0, "DROC": 1.2, "price": 2900.0},
        "TCS": {"symbol": "TCS", "close": 4200.0, "DROC": -0.5, "price": 4200.0},
    }
    dataset_cache.save(mock_data, exchange="NSE", provider="yfinance", half_year_policy="prototype")

    # 2. Setup state with failing provider
    failing_p = CountingMockProvider(should_fail=True)
    state = _setup_test_state(tmp_path, failing_p, autoload_cache=True)
    assert len(state.dataset) == 2

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # 3. Trigger background rebuild that will fail
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance", "background": True})
    assert res.status_code == 200

    # Wait for completion of failure
    if state.build_thread:
        state.build_thread.join(timeout=5.0)

    status = client.get("/api/status").json()
    assert status["build_status"] == "FAILED"
    assert status["error"] is not None
    # Critical: Active dataset must still have the 2 original symbols
    assert len(state.dataset) == 2
    assert "RELIANCE" in state.dataset
    assert "TCS" in state.dataset


def test_demo_and_live_isolation(tmp_path: Path):
    """Verify demo mode switching does not overwrite the persistent live cache."""
    cache_dir = tmp_path / "cache"
    dataset_cache = DatasetCache(cache_dir=cache_dir)
    live_data = {
        "RELIANCE": {"symbol": "RELIANCE", "close": 3000.0, "price": 3000.0},
        "TCS": {"symbol": "TCS", "close": 4000.0, "price": 4000.0},
    }
    dataset_cache.save(live_data, exchange="NSE", provider="yfinance", half_year_policy="prototype")

    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS"])
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=True)
    assert state.is_demo is False
    assert state.is_cached is True

    app = create_app(app_state=state, autoload_cache=False, auto_refresh=False)
    client = AsgiTestClient(app)

    # 1. Switch to demo mode via refresh with demo provider
    res = client.post("/api/dataset/refresh", json={"provider": "demo"})
    assert res.status_code == 200
    assert res.json()["is_demo"] is True
    assert state.is_demo is True
    assert state.is_cached is False
    # Demo dataset loaded (5 golden demo stocks)
    assert len(state.dataset) == 5

    # 2. Verify disk cache was NOT modified or overwritten with demo data
    persisted_live = dataset_cache.load(exchange="NSE", provider="yfinance", half_year_policy="prototype")
    assert persisted_live is not None
    assert len(persisted_live["dataset"]) == 2
    assert "RELIANCE" in persisted_live["dataset"]

    # 3. Switch back to live mode
    res = client.post("/api/dataset/refresh", json={"provider": "yfinance"})
    assert res.status_code == 200
    assert res.json()["is_demo"] is False
    assert state.is_demo is False


@pytest.mark.anyio
async def test_lifespan_triggers_background_rebuild_on_first_run_without_blocking(tmp_path: Path):
    """Verify that entering FastAPI lifespan when cache is empty initiates background rebuild without blocking startup."""
    mock_p = CountingMockProvider(symbols=["RELIANCE", "TCS", "INFY"])
    state = _setup_test_state(tmp_path, mock_p, autoload_cache=True)
    assert len(state.dataset) == 0

    app = create_app(app_state=state, autoload_cache=True, auto_refresh=False, auto_background=True)

    # Trigger lifespan
    async with app.router.lifespan_context(app):
        # Startup yielded immediately, background thread is running
        assert state.build_thread is not None
        assert state.build_status == "BUILDING"

        # Wait for rebuild to finish
        state.build_thread.join(timeout=5.0)

    assert state.build_status == "READY"
    assert len(state.dataset) == 3
    assert state.is_cached is False
    # Verify disk cache was saved
    cached = state.dataset_cache.load(exchange="NSE", provider="yfinance", half_year_policy="prototype")
    assert cached is not None
    assert len(cached["dataset"]) == 3


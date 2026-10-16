"""Regression check demonstrating test refresh operations cannot alter production cache files.

Verifies Step 2C acceptance criteria:
1. Test refresh operations using mock providers direct dataset and raw-bars writes strictly to isolated temporary storage.
2. Production cache files in data/cache/ remain unmodified (timestamps and sizes identical).
3. YOGI_CACHE_DIR environment override directs unparameterized AppState instances to isolated cache directories.
"""

import os
from pathlib import Path
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.state import AppState
from yogi.storage.cache import DatasetCache, MarketBarsCache
from yogi.storage.paths import get_cache_dir
from tests.cockpit.test_cockpit_api import AsgiTestClient
from tests.cockpit.test_cockpit_yfinance import MockYFinanceProvider


def _get_file_signatures(directory: Path) -> dict[str, tuple[int, int]]:
    """Capture (st_size, st_mtime_ns) for all files in directory."""
    sigs = {}
    if directory.is_dir():
        for f in directory.iterdir():
            if f.is_file():
                st = f.stat()
                sigs[f.name] = (st.st_size, st.st_mtime_ns)
    return sigs


def test_refresh_with_isolated_cache_does_not_alter_production_cache(tmp_path: Path):
    """Verify that AppState with injected temporary caches directs all writes to tmp_path,
    leaving production cache files completely untouched.
    """
    prod_cache_dir = get_cache_dir()
    prod_sigs_before = _get_file_signatures(prod_cache_dir)

    # 1. Setup isolated test environment
    test_cache_dir = tmp_path / "isolated_cache"
    test_cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache = DatasetCache(cache_dir=test_cache_dir)
    bars_cache = MarketBarsCache(cache_dir=test_cache_dir)

    mock_provider = MockYFinanceProvider(symbols=["ISOLATED_A", "ISOLATED_B"])
    state = AppState(
        dataset_cache=dataset_cache,
        bars_cache=bars_cache,
    )
    state.orchestrator.registry.providers._instances["yfinance"] = mock_provider
    state.orchestrator.registry.providers._factories.pop("yfinance", None)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # 2. Execute live dataset refresh with the mock provider
    res = client.post("/api/dataset/refresh", json={"provider": "live"})
    assert res.status_code == 200
    data = res.json()
    assert data["universe_count"] == 2
    assert data["is_demo"] is False
    assert data["provider"] == "yfinance"

    # 3. Verify writes landed strictly in the isolated temporary cache
    isolated_dataset = test_cache_dir / "dataset_NSE_yfinance.pkl"
    isolated_bars = test_cache_dir / "bars_NSE_yfinance.pkl"

    assert isolated_dataset.is_file(), "Dataset cache must be written to isolated test directory"
    assert isolated_bars.is_file(), "Bars cache must be written to isolated test directory"

    loaded_dataset = dataset_cache.load(exchange="NSE", provider="yfinance", half_year_policy="prototype")
    assert loaded_dataset is not None
    assert set(loaded_dataset["dataset"].keys()) == {"ISOLATED_A", "ISOLATED_B"}

    loaded_bars = bars_cache.load_bars(exchange="NSE", provider="yfinance")
    assert "ISOLATED_A" in loaded_bars
    assert "ISOLATED_B" in loaded_bars

    # 4. Strictly assert that NO production cache files were modified or touched
    prod_sigs_after = _get_file_signatures(prod_cache_dir)
    assert prod_sigs_before == prod_sigs_after, (
        f"Production cache files were modified during test execution! "
        f"Before: {prod_sigs_before}, After: {prod_sigs_after}"
    )


def test_yogi_cache_dir_env_variable_redirects_default_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify that setting YOGI_CACHE_DIR environment variable redirects get_cache_dir()
    and default-instantiated DatasetCache / MarketBarsCache to the specified directory.
    """
    env_cache_dir = tmp_path / "env_redirected_cache"
    env_cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YOGI_CACHE_DIR", str(env_cache_dir))

    # Path resolution check
    assert get_cache_dir() == env_cache_dir

    # Unparameterized cache instantiations must use redirected directory
    ds_cache = DatasetCache()
    bars_cache = MarketBarsCache()
    assert ds_cache.cache_dir == env_cache_dir
    assert bars_cache.cache_dir == env_cache_dir

    # Default AppState must inherit redirected cache directory
    state = AppState()
    assert state.dataset_cache.cache_dir == env_cache_dir
    assert state.bars_cache.cache_dir == env_cache_dir

    prod_cache_dir = get_cache_dir(Path("data/cache"))
    prod_sigs_before = _get_file_signatures(prod_cache_dir)

    # Perform mock refresh
    mock_provider = MockYFinanceProvider(symbols=["ENV_SYM_1"])
    state.orchestrator.registry.providers._instances["yfinance"] = mock_provider
    state.orchestrator.registry.providers._factories.pop("yfinance", None)

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)
    res = client.post("/api/dataset/refresh", json={"provider": "live"})
    assert res.status_code == 200

    # Writes must be in env_cache_dir, NOT production
    assert (env_cache_dir / "dataset_NSE_yfinance.pkl").is_file()
    assert (env_cache_dir / "bars_NSE_yfinance.pkl").is_file()

    prod_sigs_after = _get_file_signatures(prod_cache_dir)
    assert prod_sigs_before == prod_sigs_after

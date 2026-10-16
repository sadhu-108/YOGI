"""Pytest configuration and shared fixtures for YOGI test suite.

Note on Cache Isolation Architecture:
A global autouse=True fixture setting YOGI_CACHE_DIR is intentionally avoided
because tests in `tests/storage/test_paths_and_startup.py` deliberately verify
unconfigured default production-path discovery and environment overrides, and
tests in `tests/cockpit/test_chart_repair.py` verify fast-startup candle and
band calculation from existing pre-cached data.

Tests performing persistent cache writes use explicit per-test dependency
injection (`DatasetCache(cache_dir=tmp_path)` / `MarketBarsCache(cache_dir=tmp_path)`)
or can explicitly request the `isolated_cache_env` fixture below.
"""

from pathlib import Path
import pytest


@pytest.fixture
def isolated_cache_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Provide an isolated temporary cache directory configured via the YOGI_CACHE_DIR environment variable.

    Preserves and restores prior environment state automatically via monkeypatch.
    """
    cache_dir = tmp_path / "isolated_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("YOGI_CACHE_DIR", str(cache_dir))
    return cache_dir

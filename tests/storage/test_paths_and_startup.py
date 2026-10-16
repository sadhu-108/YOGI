"""Regression tests for persistent storage path anchoring and startup stability.

Validates Step 2A:
1. Path resolution for project root, data dir, and cache dir.
2. Cwd-independence: paths resolve to project root even when CWD is changed (e.g. to src/ or tmp).
3. Cache, bands, metadata, and settings components anchor correctly by default.
4. AppState loads existing cache file reliably from any working directory.
5. Empty dataset does not mutate state to demo provider.
6. Explicit demo provider selection is preserved and functional.
"""

from pathlib import Path
import pytest

from yogi.cockpit.state import AppState
from yogi.storage.bands import CsvBandsRepository
from yogi.storage.cache import DatasetCache, MarketBarsCache
from yogi.storage.metadata import CsvMetadataRepository
from yogi.storage.paths import get_cache_dir, get_data_dir, get_project_root


def test_project_root_discovery():
    """Verify get_project_root finds the repository root containing pyproject.toml."""
    root = get_project_root()
    assert root.is_dir()
    assert (root / "pyproject.toml").is_file()
    assert (root / "data").is_dir()


def test_data_dir_default_and_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify get_data_dir defaults to project root / data, and honors overrides."""
    default_data = get_data_dir()
    assert default_data == get_project_root() / "data"

    # Absolute custom path
    custom_abs = get_data_dir(tmp_path)
    assert custom_abs == tmp_path.resolve()

    # Relative custom path anchors to project root
    custom_rel = get_data_dir("custom_data")
    assert custom_rel == (get_project_root() / "custom_data").resolve()

    # Environment variable override
    monkeypatch.setenv("YOGI_DATA_DIR", str(tmp_path))
    assert get_data_dir() == tmp_path.resolve()


def test_cache_dir_default_and_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify get_cache_dir defaults to project root / data / cache."""
    default_cache = get_cache_dir()
    assert default_cache == get_project_root() / "data" / "cache"

    # Absolute custom path
    custom_abs = get_cache_dir(tmp_path)
    assert custom_abs == tmp_path.resolve()


def test_default_repositories_anchor_to_project_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify repositories and caches instantiate with absolute paths anchored to project root even when CWD is changed."""
    # Simulate changing working directory to an arbitrary temporary directory
    monkeypatch.chdir(tmp_path)

    d_cache = DatasetCache()
    assert d_cache.cache_dir == get_project_root() / "data" / "cache"
    assert d_cache.cache_dir.is_absolute()

    b_cache = MarketBarsCache()
    assert b_cache.cache_dir == get_project_root() / "data" / "cache"
    assert b_cache.cache_dir.is_absolute()

    bands_repo = CsvBandsRepository()
    assert bands_repo.data_dir == get_project_root() / "data"
    assert bands_repo.data_dir.is_absolute()

    meta_repo = CsvMetadataRepository()
    assert meta_repo._dir == get_project_root() / "data"
    assert meta_repo._dir.is_absolute()


def test_app_state_paths_anchor_when_cwd_is_src(monkeypatch: pytest.MonkeyPatch):
    """Verify AppState config and persistence files resolve to project root when launched from src/."""
    src_dir = get_project_root() / "src"
    monkeypatch.chdir(src_dir)

    state = AppState(autoload_cache=False)
    assert state._settings_file == get_project_root() / "data" / "settings.json"
    assert state._presets_file == get_project_root() / "data" / "user_presets.json"
    assert state._dataset_cache.cache_dir == get_project_root() / "data" / "cache"
    assert state._bars_cache.cache_dir == get_project_root() / "data" / "cache"
    assert state._metadata_repo._dir == get_project_root() / "data"


def test_app_state_autoload_from_different_cwd(monkeypatch: pytest.MonkeyPatch):
    """Verify AppState successfully autoloads existing cached dataset when CWD is src/."""
    src_dir = get_project_root() / "src"
    monkeypatch.chdir(src_dir)

    state = AppState(autoload_cache=True)
    # The existing live cache is loaded
    assert len(state.dataset) > 0
    assert state.is_cached is True
    assert state.is_demo is False
    assert state.build_status == "READY"


def test_empty_dataset_preserves_non_demo_mode():
    """Verify an empty dataset on startup does NOT mark the state as demo mode."""
    state = AppState(autoload_cache=False)
    assert len(state.dataset) == 0
    assert state.is_demo is False
    assert state.config.provider == "yfinance"


@pytest.mark.anyio
async def test_explicit_demo_activation_still_works():
    """Verify user can explicitly switch to demo data when requested."""
    state = AppState(autoload_cache=False)
    assert state.is_demo is False

    await state.refresh(provider="demo")
    assert state.is_demo is True
    assert len(state.dataset) == 5
    assert "MANYAVAR" in state.dataset

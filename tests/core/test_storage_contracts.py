"""Tests for storage and cache formal contract protocols."""

from typing import Protocol, runtime_checkable
import pytest

from yogi.core.contracts.storage import IBarsCache, IDatasetCache
from yogi.storage.cache import DatasetCache, MarketBarsCache


def test_storage_protocols_runtime_checkable():
    """Verify IBarsCache and IDatasetCache are runtime-checkable protocols."""
    assert issubclass(IBarsCache, Protocol)
    assert issubclass(IDatasetCache, Protocol)
    assert hasattr(IBarsCache, "_is_runtime_protocol")
    assert hasattr(IDatasetCache, "_is_runtime_protocol")


def test_market_bars_cache_satisfies_protocol(tmp_path):
    """Verify MarketBarsCache structurally implements IBarsCache."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    assert isinstance(cache, IBarsCache)

    # Check required protocol methods exist and are callable
    assert callable(getattr(cache, "save_bars"))
    assert callable(getattr(cache, "load_bars"))
    assert callable(getattr(cache, "get_bars_for_symbols"))
    assert callable(getattr(cache, "clear"))


def test_dataset_cache_satisfies_protocol(tmp_path):
    """Verify DatasetCache structurally implements IDatasetCache."""
    cache = DatasetCache(cache_dir=tmp_path)
    assert isinstance(cache, IDatasetCache)

    # Check required protocol methods exist and are callable
    assert callable(getattr(cache, "save"))
    assert callable(getattr(cache, "load"))
    assert callable(getattr(cache, "validate"))
    assert callable(getattr(cache, "clear"))


def test_contracts_package_reexports():
    """Verify IBarsCache and IDatasetCache are re-exported by yogi.core.contracts."""
    import yogi.core.contracts as contracts

    assert hasattr(contracts, "IBarsCache")
    assert hasattr(contracts, "IDatasetCache")
    assert "IBarsCache" in contracts.__all__
    assert "IDatasetCache" in contracts.__all__

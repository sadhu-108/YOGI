"""Unit tests for AppState dataset immutability, freezing, and ColumnProjectingAssembler."""

import asyncio
from datetime import datetime
from types import MappingProxyType
import pytest

from yogi.cockpit.state import AppState, ColumnProjectingAssembler, freeze_dataset
from yogi.core.contracts.results import IResultAssembler, QueryResultPayload
from yogi.results.assembler import ResultAssembler


def test_freeze_dataset_deep_immutability():
    """Verify that freeze_dataset enforces MappingProxyType at both outer, inner, and nested levels."""
    raw = {
        "RELIANCE": {
            "price": 2500.0,
            "M_CUR": 10.5,
            "BANDST_M": "ABOVE",
            "nested_dict": {"sub_key": 42},
            "nested_list": [1, 2, [3, 4]],
        },
        "TCS": {"price": 3500.0, "M_CUR": 5.2, "BANDST_M": "IN"},
    }

    frozen = freeze_dataset(raw)

    # 1. Outer mapping is MappingProxyType
    assert isinstance(frozen, MappingProxyType)
    with pytest.raises(TypeError):
        frozen["INFY"] = {"price": 1500.0}
    with pytest.raises(TypeError):
        del frozen["RELIANCE"]

    # 2. Inner mapping is MappingProxyType
    inner = frozen["RELIANCE"]
    assert isinstance(inner, MappingProxyType)
    with pytest.raises(TypeError):
        inner["price"] = 2600.0
    with pytest.raises(TypeError):
        inner["NEW_METRIC"] = 1.0

    # 3. Nested dictionary is MappingProxyType
    assert isinstance(inner["nested_dict"], MappingProxyType)
    with pytest.raises(TypeError):
        inner["nested_dict"]["sub_key"] = 99

    # 4. Nested lists are converted to immutable tuples recursively
    assert isinstance(inner["nested_list"], tuple)
    assert isinstance(inner["nested_list"][2], tuple)

    # 5. Caller modifying the original dictionary cannot alter frozen data
    raw["RELIANCE"]["price"] = 9999.0
    raw["RELIANCE"]["nested_dict"]["sub_key"] = 1000
    raw["NEW_STOCK"] = {"price": 100.0}
    assert frozen["RELIANCE"]["price"] == 2500.0
    assert frozen["RELIANCE"]["nested_dict"]["sub_key"] == 42
    assert "NEW_STOCK" not in frozen


def test_app_state_initialization_and_read_only():
    """Verify AppState holds read-only dataset and exposes core dependencies."""
    sample_data = {
        "STOCK_A": {"symbol": "STOCK_A", "price": 100.0, "M_CUR": 12.0},
    }
    state = AppState(initial_dataset=sample_data)

    assert len(state.dataset) == 1
    assert state.dataset["STOCK_A"]["price"] == 100.0
    assert isinstance(state.dataset, MappingProxyType)
    assert isinstance(state.dataset["STOCK_A"], MappingProxyType)

    # Handlers cannot mutate dataset in place
    with pytest.raises(TypeError):
        state.dataset["STOCK_A"]["price"] = 200.0
    with pytest.raises(TypeError):
        state.dataset["STOCK_B"] = {}


from yogi.storage.cache import DatasetCache, MarketBarsCache


def test_app_state_atomic_refresh(monkeypatch, tmp_path):
    """Verify AppState dataset updates replace the reference atomically without in-place mutation."""
    sample_data = {
        "OLD": {"symbol": "OLD", "price": 50.0},
    }
    state = AppState(
        initial_dataset=sample_data,
        dataset_cache=DatasetCache(cache_dir=tmp_path),
        bars_cache=MarketBarsCache(cache_dir=tmp_path),
    )

    old_ref = state.dataset
    assert "OLD" in old_ref

    # Mock build_dataset on orchestrator
    new_data = {
        "NEW_1": {"symbol": "NEW_1", "price": 100.0},
        "NEW_2": {"symbol": "NEW_2", "price": 200.0},
    }
    monkeypatch.setattr(state.orchestrator, "build_dataset", lambda cfg: new_data)

    asyncio.run(state.refresh())

    # The dataset reference was replaced atomically
    assert state.dataset is not old_ref
    assert "OLD" not in state.dataset
    assert "NEW_1" in state.dataset
    assert "NEW_2" in state.dataset
    assert len(state.dataset) == 2
    assert state.last_built_at is not None

    # Old reference held by any prior reader remains valid and unchanged
    assert "OLD" in old_ref
    assert len(old_ref) == 1


def test_column_projecting_assembler():
    """Verify ColumnProjectingAssembler binds presentation columns and implements IResultAssembler."""
    base_assembler = ResultAssembler()
    requested_cols = ("symbol", "price", "ACCEL_L")
    projecting_assembler = ColumnProjectingAssembler(delegate=base_assembler, columns=requested_cols)

    assert isinstance(projecting_assembler, IResultAssembler)

    records = [
        {"symbol": "AAA", "price": 100.0, "ACCEL_L": 5.0, "M_CUR": 15.0, "EMA_W": "upcut"},
        {"symbol": "BBB", "price": 200.0, "ACCEL_L": 2.0, "M_CUR": 10.0, "EMA_W": "yes"},
    ]

    # When called with columns=None (as PipelineOrchestrator does), it projects the bound columns
    payload = projecting_assembler.assemble(records=records, columns=None)

    assert isinstance(payload, QueryResultPayload)
    assert len(payload.columns) == 3
    col_keys = [c.key for c in payload.columns]
    assert col_keys == ["symbol", "price", "ACCEL_L"]

    # Rows contain only the projected columns
    for row in payload.rows:
        assert set(row.keys()) == {"symbol", "price", "ACCEL_L"}
        assert "M_CUR" not in row


def test_column_projecting_assembler_preserves_row_order():
    """Verify ColumnProjectingAssembler strictly preserves the ordering of input records."""
    base_assembler = ResultAssembler()
    projecting_assembler = ColumnProjectingAssembler(
        delegate=base_assembler,
        columns=("symbol", "price"),
    )

    records = [
        {"symbol": "FIRST", "price": 300.0},
        {"symbol": "SECOND", "price": 200.0},
        {"symbol": "THIRD", "price": 100.0},
    ]

    payload = projecting_assembler.assemble(records=records, columns=None)
    assert [r["symbol"] for r in payload.rows] == ["FIRST", "SECOND", "THIRD"]


def test_column_projecting_assembler_handles_unknown_or_custom_column():
    """Verify requesting an unknown/custom column creates a definition with None values without crashing."""
    base_assembler = ResultAssembler()
    projecting_assembler = ColumnProjectingAssembler(
        delegate=base_assembler,
        columns=("symbol", "UNKNOWN_FIELD"),
    )

    records = [
        {"symbol": "AAA", "price": 100.0},
    ]

    payload = projecting_assembler.assemble(records=records, columns=None)
    assert len(payload.columns) == 2
    col_keys = [c.key for c in payload.columns]
    assert col_keys == ["symbol", "UNKNOWN_FIELD"]
    assert payload.rows[0]["UNKNOWN_FIELD"] is None


def test_app_state_concurrent_readers_during_refresh(monkeypatch, tmp_path):
    """Verify concurrent reader coroutines always observe consistent snapshots during refresh."""
    import time

    initial = {"OLD": {"symbol": "OLD", "price": 50.0}}
    state = AppState(
        initial_dataset=initial,
        dataset_cache=DatasetCache(cache_dir=tmp_path),
        bars_cache=MarketBarsCache(cache_dir=tmp_path),
    )

    def slow_build(cfg):
        time.sleep(0.02)
        return {"NEW": {"symbol": "NEW", "price": 100.0}}

    monkeypatch.setattr(state.orchestrator, "build_dataset", slow_build)

    observed_snapshots = []

    async def reader():
        for _ in range(20):
            ds = state.dataset
            keys = set(ds.keys())
            observed_snapshots.append(keys)
            # Must always be strictly {'OLD'} or strictly {'NEW'}, never empty or mixed
            assert keys in ({"OLD"}, {"NEW"})
            await asyncio.sleep(0.002)

    async def runner():
        await asyncio.gather(
            state.refresh(),
            reader(),
            reader(),
        )

    asyncio.run(runner())
    assert {"OLD"} in observed_snapshots
    assert {"NEW"} in observed_snapshots
    assert set(state.dataset.keys()) == {"NEW"}


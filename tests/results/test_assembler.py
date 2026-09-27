"""Tests for ResultAssembler — Presentation Packaging and Column Projection."""

import math
import numpy as np
import pytest

from yogi.core.contracts.results import ColumnDefinition, QueryResultPayload
from yogi.results.assembler import ResultAssembler
from yogi.results.columns import DEFAULT_SUMMARY_COLUMNS, build_column_definition


def test_assembler_default_columns_projection():
    """Test 1: When columns=None, ResultAssembler projects default summary columns and dynamic RANK_* columns."""
    assembler = ResultAssembler()
    records = [
        {
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "exchange": "NSE",
            "price": 2500.0,
            "M_CUR": 5.4,
            "RANK_M_CUR": 1,
            "RANK_DROC": 3,
            "EMA_W": "upcut",
            "EMA_M": "yes",
            "BANDST_M": "IN",
            "BD_M": 1.2,
            "S4": 12.5,
            "ACCEL_L": 0.8,
            "ATH_DIFF": -3.2,
            "sector": "Energy",
            "grade": "A",
            "EXTRA_UNPROJECTED": 999.0,
        },
        {
            "symbol": "TCS",
            "name": "Tata Consultancy Services",
            "exchange": "NSE",
            "price": 3500.0,
            "M_CUR": 4.1,
            "RANK_M_CUR": 2,
            "RANK_DROC": 1,
            "EMA_W": "yes",
            "EMA_M": "yes",
            "BANDST_M": "IN",
            "BD_M": 0.5,
            "S4": 8.2,
            "ACCEL_L": 0.3,
            "ATH_DIFF": -1.5,
            "sector": "IT",
            "grade": "A",
            "EXTRA_UNPROJECTED": 888.0,
        },
    ]

    payload = assembler.assemble(records=records, columns=None)

    assert isinstance(payload, QueryResultPayload)
    assert len(payload.rows) == 2
    # Check that EXTRA_UNPROJECTED is NOT in the default projected summary columns
    assert "EXTRA_UNPROJECTED" not in payload.rows[0]
    # Check that standard summary columns are present
    assert payload.rows[0]["symbol"] == "RELIANCE"
    assert payload.rows[0]["price"] == 2500.0
    assert payload.rows[0]["RANK_M_CUR"] == 1
    # Check that dynamic rank column is included
    assert payload.rows[0]["RANK_DROC"] == 3

    # Check column definitions
    col_keys = [c.key for c in payload.columns]
    assert "symbol" in col_keys
    assert "RANK_M_CUR" in col_keys
    assert "RANK_DROC" in col_keys
    assert "EXTRA_UNPROJECTED" not in col_keys


def test_assembler_explicit_column_projection():
    """Test 2: When columns list is explicitly specified, only those columns are projected in exact order."""
    assembler = ResultAssembler()
    records = [
        {"symbol": "INFY", "price": 1800.0, "M_CUR": 3.2, "RANK_M_CUR": 5},
        {"symbol": "HDFC", "price": 1600.0, "M_CUR": 2.1, "RANK_M_CUR": 12},
    ]

    requested_columns = ["symbol", "RANK_M_CUR", "price"]
    payload = assembler.assemble(records=records, columns=requested_columns)

    assert len(payload.columns) == 3
    assert [c.key for c in payload.columns] == requested_columns
    assert list(payload.rows[0].keys()) == requested_columns
    assert payload.rows[0]["symbol"] == "INFY"
    assert payload.rows[0]["RANK_M_CUR"] == 5
    assert payload.rows[0]["price"] == 1800.0


def test_assembler_unknown_column_produces_none():
    """Test 3: Requesting an unknown column produces None rather than raising KeyError."""
    assembler = ResultAssembler()
    records = [{"symbol": "INFY", "price": 1800.0}]

    payload = assembler.assemble(records=records, columns=["symbol", "NON_EXISTENT_METRIC", "price"])

    assert len(payload.rows) == 1
    assert payload.rows[0]["symbol"] == "INFY"
    assert payload.rows[0]["NON_EXISTENT_METRIC"] is None
    assert payload.rows[0]["price"] == 1800.0

    col_keys = [c.key for c in payload.columns]
    assert col_keys == ["symbol", "NON_EXISTENT_METRIC", "price"]


def test_assembler_nan_and_none_normalization():
    """Test 4: ResultAssembler normalizes math.nan, np.nan to None and preserves None."""
    assembler = ResultAssembler()
    records = [
        {
            "symbol": "STOCK_A",
            "val_float_nan": float("nan"),
            "val_np_nan": np.nan,
            "val_none": None,
            "val_valid": 42.5,
        }
    ]

    payload = assembler.assemble(records=records, columns=["symbol", "val_float_nan", "val_np_nan", "val_none", "val_valid"])

    row = payload.rows[0]
    assert row["symbol"] == "STOCK_A"
    assert row["val_float_nan"] is None
    assert row["val_np_nan"] is None
    assert row["val_none"] is None
    assert row["val_valid"] == 42.5


def test_assembler_preserves_order():
    """Test 5: ResultAssembler strictly preserves the incoming record order."""
    assembler = ResultAssembler()
    records = [
        {"symbol": "Z", "rank": 1},
        {"symbol": "M", "rank": 2},
        {"symbol": "A", "rank": 3},
        {"symbol": "C", "rank": 4},
    ]

    payload = assembler.assemble(records=records, columns=["symbol", "rank"])

    symbols_in_payload = [r["symbol"] for r in payload.rows]
    assert symbols_in_payload == ["Z", "M", "A", "C"]


def test_assembler_metadata_preservation():
    """Test 6: ResultAssembler preserves supplied metadata and cardinality counts."""
    assembler = ResultAssembler()
    records = [{"symbol": "A"}, {"symbol": "B"}]
    custom_metadata = {
        "universe_count": 500,
        "qualified_count": 50,
        "selected_count": 2,
        "limit": 10,
        "strategy": "TEST_PRESET",
    }

    payload = assembler.assemble(records=records, metadata=custom_metadata)

    assert payload.universe_count == 500
    assert payload.qualified_count == 50
    assert payload.selected_count == 2
    assert payload.metadata["limit"] == 10
    assert payload.metadata["strategy"] == "TEST_PRESET"


def test_assembler_empty_records():
    """Test 7: Assembling an empty record list produces a valid payload with zero counts."""
    assembler = ResultAssembler()
    payload = assembler.assemble(records=[], columns=["symbol", "price"])

    assert isinstance(payload, QueryResultPayload)
    assert payload.universe_count == 0
    assert payload.qualified_count == 0
    assert payload.selected_count == 0
    assert len(payload.rows) == 0
    assert len(payload.columns) == 2
    assert [c.key for c in payload.columns] == ["symbol", "price"]


def test_assembler_column_definition_attributes():
    """Test 8: Column definitions contain accurate category, label, and format_string."""
    assembler = ResultAssembler()
    records = [{
        "symbol": "SBIN",
        "RANK_M_CUR": 1,
        "M_CUR": 12.345,
        "BANDST_M": "ABOVE",
        "IC": "IP",
        "OUT_ABOVE": 2,
    }]

    cols = ["symbol", "RANK_M_CUR", "M_CUR", "BANDST_M", "IC", "OUT_ABOVE"]
    payload = assembler.assemble(records=records, columns=cols)

    defs = {c.key: c for c in payload.columns}

    # symbol: IDENTIFIER, not numeric
    assert defs["symbol"].category == "IDENTIFIER"
    assert defs["symbol"].is_numeric is False
    assert defs["symbol"].format_string is None

    # RANK_M_CUR: RANKS, numeric, format '0'
    assert defs["RANK_M_CUR"].category == "RANKS"
    assert defs["RANK_M_CUR"].is_numeric is True
    assert defs["RANK_M_CUR"].format_string == "0"

    # M_CUR: MONTHS, numeric, format '0.00'
    assert defs["M_CUR"].category == "MONTHS"
    assert defs["M_CUR"].is_numeric is True
    assert defs["M_CUR"].format_string == "0.00"

    # BANDST_M: BANDS, string state, not numeric
    assert defs["BANDST_M"].category == "BANDS"
    assert defs["BANDST_M"].is_numeric is False

    # IC: IMPULSE, string state, not numeric
    assert defs["IC"].category == "IMPULSE"
    assert defs["IC"].is_numeric is False

    # OUT_ABOVE: BANDS, integer count
    assert defs["OUT_ABOVE"].category == "BANDS"
    assert defs["OUT_ABOVE"].is_numeric is True
    assert defs["OUT_ABOVE"].format_string == "0"

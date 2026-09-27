"""Tests for the 21 Verified Mentor Presets.

Validates strategy specifications, catalog loading, and rule evaluation parity
against prototype LISTS_LOGIC.txt and verify_lists.py.
"""

import pytest

from yogi.core.configuration.catalog import StrategyCatalog
from yogi.core.contracts.strategy import StrategySpec
from yogi.filter.engine import FilterEngine
from yogi.strategy.presets import (
    A1_IMPULSE_CONFIRMED,
    A2_ALL_6_TF_EMA_UP,
    A3_FRESH_MONTHLY_UPCUT,
    A4_FRESH_WEEKLY_UPCUT,
    B1_SPRINTERS_MONTH,
    B2_SPRINTERS_QUARTER,
    B3_SPRINTERS_YEAR,
    B4_ACCELERATING,
    B5_ACCEL_AND_EMA_UP,
    B6_CONSISTENT_RUNNERS,
    B7_IN_IMPULSE,
    B8_IN_CORRECTION,
    C1_BROKE_ABOVE_BAND,
    C2_BROKE_BELOW_BAND,
    C3_OUTSIDE_BAND_2PLUS_TF,
    C4_REACTION_TRADE,
    D1_EXIT_FNO,
    D2_EXIT_CASH,
    E1_TOP_100_MONTH,
    E2_TOP_100_YEAR,
    E3_RANK_CLIMBERS,
    MENTOR_PRESETS,
    load_mentor_presets,
)


def test_mentor_presets_count_and_uniqueness():
    """Verify exactly 21 unique mentor presets exist and are marked as mentor presets."""
    assert len(MENTOR_PRESETS) == 21
    names = [p.name for p in MENTOR_PRESETS]
    assert len(set(names)) == 21

    for preset in MENTOR_PRESETS:
        assert isinstance(preset, StrategySpec)
        assert preset.is_mentor_preset is True
        assert preset.description is not None
        assert len(preset.description) > 0


def test_load_mentor_presets_populates_catalog():
    """Verify load_mentor_presets registers all 21 presets into StrategyCatalog."""
    catalog = load_mentor_presets()
    assert len(catalog) == 21
    for preset in MENTOR_PRESETS:
        assert catalog.has(preset.name)
        retrieved = catalog.get(preset.name)
        assert retrieved.name == preset.name

    # Test idempotence (loading again does not error)
    catalog2 = load_mentor_presets(catalog)
    assert len(catalog2) == 21


def test_group_a_presets_evaluation():
    """Verify Group A (Impulse / Rally) qualification logic."""
    engine = FilterEngine()

    records = {
        "PASS_A1": {"BANDST_M": "ABOVE", "EMA_M": "upcut", "RANK_CHG": 10},
        "FAIL_A1_BAND": {"BANDST_M": "IN", "EMA_M": "yes", "RANK_CHG": 5},
        "FAIL_A1_EMA": {"BANDST_M": "ABOVE", "EMA_M": "downcut", "RANK_CHG": 5},
        "FAIL_A1_CHG": {"BANDST_M": "ABOVE", "EMA_M": "yes", "RANK_CHG": -1},
        "PASS_A2": {f"EMA_{tf}": "yes" for tf in ("D", "W", "M", "Q", "H", "Y")},
        "FAIL_A2": {**{f"EMA_{tf}": "yes" for tf in ("D", "W", "M", "Q", "H")}, "EMA_Y": "no"},
        "PASS_A3": {"EMA_M": "upcut"},
        "PASS_A4": {"EMA_W": "upcut"},
    }

    # A1
    res_a1 = engine.evaluate(records, A1_IMPULSE_CONFIRMED.filter_group)
    assert res_a1.matching_symbols == ["PASS_A1"]

    # A2
    res_a2 = engine.evaluate(records, A2_ALL_6_TF_EMA_UP.filter_group)
    assert res_a2.matching_symbols == ["PASS_A2"]

    # A3
    res_a3 = engine.evaluate(records, A3_FRESH_MONTHLY_UPCUT.filter_group)
    assert "PASS_A3" in res_a3.matching_symbols

    # A4
    res_a4 = engine.evaluate(records, A4_FRESH_WEEKLY_UPCUT.filter_group)
    assert "PASS_A4" in res_a4.matching_symbols


def test_group_b_presets_evaluation():
    """Verify Group B (Sprint / Momentum) qualification logic."""
    engine = FilterEngine()

    records = {
        "STOCK_1": {
            "SPD_M": 5.0,
            "SPD_Q": 10.0,
            "SPD_Y": 25.0,
            "ACCEL_L": 1.5,
            "EMA_W": "yes",
            "EMA_M": "upcut",
            "SPR_CONSIST": 80.0,
            "IC": "IP",
        },
        "STOCK_2": {
            "SPD_M": -1.0,
            "SPD_Q": -5.0,
            "SPD_Y": -10.0,
            "ACCEL_L": -0.5,
            "EMA_W": "no",
            "EMA_M": "downcut",
            "SPR_CONSIST": 50.0,
            "IC": "CR",
        },
    }

    # B1, B2, B3
    assert engine.evaluate(records, B1_SPRINTERS_MONTH.filter_group).matching_symbols == ["STOCK_1"]
    assert engine.evaluate(records, B2_SPRINTERS_QUARTER.filter_group).matching_symbols == ["STOCK_1"]
    assert engine.evaluate(records, B3_SPRINTERS_YEAR.filter_group).matching_symbols == ["STOCK_1"]

    # B4, B5
    assert engine.evaluate(records, B4_ACCELERATING.filter_group).matching_symbols == ["STOCK_1"]
    assert engine.evaluate(records, B5_ACCEL_AND_EMA_UP.filter_group).matching_symbols == ["STOCK_1"]

    # B6, B7, B8
    assert engine.evaluate(records, B6_CONSISTENT_RUNNERS.filter_group).matching_symbols == ["STOCK_1"]
    assert engine.evaluate(records, B7_IN_IMPULSE.filter_group).matching_symbols == ["STOCK_1"]
    assert engine.evaluate(records, B8_IN_CORRECTION.filter_group).matching_symbols == ["STOCK_2"]


def test_group_c_presets_evaluation():
    """Verify Group C (Band Breakouts) qualification logic."""
    engine = FilterEngine()

    records = {
        "OUT_ABOVE_ONLY": {"OUT_ABOVE": "D,W", "OUT_BELOW": "", "N_ABOVE": 2, "N_BELOW": 0},
        "OUT_BELOW_ONLY": {"OUT_ABOVE": "", "OUT_BELOW": "M", "N_ABOVE": 0, "N_BELOW": 1},
        "OUT_BOTH_1": {"OUT_ABOVE": "D", "OUT_BELOW": "Y", "N_ABOVE": 1, "N_BELOW": 1},
        "INSIDE": {"OUT_ABOVE": "", "OUT_BELOW": "", "N_ABOVE": 0, "N_BELOW": 0},
        "REACTION": {"BANDST_Y": "BELOW", "EMA_W": "upcut"},
    }

    # C1: OUT_ABOVE not blank
    assert engine.evaluate(records, C1_BROKE_ABOVE_BAND.filter_group).matching_symbols == [
        "OUT_ABOVE_ONLY",
        "OUT_BOTH_1",
    ]

    # C2: OUT_BELOW not blank
    assert engine.evaluate(records, C2_BROKE_BELOW_BAND.filter_group).matching_symbols == [
        "OUT_BELOW_ONLY",
        "OUT_BOTH_1",
    ]

    # C3: N_ABOVE + N_BELOW >= 2 (OUT_ABOVE_ONLY has 2+0=2, OUT_BOTH_1 has 1+1=2)
    assert engine.evaluate(records, C3_OUTSIDE_BAND_2PLUS_TF.filter_group).matching_symbols == [
        "OUT_ABOVE_ONLY",
        "OUT_BOTH_1",
    ]

    # C4: BANDST_Y == "BELOW" & EMA_W == "upcut"
    assert engine.evaluate(records, C4_REACTION_TRADE.filter_group).matching_symbols == [
        "REACTION",
    ]


def test_group_d_presets_evaluation():
    """Verify Group D (Exit Signals) qualification logic."""
    engine = FilterEngine()

    records = {
        "EXIT_FNO": {"fno": "Y", "EMA_D": "downcut", "EMA_W": "yes"},
        "EXIT_CASH": {"fno": "N", "EMA_D": "upcut", "EMA_W": "downcut"},
        "SAFE_FNO": {"fno": "Y", "EMA_D": "upcut", "EMA_W": "upcut"},
    }

    # D1
    assert engine.evaluate(records, D1_EXIT_FNO.filter_group).matching_symbols == ["EXIT_FNO"]

    # D2
    assert engine.evaluate(records, D2_EXIT_CASH.filter_group).matching_symbols == ["EXIT_CASH"]


def test_group_e_presets_ranking_and_cutoffs():
    """Verify Group E (Ranking & Cutoffs) specifications and catalog query generation."""
    catalog = load_mentor_presets()

    # E1 Top 100 Month
    q_e1 = catalog.to_query("E1_TOP_100_MONTH")
    assert q_e1.ranking_metric == "M_CUR"
    assert len(q_e1.selection_cutoffs) == 1
    assert q_e1.selection_cutoffs[0].rank_metric == "M_CUR"
    assert q_e1.selection_cutoffs[0].max_rank == 100

    # E2 Top 100 Year
    q_e2 = catalog.to_query("E2_TOP_100_YEAR")
    assert q_e2.ranking_metric == "YROC"
    assert len(q_e2.selection_cutoffs) == 1
    assert q_e2.selection_cutoffs[0].rank_metric == "YROC"
    assert q_e2.selection_cutoffs[0].max_rank == 100

    # E3 Rank Climbers
    engine = FilterEngine()
    records = {
        "CLIMBER": {"RANK_CHG": 5},
        "FALLER": {"RANK_CHG": -3},
        "FLAT": {"RANK_CHG": 0},
    }
    res_e3 = engine.evaluate(records, E3_RANK_CLIMBERS.filter_group)
    assert res_e3.matching_symbols == ["CLIMBER"]

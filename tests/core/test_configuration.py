"""Tests for YOGI Core Configuration — verifying EngineConfig, ScreeningQuery, and StrategyCatalog."""

from dataclasses import FrozenInstanceError
import pytest

from yogi.core.configuration import (
    EngineConfig,
    ScreeningQuery,
    StrategyCatalog,
)
from yogi.core.contracts.filter import (
    FilterGroupSpec,
    FilterOperator,
    FilterRuleSpec,
)
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.selection import RankCutoffSpec
from yogi.core.contracts.strategy import StrategySpec


# ---------------------------------------------------------------------------
# EngineConfig Tests
# ---------------------------------------------------------------------------


def test_engine_config_defaults():
    """Test 1: EngineConfig initializes with approved standard defaults."""
    config = EngineConfig()

    assert config.provider == "yfinance"
    assert config.bands_repository == "excel"
    assert config.calculation_modules == ("bands", "velocity", "impulse", "trend")
    assert config.exchange == "NSE"
    assert config.timeframes == ("D", "W", "M", "Q", "H", "Y")
    assert config.historical_years == 10
    assert config.symbol_limit is None
    assert config.symbols is None
    assert config.provider_options == {}


def test_engine_config_immutability():
    """Test 2: EngineConfig is immutable (frozen)."""
    config = EngineConfig()

    with pytest.raises(FrozenInstanceError):
        config.provider = "zerodha"  # type: ignore

    with pytest.raises(FrozenInstanceError):
        config.exchange = "BSE"  # type: ignore


def test_engine_config_stores_keys_as_pure_data():
    """Test 3: Capability keys are stored as strings and are not resolved/instantiated."""
    config = EngineConfig(provider="custom_provider", bands_repository="custom_bands")

    assert isinstance(config.provider, str)
    assert config.provider == "custom_provider"
    assert isinstance(config.bands_repository, str)
    assert config.bands_repository == "custom_bands"

    # Confirms config does not possess Registry lookup methods
    assert not hasattr(config, "resolve")
    assert not hasattr(config, "get_provider_instance")


def test_multiple_calculation_capability_keys_configurable():
    """Test 4: Multiple calculation capability keys can be configured."""
    config = EngineConfig(calculation_modules=("bands", "trend"))

    assert len(config.calculation_modules) == 2
    assert "bands" in config.calculation_modules
    assert "trend" in config.calculation_modules
    assert "velocity" not in config.calculation_modules


# ---------------------------------------------------------------------------
# ScreeningQuery Tests (QUALIFY -> ORDER -> SHOW)
# ---------------------------------------------------------------------------


def test_screening_query_qualify_order_show():
    """Test 5: ScreeningQuery correctly represents QUALIFY -> ORDER -> SHOW."""
    rule = FilterRuleSpec(field="WROC", op=FilterOperator.GT, value=0.0)
    group = FilterGroupSpec(match="all", rules=[rule])
    cutoff = RankCutoffSpec(rank_metric="M_CUR", max_rank=50)

    query = ScreeningQuery(
        filter_group=group,
        ranking_metric="M_CUR",
        ranking_order=RankingOrder.DESCENDING,
        selection_cutoffs=(cutoff,),
        limit=50,
    )

    # QUALIFY
    assert query.filter_group is group
    # ORDER
    assert query.ranking_metric == "M_CUR"
    assert query.ranking_order == RankingOrder.DESCENDING
    # SHOW
    assert len(query.selection_cutoffs) == 1
    assert query.selection_cutoffs[0].max_rank == 50
    assert query.limit == 50


def test_existing_contract_types_reused():
    """Tests 6, 7, 8: Existing contract types are reused rather than duplicated."""
    rule = FilterRuleSpec(field="DROC", op=FilterOperator.GTE, value=5.0)
    group = FilterGroupSpec(match="any", rules=[rule])
    cutoff = RankCutoffSpec(rank_metric="RANK_M", max_rank=100)

    query = ScreeningQuery(
        filter_group=group,
        ranking_metric="RANK_M",
        ranking_order=RankingOrder.ASCENDING,
        selection_cutoffs=(cutoff,),
    )

    # Test 6: Existing FilterGroupSpec is used
    assert isinstance(query.filter_group, FilterGroupSpec)
    # Test 7: Existing RankingOrder enum is used
    assert isinstance(query.ranking_order, RankingOrder)
    assert query.ranking_order == RankingOrder.ASCENDING
    # Test 8: Existing RankCutoffSpec is used
    assert isinstance(query.selection_cutoffs[0], RankCutoffSpec)


def test_screening_query_does_not_contain_presentation_columns():
    """Test 9: ScreeningQuery does NOT contain presentation-column projection."""
    query = ScreeningQuery()

    assert not hasattr(query, "columns"), (
        "ScreeningQuery must not absorb presentation column projection, "
        "which belongs to the Results Engine (IResultAssembler)."
    )
    assert not hasattr(query, "column_definitions")
    assert not hasattr(query, "fields")


# ---------------------------------------------------------------------------
# StrategyCatalog Tests
# ---------------------------------------------------------------------------


def test_strategy_catalog_register_retrieve_list():
    """Test 10: StrategyCatalog can register, retrieve, and list StrategySpec recipes."""
    rule = FilterRuleSpec(field="M_CUR", op=FilterOperator.GT, value=0.0)
    group = FilterGroupSpec(match="all", rules=[rule])
    spec = StrategySpec(
        name="YOGI WINNERS",
        filter_group=group,
        target_ranking_metric="M_CUR",
        target_cutoff_limit=100,
        is_mentor_preset=True,
    )

    catalog = StrategyCatalog()
    catalog.register(spec)

    assert catalog.has("YOGI WINNERS") is True
    assert "YOGI WINNERS" in catalog
    assert catalog.get("YOGI WINNERS") is spec
    assert catalog["YOGI WINNERS"] is spec
    assert catalog.list_names() == ["YOGI WINNERS"]
    assert len(catalog) == 1

    # Duplicate rejected
    with pytest.raises(ValueError):
        catalog.register(spec)

    # Missing key error
    with pytest.raises(KeyError):
        catalog.get("NONEXISTENT")


def test_strategy_catalog_does_not_instantiate_implementations():
    """Test 11: StrategyCatalog stores declarative data recipes only."""
    catalog = StrategyCatalog()

    # Confirms catalog is not a Registry and does not possess factory/instance caches
    assert not hasattr(catalog, "register_factory")
    assert not hasattr(catalog, "_factories")
    assert not hasattr(catalog, "_instances")


def test_strategy_catalog_to_query_conversion():
    """Test 12: Strategy conversion maps target_cutoff_limit to RankCutoffSpec, not display limit."""
    rule = FilterRuleSpec(field="ACCEL_L", op=FilterOperator.GT, value=0.0)
    group = FilterGroupSpec(match="all", rules=[rule])
    spec = StrategySpec(
        name="ACCELERATING",
        filter_group=group,
        target_ranking_metric="ACCEL_L",
        target_cutoff_limit=30,
        is_mentor_preset=True,
    )

    catalog = StrategyCatalog([spec])
    query = catalog.to_query("ACCELERATING")

    assert isinstance(query, ScreeningQuery)
    # QUALIFY
    assert query.filter_group is group
    # ORDER
    assert query.ranking_metric == "ACCEL_L"
    assert query.ranking_order == RankingOrder.DESCENDING
    # SHOW (Selection)
    assert len(query.selection_cutoffs) == 1
    assert query.selection_cutoffs[0].rank_metric == "ACCEL_L"
    assert query.selection_cutoffs[0].max_rank == 30
    # PRESENTATION: query.limit remains None (StrategySpec is decoupled from display truncation)
    assert query.limit is None


def test_strategy_catalog_to_query_without_ranking_metric():
    """Test 13: A strategy without a target ranking metric produces an unranked query without cutoffs."""
    rule = FilterRuleSpec(field="WROC", op=FilterOperator.GT, value=0.0)
    group = FilterGroupSpec(match="all", rules=[rule])
    spec = StrategySpec(
        name="POSITIVE_ROC",
        filter_group=group,
        target_ranking_metric=None,
        target_cutoff_limit=None,
    )

    catalog = StrategyCatalog([spec])
    query = catalog.to_query("POSITIVE_ROC")

    assert query.filter_group is group
    assert query.ranking_metric is None
    assert query.selection_cutoffs == ()
    assert query.limit is None


def test_rank_cutoff_spec_and_query_limit_distinct_responsibilities():
    """Test 14: Proves RankCutoffSpec (SHOW/Selection) and limit (Result cap) represent distinct responsibilities."""
    cutoff = RankCutoffSpec(rank_metric="M_CUR", max_rank=100)
    query = ScreeningQuery(
        ranking_metric="M_CUR",
        selection_cutoffs=(cutoff,),
        limit=25,
    )

    # Rank cutoff evaluates whether a security's calculated rank qualifies (analytical selection)
    assert query.selection_cutoffs[0].max_rank == 100
    # Query limit truncates the number of returned records (presentation/pagination)
    assert query.limit == 25
    # The two are fundamentally decoupled in the contract
    assert query.selection_cutoffs[0].max_rank != query.limit

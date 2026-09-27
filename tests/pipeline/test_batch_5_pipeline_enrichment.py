"""Tests for Batch 5 Pipeline Record Enrichment and F&O Screening."""

from datetime import datetime
from pathlib import Path
import pytest

from tests.core.test_orchestration import MockBandsRepo, MockDataProvider
from yogi.core.configuration.engine import EngineConfig
from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.market_data import MarketBar
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.filter.engine import FilterEngine
from yogi.ranking.engine import RankingEngine
from yogi.selection.engine import SelectionEngine
from yogi.storage.metadata import CsvMetadataRepository
from yogi.timeframe.engine import TimeframeEngine


def test_pipeline_build_dataset_enriches_metadata(tmp_path: Path):
    repo = CsvMetadataRepository(data_dir=tmp_path)
    repo.update_metadata("RELIANCE", "name", "Reliance Industries Limited")
    repo.update_metadata("RELIANCE", "sector", "Oil & Gas")
    repo.update_metadata("RELIANCE", "grade", "A")
    repo.update_metadata("RELIANCE", "mcap", 1950000.0)
    repo.update_metadata("RELIANCE", "fno", "Y")
    repo.update_metadata("RELIANCE", "instrument_type", "EQ")
    repo.update_metadata("RELIANCE", "series_or_group", "EQ")

    repo.update_metadata("TCS", "name", "Tata Consultancy Services")
    repo.update_metadata("TCS", "sector", "IT")
    repo.update_metadata("TCS", "fno", "N")

    hub = RegistryHub()
    bars = [
        MarketBar(
            timestamp=datetime(2026, 1, 1),
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
            volume=1000.0,
        )
    ]
    provider = MockDataProvider(
        universe_symbols=["RELIANCE", "TCS"],
        history_map={"RELIANCE": bars, "TCS": bars},
    )
    hub.providers.register("mock", provider)
    hub.bands.register("mock_bands", MockBandsRepo())

    orchestrator = PipelineOrchestrator(
        registry=hub,
        metadata_repository=repo,
        timeframe_engine=TimeframeEngine(),
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )

    config = EngineConfig(
        provider="mock",
        bands_repository="mock_bands",
        calculation_modules=[],
        symbols=["RELIANCE", "TCS"],
    )

    records = orchestrator.build_dataset(config)

    assert "RELIANCE" in records
    rel = records["RELIANCE"]
    assert rel["symbol"] == "RELIANCE"
    assert rel["name"] == "Reliance Industries Limited"
    assert rel["sector"] == "Oil & Gas"
    assert rel["grade"] == "A"
    assert rel["mcap"] == 1950000.0
    assert rel["fno"] == "Y"
    assert rel["instr"] == "EQ"
    assert rel["grp"] == "EQ"

    assert "TCS" in records
    tcs = records["TCS"]
    assert tcs["symbol"] == "TCS"
    assert tcs["name"] == "Tata Consultancy Services"
    assert tcs["sector"] == "IT"
    assert tcs["fno"] == "N"


def test_pipeline_screening_fno_filter(tmp_path: Path):
    records = {
        "RELIANCE": {"symbol": "RELIANCE", "price": 2500.0, "fno": "Y"},
        "TCS": {"symbol": "TCS", "price": 3800.0, "fno": "N"},
        "INFY": {"symbol": "INFY", "price": 1800.0, "fno": "Y"},
    }

    orchestrator = PipelineOrchestrator(
        registry=RegistryHub(),
        filter_rule=FilterEngine(),
        ranking_rule=RankingEngine(),
        selection_rule=SelectionEngine(),
    )

    fno_filter = FilterGroupSpec(
        match="all",
        rules=[
            FilterRuleSpec(field="fno", op=FilterOperator.EQ, value="Y"),
        ],
    )

    query = ScreeningQuery(
        filter_group=fno_filter,
    )

    result = orchestrator.execute_screen(query=query, records=records)
    selected_symbols = [r["symbol"] for r in result.rows]

    assert "RELIANCE" in selected_symbols
    assert "INFY" in selected_symbols
    assert "TCS" not in selected_symbols
    assert len(selected_symbols) == 2

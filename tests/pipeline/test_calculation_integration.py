"""Pipeline calculation integration tests — verify dispatch of calculation modules via RegistryHub."""

from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence
import pytest

from tests.core.test_orchestration import MockBandsRepo, MockDataProvider
from yogi.calculation.bands import BandsCalculator
from yogi.calculation.candles import CandleCalculator
from yogi.calculation.impulse import ImpulseCalculator
from yogi.calculation.trend import TrendCalculator
from yogi.calculation.velocity import VelocityCalculator
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.timeframe.engine import TimeframeEngine


@pytest.fixture
def sample_daily_bars() -> Sequence[MarketBar]:
    base_date = datetime(2025, 1, 1)
    bars = []
    for i in range(300):
        dt = base_date + timedelta(days=i)
        p = 100.0 + i * 0.2
        bars.append(
            MarketBar(
                timestamp=dt,
                open=p,
                high=p + 1.0,
                low=p - 1.0,
                close=p,
                volume=10000.0,
            )
        )
    return bars


@pytest.fixture
def configured_orchestrator(sample_daily_bars: Sequence[MarketBar]) -> tuple[PipelineOrchestrator, RegistryHub]:
    registry = RegistryHub()

    # Register Data Provider
    provider = MockDataProvider(
        universe_symbols=["TEST1", "TEST2"],
        history_map={"TEST1": sample_daily_bars, "TEST2": sample_daily_bars},
    )
    registry.providers.register("mock", provider)

    # Register Bands Repo
    bands_repo = MockBandsRepo(
        bands_store={"TEST1": {"D": 0.05, "W": 0.10, "M": 0.15}},
    )
    registry.bands.register("mock_bands", bands_repo)

    # Register all 4 Calculation Modules
    registry.calculations.register("bands", BandsCalculator())
    registry.calculations.register("velocity", VelocityCalculator())
    registry.calculations.register("impulse", ImpulseCalculator())
    registry.calculations.register("trend", TrendCalculator())

    orchestrator = PipelineOrchestrator(
        registry=registry,
        timeframe_engine=TimeframeEngine(),
    )
    return orchestrator, registry


def test_build_dataset_all_four_pillars(configured_orchestrator):
    orchestrator, registry = configured_orchestrator

    config = EngineConfig(
        provider="mock",
        bands_repository="mock_bands",
        calculation_modules=("bands", "velocity", "impulse", "trend"),
        symbols=("TEST1", "TEST2"),
        timeframes=("D", "W", "M", "Q", "H", "Y"),
    )

    records = orchestrator.build_dataset(config)
    assert set(records.keys()) == {"TEST1", "TEST2"}

    rec1 = records["TEST1"]
    assert rec1["symbol"] == "TEST1"
    assert rec1["price"] is not None

    # Pillar 1: Bands
    assert "BAND_D" in rec1
    assert "BANDST_D" in rec1
    assert "BD_D" in rec1
    assert "OUT_ABOVE" in rec1

    # Pillar 2: Velocity
    assert "S4" in rec1
    assert "S13" in rec1
    assert "ACCEL_S" in rec1
    assert "SPR_CONSIST" in rec1

    # Pillar 3: Impulse
    assert "IC" in rec1
    assert rec1["IC"] in ("IP", "CR", "up", "na")

    # Pillar 4: Trend
    assert "DROC" in rec1
    assert "M_CUR" in rec1
    assert "EMA_D" in rec1
    assert "CAGR_1" in rec1
    assert "SUSPECT" in rec1


def test_build_dataset_selective_modules(configured_orchestrator):
    orchestrator, registry = configured_orchestrator

    config = EngineConfig(
        provider="mock",
        bands_repository="mock_bands",
        calculation_modules=("bands", "impulse"),
        symbols=("TEST1",),
        timeframes=("D",),
    )

    records = orchestrator.build_dataset(config)
    rec1 = records["TEST1"]

    # Bands & Impulse present
    assert "BAND_D" in rec1
    assert "IC" in rec1

    # Velocity & Trend omitted
    assert "S4" not in rec1
    assert "DROC" not in rec1


def test_unregistered_calculation_module_raises(configured_orchestrator):
    orchestrator, registry = configured_orchestrator

    config = EngineConfig(
        provider="mock",
        bands_repository="mock_bands",
        calculation_modules=("bands", "nonexistent_module"),
        symbols=("TEST1",),
    )

    with pytest.raises(KeyError, match="nonexistent_module"):
        orchestrator.build_dataset(config)


def test_build_dataset_with_candle_calculator(sample_daily_bars):
    """Verify CandleCalculator registers in RegistryHub and executes via PipelineOrchestrator."""
    registry = RegistryHub()
    provider = MockDataProvider(
        universe_symbols=["CANDLE1"],
        history_map={"CANDLE1": sample_daily_bars},
    )
    registry.providers.register("mock", provider)
    registry.bands.register("mock_bands", MockBandsRepo())
    registry.calculations.register("candles", CandleCalculator())

    orchestrator = PipelineOrchestrator(
        registry=registry,
        timeframe_engine=TimeframeEngine(),
    )

    config = EngineConfig(
        provider="mock",
        bands_repository="mock_bands",
        calculation_modules=("candles",),
        symbols=("CANDLE1",),
        timeframes=("D", "W", "M", "Q", "H", "Y"),
    )

    records = orchestrator.build_dataset(config)
    assert "CANDLE1" in records
    rec = records["CANDLE1"]
    assert "CD_O" in rec
    assert "CD_C" in rec
    assert "CD_BODY" in rec
    assert "CD_BULL_ENGULF" in rec
    assert "CW_O" in rec
    assert "CM_O" in rec

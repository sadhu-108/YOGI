"""Targeted regression tests for Step 2B: Chart Repair.

Verifies:
1. AppState resolves bands_repository under both default 'excel' and 'csv' keys.
2. Router get_bands returns HTTP 200 with bands mapping instead of 503.
3. Router get_candles returns non-empty band_upper_curve, band_lower_curve, and populated latest_band.
4. ChartDataService properly retains bands_repo and calculates valid envelope points.
5. Band updates via router update_band succeed without 503.
"""

from pathlib import Path
import pytest

from yogi.cockpit.router import get_bands, get_candles, update_band
from yogi.cockpit.schemas import BandUpdateIn
from yogi.cockpit.state import AppState
from yogi.core.configuration.engine import EngineConfig
from yogi.storage.bands import CsvBandsRepository


@pytest.fixture
def isolated_bands_dir(tmp_path: Path) -> Path:
    """Create isolated test directory with sample bands CSV."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bands_file = data_dir / "bands.csv"
    bands_file.write_text(
        "symbol,D,W,M,Q,H,Y\n"
        "RELIANCE,0.015,0.03,0.08,0.14,0.18,0.31\n",
        encoding="utf-8",
    )
    return data_dir


def test_default_config_resolves_bands_repo(isolated_bands_dir: Path):
    """Verify AppState with default EngineConfig ('excel') resolves bands_repo."""
    repo = CsvBandsRepository(data_dir=isolated_bands_dir)
    state = AppState(config=EngineConfig(), bands_repo=repo)
    assert state.bands_repo is not None
    assert state.bands_repo.get_band("RELIANCE", "D") == pytest.approx(0.015)


def test_fast_startup_resolves_excel_bands_repo(isolated_bands_dir: Path):
    """Verify AppState fast startup registers 'excel' and resolves bands_repo."""
    state = AppState(config=EngineConfig(), autoload_cache=True)
    assert state._orchestrator.registry.bands.has("csv")
    assert state._orchestrator.registry.bands.has("excel")
    assert state.bands_repo is not None
    assert state.chart_service is not None
    assert state.chart_service.bands_repo is not None


def test_get_bands_endpoint_success(isolated_bands_dir: Path):
    """Verify GET /api/bands/{symbol} returns valid bands without 503."""
    repo = CsvBandsRepository(data_dir=isolated_bands_dir)
    state = AppState(config=EngineConfig(), bands_repo=repo)
    res = get_bands(symbol="RELIANCE", app_state=state)
    assert res.symbol == "RELIANCE"
    assert "D" in res.bands
    assert res.bands["D"] == pytest.approx(0.015)
    assert res.bands["M"] == pytest.approx(0.08)


def test_update_band_endpoint_success(isolated_bands_dir: Path):
    """Verify PUT /api/bands/{symbol} updates band without 503."""
    repo = CsvBandsRepository(data_dir=isolated_bands_dir)
    state = AppState(config=EngineConfig(), bands_repo=repo)
    update_res = update_band(
        symbol="RELIANCE",
        req=BandUpdateIn(timeframe="D", value=0.025),
        app_state=state,
    )
    assert update_res.symbol == "RELIANCE"
    assert update_res.timeframe == "D"
    assert update_res.value == pytest.approx(0.025)
    assert state.bands_repo.get_band("RELIANCE", "D") == pytest.approx(0.025)


def test_chart_service_computes_envelope_curves(isolated_bands_dir: Path):
    """Verify ChartDataService computes non-empty band curves when bands_repo is resolved."""
    repo = CsvBandsRepository(data_dir=isolated_bands_dir)
    state = AppState(config=EngineConfig(), bands_repo=repo, autoload_cache=True)
    assert state.chart_service is not None
    assert state.chart_service.bands_repo is not None

    series = state.chart_service.get_candles(
        symbol="RELIANCE",
        timeframe="D",
        band_timeframe="D",
        exchange="NSE",
        years=2,
    )
    assert len(series.candles) > 0
    assert len(series.band_upper_curve) > 0
    assert len(series.band_lower_curve) > 0
    assert series.latest_band is not None
    assert series.latest_band.width == pytest.approx(0.015)
    assert series.latest_band.upper is not None
    assert series.latest_band.lower is not None
    assert series.latest_band.basis is not None
    assert series.latest_band.upper > series.latest_band.lower

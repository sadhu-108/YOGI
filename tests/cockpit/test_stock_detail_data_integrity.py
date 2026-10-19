"""Regression tests for Stock Detail Data Integrity:
1. On-demand stock detail reuses cached bars and avoids unnecessary provider calls.
2. Band updates become visible in stock-detail results without full-universe rebuild.
3. Daily Speed is represented as unsupported (N/A) with no invented formula.
4. QROC and HROC are exposed in StockDetailPanelOut.key_metrics and serialized correctly.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
import pytest

from yogi.cockpit.app import create_app
from yogi.cockpit.charting import ChartDataService
from yogi.cockpit.demo import DemoBandsRepository
from yogi.cockpit.schemas import StockDetailPanelOut
from yogi.cockpit.state import AppState, EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry import RegistryHub
from yogi.timeframe.engine import TimeframeEngine
from yogi.calculation.bands import BandsCalculator
from yogi.calculation.candles import CandleCalculator
from yogi.calculation.impulse import ImpulseCalculator
from yogi.calculation.trend import TrendCalculator
from yogi.calculation.velocity import VelocityCalculator
from yogi.storage.bands import CsvBandsRepository
from yogi.storage.cache import MarketBarsCache
from tests.cockpit.test_cockpit_demo import AsgiTestClient


class StrictMockProvider(IDataProvider):
    """Mock provider tracking calls and strictly raising when live fetching is forbidden."""

    def __init__(self, name: str = "strict_mock") -> None:
        self._name = name
        self.daily_history_calls: list[str] = []
        self.batch_calls: list[Sequence[str]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return ["CACHED_STOCK", "UNCACHED_STOCK"]

    def daily_history(
        self, symbol: str, exchange: str = "NSE", years: int = 2
    ) -> Sequence[MarketBar]:
        self.daily_history_calls.append(symbol)
        if symbol == "UNCACHED_STOCK":
            base = datetime(2025, 1, 1)
            return [
                MarketBar(
                    timestamp=base + timedelta(days=i),
                    open=100.0 + i,
                    high=105.0 + i,
                    low=95.0 + i,
                    close=102.0 + i,
                    volume=1000.0,
                )
                for i in range(100)
            ]
        raise RuntimeError(f"Unexpected live provider call for '{symbol}'!")

    def batch_daily_history(
        self, symbols: Sequence[str], exchange: str = "NSE", years: int = 2
    ) -> Mapping[str, Sequence[MarketBar]]:
        self.batch_calls.append(symbols)
        return {s: self.daily_history(s, exchange, years) for s in symbols}

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        return 100.0

    def intraday(self, *args, **kwargs):
        return ()

    def subscribe_ticks(self, *args, **kwargs):
        return None

    def trading_holidays(self, year=None):
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self._name, ok=True)


def _generate_bars(num_bars: int = 150) -> list[MarketBar]:
    base = datetime(2025, 1, 1)
    return [
        MarketBar(
            timestamp=base + timedelta(days=i),
            open=100.0 + i * 0.5,
            high=105.0 + i * 0.5,
            low=95.0 + i * 0.5,
            close=100.0 + i * 0.5,
            volume=5000.0,
        )
        for i in range(num_bars)
    ]


# =============================================================================
# 1. Reuse Cached Bars in On-Demand Stock Detail
# =============================================================================

def test_on_demand_panel_reuses_cached_bars_without_calling_provider(tmp_path: Path):
    """Verify on-demand panel resolution uses _bars_cache avoiding live provider calls."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    # Seed 100 bars for CACHED_STOCK into local cache
    bars = _generate_bars(100)
    bars_cache.save_bars({"CACHED_STOCK": bars}, exchange="NSE", provider="strict_mock")

    provider = StrictMockProvider()
    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("demo", DemoBandsRepository())

    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
    state = AppState(
        orchestrator=orchestrator,
        config=EngineConfig(provider="strict_mock", bands_repository="demo"),
        bars_cache=bars_cache,
    )

    # Symbol is NOT in state.dataset
    assert "CACHED_STOCK" not in state.dataset

    # Request panel on-demand
    panel = state.get_stock_panel("CACHED_STOCK")

    # Verification:
    # 1. Panel is successfully computed from cached bars
    assert panel is not None
    assert panel.symbol == "CACHED_STOCK"
    assert panel.price == bars[-1].close
    assert len(panel.timeframes) == 6

    # 2. Strict provider was NOT invoked for CACHED_STOCK (would raise RuntimeError if called)
    assert "CACHED_STOCK" not in provider.daily_history_calls

    # 3. Requesting an uncached stock genuine calls provider
    uncached_panel = state.get_stock_panel("UNCACHED_STOCK")
    assert uncached_panel is not None
    assert "UNCACHED_STOCK" in provider.daily_history_calls


# =============================================================================
# 2. Refresh Stock Detail After Band Configuration Changes
# =============================================================================

def test_band_update_visible_in_stock_detail_without_full_rebuild(tmp_path: Path):
    """Verify band updates invalidate stale cohort row and compute fresh levels in matrix."""
    bands_repo = CsvBandsRepository(data_dir=tmp_path)
    # Seed initial bands
    bands_repo.set_band("STOCK_A", "M", 0.10)
    bands_repo.set_band("STOCK_B", "M", 0.20)

    # Initial materialized cohort with pre-calculated values
    initial_dataset = {
        "STOCK_A": {
            "symbol": "STOCK_A",
            "price": 100.0,
            "exchange": "NSE",
            "BAND_M": 0.10,
            "BANDST_M": "IN",
            "BANDUP_M": 110.0,
            "BANDLO_M": 90.0,
            "BD_M": 0.0,
        },
        "STOCK_B": {
            "symbol": "STOCK_B",
            "price": 200.0,
            "exchange": "NSE",
            "BAND_M": 0.20,
            "BANDST_M": "IN",
            "BANDUP_M": 240.0,
            "BANDLO_M": 160.0,
            "BD_M": 0.0,
        },
    }

    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    bars_cache.save_bars({"STOCK_A": _generate_bars(100), "STOCK_B": _generate_bars(100)}, "NSE", "strict_mock")

    provider = StrictMockProvider()
    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("csv", bands_repo)

    orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
    state = AppState(
        orchestrator=orchestrator,
        bands_repo=bands_repo,
        config=EngineConfig(provider="strict_mock", bands_repository="csv"),
        bars_cache=bars_cache,
        initial_dataset=initial_dataset,
    )

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Initial check: STOCK_A has 0.10 band
    res0 = client.get("/api/panel/STOCK_A")
    assert res0.status_code == 200
    panel_data0 = res0.json()
    m_row0 = next(r for r in panel_data0["timeframes"] if r["timeframe"] == "M")
    assert m_row0["band_width"] == 0.10
    assert m_row0["band_upper"] == 110.0

    # User updates STOCK_A band via API to 0.25
    update_res = client.put("/api/bands/STOCK_A", json={"timeframe": "M", "value": 0.25})
    assert update_res.status_code == 200

    # Verification:
    # 1. Immediate call to /api/panel/STOCK_A reflects new band width (0.25) and recalculated levels
    res1 = client.get("/api/panel/STOCK_A")
    assert res1.status_code == 200
    panel_data1 = res1.json()
    m_row1 = next(r for r in panel_data1["timeframes"] if r["timeframe"] == "M")
    assert m_row1["band_width"] == 0.25
    assert m_row1["band_upper"] != 110.0  # Recalculated with 0.25 width

    # 2. Unrelated STOCK_B remains completely intact with its original values
    res_b = client.get("/api/panel/STOCK_B")
    assert res_b.status_code == 200
    m_row_b = next(r for r in res_b.json()["timeframes"] if r["timeframe"] == "M")
    assert m_row_b["band_width"] == 0.20
    assert m_row_b["band_upper"] == 240.0

    # 3. self._dataset immutability was preserved
    assert state.dataset["STOCK_A"]["BAND_M"] == 0.10


# =============================================================================
# 3. Handle Daily Speed Consistently
# =============================================================================

def test_daily_speed_is_consistently_none_without_invented_formula(tmp_path: Path):
    """Verify Daily Speed is null in payload and app.js renders N/A for D timeframe."""
    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    bars_cache.save_bars({"STOCK_A": _generate_bars(100)}, "NSE", "strict_mock")

    provider = StrictMockProvider()
    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("demo", DemoBandsRepository())

    state = AppState(
        orchestrator=PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine()),
        config=EngineConfig(provider="strict_mock", bands_repository="demo"),
        bars_cache=bars_cache,
    )

    panel = state.get_stock_panel("STOCK_A")
    assert panel is not None

    d_row = next(r for r in panel.timeframes if r.timeframe == "D")
    w_row = next(r for r in panel.timeframes if r.timeframe == "W")

    # In calculation / backend, Daily speed is None (unsupported lookback)
    assert d_row.speed is None
    # Weekly speed is calculated and present
    assert w_row.speed is not None

    # Inspect app.js source to confirm timeframe D is explicitly represented as N/A
    app_js_path = Path("src/yogi/cockpit/static/js/app.js")
    content = app_js_path.read_text(encoding="utf-8")
    assert "if (row.timeframe === 'D') return '<span class=\"val-null\" title=\"Sprint velocity is defined for Weekly (W) and higher timeframes\">N/A</span>';" in content


# =============================================================================
# 4. Expose QROC and HROC in Stock-Detail Metrics
# =============================================================================

def test_qroc_and_hroc_exposed_in_stock_detail_metrics(tmp_path: Path):
    """Verify QROC and HROC reach key_metrics and correctly serialize to float or null."""
    # 1. Sufficient history (150 bars > 126 bars needed for HROC)
    long_bars = _generate_bars(150)
    # 2. Mid history (100 bars >= 63 bars for QROC, but < 126 bars needed for HROC)
    mid_bars = _generate_bars(100)
    # 3. Short history (61 bars satisfies cache min_bars=60, but < 63 bars needed for QROC)
    short_bars = _generate_bars(61)

    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    bars_cache.save_bars(
        {"LONG_STOCK": long_bars, "MID_STOCK": mid_bars, "SHORT_STOCK": short_bars},
        "NSE",
        "strict_mock",
    )

    provider = StrictMockProvider()
    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("demo", DemoBandsRepository())

    state = AppState(
        orchestrator=PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine()),
        config=EngineConfig(provider="strict_mock", bands_repository="demo"),
        bars_cache=bars_cache,
    )

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Test LONG_STOCK: both QROC and HROC are available floats
    res_long = client.get("/api/panel/LONG_STOCK")
    assert res_long.status_code == 200
    data_long = res_long.json()
    km_long = data_long.get("key_metrics", {})
    assert "QROC" in km_long
    assert "HROC" in km_long
    assert isinstance(km_long["QROC"], float)
    assert isinstance(km_long["HROC"], float)

    # Test MID_STOCK: QROC is available float, HROC is unavailable (null)
    res_mid = client.get("/api/panel/MID_STOCK")
    assert res_mid.status_code == 200
    data_mid = res_mid.json()
    km_mid = data_mid.get("key_metrics", {})
    assert "QROC" in km_mid
    assert "HROC" in km_mid
    assert isinstance(km_mid["QROC"], float)
    assert km_mid["HROC"] is None

    # Test SHORT_STOCK: QROC and HROC are both unavailable and cleanly serialized as null
    res_short = client.get("/api/panel/SHORT_STOCK")
    assert res_short.status_code == 200
    data_short = res_short.json()
    km_short = data_short.get("key_metrics", {})
    assert "QROC" in km_short
    assert "HROC" in km_short
    assert km_short["QROC"] is None
    assert km_short["HROC"] is None


# =============================================================================
# 5. Band Update Preserves Chart Cache (No Live Provider Fetch)
# =============================================================================

def test_band_update_preserves_chart_cache_and_updates_envelope(tmp_path: Path):
    """Verify band update does not evict raw bars from ChartDataService and envelope updates instantly."""
    bands_repo = CsvBandsRepository(data_dir=tmp_path)
    bands_repo.set_band("STOCK_A", "M", 0.10)

    provider = StrictMockProvider()
    chart_svc = ChartDataService(provider=provider, bands_repo=bands_repo)
    # Prime ChartDataService cache with 100 historical bars
    bars = _generate_bars(100)
    chart_svc._put_cached(("STOCK_A", "NSE", 2), bars)
    assert chart_svc.cache_size == 1

    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("csv", bands_repo)

    state = AppState(
        orchestrator=PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine()),
        bands_repo=bands_repo,
        chart_service=chart_svc,
        config=EngineConfig(provider="strict_mock", bands_repository="csv"),
    )

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Initial chart request: uses cached bars, reflects 0.10 band
    res0 = client.get("/api/candles/STOCK_A", params={"tf": "D", "band_tf": "M"})
    assert res0.status_code == 200
    data0 = res0.json()
    assert data0["latest_band"]["width"] == 0.10
    assert "STOCK_A" not in provider.daily_history_calls

    # Update band width to 0.35 via API
    up_res = client.put("/api/bands/STOCK_A", json={"timeframe": "M", "value": 0.35})
    assert up_res.status_code == 200

    # Verification:
    # 1. Chart cache size is preserved (raw bars NOT evicted)
    assert chart_svc.cache_size == 1
    # 2. Subsequent chart request uses retained bars without calling provider
    res1 = client.get("/api/candles/STOCK_A", params={"tf": "D", "band_tf": "M"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["latest_band"]["width"] == 0.35
    assert data1["latest_band"]["upper"] != data0["latest_band"]["upper"]
    # 3. Provider daily_history was strictly never called (StrictMockProvider would raise on call)
    assert "STOCK_A" not in provider.daily_history_calls


# =============================================================================
# 6. Matrix and Chart Consistency After Band Update
# =============================================================================

def test_matrix_and_chart_consistency_after_band_update(tmp_path: Path):
    """Verify matrix and chart both reflect latest band configuration and calculated levels."""
    bands_repo = CsvBandsRepository(data_dir=tmp_path)
    bands_repo.set_band("STOCK_A", "D", 0.10)

    bars_cache = MarketBarsCache(cache_dir=tmp_path)
    bars = _generate_bars(100)
    bars_cache.save_bars({"STOCK_A": bars}, "NSE", "strict_mock")

    provider = StrictMockProvider()
    chart_svc = ChartDataService(provider=provider, bands_repo=bands_repo)
    chart_svc._put_cached(("STOCK_A", "NSE", 2), bars)

    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("csv", bands_repo)

    state = AppState(
        orchestrator=PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine()),
        bands_repo=bands_repo,
        chart_service=chart_svc,
        bars_cache=bars_cache,
        config=EngineConfig(provider="strict_mock", bands_repository="csv"),
    )

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Update band width to 0.18 for Daily timeframe
    up_res = client.put("/api/bands/STOCK_A", json={"timeframe": "D", "value": 0.18})
    assert up_res.status_code == 200

    # Retrieve panel and candles
    panel_res = client.get("/api/panel/STOCK_A")
    chart_res = client.get("/api/candles/STOCK_A", params={"tf": "D", "band_tf": "D"})
    assert panel_res.status_code == 200
    assert chart_res.status_code == 200

    panel = panel_res.json()
    chart = chart_res.json()

    d_row = next(r for r in panel["timeframes"] if r["timeframe"] == "D")
    assert d_row["band_width"] == 0.18
    assert chart["latest_band"]["width"] == 0.18

    # Verification: Calculated upper and lower levels are strictly consistent
    assert d_row["band_upper"] == chart["latest_band"]["upper"]
    assert d_row["band_lower"] == chart["latest_band"]["lower"]


# =============================================================================
# 7. Backup Restoration Preserves Chart Cache
# =============================================================================

def test_band_backup_restoration_preserves_chart_cache(tmp_path: Path):
    """Verify backup restoration marks panel dirty but preserves raw bars in chart cache."""
    bands_repo = CsvBandsRepository(data_dir=tmp_path)
    bands_repo.set_band("STOCK_A", "M", 0.10)

    # Write a dated backup snapshot file with 0.10 band
    backup_filename = "bands_2026-04-01.csv"
    bands_repo.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = bands_repo.backup_dir / backup_filename
    bands_repo._atomic_write_bands_file({"STOCK_A": {"M": 0.10}}, backup_path)
    assert backup_path.is_file()

    # Modify active band to 0.40
    bands_repo.set_band("STOCK_A", "M", 0.40)
    assert bands_repo.get_band("STOCK_A", "M") == 0.40

    provider = StrictMockProvider()
    chart_svc = ChartDataService(provider=provider, bands_repo=bands_repo)
    bars = _generate_bars(100)
    chart_svc._put_cached(("STOCK_A", "NSE", 2), bars)

    hub = RegistryHub()
    hub.providers.register("strict_mock", provider)
    hub.calculations.register("bands", BandsCalculator())
    hub.calculations.register("velocity", VelocityCalculator())
    hub.calculations.register("impulse", ImpulseCalculator())
    hub.calculations.register("trend", TrendCalculator())
    hub.calculations.register("candles", CandleCalculator())
    hub.bands.register("csv", bands_repo)

    state = AppState(
        orchestrator=PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine()),
        bands_repo=bands_repo,
        chart_service=chart_svc,
        config=EngineConfig(provider="strict_mock", bands_repository="csv"),
    )

    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # Restore backup
    restore_res = client.post(f"/api/bands/restore/{backup_filename}")
    assert restore_res.status_code == 200

    # Verification:
    # 1. Chart cache size preserved (raw bars NOT evicted)
    assert chart_svc.cache_size == 1
    # 2. Subsequent chart request uses restored band width (0.10) without calling provider
    res_chart = client.get("/api/candles/STOCK_A", params={"tf": "D", "band_tf": "M"})
    assert res_chart.status_code == 200
    assert res_chart.json()["latest_band"]["width"] == 0.10
    assert "STOCK_A" not in provider.daily_history_calls


# =============================================================================
# 8. Frontend Enter-to-Save and Validation Specifications
# =============================================================================

def test_frontend_band_editor_enter_to_save_specs():
    """Verify frontend code contains only compact numeric input and robust Enter-to-save."""
    app_js_path = Path("src/yogi/cockpit/static/js/app.js")
    content = app_js_path.read_text(encoding="utf-8")

    # 1. btn-matrix-save is removed from app.js
    assert "btn-matrix-save" not in content

    # 2. In renderBandWidthCell, there is only the numeric input (no button, no tick, no ellipsis)
    cell_start = content.find("function renderBandWidthCell")
    cell_end = content.find("function renderLevelCell")
    matrix_cell_code = content[cell_start:cell_end]
    assert "<button" not in matrix_cell_code
    assert "✓" not in matrix_cell_code
    assert "..." not in matrix_cell_code

    # 3. Numeric input has data-confirmed-val and keydown Enter handler
    assert 'class="matrix-band-input" data-tf="${row.timeframe}" data-confirmed-val="${val}"' in content
    assert "if (e.key !== 'Enter') return;" in content
    assert "e.preventDefault();" in content

    # 4. Validation rejects out-of-range, non-finite, and negative values
    assert "if (isNaN(val) || !isFinite(val) || val <= 0 || val > 100)" in content

    # 5. Unchanged value check prevents wasteful requests
    assert "Math.abs(val - confirmedNum) < 0.0001" in content

    # 6. Duplicate submission guard disables input during in-flight request and restores in finally
    assert "if (!activeSymbol || input.disabled) return;" in content
    assert "input.disabled = true;" in content
    assert "input.disabled = false;" in content

    # 7. Promise.allSettled used for concurrent refreshes
    assert "Promise.allSettled([" in content
    assert "loadChartData(targetSymbol, reqId)" in content
    assert "loadStockPanel(targetSymbol, reqId)" in content

    # 8. CSS verifies btn-matrix-save removed and matrix-band-input centered
    css_path = Path("src/yogi/cockpit/static/css/cockpit.css")
    css_content = css_path.read_text(encoding="utf-8")
    assert ".btn-matrix-save" not in css_content
    assert "text-align: center;" in css_content


# =============================================================================
# 9. Fast-Startup Cached State Resolves Chart Service and Bands Repo
# =============================================================================

def test_fast_startup_cached_state_resolves_services_and_endpoints(tmp_path: Path):
    """Verify that an AppState initialized with an existing persisted dataset
    resolves bands_repo and chart_service through the Registry without 503 errors.
    """
    from yogi.storage.cache import DatasetCache, MarketBarsCache
    from yogi.storage.bands import CsvBandsRepository

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_cache = DatasetCache(cache_dir=cache_dir)
    bars_cache = MarketBarsCache(cache_dir=cache_dir)

    bands_dir = tmp_path / "bands"
    bands_dir.mkdir(parents=True, exist_ok=True)
    bands_repo = CsvBandsRepository(data_dir=bands_dir)

    # 1. Pre-populate persisted dataset cache
    dataset_cache.save(
        {
            "INFY": {
                "symbol": "INFY",
                "price": 1500.0,
                "close": 1500.0,
                "BAND_D": 0.05,
                "EMA_D": "upcut",
            }
        },
        exchange="NSE",
        provider="yfinance",
        half_year_policy="prototype",
    )

    # 2. Mock provider with deterministic daily history
    bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 1) + timedelta(days=i),
            open=1500.0 + i,
            high=1520.0 + i,
            low=1490.0 + i,
            close=1510.0 + i,
            volume=10000.0,
        )
        for i in range(50)
    ]

    class FastStartupMockProvider(IDataProvider):
        name = "yfinance"

        def universe(self, exchange="NSE"):
            return ("INFY",)

        def daily_history(self, symbol, exchange="NSE", years=10):
            return bars

        def batch_daily_history(self, symbols, exchange="NSE", years=10):
            return {s: bars for s in symbols}

        def last_price(self, symbol, exchange="NSE"):
            return 1510.0

        def intraday(self, symbol, exchange="NSE", interval="5minute", days=5):
            return ()

        def subscribe_ticks(self, symbols, on_tick, exchange="NSE"):
            raise NotImplementedError

        def trading_holidays(self, year=None):
            return ()

        def health(self, symbol=None, exchange=None):
            return ProviderHealth(provider="yfinance", ok=True)

        @property
        def supports_intraday(self):
            return False

        @property
        def supports_live_ticks(self):
            return False

    mock_p = FastStartupMockProvider()

    # 3. Instantiate AppState in fast-startup mode with cached dataset
    state = AppState(
        bands_repo=bands_repo,
        autoload_cache=True,
        dataset_cache=dataset_cache,
        bars_cache=bars_cache,
    )
    # Inject mock provider into the application's single Registry instance
    state.orchestrator.registry.providers._instances["yfinance"] = mock_p
    state.orchestrator.registry.providers._factories.pop("yfinance", None)

    # Verify cached dataset is active
    assert len(state.dataset) == 1
    assert "INFY" in state.dataset

    # Verify Registry and service resolution correctness
    assert state.bands_repo is bands_repo
    assert state.chart_service is not None
    assert state.chart_service.provider is mock_p
    assert state.chart_service.bands_repo is bands_repo

    # 4. Mount in FastAPI and execute ASGI requests
    app = create_app(app_state=state, auto_refresh=False)
    client = AsgiTestClient(app)

    # GET /api/candles/INFY must succeed with 200 (no 503)
    res_candles = client.get("/api/candles/INFY")
    assert res_candles.status_code == 200
    candle_data = res_candles.json()
    assert "candles" in candle_data
    assert len(candle_data["candles"]) > 0

    # PUT /api/bands/INFY must succeed with 200 (no 503)
    res_band = client.put("/api/bands/INFY", json={"timeframe": "D", "value": 0.08})
    assert res_band.status_code == 200
    assert res_band.json()["success"] is True
    assert res_band.json()["value"] == 0.08

    # POST /api/screen and GET /api/panel must both return 200
    assert client.post("/api/screen", json={}).status_code == 200
    assert client.get("/api/panel/INFY").status_code == 200


# =============================================================================
# 10. Genuinely Missing Dependencies Produce Controlled 503
# =============================================================================

def test_missing_required_dependencies_produce_controlled_503(tmp_path: Path):
    """Verify that genuinely missing providers or bands repositories produce
    controlled, meaningful HTTP 503 errors and are not silently replaced.
    """
    # 1. Unregistered provider produces 503 on /api/candles
    state_no_provider = AppState(
        config=EngineConfig(provider="unregistered_market_provider", bands_repository="demo"),
        initial_dataset={"STOCK": {"symbol": "STOCK", "price": 100.0}},
    )
    app_no_provider = create_app(app_state=state_no_provider, auto_refresh=False)
    client_no_provider = AsgiTestClient(app_no_provider)

    res_candles = client_no_provider.get("/api/candles/STOCK")
    assert res_candles.status_code == 503
    assert "no market data provider registered" in res_candles.json()["detail"]

    # 2. Unregistered bands repository produces 503 on PUT /api/bands
    state_no_bands = AppState(
        config=EngineConfig(provider="demo", bands_repository="unregistered_bands_repo"),
        initial_dataset={"STOCK": {"symbol": "STOCK", "price": 100.0}},
    )
    app_no_bands = create_app(app_state=state_no_bands, auto_refresh=False)
    client_no_bands = AsgiTestClient(app_no_bands)

    res_put = client_no_bands.put("/api/bands/STOCK", json={"timeframe": "D", "value": 0.05})
    assert res_put.status_code == 503
    assert "Bands repository not configured" in res_put.json()["detail"]



"""Tests for MarketDataIngestionService and PipelineOrchestrator delegation."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union
from unittest.mock import MagicMock
import pytest

from tests.core.test_orchestration import MockBandsRepo
from yogi.core.configuration.engine import EngineConfig
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.contracts.storage import IBarsCache
from yogi.core.orchestration.pipeline import PipelineOrchestrator
from yogi.core.registry.hub import RegistryHub
from yogi.data.ingestion import IngestionResult, MarketDataIngestionService
from yogi.data.providers.exceptions import DataProviderError
from yogi.storage.cache import MarketBarsCache
from yogi.timeframe.engine import TimeframeEngine


def make_test_bar(dt: datetime, close: float = 100.0) -> MarketBar:
    return MarketBar(
        timestamp=dt,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=10000.0,
    )


def generate_bar_series(
    start_dt: datetime,
    count: int,
    start_price: float = 100.0,
    daily_delta: float = 0.5,
) -> tuple[MarketBar, ...]:
    return tuple(
        make_test_bar(start_dt + timedelta(days=i), start_price + i * daily_delta)
        for i in range(count)
    )


class MockTestProvider(IDataProvider):
    """Controlled mock data provider for testing ingestion service directly."""

    def __init__(
        self,
        canned_data: Optional[Mapping[str, Sequence[MarketBar]]] = None,
        can_batch: bool = True,
        fail_symbols: Optional[Mapping[str, Exception]] = None,
    ) -> None:
        self.canned_data = dict(canned_data or {})
        self._can_batch = can_batch
        self.fail_symbols = dict(fail_symbols or {})
        self.daily_calls: list[dict[str, Any]] = []
        self.batch_calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock_test_provider"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return tuple(self.canned_data.keys())

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Sequence[MarketBar]:
        self.daily_calls.append({
            "symbol": symbol,
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        if symbol in self.fail_symbols:
            raise self.fail_symbols[symbol]
        return self.canned_data.get(symbol, ())

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        if not self._can_batch:
            raise AttributeError("batch not supported")
        self.batch_calls.append({
            "symbols": list(symbols),
            "exchange": exchange,
            "years": years,
            "start_date": start_date,
            "end_date": end_date,
        })
        res: dict[str, Sequence[MarketBar]] = {}
        for s in symbols:
            if s in self.fail_symbols:
                raise self.fail_symbols[s]
            res[s] = self.canned_data.get(s, ())
        return res

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.canned_data.get(symbol)
        return bars[-1].close if bars else None

    def intraday(self, symbol: str, exchange: str = "NSE", interval: str = "5minute", days: int = 5) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(self, symbols: Sequence[str], on_tick: Any, exchange: str = "NSE") -> Any:
        return None

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider="mock", ok=True)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_ingestion_service_up_to_date_triggers_no_provider_calls(tmp_path: Path):
    """Cohort A: UP_TO_DATE cached bars result in zero provider calls."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    fresh_bars = generate_bar_series(datetime(2026, 1, 1), 105)
    cache.save_bars({"TCS": fresh_bars}, exchange="NSE", provider="mock_test_provider")

    provider = MockTestProvider()
    service = MarketDataIngestionService()

    result = service.ingest_daily_bars(
        symbols=["TCS"],
        provider=provider,
        exchange="NSE",
        bars_cache=cache,
        target_date=date(2026, 4, 15),
    )

    assert "TCS" in result
    assert len(result["TCS"]) == 105
    assert len(provider.daily_calls) == 0
    assert len(provider.batch_calls) == 0
    assert len(result.failed_symbols) == 0


def test_ingestion_service_incremental_fetches_and_persists(tmp_path: Path):
    """Cohort B: Stale symbols trigger incremental start_date request and save to cache."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    old_bars = generate_bar_series(datetime(2026, 1, 1), 70)
    cache.save_bars({"INFY": old_bars}, exchange="NSE", provider="mock_test_provider")

    # Incremental update new bars starting from 2026-03-12 (with overlap)
    new_bars = generate_bar_series(datetime(2026, 3, 7), 39, start_price=135.0)
    provider = MockTestProvider(canned_data={"INFY": new_bars})
    service = MarketDataIngestionService()

    result = service.ingest_daily_bars(
        symbols=["INFY"],
        provider=provider,
        exchange="NSE",
        bars_cache=cache,
        target_date=date(2026, 4, 15),
    )

    assert "INFY" in result
    assert len(result["INFY"]) > 70
    assert len(result.failed_symbols) == 0

    # Verify cached bars on disk were updated
    reloaded = cache.load_bars("NSE", "mock_test_provider")
    assert "INFY" in reloaded
    assert len(reloaded["INFY"]) == len(result["INFY"])


def test_ingestion_service_full_backfill(tmp_path: Path):
    """Cohort C: Unknown symbols without cached history trigger full backfill."""
    cache = MarketBarsCache(cache_dir=tmp_path)
    backfill_bars = generate_bar_series(datetime(2020, 1, 1), 200)
    provider = MockTestProvider(canned_data={"NEWSTOCK": backfill_bars})
    service = MarketDataIngestionService()

    result = service.ingest_daily_bars(
        symbols=["NEWSTOCK"],
        provider=provider,
        exchange="NSE",
        bars_cache=cache,
        historical_years=5,
        target_date=date(2026, 4, 15),
    )

    assert "NEWSTOCK" in result
    assert len(result["NEWSTOCK"]) == 200
    assert len(result.failed_symbols) == 0

    reloaded = cache.load_bars("NSE", "mock_test_provider")
    assert "NEWSTOCK" in reloaded


def test_ingestion_service_systemic_failure_raises_error():
    """If all requested symbols fail, DataProviderError is raised."""
    provider = MockTestProvider(
        fail_symbols={"FAIL1": RuntimeError("network timeout"), "FAIL2": RuntimeError("503 gateway")}
    )
    service = MarketDataIngestionService()

    with pytest.raises(DataProviderError, match="systemic failure"):
        service.ingest_daily_bars(
            symbols=["FAIL1", "FAIL2"],
            provider=provider,
            exchange="NSE",
        )


def test_ingestion_service_required_symbols_failure_raises():
    """If a symbol marked as required fails, DataProviderError is raised."""
    bars_ok = generate_bar_series(datetime(2026, 1, 1), 10)
    provider = MockTestProvider(
        canned_data={"OK_SYM": bars_ok},
        fail_symbols={"CRITICAL": RuntimeError("symbol missing")},
    )
    service = MarketDataIngestionService()

    with pytest.raises(DataProviderError, match="failed for required symbol 'CRITICAL'"):
        service.ingest_daily_bars(
            symbols=["OK_SYM", "CRITICAL"],
            provider=provider,
            exchange="NSE",
            provider_options={"required_symbols": ["CRITICAL"]},
        )


def test_ingestion_service_non_required_symbol_failure_omitted():
    """Non-required symbol failure is captured in failed_symbols while remaining symbols succeed."""
    bars_ok = generate_bar_series(datetime(2026, 1, 1), 10)
    provider = MockTestProvider(
        canned_data={"OK_SYM": bars_ok},
        fail_symbols={"MINOR": RuntimeError("bad response")},
    )
    service = MarketDataIngestionService()

    result = service.ingest_daily_bars(
        symbols=["OK_SYM", "MINOR"],
        provider=provider,
        exchange="NSE",
    )

    assert "OK_SYM" in result
    assert "MINOR" not in result
    assert len(result.failed_symbols) == 1
    assert result.failed_symbols[0][0] == "MINOR"
    assert "MINOR" in result.failed_symbol_names


def test_pipeline_orchestrator_delegates_to_injected_ingestion_service():
    """Verify PipelineOrchestrator delegates bar acquisition to injected MarketDataIngestionService."""
    mock_service = MagicMock(spec=MarketDataIngestionService)
    test_bars = generate_bar_series(datetime(2026, 1, 1), 80)
    mock_service.ingest_daily_bars.return_value = IngestionResult(
        bars={"SYM1": test_bars},
        failed_symbols=(),
    )

    hub = RegistryHub()
    hub.providers.register("mock_p", MockTestProvider(canned_data={"SYM1": test_bars}))
    hub.bands.register("excel", MockBandsRepo())

    orchestrator = PipelineOrchestrator(
        registry=hub,
        timeframe_engine=TimeframeEngine(),
        ingestion_service=mock_service,
    )

    config = EngineConfig(
        provider="mock_p",
        exchange="NSE",
        symbols=["SYM1"],
        calculation_modules=[],
    )

    result = orchestrator.build_dataset(config)

    # Assert the mock service was invoked with expected parameters
    mock_service.ingest_daily_bars.assert_called_once()
    call_kwargs = mock_service.ingest_daily_bars.call_args.kwargs
    assert call_kwargs["symbols"] == ["SYM1"]
    assert call_kwargs["exchange"] == "NSE"
    assert call_kwargs["provider_name"] == "mock_p"
    assert "SYM1" in result


def test_pipeline_orchestrator_build_dataset_per_call_ingestion_service_override():
    """Verify build_dataset accepts per-call ingestion_service override."""
    default_service = MagicMock(spec=MarketDataIngestionService)
    override_service = MagicMock(spec=MarketDataIngestionService)

    test_bars = generate_bar_series(datetime(2026, 1, 1), 80)
    override_service.ingest_daily_bars.return_value = IngestionResult(
        bars={"SYM1": test_bars},
        failed_symbols=(),
    )

    hub = RegistryHub()
    hub.providers.register("mock_p", MockTestProvider(canned_data={"SYM1": test_bars}))
    hub.bands.register("excel", MockBandsRepo())

    orchestrator = PipelineOrchestrator(
        registry=hub,
        timeframe_engine=TimeframeEngine(),
        ingestion_service=default_service,
    )

    config = EngineConfig(
        provider="mock_p",
        exchange="NSE",
        symbols=["SYM1"],
        calculation_modules=[],
    )

    orchestrator.build_dataset(config, ingestion_service=override_service)

    default_service.ingest_daily_bars.assert_not_called()
    override_service.ingest_daily_bars.assert_called_once()


def test_ingestion_service_layer_independence():
    """Verify MarketDataIngestionService has no dependency on Cockpit UI layer."""
    import sys
    import yogi.data.ingestion.service as svc_module

    # Check imported modules in service file
    module_file = Path(svc_module.__file__).read_text(encoding="utf-8")
    assert "yogi.cockpit" not in module_file
    assert "cockpit" not in module_file

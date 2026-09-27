"""Tests for YFinanceDataProvider."""

from datetime import datetime
from typing import Any
import pandas as pd
import pytest

from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.yfinance import (
    YFinanceDataProvider,
    yf_ticker,
)


def _mock_single_df(*args: Any, **kwargs: Any) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0, 101.0],
            "High": [105.0, 106.0, 104.0],
            "Low": [99.0, 101.0, 100.0],
            "Close": [103.0, 104.0, 102.5],
            "Volume": [1000, 1500, 1200],
        },
        index=dates,
    )


def _mock_batch_df(*args: Any, **kwargs: Any) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    cols = pd.MultiIndex.from_tuples(
        [
            ("Close", "RELIANCE.NS"),
            ("Close", "TCS.NS"),
            ("Open", "RELIANCE.NS"),
            ("Open", "TCS.NS"),
        ]
    )
    return pd.DataFrame(
        [
            [2500.0, 3800.0, 2490.0, 3790.0],
            [2520.0, 3850.0, 2505.0, 3810.0],
        ],
        index=dates,
        columns=cols,
    )


class TestYFinanceDataProvider:
    def test_satisfies_contract(self):
        provider = YFinanceDataProvider()
        assert isinstance(provider, IDataProvider)
        assert provider.name == "yfinance"
        assert provider.supports_intraday is True
        assert provider.supports_live_ticks is False

    def test_yf_ticker_resolution(self):
        # Default NSE
        assert yf_ticker("RELIANCE") == "RELIANCE.NS"
        assert yf_ticker("reliance") == "RELIANCE.NS"
        # BSE
        assert yf_ticker("500325", exchange="BSE") == "500325.BO"
        # Already suffixed
        assert yf_ticker("INFY.NS") == "INFY.NS"
        assert yf_ticker("500325.BO", exchange="BSE") == "500325.BO"
        # Custom alias override
        aliases = {"M&M": "M_M.NS", "L&TFH": "LTF.NS"}
        assert yf_ticker("M&M", aliases=aliases) == "M_M.NS"
        assert yf_ticker("l&tfh", aliases=aliases) == "LTF.NS"
        assert yf_ticker("TCS", aliases=aliases) == "TCS.NS"

    def test_daily_history_offline(self):
        recorded_calls = []

        def mock_dl(*args, **kwargs):
            recorded_calls.append(kwargs)
            return _mock_single_df()

        provider = YFinanceDataProvider(download_fn=mock_dl)
        bars = provider.daily_history("INFY", exchange="NSE", years=5)

        assert len(bars) == 3
        assert isinstance(bars[0], MarketBar)
        assert bars[0].close == 103.0
        assert bars[-1].close == 102.5
        assert recorded_calls[0]["tickers"] == "INFY.NS"
        assert recorded_calls[0]["period"] == "5y"
        assert recorded_calls[0]["interval"] == "1d"

    def test_batch_daily_history_offline(self):
        provider = YFinanceDataProvider(download_fn=_mock_batch_df)
        res = provider.batch_daily_history(["RELIANCE", "TCS"], exchange="NSE", years=2)

        assert "RELIANCE" in res
        assert "TCS" in res
        assert len(res["RELIANCE"]) == 2
        assert len(res["TCS"]) == 2
        assert res["RELIANCE"][0].close == 2500.0
        assert res["TCS"][1].close == 3850.0

    def test_batch_daily_history_empty_symbols(self):
        provider = YFinanceDataProvider(download_fn=_mock_batch_df)
        assert provider.batch_daily_history([]) == {}

    def test_last_price(self):
        provider = YFinanceDataProvider(download_fn=_mock_single_df)
        price = provider.last_price("INFY")
        assert price == 102.5

    def test_intraday_interval_mapping(self):
        recorded_calls = []

        def mock_dl(*args, **kwargs):
            recorded_calls.append(kwargs)
            return _mock_single_df()

        provider = YFinanceDataProvider(download_fn=mock_dl)
        bars = provider.intraday("INFY", exchange="NSE", interval="5minute", days=3)

        assert len(bars) == 3
        assert recorded_calls[0]["interval"] == "5m"
        assert recorded_calls[0]["period"] == "3d"

    def test_subscribe_ticks_raises(self):
        provider = YFinanceDataProvider()
        with pytest.raises(NotImplementedError, match="does not support real-time tick"):
            provider.subscribe_ticks(["RELIANCE"], lambda tick: None)

    def test_trading_holidays(self):
        provider = YFinanceDataProvider()
        hols_2024 = provider.trading_holidays(2024)
        assert "2024-01-26" in hols_2024
        assert "2024-12-25" in hols_2024

        hols_all = provider.trading_holidays()
        assert len(hols_all) >= 40
        assert "2025-08-15" in hols_all
        assert "2026-01-26" in hols_all

    def test_health_check_success(self):
        provider = YFinanceDataProvider(download_fn=_mock_single_df)
        health = provider.health()
        assert isinstance(health, ProviderHealth)
        assert health.provider == "yfinance"
        assert health.ok is True
        assert health.sample_price == 102.5
        assert health.error is None

    def test_health_check_configurable_symbol(self):
        recorded_tickers = []

        def mock_dl(*args, **kwargs):
            recorded_tickers.append(kwargs.get("tickers"))
            return _mock_single_df()

        # Constructor configured symbol
        provider = YFinanceDataProvider(download_fn=mock_dl, health_symbol="TCS", health_exchange="NSE")
        health = provider.health()
        assert health.ok is True
        assert recorded_tickers[0] == "TCS.NS"

        # Runtime argument override
        health_override = provider.health(symbol="INFY", exchange="NSE")
        assert health_override.ok is True
        assert recorded_tickers[1] == "INFY.NS"

    def test_health_check_failure(self):
        def mock_err(*args, **kwargs):
            raise ConnectionError("Network down")

        provider = YFinanceDataProvider(download_fn=mock_err)
        health = provider.health()
        assert health.ok is False
        assert health.sample_price is None
        assert "Network down" in str(health.error) or health.error is not None

    def test_universe_offline(self, tmp_path):
        dummy_csv = tmp_path / "nse.csv"
        dummy_csv.write_text("SYMBOL,SERIES\nSBIN,EQ\nAXISBANK,EQ\n", encoding="utf-8")

        provider = YFinanceDataProvider(fallback_universe_path=dummy_csv)
        syms = provider.universe("NSE")
        assert "SBIN" in syms
        assert "AXISBANK" in syms

    def test_expected_empty_data_behavior(self):
        # Vendor returns empty DataFrame (symbol not found / inactive)
        provider_empty = YFinanceDataProvider(download_fn=lambda *a, **kw: pd.DataFrame())
        assert provider_empty.daily_history("UNKNOWN") == ()
        assert provider_empty.batch_daily_history(["UNKNOWN"]) == {"UNKNOWN": ()}
        assert provider_empty.last_price("UNKNOWN") is None
        assert provider_empty.intraday("UNKNOWN") == ()

    def test_programming_errors_propagate_not_swallowed(self):
        # Programming error (TypeError) must NOT be caught or turned into empty data
        def buggy_download(*args, **kwargs):
            raise TypeError("Programming bug: unexpected keyword argument")

        provider = YFinanceDataProvider(download_fn=buggy_download)
        with pytest.raises(TypeError, match="Programming bug"):
            provider.daily_history("INFY")

        with pytest.raises(TypeError, match="Programming bug"):
            provider.batch_daily_history(["INFY"])

        with pytest.raises(TypeError, match="Programming bug"):
            provider.intraday("INFY")

    def test_operational_outage_raises_data_provider_error(self):
        from yogi.data.providers.exceptions import DataProviderError

        def network_failing(*args, **kwargs):
            raise ConnectionError("API connection reset by peer")

        provider = YFinanceDataProvider(download_fn=network_failing)
        with pytest.raises(DataProviderError, match="Failed to fetch daily history"):
            provider.daily_history("INFY")

        with pytest.raises(DataProviderError, match="Batch daily history download failed"):
            provider.batch_daily_history(["INFY", "TCS"])

        with pytest.raises(DataProviderError, match="Failed to fetch intraday bars"):
            provider.intraday("INFY")

    def test_register_in_registry_hub(self):
        from yogi.core.registry import RegistryHub

        hub = RegistryHub()
        provider = YFinanceDataProvider(download_fn=_mock_single_df)
        hub.providers.register("yfinance", provider)

        resolved = hub.providers.get("yfinance")
        assert resolved is provider
        assert resolved.name == "yfinance"

    def test_orchestrator_build_dataset_with_yfinance(self):
        from yogi.core.configuration.engine import EngineConfig
        from yogi.core.contracts.bands import IBandsRepository
        from yogi.core.orchestration.pipeline import PipelineOrchestrator
        from yogi.core.registry import RegistryHub
        from yogi.timeframe.engine import TimeframeEngine

        class MockBandsRepo(IBandsRepository):
            def get_band(self, symbol: str, timeframe: str) -> Optional[float]:
                return None

            def get_all_bands(self, symbol: str) -> Mapping[str, Optional[float]]:
                return {tf: None for tf in ("D", "W", "M", "Q", "H", "Y")}

            def set_band(
                self,
                symbol: str,
                timeframe: str,
                value: float,
                who: str = "app",
                source: str = "app",
            ) -> float:
                return value

        hub = RegistryHub()
        provider = YFinanceDataProvider(download_fn=_mock_batch_df)
        hub.providers.register("yfinance", provider)
        hub.bands.register("mock_bands", MockBandsRepo())

        orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
        config = EngineConfig(
            provider="yfinance",
            bands_repository="mock_bands",
            calculation_modules=(),
            symbols=("RELIANCE", "TCS"),
        )

        dataset = orchestrator.build_dataset(config)
        assert "RELIANCE" in dataset
        assert "TCS" in dataset
        assert dataset["RELIANCE"]["symbol"] == "RELIANCE"
        assert dataset["TCS"]["symbol"] == "TCS"



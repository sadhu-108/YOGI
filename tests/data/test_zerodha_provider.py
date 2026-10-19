"""Tests for ZerodhaDataProvider."""

from datetime import datetime
from typing import Any, Mapping, Sequence
import pytest

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.providers.zerodha import ZerodhaDataProvider


class MockKiteClient:
    """Mock KiteConnect client for deterministic offline testing."""

    def __init__(self) -> None:
        self.instruments_data = [
            {
                "instrument_token": 738561,
                "tradingsymbol": "RELIANCE",
                "instrument_type": "EQ",
                "segment": "NSE",
            },
            {
                "instrument_token": 2953217,
                "tradingsymbol": "TCS",
                "instrument_type": "EQ",
                "segment": "NSE",
            },
            {
                "instrument_token": 12345,
                "tradingsymbol": "RELIANCE24JANFUT",
                "instrument_type": "FUT",
                "segment": "NFO",
            },
        ]
        self.history_calls: list[dict[str, Any]] = []

    def instruments(self, exchange: str = "NSE") -> Sequence[Mapping[str, Any]]:
        return self.instruments_data

    def historical_data(
        self,
        token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
    ) -> Sequence[Mapping[str, Any]]:
        self.history_calls.append(
            {
                "token": token,
                "from": from_date,
                "to": to_date,
                "interval": interval,
            }
        )
        return [
            {
                "date": "2024-01-01 09:15:00",
                "open": 2500.0,
                "high": 2520.0,
                "low": 2490.0,
                "close": 2510.0,
                "volume": 100000,
            },
            {
                "date": "2024-01-02 09:15:00",
                "open": 2510.0,
                "high": 2530.0,
                "low": 2505.0,
                "close": 2525.0,
                "volume": 120000,
            },
        ]

    def ltp(self, keys: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
        out = {}
        for k in keys:
            if "RELIANCE" in k:
                out[k] = {"last_price": 2525.0}
            elif "TCS" in k:
                out[k] = {"last_price": 3850.0}
        return out


class MockTickerClient:
    """Mock KiteTicker client for testing tick streaming callback."""

    def __init__(self) -> None:
        self.on_ticks = None
        self.on_connect = None
        self.subscribed_tokens: list[int] = []
        self.mode = None

    def subscribe(self, tokens: Sequence[int]) -> None:
        self.subscribed_tokens.extend(tokens)

    def set_mode(self, mode: Any, tokens: Sequence[int]) -> None:
        self.mode = mode

    def connect(self, threaded: bool = True) -> None:
        pass


class TestZerodhaDataProvider:
    def test_satisfies_contract(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        assert isinstance(provider, IDataProvider)
        assert provider.name == "zerodha"
        assert provider.supports_intraday is True
        assert provider.supports_live_ticks is True

    def test_uninitialized_client_raises(self):
        provider = ZerodhaDataProvider()
        with pytest.raises(ValueError, match="Zerodha client is not initialized"):
            provider.token_for("RELIANCE")

    def test_token_and_universe(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        assert provider.token_for("RELIANCE") == 738561
        assert provider.token_for("reliance") == 738561
        assert provider.token_for("TCS") == 2953217
        assert provider.token_for("NONEXISTENT") is None

        universe = provider.universe("NSE")
        assert universe == ("RELIANCE", "TCS")
        assert "RELIANCE24JANFUT" not in universe  # FUT filtered out

    def test_daily_history(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        bars = provider.daily_history("RELIANCE", exchange="NSE", years=2)

        assert len(bars) >= 2
        assert isinstance(bars[0], MarketBar)
        assert bars[0].close == 2510.0
        assert bars[1].close == 2525.0
        # Historical chunking was called
        assert len(mock_kite.history_calls) >= 2

    def test_daily_history_date_range(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        bars = provider.daily_history(
            "RELIANCE",
            exchange="NSE",
            start_date="2024-01-01",
            end_date="2024-06-01",
        )
        assert len(bars) >= 2
        assert len(mock_kite.history_calls) >= 1
        assert mock_kite.history_calls[0]["from"] == datetime(2024, 1, 1)

    def test_daily_history_invalid_date_range_rejected(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        with pytest.raises(ValueError, match="must be strictly earlier than end_date"):
            provider.daily_history("RELIANCE", start_date="2024-06-01", end_date="2024-01-01")

        with pytest.raises(ValueError, match="Cannot specify end_date without start_date"):
            provider.daily_history("RELIANCE", end_date="2024-01-01")

    def test_daily_history_unknown_token(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)
        assert provider.daily_history("UNKNOWN") == ()

    def test_batch_daily_history(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        res = provider.batch_daily_history(["RELIANCE", "TCS"], exchange="NSE", years=1)
        assert "RELIANCE" in res
        assert "TCS" in res
        assert len(res["RELIANCE"]) == 2
        assert len(res["TCS"]) == 2

    def test_intraday(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        bars = provider.intraday("RELIANCE", exchange="NSE", interval="5minute", days=3)
        assert len(bars) == 2
        assert bars[0].open == 2500.0

    def test_last_price(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        price = provider.last_price("RELIANCE")
        assert price == 2525.0

        unknown_price = provider.last_price("UNKNOWN")
        assert unknown_price is None

    def test_subscribe_ticks(self):
        mock_kite = MockKiteClient()
        mock_ticker = MockTickerClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite, ticker_client=mock_ticker)

        received_ticks: list[TickData] = []

        def on_tick(t: TickData) -> None:
            received_ticks.append(t)

        ws = provider.subscribe_ticks(["RELIANCE"], on_tick=on_tick)
        assert ws is mock_ticker

        # Trigger simulated connect
        mock_ticker.on_connect(mock_ticker, None)
        assert 738561 in mock_ticker.subscribed_tokens

        # Trigger simulated tick
        fake_ticks = [
            {
                "instrument_token": 738561,
                "last_price": 2530.0,
                "last_traded_quantity": 50,
                "timestamp": "2024-01-02 12:00:00",
            }
        ]
        mock_ticker.on_ticks(mock_ticker, fake_ticks)

        assert len(received_ticks) == 1
        assert received_ticks[0].symbol == "RELIANCE"
        assert received_ticks[0].last_price == 2530.0
        assert received_ticks[0].last_quantity == 50

    def test_trading_holidays(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        hols = provider.trading_holidays(2025)
        assert "2025-08-15" in hols

    def test_health_check(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        health = provider.health()
        assert isinstance(health, ProviderHealth)
        assert health.provider == "zerodha"
        assert health.ok is True
        assert health.sample_price == 2525.0
        assert health.error is None

    def test_health_check_configurable_symbol(self):
        mock_kite = MockKiteClient()
        # Custom configured symbol in constructor
        provider = ZerodhaDataProvider(kite_client=mock_kite, health_symbol="TCS", health_exchange="NSE")
        health = provider.health()
        assert health.ok is True
        assert health.sample_price == 3850.0

        # Runtime argument override
        health_reliance = provider.health(symbol="RELIANCE", exchange="NSE")
        assert health_reliance.ok is True
        assert health_reliance.sample_price == 2525.0

    def test_expected_empty_data_behavior(self):
        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        # Unknown token (symbol not in instruments) returns ()
        assert provider.daily_history("UNKNOWN") == ()
        assert provider.intraday("UNKNOWN") == ()
        assert provider.last_price("UNKNOWN") is None

        # Empty history returned by Kite
        mock_kite_empty = MockKiteClient()
        mock_kite_empty.historical_data = lambda *a, **kw: []
        provider_empty = ZerodhaDataProvider(kite_client=mock_kite_empty)
        assert provider_empty.daily_history("RELIANCE") == ()
        assert provider_empty.intraday("RELIANCE") == ()

    def test_programming_errors_propagate_not_swallowed(self):
        mock_kite = MockKiteClient()

        def buggy_history(*args, **kwargs):
            raise TypeError("Programming bug: invalid argument type")

        mock_kite.historical_data = buggy_history
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        with pytest.raises(TypeError, match="Programming bug"):
            provider.daily_history("RELIANCE")

        with pytest.raises(TypeError, match="Programming bug"):
            provider.intraday("RELIANCE")

    def test_operational_outage_raises_data_provider_error(self):
        from yogi.data.providers.exceptions import DataProviderError

        mock_kite = MockKiteClient()

        def network_failing(*args, **kwargs):
            raise ConnectionError("Zerodha server unreachable")

        mock_kite.historical_data = network_failing
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        with pytest.raises(DataProviderError, match="Failed to fetch Zerodha historical data"):
            provider.daily_history("RELIANCE")

        with pytest.raises(DataProviderError, match="Failed to fetch Zerodha intraday data"):
            provider.intraday("RELIANCE")

    def test_authentication_failure_raises_auth_error(self):
        from yogi.data.providers.exceptions import DataProviderAuthenticationError

        mock_kite = MockKiteClient()

        def auth_failing(*args, **kwargs):
            raise Exception("TokenException: Token is invalid or has expired")

        mock_kite.historical_data = auth_failing
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        with pytest.raises(DataProviderAuthenticationError, match="Zerodha authentication failed"):
            provider.daily_history("RELIANCE")

        with pytest.raises(DataProviderAuthenticationError, match="Zerodha authentication failed"):
            provider.intraday("RELIANCE")

    def test_register_in_registry_hub(self):
        from yogi.core.registry import RegistryHub

        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        hub = RegistryHub()
        hub.providers.register("zerodha", provider)

        resolved = hub.providers.get("zerodha")
        assert resolved is provider
        assert resolved.name == "zerodha"

    def test_orchestrator_build_dataset_with_zerodha(self):
        from typing import Optional
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

        mock_kite = MockKiteClient()
        provider = ZerodhaDataProvider(kite_client=mock_kite)

        hub = RegistryHub()
        hub.providers.register("zerodha", provider)
        hub.bands.register("mock_bands", MockBandsRepo())

        orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
        config = EngineConfig(
            provider="zerodha",
            bands_repository="mock_bands",
            calculation_modules=(),
            symbols=("RELIANCE", "TCS"),
        )

        dataset = orchestrator.build_dataset(config)
        assert "RELIANCE" in dataset
        assert "TCS" in dataset
        assert dataset["RELIANCE"]["symbol"] == "RELIANCE"
        assert dataset["TCS"]["symbol"] == "TCS"



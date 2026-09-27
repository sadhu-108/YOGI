"""Unit and integration tests for TwelveDataProvider."""

from datetime import datetime
import json
import os
from typing import Any, Mapping
import pytest

from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.core.registry.base import CapabilityRegistry
from yogi.data.normalization.bars import (
    normalize_twelve_data_bars,
    normalize_twelve_data_batch,
)
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)
from yogi.data.providers.twelve_data import (
    TwelveDataProvider,
    _mask_api_key,
    twelve_data_symbol,
)


class MockResponse:
    """Mock requests.Response for offline deterministic testing."""

    def __init__(
        self,
        json_data: Any,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self._json_data = json_data
        self.status_code = status_code
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self) -> Any:
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


def _sample_single_time_series() -> dict[str, Any]:
    """Sample Twelve Data time_series response (returned in descending order)."""
    return {
        "meta": {
            "symbol": "RELIANCE",
            "interval": "1day",
            "currency": "INR",
            "exchange_timezone": "Asia/Kolkata",
            "exchange": "NSE",
            "type": "Common Stock",
        },
        "values": [
            {
                "datetime": "2024-01-03",
                "open": "2520.00000",
                "high": "2540.00000",
                "low": "2510.00000",
                "close": "2535.00000",
                "volume": "150000",
            },
            {
                "datetime": "2024-01-02",
                "open": "2505.00000",
                "high": "2530.00000",
                "low": "2500.00000",
                "close": "2525.00000",
                "volume": "120000",
            },
            {
                "datetime": "2024-01-01",
                "open": "2490.00000",
                "high": "2515.00000",
                "low": "2485.00000",
                "close": "2510.00000",
                "volume": "100000",
            },
        ],
        "status": "ok",
    }


def _sample_batch_time_series() -> dict[str, Any]:
    """Sample Twelve Data batch time_series response for RELIANCE and TCS."""
    return {
        "RELIANCE": {
            "meta": {"symbol": "RELIANCE", "interval": "1day", "exchange": "NSE"},
            "values": [
                {
                    "datetime": "2024-01-02",
                    "open": "2505.0",
                    "high": "2530.0",
                    "low": "2500.0",
                    "close": "2525.0",
                    "volume": "120000",
                },
                {
                    "datetime": "2024-01-01",
                    "open": "2490.0",
                    "high": "2515.0",
                    "low": "2485.0",
                    "close": "2510.0",
                    "volume": "100000",
                },
            ],
            "status": "ok",
        },
        "TCS": {
            "meta": {"symbol": "TCS", "interval": "1day", "exchange": "NSE"},
            "values": [
                {
                    "datetime": "2024-01-02",
                    "open": "3810.0",
                    "high": "3850.0",
                    "low": "3800.0",
                    "close": "3840.0",
                    "volume": "80000",
                },
                {
                    "datetime": "2024-01-01",
                    "open": "3780.0",
                    "high": "3820.0",
                    "low": "3775.0",
                    "close": "3800.0",
                    "volume": "75000",
                },
            ],
            "status": "ok",
        },
    }


# =============================================================================
# 1. CONTRACT COMPLIANCE & CAPABILITIES
# =============================================================================

class TestTwelveDataContract:
    def test_satisfies_idataprovider_contract(self):
        provider = TwelveDataProvider(api_key="mock_test_key")
        assert isinstance(provider, IDataProvider)
        assert provider.name == "twelvedata"
        assert provider.supports_intraday is True
        assert provider.supports_live_ticks is False

    def test_subscribe_ticks_raises_not_implemented(self):
        provider = TwelveDataProvider(api_key="mock_test_key")
        with pytest.raises(NotImplementedError, match="not support real-time tick streaming"):
            provider.subscribe_ticks(["RELIANCE"], lambda tick: None)

    def test_trading_holidays(self):
        provider = TwelveDataProvider(api_key="mock_test_key")
        holidays_2025 = provider.trading_holidays(2025)
        assert len(holidays_2025) > 0
        assert "2025-01-26" not in holidays_2025 or "2025-08-15" in holidays_2025
        all_holidays = provider.trading_holidays()
        assert len(all_holidays) >= len(holidays_2025)

    def test_repr_masks_presence_without_leaking_key(self):
        secret = "secret_twelve_data_key_123"
        provider = TwelveDataProvider(api_key=secret)
        rep = repr(provider)
        assert secret not in rep
        assert "authenticated=True" in rep

        unauth = TwelveDataProvider(api_key="")
        assert "authenticated=False" in repr(unauth)


# =============================================================================
# 2. SYMBOL & EXCHANGE TRANSLATION
# =============================================================================

class TestTwelveDataSymbolTranslation:
    def test_standard_symbols(self):
        assert twelve_data_symbol("RELIANCE") == ("RELIANCE", "NSE")
        assert twelve_data_symbol("reliance") == ("RELIANCE", "NSE")
        assert twelve_data_symbol("tcs", exchange="NSE") == ("TCS", "NSE")

    def test_strips_vendor_suffixes(self):
        assert twelve_data_symbol("RELIANCE.NS") == ("RELIANCE", "NSE")
        assert twelve_data_symbol("infy.ns") == ("INFY", "NSE")
        assert twelve_data_symbol("500325.BO", exchange="BSE") == ("500325", "BSE")

    def test_colon_notation(self):
        assert twelve_data_symbol("RELIANCE:NSE") == ("RELIANCE", "NSE")
        assert twelve_data_symbol("500325:BSE") == ("500325", "BSE")

    def test_custom_aliases(self):
        aliases = {"M&M": "M_M", "L&TFH": "LTF", "CUSTOM": "SPECIAL:NSE"}
        assert twelve_data_symbol("M&M", aliases=aliases) == ("M_M", "NSE")
        assert twelve_data_symbol("m&m", aliases=aliases) == ("M_M", "NSE")
        assert twelve_data_symbol("CUSTOM", aliases=aliases) == ("SPECIAL", "NSE")
        assert twelve_data_symbol("TCS", aliases=aliases) == ("TCS", "NSE")


# =============================================================================
# 3. NORMALIZATION PATH
# =============================================================================

class TestTwelveDataNormalization:
    def test_normalize_bars_chronological_order_and_numeric_types(self):
        payload = _sample_single_time_series()
        bars = normalize_twelve_data_bars(payload)

        # Output must be sorted ASCENDING chronologically
        assert len(bars) == 3
        assert bars[0].timestamp == datetime(2024, 1, 1)
        assert bars[1].timestamp == datetime(2024, 1, 2)
        assert bars[2].timestamp == datetime(2024, 1, 3)

        # Verify numeric conversions
        assert isinstance(bars[0], MarketBar)
        assert bars[0].open == 2490.0
        assert bars[0].high == 2515.0
        assert bars[0].low == 2485.0
        assert bars[0].close == 2510.0
        assert bars[0].volume == 100000.0

    def test_normalize_bars_empty_and_error_cases(self):
        assert normalize_twelve_data_bars(None) == ()
        assert normalize_twelve_data_bars({}) == ()
        assert normalize_twelve_data_bars({"status": "error", "message": "fail"}) == ()
        assert normalize_twelve_data_bars({"values": []}) == ()

    def test_normalize_bars_missing_volume(self):
        payload = {
            "values": [
                {
                    "datetime": "2024-01-01",
                    "open": "100.0",
                    "high": "105.0",
                    "low": "95.0",
                    "close": "102.0",
                    "volume": None,
                }
            ]
        }
        bars = normalize_twelve_data_bars(payload)
        assert len(bars) == 1
        assert bars[0].volume is None

    def test_normalize_batch_multi_symbol(self):
        batch_payload = _sample_batch_time_series()
        res = normalize_twelve_data_batch(batch_payload, ["RELIANCE", "TCS"])

        assert "RELIANCE" in res
        assert "TCS" in res
        assert len(res["RELIANCE"]) == 2
        assert len(res["TCS"]) == 2
        # Chronological ascending
        assert res["RELIANCE"][0].timestamp < res["RELIANCE"][1].timestamp
        assert res["RELIANCE"][0].close == 2510.0
        assert res["RELIANCE"][1].close == 2525.0
        assert res["TCS"][1].close == 3840.0

    def test_normalize_batch_single_symbol_payload_fallback(self):
        single_payload = _sample_single_time_series()
        res = normalize_twelve_data_batch(single_payload, ["RELIANCE"])
        assert "RELIANCE" in res
        assert len(res["RELIANCE"]) == 3


# =============================================================================
# 4. OFFLINE PROVIDER REQUEST & METHOD TESTS
# =============================================================================

class TestTwelveDataProviderMethods:
    def test_daily_history_offline(self):
        recorded_calls = []

        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            recorded_calls.append({"url": url, "params": params})
            return MockResponse(_sample_single_time_series(), status_code=200)

        provider = TwelveDataProvider(
            api_key="mock_key",
            request_fn=mock_request,
        )
        bars = provider.daily_history("RELIANCE", exchange="NSE", years=2)

        assert len(bars) == 3
        assert bars[-1].close == 2535.0
        assert len(recorded_calls) == 1
        assert recorded_calls[0]["params"]["symbol"] == "RELIANCE"
        assert recorded_calls[0]["params"]["exchange"] == "NSE"
        assert recorded_calls[0]["params"]["interval"] == "1day"
        assert recorded_calls[0]["params"]["apikey"] == "mock_key"

    def test_batch_daily_history_offline(self):
        recorded_calls = []

        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            recorded_calls.append({"url": url, "params": params})
            return MockResponse(_sample_batch_time_series(), status_code=200)

        provider = TwelveDataProvider(
            api_key="mock_key",
            request_fn=mock_request,
            batch_chunk_size=5,
        )
        res = provider.batch_daily_history(["RELIANCE", "TCS"], exchange="NSE", years=1)

        assert "RELIANCE" in res
        assert "TCS" in res
        assert len(res["RELIANCE"]) == 2
        assert len(res["TCS"]) == 2
        assert recorded_calls[0]["params"]["symbol"] == "RELIANCE,TCS"

    def test_last_price_via_price_endpoint(self):
        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            if "price" in url:
                return MockResponse({"price": "2535.50"}, status_code=200)
            return MockResponse({}, status_code=404)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        price = provider.last_price("RELIANCE", exchange="NSE")
        assert price == 2535.50

    def test_last_price_fallback_to_daily_history(self):
        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            if "price" in url:
                return MockResponse({"status": "error", "message": "Endpoint not available"}, status_code=400)
            if "time_series" in url:
                return MockResponse(_sample_single_time_series(), status_code=200)
            return MockResponse({}, status_code=404)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        price = provider.last_price("RELIANCE", exchange="NSE")
        assert price == 2535.0  # last candle close

    def test_intraday_history(self):
        recorded_calls = []

        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            recorded_calls.append({"url": url, "params": params})
            return MockResponse(
                {
                    "values": [
                        {
                            "datetime": "2024-01-02 15:25:00",
                            "open": "2520.0",
                            "high": "2525.0",
                            "low": "2518.0",
                            "close": "2522.0",
                            "volume": "1000",
                        }
                    ],
                    "status": "ok",
                },
                status_code=200,
            )

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        bars = provider.intraday("RELIANCE", exchange="NSE", interval="5minute", days=2)

        assert len(bars) == 1
        assert bars[0].close == 2522.0
        assert recorded_calls[0]["params"]["interval"] == "5min"

    def test_universe_from_stocks_endpoint(self):
        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            if "stocks" in url:
                return MockResponse(
                    {
                        "data": [
                            {"symbol": "RELIANCE", "type": "Common Stock", "exchange": "NSE"},
                            {"symbol": "TCS", "type": "Common Stock", "exchange": "NSE"},
                            {"symbol": "IGNORED_BOND", "type": "Bond", "exchange": "NSE"},
                        ],
                        "status": "ok",
                    },
                    status_code=200,
                )
            return MockResponse({}, status_code=404)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        univ = provider.universe("NSE")
        assert "RELIANCE" in univ
        assert "TCS" in univ
        assert "IGNORED_BOND" not in univ

    def test_health_check_ok(self):
        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            return MockResponse({"price": "2500.00"}, status_code=200)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        h = provider.health("RELIANCE", "NSE")
        assert h.ok is True
        assert h.sample_price == 2500.00
        assert h.error is None

    def test_health_check_missing_api_key(self):
        provider = TwelveDataProvider(api_key="")
        h = provider.health()
        assert h.ok is False
        assert h.sample_price is None
        assert "API key is missing" in (h.error or "")


# =============================================================================
# 5. ERROR HANDLING & SECRET PROTECTION
# =============================================================================

class TestTwelveDataErrorHandling:
    def test_missing_api_key_raises_auth_error(self):
        provider = TwelveDataProvider(api_key="")
        with pytest.raises(DataProviderAuthenticationError, match="API key is required"):
            provider.daily_history("RELIANCE")

    def test_http_401_raises_auth_error(self):
        def mock_request(*args, **kwargs):
            return MockResponse({"code": 401, "message": "Invalid API key", "status": "error"}, status_code=401)

        provider = TwelveDataProvider(api_key="invalid_key", request_fn=mock_request)
        with pytest.raises(DataProviderAuthenticationError, match="authentication failed"):
            provider.daily_history("RELIANCE")

    def test_http_429_raises_rate_limit_error(self):
        def mock_request(*args, **kwargs):
            return MockResponse({"code": 429, "message": "Rate limit exceeded", "status": "error"}, status_code=429)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        with pytest.raises(DataProviderError, match="rate limit exceeded"):
            provider.daily_history("RELIANCE")

    def test_http_500_raises_dataprovider_error(self):
        def mock_request(*args, **kwargs):
            return MockResponse({"message": "Server Error"}, status_code=500)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        with pytest.raises(DataProviderError, match="HTTP 500"):
            provider.daily_history("RELIANCE")

    def test_malformed_json_raises_dataprovider_error(self):
        def mock_request(*args, **kwargs):
            return MockResponse(ValueError("Not valid JSON"), status_code=200, text="<!DOCTYPE html>Gateway Timeout")

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        with pytest.raises(DataProviderError, match="malformed JSON"):
            provider.daily_history("RELIANCE")

    def test_symbol_not_found_returns_empty_tuple(self):
        def mock_request(*args, **kwargs):
            return MockResponse({"code": 400, "message": "Cannot find symbol NONEXISTENT", "status": "error"}, status_code=200)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        bars = provider.daily_history("NONEXISTENT")
        assert bars == ()

    def test_secret_is_never_leaked_in_exception_messages(self):
        secret = "secret_apikey_abc_12345_xyz"

        def mock_request(url, params, timeout):
            # Simulate exception mentioning the full URL with query parameters
            raise RuntimeError(f"Connection failed to {url}?apikey={secret}&symbol=RELIANCE")

        provider = TwelveDataProvider(api_key=secret, request_fn=mock_request)
        with pytest.raises(DataProviderError) as exc_info:
            provider.daily_history("RELIANCE")

        err_msg = str(exc_info.value)
        assert secret not in err_msg
        assert "apikey=***" in err_msg or "***" in err_msg

    def test_mask_api_key_helper(self):
        secret = "my_secret_key"
        text = f"Error calling api: apikey={secret}&other=123 with key {secret}"
        masked = _mask_api_key(text, secret)
        assert secret not in masked
        assert "***" in masked


# =============================================================================
# 6. REGISTRY & DEPENDENCY INJECTION INTEGRATION
# =============================================================================

class TestTwelveDataRegistryIntegration:
    def test_register_and_retrieve_from_capability_registry(self):
        registry = CapabilityRegistry("providers", IDataProvider)
        provider = TwelveDataProvider(api_key="test_key")

        registry.register("twelvedata", provider)
        assert registry.has("twelvedata") is True
        retrieved = registry.get("twelvedata")
        assert retrieved is provider
        assert retrieved.name == "twelvedata"

    def test_register_factory_lazy_evaluation(self):
        registry = CapabilityRegistry("providers", IDataProvider)
        created = []

        def factory():
            p = TwelveDataProvider(api_key="lazy_key")
            created.append(p)
            return p

        registry.register_factory("twelvedata", factory)
        assert len(created) == 0
        retrieved = registry.get("twelvedata")
        assert len(created) == 1
        assert retrieved.name == "twelvedata"

    def test_pipeline_orchestrator_integration(self):
        """Verify that PipelineOrchestrator seamlessly consumes TwelveDataProvider through RegistryHub."""
        from yogi.calculation.bands.calculator import BandsCalculator
        from yogi.cockpit.demo import DemoBandsRepository
        from yogi.core.configuration.engine import EngineConfig
        from yogi.core.orchestration.pipeline import PipelineOrchestrator
        from yogi.core.registry.hub import RegistryHub
        from yogi.timeframe.engine import TimeframeEngine

        def mock_request(url: str, params: Mapping[str, Any], timeout: float):
            return MockResponse(_sample_single_time_series(), status_code=200)

        provider = TwelveDataProvider(api_key="mock_key", request_fn=mock_request)
        hub = RegistryHub()
        hub.providers.register("twelvedata", provider)
        hub.bands.register("demo", DemoBandsRepository())
        hub.calculations.register("bands", BandsCalculator())

        orchestrator = PipelineOrchestrator(registry=hub, timeframe_engine=TimeframeEngine())
        config = EngineConfig(
            provider="twelvedata",
            bands_repository="demo",
            calculation_modules=("bands",),
            symbols=["RELIANCE"],
            historical_years=1,
        )

        dataset = orchestrator.build_dataset(config)
        assert "RELIANCE" in dataset
        assert dataset["RELIANCE"]["symbol"] == "RELIANCE"
        assert dataset["RELIANCE"]["price"] == 2535.0


# =============================================================================
# 7. OPTIONAL LIVE SMOKE TEST (OPT-IN ONLY)
# =============================================================================

@pytest.mark.skipif(
    not (os.getenv("TWELVE_DATA_API_KEY") or os.getenv("TWELVEDATA_API_KEY")),
    reason="Live smoke test requires TWELVE_DATA_API_KEY environment variable",
)
def test_live_twelve_data_smoke():
    """Explicitly opt-in live test. Never runs unless user exports TWELVE_DATA_API_KEY."""
    provider = TwelveDataProvider()
    # 1. Health check with benchmark symbol (INFY on NSE, supported across free and paid plans)
    h_default = provider.health()
    assert h_default.ok is True
    assert h_default.sample_price is not None and h_default.sample_price > 0

    # 2. Daily history for universally accessible NSE benchmark equity (INFY)
    bars = provider.daily_history("INFY", exchange="NSE", years=1)
    assert len(bars) > 0
    assert bars[-1].close > 0


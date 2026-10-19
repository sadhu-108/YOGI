"""YOGI Data Providers — External Market Feed Adapters."""

from yogi.data.providers.demo import DemoDataProvider
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)
from yogi.market.calendar import INDIAN_TRADING_HOLIDAYS
__all__ = [
    "DataProviderError",
    "DataProviderAuthenticationError",
    "DemoDataProvider",
    "YFinanceDataProvider",
    "ZerodhaDataProvider",
    "yf_ticker",
    "INDIAN_TRADING_HOLIDAYS",
]


def __getattr__(name: str):
    if name in ("YFinanceDataProvider", "yf_ticker"):
        from yogi.data.providers.yfinance import YFinanceDataProvider, yf_ticker
        mapping = {"YFinanceDataProvider": YFinanceDataProvider, "yf_ticker": yf_ticker}
        return mapping[name]
    if name == "ZerodhaDataProvider":
        from yogi.data.providers.zerodha import ZerodhaDataProvider
        return ZerodhaDataProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


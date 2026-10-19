"""YOGI Data — External Ingestion and Normalization Layer."""

from yogi.data.ingestion import (
    IngestionResult,
    MarketDataIngestionService,
)
from yogi.data.normalization import (
    fetch_bse_universe,
    fetch_nse_universe,
    normalize_yfinance_bars,
    normalize_yfinance_batch,
    normalize_zerodha_history,
    normalize_zerodha_tick,
    parse_bse_scrip_json,
    parse_nse_equity_csv,
)
from yogi.data.providers import (
    INDIAN_TRADING_HOLIDAYS,
    DataProviderAuthenticationError,
    DataProviderError,
    DemoDataProvider,
)

__all__ = [
    "IngestionResult",
    "MarketDataIngestionService",
    "DataProviderError",
    "DataProviderAuthenticationError",
    "DemoDataProvider",
    "YFinanceDataProvider",
    "ZerodhaDataProvider",
    "yf_ticker",
    "INDIAN_TRADING_HOLIDAYS",
    "normalize_yfinance_bars",
    "normalize_yfinance_batch",
    "normalize_zerodha_history",
    "normalize_zerodha_tick",
    "parse_nse_equity_csv",
    "parse_bse_scrip_json",
    "fetch_nse_universe",
    "fetch_bse_universe",
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

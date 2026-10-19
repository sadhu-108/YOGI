"""Yahoo Finance market data provider for YOGI.

Implements the IDataProvider contract using yfinance and canonical normalizers.
Supports daily history, batch daily history, intraday historical bars, and health checks.
"""

from datetime import date, datetime
import logging
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.normalization.bars import (
    normalize_yfinance_bars,
    normalize_yfinance_batch,
)
from yogi.data.normalization.universe import (
    fetch_bse_universe,
    fetch_nse_universe,
)
from yogi.data.providers.exceptions import DataProviderError

SUFFIX_MAP: Mapping[str, str] = {
    "NSE": ".NS",
    "BSE": ".BO",
}

DEFAULT_HEALTH_SYMBOL: str = "RELIANCE"

# Shared Indian market calendar and date utilities (re-exported for backward compatibility)
from yogi.market.calendar import (
    INDIAN_TRADING_HOLIDAYS,
    parse_date_boundary,
    validate_and_format_date_range,
)

_parse_date_boundary = parse_date_boundary
_validate_and_format_date_range = validate_and_format_date_range


def yf_ticker(
    symbol: str,
    exchange: str = "NSE",
    aliases: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve a raw symbol to its Yahoo Finance ticker string.

    Honors custom symbol aliases (e.g. from inputs mapping), otherwise
    appends the exchange suffix (.NS or .BO).
    """
    sym_u = str(symbol).strip().upper()
    if aliases and sym_u in aliases:
        return aliases[sym_u]

    if sym_u.endswith(".NS") or sym_u.endswith(".BO"):
        return sym_u

    suffix = SUFFIX_MAP.get((exchange or "NSE").upper(), ".NS")
    return f"{sym_u}{suffix}"



class YFinanceDataProvider(IDataProvider):
    """Yahoo Finance market data provider implementation.

    Fulfills the IDataProvider contract for research, historical backfills,
    and daily batch updates.
    """

    def __init__(
        self,
        aliases: Optional[Mapping[str, str]] = None,
        auto_adjust: bool = True,
        download_fn: Optional[Callable[..., Any]] = None,
        session: Optional[Any] = None,
        fallback_universe_path: Optional[Union[str, Path]] = None,
        use_network: bool = True,
        health_symbol: Optional[str] = None,
        health_exchange: str = "NSE",
    ) -> None:
        self._aliases = dict(aliases) if aliases else {}
        self._auto_adjust = auto_adjust
        self._download_fn = download_fn or yf.download
        self._session = session
        self._fallback_universe_path = fallback_universe_path
        self._use_network = use_network
        self._health_symbol = str(health_symbol).strip().upper() if health_symbol else DEFAULT_HEALTH_SYMBOL
        self._health_exchange = (health_exchange or "NSE").upper()

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def supports_intraday(self) -> bool:
        return True

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        """Return the list of tradable symbols for the specified exchange."""
        ex = (exchange or "NSE").upper()
        if ex == "NSE":
            return fetch_nse_universe(
                session=self._session,
                fallback_csv_path=self._fallback_universe_path,
                use_network=self._use_network,
            )
        elif ex == "BSE":
            return fetch_bse_universe(
                session=self._session,
                cache_path=self._fallback_universe_path,
                use_network=self._use_network,
            )
        raise ValueError(f"Unsupported exchange for universe discovery: {exchange}")

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Sequence[MarketBar]:
        """Return historical daily OHLCV bars for a single symbol.

        Raises:
            ValueError: If date range is invalid (start >= end, missing start when end provided, etc.).
            DataProviderError: If external vendor download fails due to network or API outage.
            TypeError / AttributeError: Re-raised directly if programming errors occur.
        """
        start_str, end_str = _validate_and_format_date_range(start_date, end_date)
        tk = yf_ticker(symbol, exchange=exchange, aliases=self._aliases)
        period = f"{years}y" if years > 0 else "max"
        t0 = time.perf_counter()

        dl_kwargs: dict[str, Any] = {
            "tickers": tk,
            "interval": "1d",
            "auto_adjust": self._auto_adjust,
            "progress": False,
        }
        if start_str is not None:
            dl_kwargs["start"] = start_str
            if end_str is not None:
                dl_kwargs["end"] = end_str
        else:
            dl_kwargs["period"] = period

        try:
            df = self._download_fn(**dl_kwargs)
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as err:
            raise DataProviderError(
                f"Failed to fetch daily history for '{symbol}' ({tk}) from yfinance: {err}"
            ) from err

        bars = normalize_yfinance_bars(df)
        elapsed = time.perf_counter() - t0
        range_desc = f"range: '{start_str}' to '{end_str or 'latest'}'" if start_str else f"period: '{period}'"
        logger.debug(
            "YFinanceDataProvider: daily_history for '%s' (%s, %s) finished in %.2fs (%d bars)",
            symbol,
            tk,
            range_desc,
            elapsed,
            len(bars),
        )
        return bars

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        """Batch fetch daily history for multiple symbols.

        Raises:
            ValueError: If date range is invalid (start >= end, missing start when end provided, etc.).
            DataProviderError: If external vendor batch download fails due to network or API outage.
            TypeError / AttributeError: Re-raised directly if programming errors occur.
        """
        if not symbols:
            return {}

        start_str, end_str = _validate_and_format_date_range(start_date, end_date)
        tickers = [yf_ticker(s, exchange=exchange, aliases=self._aliases) for s in symbols]
        period = f"{years}y" if years > 0 else "max"
        t0 = time.perf_counter()
        range_desc = f"range: '{start_str}' to '{end_str or 'latest'}'" if start_str else f"period: '{period}'"
        logger.info(
            "YFinanceDataProvider: batch_daily_history requesting %d symbols (first: '%s', %s)",
            len(symbols),
            tickers[0] if tickers else "",
            range_desc,
        )

        dl_kwargs: dict[str, Any] = {
            "tickers": tickers,
            "interval": "1d",
            "auto_adjust": self._auto_adjust,
            "progress": False,
            "threads": True,
            "group_by": "column",
        }
        if start_str is not None:
            dl_kwargs["start"] = start_str
            if end_str is not None:
                dl_kwargs["end"] = end_str
        else:
            dl_kwargs["period"] = period

        try:
            df = self._download_fn(**dl_kwargs)
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as err:
            raise DataProviderError(
                f"Batch daily history download failed for {len(symbols)} symbols from yfinance: {err}"
            ) from err

        batch_result = normalize_yfinance_batch(
            df=df,
            symbols=symbols,
            exchange=exchange,
            ticker_map=self._aliases,
        )
        elapsed = time.perf_counter() - t0
        valid_count = sum(1 for b in batch_result.values() if b)
        logger.info(
            "YFinanceDataProvider: batch_daily_history completed in %.2fs (received %d symbols with data, %d empty)",
            elapsed,
            valid_count,
            len(symbols) - valid_count,
        )
        return batch_result

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        """Return the most recent close or traded price for a symbol."""
        bars = self.daily_history(symbol=symbol, exchange=exchange, years=1)
        if bars:
            return bars[-1].close
        return None

    def intraday(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 5,
    ) -> Sequence[MarketBar]:
        """Fetch intraday bars.

        Raises:
            DataProviderError: If external vendor download fails due to network or API outage.
            TypeError / AttributeError: Re-raised directly if programming errors occur.
        """
        # Standardize interval to yfinance syntax (e.g. '5minute' -> '5m')
        inv = interval.lower().strip()
        inv_map = {
            "1minute": "1m",
            "1min": "1m",
            "2minute": "2m",
            "2min": "2m",
            "5minute": "5m",
            "5min": "5m",
            "15minute": "15m",
            "15min": "15m",
            "30minute": "30m",
            "30min": "30m",
            "60minute": "60m",
            "60min": "60m",
            "1hour": "60m",
            "1h": "60m",
            "1day": "1d",
            "day": "1d",
        }
        yf_interval = inv_map.get(inv, inv)
        period = f"{days}d" if days > 0 else "1d"
        tk = yf_ticker(symbol, exchange=exchange, aliases=self._aliases)

        try:
            df = self._download_fn(
                tickers=tk,
                period=period,
                interval=yf_interval,
                auto_adjust=self._auto_adjust,
                progress=False,
            )
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as err:
            raise DataProviderError(
                f"Failed to fetch intraday bars for '{symbol}' ({tk}) from yfinance: {err}"
            ) from err

        return normalize_yfinance_bars(df)

    def subscribe_ticks(
        self,
        symbols: Sequence[str],
        on_tick: Callable[[TickData], None],
        exchange: str = "NSE",
    ) -> Any:
        """Subscribe to live ticks with a callback. yfinance does not support streaming."""
        raise NotImplementedError("yfinance provider does not support real-time tick streaming")

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        """Return list of trading holiday date strings (YYYY-MM-DD)."""
        if year is not None:
            return INDIAN_TRADING_HOLIDAYS.get(year, ())

        all_holidays: list[str] = []
        for hol_list in INDIAN_TRADING_HOLIDAYS.values():
            all_holidays.extend(hol_list)
        return tuple(sorted(set(all_holidays)))

    def health(
        self,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> ProviderHealth:
        """Verify provider connectivity and return health status.

        Checks the configured sample symbol (or parameter override) rather than
        permanently hardcoding RELIANCE.
        """
        check_sym = str(symbol).strip().upper() if symbol else self._health_symbol
        check_ex = (exchange or self._health_exchange).upper()

        try:
            sample_p = self.last_price(check_sym, exchange=check_ex)
            if sample_p is not None:
                return ProviderHealth(
                    provider=self.name,
                    ok=True,
                    sample_price=sample_p,
                    error=None,
                )
            return ProviderHealth(
                provider=self.name,
                ok=False,
                sample_price=None,
                error=f"Provider returned empty sample price for {check_sym}",
            )
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as e:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                sample_price=None,
                error=str(e),
            )

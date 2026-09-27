"""Twelve Data market data provider for YOGI.

Implements the IDataProvider contract using Twelve Data REST API.
Fulfills requirements for historical daily/intraday bars, real-time prices,
and exchange universe discovery with offline testing injection.
"""

from datetime import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import requests

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.normalization.bars import (
    normalize_twelve_data_bars,
    normalize_twelve_data_batch,
)
from yogi.data.normalization.universe import (
    fetch_bse_universe,
    fetch_nse_universe,
)
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)
from yogi.data.providers.yfinance import INDIAN_TRADING_HOLIDAYS

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL: str = "https://api.twelvedata.com"
# INFY is a benchmark NSE equity accessible across Twelve Data free (basic) and paid tiers
DEFAULT_HEALTH_SYMBOL: str = "INFY"


def _get_env_api_key() -> Optional[str]:
    """Retrieve Twelve Data API key from environment, checking Windows user registry as fallback."""
    key = os.getenv("TWELVE_DATA_API_KEY") or os.getenv("TWELVEDATA_API_KEY")
    if key and key.strip():
        return key.strip()

    if os.name == "nt":
        try:
            import winreg

            reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
            for var_name in ("TWELVE_DATA_API_KEY", "TWELVEDATA_API_KEY"):
                try:
                    val, _ = winreg.QueryValueEx(reg_key, var_name)
                    if val and str(val).strip():
                        return str(val).strip()
                except OSError:
                    continue
        except Exception:
            pass

    return None


def twelve_data_symbol(
    symbol: str,
    exchange: str = "NSE",
    aliases: Optional[Mapping[str, str]] = None,
) -> tuple[str, str]:
    """Resolve a raw symbol and exchange to Twelve Data format.

    Strips vendor-specific suffixes (.NS, .BO) and colons, applies custom aliases,
    and returns (clean_symbol, clean_exchange).
    """
    sym_u = str(symbol).strip().upper()
    ex_u = str(exchange or "NSE").strip().upper()

    if aliases and sym_u in aliases:
        mapped = aliases[sym_u]
        if ":" in mapped:
            parts = mapped.split(":", 1)
            return parts[0].strip().upper(), parts[1].strip().upper()
        return mapped.strip().upper(), ex_u

    if ":" in sym_u:
        parts = sym_u.split(":", 1)
        return parts[0].strip().upper(), parts[1].strip().upper()

    if sym_u.endswith(".NS"):
        return sym_u[:-3], "NSE"
    if sym_u.endswith(".BO"):
        return sym_u[:-3], "BSE"

    return sym_u, ex_u


def _mask_api_key(text: str, api_key: Optional[str] = None) -> str:
    """Mask the API key from log and error messages."""
    if not text:
        return ""
    masked = str(text)
    if api_key and api_key in masked:
        masked = masked.replace(api_key, "***")
    masked = re.sub(r"(?i)(apikey|api_key)=([^&\s]+)", r"\1=***", masked)
    masked = re.sub(r"(?i)(bearer\s+|token\s+)[a-zA-Z0-9_-]+", r"\1***", masked)
    return masked


class TwelveDataProvider(IDataProvider):
    """Twelve Data REST market data provider implementation.

    Fulfills the IDataProvider contract for historical daily and intraday series,
    batch daily history, and health connectivity checks.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        request_fn: Optional[Callable[..., Any]] = None,
        timeout: float = 15.0,
        aliases: Optional[Mapping[str, str]] = None,
        batch_chunk_size: int = 8,
        fallback_universe_path: Optional[Union[str, Path]] = None,
        use_network: bool = True,
        health_symbol: Optional[str] = None,
        health_exchange: str = "NSE",
    ) -> None:
        if api_key is not None:
            self._api_key = api_key.strip() if isinstance(api_key, str) else api_key
        else:
            self._api_key = _get_env_api_key()
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._session = session
        self._request_fn = request_fn
        self._timeout = timeout
        self._aliases = dict(aliases) if aliases else {}
        self._batch_chunk_size = max(1, batch_chunk_size)
        self._fallback_universe_path = fallback_universe_path
        self._use_network = use_network
        self._health_symbol = (
            str(health_symbol).strip().upper()
            if health_symbol
            else DEFAULT_HEALTH_SYMBOL
        )
        self._health_exchange = (health_exchange or "NSE").upper()

    @property
    def name(self) -> str:
        return "twelvedata"

    @property
    def supports_intraday(self) -> bool:
        return True

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def _request(self, endpoint: str, params: Mapping[str, Any]) -> Any:
        """Execute a GET request to Twelve Data with error handling and secret protection.

        Raises:
            DataProviderAuthenticationError: If API key is missing or invalid (HTTP 401).
            DataProviderError: For rate limits (HTTP 429), server errors, timeouts, or unhandled errors.
        """
        if not self._api_key:
            raise DataProviderAuthenticationError(
                "Twelve Data API key is required. Set TWELVE_DATA_API_KEY environment variable "
                "or pass api_key to TwelveDataProvider."
            )

        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        merged_params = dict(params)
        merged_params["apikey"] = self._api_key

        try:
            if self._request_fn is not None:
                resp = self._request_fn(url, params=merged_params, timeout=self._timeout)
            else:
                s = self._session or requests
                resp = s.get(url, params=merged_params, timeout=self._timeout)

            data = None
            if hasattr(resp, "status_code"):
                try:
                    data = resp.json()
                except Exception:
                    data = None

                if resp.status_code == 401:
                    msg = (data.get("message") if isinstance(data, dict) else "") or "Invalid or missing API key."
                    raise DataProviderAuthenticationError(
                        f"Twelve Data authentication failed: {_mask_api_key(str(msg), self._api_key)}"
                    )
                if resp.status_code == 429:
                    msg = (data.get("message") if isinstance(data, dict) else "") or "Free tier credit limit reached."
                    raise DataProviderError(
                        f"Twelve Data rate limit exceeded: {_mask_api_key(str(msg), self._api_key)}"
                    )

                # For HTTP 400 or 404, Twelve Data returns rich symbol-level errors or plan restrictions in JSON
                if resp.status_code in (400, 404) and isinstance(data, dict):
                    msg = _mask_api_key(str(data.get("message", "")), self._api_key)
                    if any(
                        w in msg.lower()
                        for w in ("not found", "cannot find", "plan", "available starting with", "upgrade")
                    ):
                        return data
                    raise DataProviderError(f"Twelve Data error (code {resp.status_code}): {msg}")

                if resp.status_code >= 400:
                    msg = (data.get("message") if isinstance(data, dict) else "") or f"Server Error"
                    raise DataProviderError(
                        f"Twelve Data API returned HTTP {resp.status_code}: {_mask_api_key(str(msg), self._api_key)}"
                    )

                if data is None:
                    raise DataProviderError("Twelve Data returned malformed JSON or empty response.")

            elif isinstance(resp, (dict, list)):
                data = resp
            else:
                raise DataProviderError(
                    f"Unexpected response type from Twelve Data: {type(resp).__name__}"
                )

            # Inspect payload for application-level Twelve Data error structures
            if isinstance(data, dict):
                status_val = data.get("status")
                code_val = data.get("code")
                message_val = data.get("message", "")

                if status_val == "error" or code_val is not None:
                    sanitized_msg = _mask_api_key(str(message_val), self._api_key)
                    if code_val == 401 or "api key" in sanitized_msg.lower():
                        raise DataProviderAuthenticationError(
                            f"Twelve Data authentication failed: {sanitized_msg}"
                        )
                    if code_val == 429 or any(
                        w in sanitized_msg.lower()
                        for w in ("credit", "rate limit", "minute limit")
                    ):
                        raise DataProviderError(
                            f"Twelve Data rate limit exceeded: {sanitized_msg}"
                        )
                    if code_val in (400, 404) and any(
                        w in sanitized_msg.lower()
                        for w in ("not found", "cannot find", "plan", "available starting with", "upgrade")
                    ):
                        return data
                    raise DataProviderError(
                        f"Twelve Data error (code {code_val}): {sanitized_msg}"
                    )

            return data

        except (
            DataProviderError,
            DataProviderAuthenticationError,
            TypeError,
            AttributeError,
            NameError,
        ):
            raise
        except Exception as exc:
            sanitized = _mask_api_key(str(exc), self._api_key)
            raise DataProviderError(
                f"Twelve Data request to '{endpoint}' failed: {sanitized}"
            ) from exc

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        """Return the list of tradable symbols for the specified exchange."""
        ex = (exchange or "NSE").upper()

        if self._use_network and self._api_key:
            try:
                data = self._request("stocks", params={"exchange": ex})
                if (
                    isinstance(data, dict)
                    and "data" in data
                    and isinstance(data["data"], list)
                ):
                    symbols = []
                    for item in data["data"]:
                        if isinstance(item, dict):
                            s_type = str(item.get("type", "")).strip().lower()
                            if not s_type or s_type in ("common stock", "equity"):
                                sym = str(item.get("symbol", "")).strip().upper()
                                if sym:
                                    symbols.append(sym)
                    if symbols:
                        return tuple(sorted(set(symbols)))
            except Exception as err:
                logger.debug(
                    "Twelve Data /stocks universe query failed, falling back: %s", err
                )

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
    ) -> Sequence[MarketBar]:
        """Return historical daily OHLCV bars for a single symbol."""
        clean_sym, clean_ex = twelve_data_symbol(
            symbol, exchange=exchange, aliases=self._aliases
        )
        outputsize = min(max(years * 260, 30), 5000)

        params = {
            "symbol": clean_sym,
            "exchange": clean_ex,
            "interval": "1day",
            "outputsize": outputsize,
        }

        data = self._request("time_series", params=params)
        if isinstance(data, dict) and (
            data.get("code") in (400, 404) or data.get("status") == "error"
        ):
            msg = data.get("message", "")
            if "plan" in msg.lower():
                logger.warning(
                    "Twelve Data symbol '%s' requires higher plan tier: %s",
                    clean_sym,
                    msg,
                )
            return ()

        return normalize_twelve_data_bars(data)

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
    ) -> Mapping[str, Sequence[MarketBar]]:
        """Batch fetch daily history for multiple symbols."""
        if not symbols:
            return {}

        results: dict[str, Sequence[MarketBar]] = {}
        outputsize = min(max(years * 260, 30), 5000)

        for i in range(0, len(symbols), self._batch_chunk_size):
            chunk = symbols[i : i + self._batch_chunk_size]
            sym_pairs = [
                twelve_data_symbol(s, exchange=exchange, aliases=self._aliases)
                for s in chunk
            ]
            chunk_symbols = [pair[0] for pair in sym_pairs]
            chunk_exchanges = {pair[1] for pair in sym_pairs}
            clean_ex = (
                list(chunk_exchanges)[0]
                if len(chunk_exchanges) == 1
                else (exchange or "NSE").upper()
            )

            params = {
                "symbol": ",".join(chunk_symbols),
                "exchange": clean_ex,
                "interval": "1day",
                "outputsize": outputsize,
            }

            data = self._request("time_series", params=params)
            chunk_bars = normalize_twelve_data_batch(data, chunk)
            results.update(chunk_bars)

        return results

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        """Return the most recent close or traded price for a symbol."""
        clean_sym, clean_ex = twelve_data_symbol(
            symbol, exchange=exchange, aliases=self._aliases
        )
        params = {
            "symbol": clean_sym,
            "exchange": clean_ex,
        }
        try:
            data = self._request("price", params=params)
            if isinstance(data, dict):
                if "price" in data:
                    try:
                        return float(data["price"])
                    except (ValueError, TypeError):
                        pass
                if data.get("code") in (400, 404):
                    msg = data.get("message", "")
                    if "plan" in msg.lower():
                        logger.warning(
                            "Twelve Data symbol '%s' requires higher plan tier: %s",
                            clean_sym,
                            msg,
                        )
        except Exception as err:
            logger.debug(
                "Twelve Data /price failed for %s, falling back to daily history: %s",
                symbol,
                err,
            )

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
        """Fetch intraday historical bars."""
        clean_sym, clean_ex = twelve_data_symbol(
            symbol, exchange=exchange, aliases=self._aliases
        )
        inv = interval.lower().strip()
        inv_map = {
            "1minute": "1min",
            "1min": "1min",
            "1m": "1min",
            "5minute": "5min",
            "5min": "5min",
            "5m": "5min",
            "15minute": "15min",
            "15min": "15min",
            "15m": "15min",
            "30minute": "30min",
            "30min": "30min",
            "30m": "30min",
            "45minute": "45min",
            "45min": "45min",
            "60minute": "1h",
            "60min": "1h",
            "1hour": "1h",
            "1h": "1h",
            "2hour": "2h",
            "2h": "2h",
            "4hour": "4h",
            "4h": "4h",
            "1day": "1day",
            "day": "1day",
            "1d": "1day",
            "1week": "1week",
            "week": "1week",
            "1w": "1week",
            "1month": "1month",
            "month": "1month",
        }
        td_interval = inv_map.get(inv, inv)
        outputsize = min(max(days * 75, 30), 5000)

        params = {
            "symbol": clean_sym,
            "exchange": clean_ex,
            "interval": td_interval,
            "outputsize": outputsize,
        }

        data = self._request("time_series", params=params)
        if isinstance(data, dict) and (
            data.get("code") in (400, 404) or data.get("status") == "error"
        ):
            msg = data.get("message", "")
            if "plan" in msg.lower():
                logger.warning(
                    "Twelve Data symbol '%s' requires higher plan tier: %s",
                    clean_sym,
                    msg,
                )
            return ()
        return normalize_twelve_data_bars(data)

    def subscribe_ticks(
        self,
        symbols: Sequence[str],
        on_tick: Callable[[TickData], None],
        exchange: str = "NSE",
    ) -> Any:
        """Subscribe to live ticks with a callback.

        Twelve Data REST provider does not support real-time tick streaming.
        """
        raise NotImplementedError(
            "Twelve Data provider does not support real-time tick streaming in this configuration"
        )

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
        """Verify provider connectivity and return health status."""
        check_sym = str(symbol).strip().upper() if symbol else self._health_symbol
        check_ex = (exchange or self._health_exchange).upper()

        if not self._api_key:
            return ProviderHealth(
                provider=self.name,
                ok=False,
                sample_price=None,
                error="Twelve Data API key is missing. Set TWELVE_DATA_API_KEY environment variable.",
            )

        try:
            sample_p = self.last_price(check_sym, exchange=check_ex)
            if sample_p is not None:
                return ProviderHealth(
                    provider=self.name,
                    ok=True,
                    sample_price=sample_p,
                    error=None,
                )
            # If the user passed a specific symbol that was unavailable on their plan tier (e.g. RELIANCE on Basic tier),
            # verify connectivity using the universal benchmark health symbol (INFY)
            if check_sym != self._health_symbol:
                fallback_p = self.last_price(self._health_symbol, exchange=self._health_exchange)
                if fallback_p is not None:
                    return ProviderHealth(
                        provider=self.name,
                        ok=True,
                        sample_price=fallback_p,
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
            if check_sym != self._health_symbol:
                try:
                    fallback_p = self.last_price(self._health_symbol, exchange=self._health_exchange)
                    if fallback_p is not None:
                        return ProviderHealth(
                            provider=self.name,
                            ok=True,
                            sample_price=fallback_p,
                            error=None,
                        )
                except Exception:
                    pass
            sanitized = _mask_api_key(str(e), self._api_key)
            return ProviderHealth(
                provider=self.name,
                ok=False,
                sample_price=None,
                error=sanitized,
            )

    def __repr__(self) -> str:
        has_key = bool(self._api_key)
        return f"<TwelveDataProvider(name='{self.name}', default_exchange='{self._health_exchange}', authenticated={has_key})>"

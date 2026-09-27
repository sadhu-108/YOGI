"""Zerodha Kite Connect market data provider for YOGI.

Implements the IDataProvider contract using Kite Connect API abstractions
and canonical normalizers. Supports offline testing via dependency injection.
"""

from datetime import datetime, timedelta
import os
from typing import Any, Callable, Mapping, Optional, Sequence

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth
from yogi.data.normalization.bars import (
    normalize_zerodha_history,
    normalize_zerodha_tick,
)
from yogi.data.providers.exceptions import (
    DataProviderAuthenticationError,
    DataProviderError,
)
from yogi.data.providers.yfinance import INDIAN_TRADING_HOLIDAYS

DEFAULT_HEALTH_SYMBOL: str = "RELIANCE"


class ZerodhaDataProvider(IDataProvider):
    """Zerodha Kite Connect market data provider implementation.

    Fulfills the IDataProvider contract for real-time Indian equity data,
    intraday bars, and WebSocket tick streaming.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        kite_client: Optional[Any] = None,
        ticker_client: Optional[Any] = None,
        health_symbol: Optional[str] = None,
        health_exchange: str = "NSE",
    ) -> None:
        self._api_key = api_key or os.getenv("KITE_API_KEY")
        self._access_token = access_token or os.getenv("KITE_ACCESS_TOKEN")
        self._ticker_client = ticker_client
        self._master_cache: dict[str, Sequence[Mapping[str, Any]]] = {}
        self._health_symbol = str(health_symbol).strip().upper() if health_symbol else DEFAULT_HEALTH_SYMBOL
        self._health_exchange = (health_exchange or "NSE").upper()

        if kite_client is not None:
            self.kite = kite_client
        elif self._api_key and self._access_token:
            try:
                from kiteconnect import KiteConnect

                client = KiteConnect(api_key=self._api_key)
                client.set_access_token(self._access_token)
                self.kite = client
            except ImportError as err:
                raise ImportError(
                    "kiteconnect package is required for live Zerodha operations. "
                    "Install via 'pip install kiteconnect'."
                ) from err
        else:
            self.kite = None

    def _ensure_client(self) -> Any:
        if self.kite is None:
            raise DataProviderAuthenticationError(
                "Zerodha client is not initialized. Provide api_key and access_token "
                "or inject an initialized kite_client."
            )
        return self.kite

    @property
    def name(self) -> str:
        return "zerodha"

    @property
    def supports_intraday(self) -> bool:
        return True

    @property
    def supports_live_ticks(self) -> bool:
        return True

    def security_master(self, exchange: str = "NSE") -> Sequence[Mapping[str, Any]]:
        """Return cached security master instrument rows for the given exchange."""
        ex = (exchange or "NSE").upper()
        if ex not in self._master_cache:
            client = self._ensure_client()
            try:
                rows = client.instruments(ex)
                self._master_cache[ex] = tuple(rows) if rows else ()
            except (TypeError, AttributeError, NameError):
                raise
            except Exception as err:
                err_str = str(err).lower()
                if any(k in err_str for k in ("token", "auth", "permission", "session")):
                    raise DataProviderAuthenticationError(f"Zerodha authentication failed: {err}") from err
                raise DataProviderError(f"Failed to fetch security master from Zerodha for {ex}: {err}") from err

        return self._master_cache[ex]

    def token_for(self, symbol: str, exchange: str = "NSE") -> Optional[int]:
        """Look up the numeric Kite instrument_token for a trading symbol."""
        sym_u = str(symbol).strip().upper()
        for inst in self.security_master(exchange):
            tsym = str(inst.get("tradingsymbol", "")).strip().upper()
            if tsym == sym_u:
                tok = inst.get("instrument_token")
                return int(tok) if tok is not None else None
        return None

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        """Return the list of tradable equity symbols for the specified exchange."""
        ex = (exchange or "NSE").upper()
        symbols: set[str] = set()
        for inst in self.security_master(ex):
            itype = str(inst.get("instrument_type", "")).strip().upper()
            seg = str(inst.get("segment", "")).strip().upper()
            if itype == "EQ" and (seg == ex or seg.startswith(ex)):
                sym = str(inst.get("tradingsymbol", "")).strip().upper()
                if sym:
                    symbols.add(sym)
        return tuple(sorted(symbols))

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
    ) -> Sequence[MarketBar]:
        """Return historical daily OHLCV bars for a single symbol.

        Raises:
            DataProviderAuthenticationError: If Zerodha authentication or token fails.
            DataProviderError: If external vendor call fails due to network or API outage.
            TypeError / AttributeError: Re-raised directly if programming errors occur.
        """
        client = self._ensure_client()
        tok = self.token_for(symbol, exchange)
        if tok is None:
            return ()

        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=365 * years)
        records: list[Mapping[str, Any]] = []

        start = from_dt
        while start < to_dt:
            end = min(start + timedelta(days=365), to_dt)
            try:
                chunk = client.historical_data(tok, start, end, "day")
                if chunk:
                    records.extend(chunk)
            except (TypeError, AttributeError, NameError):
                raise
            except Exception as err:
                err_str = str(err).lower()
                if any(k in err_str for k in ("token", "auth", "permission", "session")):
                    raise DataProviderAuthenticationError(f"Zerodha authentication failed: {err}") from err
                raise DataProviderError(
                    f"Failed to fetch Zerodha historical data for symbol '{symbol}' (token {tok}): {err}"
                ) from err
            start = end

        return normalize_zerodha_history(records)

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
    ) -> Mapping[str, Sequence[MarketBar]]:
        """Batch fetch daily history for multiple symbols."""
        out: dict[str, Sequence[MarketBar]] = {}
        for s in symbols:
            out[s] = self.daily_history(s, exchange=exchange, years=years)
        return out

    def intraday(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 5,
    ) -> Sequence[MarketBar]:
        """Fetch intraday bars.

        Raises:
            DataProviderAuthenticationError: If Zerodha authentication or token fails.
            DataProviderError: If external vendor call fails due to network or API outage.
            TypeError / AttributeError: Re-raised directly if programming errors occur.
        """
        client = self._ensure_client()
        tok = self.token_for(symbol, exchange)
        if tok is None:
            return ()

        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=days)
        try:
            records = client.historical_data(tok, from_dt, to_dt, interval)
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as err:
            err_str = str(err).lower()
            if any(k in err_str for k in ("token", "auth", "permission", "session")):
                raise DataProviderAuthenticationError(f"Zerodha authentication failed: {err}") from err
            raise DataProviderError(
                f"Failed to fetch Zerodha intraday data for symbol '{symbol}' (token {tok}): {err}"
            ) from err

        return normalize_zerodha_history(records or ())

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        """Return the most recent close or traded price for a symbol."""
        client = self._ensure_client()
        k = f"{exchange.upper()}:{symbol.upper()}"
        try:
            quote = client.ltp([k])
            if quote and k in quote and "last_price" in quote[k]:
                val = quote[k]["last_price"]
                return float(val) if val is not None else None
        except (TypeError, AttributeError, NameError):
            raise
        except Exception as err:
            err_str = str(err).lower()
            if any(k in err_str for k in ("token", "auth", "permission", "session")):
                raise DataProviderAuthenticationError(f"Zerodha authentication failed: {err}") from err
            # Fallback to latest bar from 1y history
            pass

        bars = self.daily_history(symbol, exchange=exchange, years=1)
        if bars:
            return bars[-1].close
        return None

    def subscribe_ticks(
        self,
        symbols: Sequence[str],
        on_tick: Callable[[TickData], None],
        exchange: str = "NSE",
    ) -> Any:
        """Subscribe to live ticks with a callback."""
        if self._ticker_client is not None:
            kt = self._ticker_client
        else:
            if not self._api_key or not self._access_token:
                raise DataProviderAuthenticationError("Zerodha credentials required to initialize KiteTicker")
            try:
                from kiteconnect import KiteTicker

                kt = KiteTicker(self._api_key, self._access_token)
            except ImportError as err:
                raise ImportError("kiteconnect package required for WebSocket tick streaming") from err

        token_to_symbol: dict[int, str] = {}
        tokens: list[int] = []
        for s in symbols:
            tok = self.token_for(s, exchange)
            if tok is not None:
                tokens.append(tok)
                token_to_symbol[tok] = s.upper()

        def _ticks_handler(ws: Any, ticks: Sequence[Mapping[str, Any]]) -> None:
            for t in ticks:
                raw_tok = t.get("instrument_token")
                sym = token_to_symbol.get(int(raw_tok)) if raw_tok is not None else None
                if sym:
                    tick_dto = normalize_zerodha_tick(symbol=sym, tick=t)
                    on_tick(tick_dto)

        def _connect_handler(ws: Any, resp: Any) -> None:
            if hasattr(ws, "subscribe"):
                ws.subscribe(tokens)
            if hasattr(ws, "set_mode") and hasattr(ws, "MODE_FULL"):
                ws.set_mode(ws.MODE_FULL, tokens)

        kt.on_ticks = _ticks_handler
        kt.on_connect = _connect_handler
        if hasattr(kt, "connect"):
            kt.connect(threaded=True)
        return kt

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

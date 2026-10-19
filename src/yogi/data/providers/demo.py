"""Demo Data Provider for YOGI.

Loads verified offline golden fixtures (prices.csv) so the system
can be fully demonstrated without external internet access or live broker credentials.
Satisfies the frozen IDataProvider Core contract.
Migrated from yogi.cockpit.demo under YOGI-F02 architectural correction.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence, Union
import pandas as pd

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.core.contracts.provider import IDataProvider, ProviderHealth


def _resolve_fixtures_dir(explicit_dir: Optional[Path] = None) -> Path:
    """Resolve the test fixtures directory containing golden price datasets."""
    if explicit_dir is not None:
        p = Path(explicit_dir)
        if p.exists() and (p / "prices.csv").exists():
            return p

    # Strategy 1: Bundled provider package data directory (src/yogi/data/providers/data)
    pkg_data = Path(__file__).resolve().parent / "data"
    if pkg_data.exists() and (pkg_data / "prices.csv").exists():
        return pkg_data

    # Strategy 2: Bundled cockpit package data directory (src/yogi/cockpit/data)
    cockpit_data = Path(__file__).resolve().parents[2] / "cockpit" / "data"
    if cockpit_data.exists() and (cockpit_data / "prices.csv").exists():
        return cockpit_data

    # Strategy 3: Walk upwards from __file__ to find tests/fixtures or data
    curr = Path(__file__).resolve().parent
    for _ in range(6):
        c1 = curr / "tests" / "fixtures"
        if c1.exists() and (c1 / "prices.csv").exists():
            return c1
        c2 = curr / "data"
        if c2.exists() and (c2 / "prices.csv").exists():
            return c2
        curr = curr.parent

    # Strategy 4: Walk upwards from current working directory
    curr = Path.cwd()
    for _ in range(6):
        c1 = curr / "tests" / "fixtures"
        if c1.exists() and (c1 / "prices.csv").exists():
            return c1
        c2 = curr / "data"
        if c2.exists() and (c2 / "prices.csv").exists():
            return c2
        curr = curr.parent

    raise FileNotFoundError(
        "Unable to locate demo fixture dataset (prices.csv) in package data or tests/fixtures."
    )


class DemoDataProvider(IDataProvider):
    """Offline market data provider backed by the verified golden prices.csv fixture.

    Provides 10 years of daily history for the 5 golden demonstration symbols:
    MANYAVAR, SBCL, EMIL, MOREPENLAB, SHILPAMED.
    """

    def __init__(self, fixtures_dir: Optional[Path] = None) -> None:
        fixtures_path = _resolve_fixtures_dir(fixtures_dir)
        prices_file = fixtures_path / "prices.csv"
        if not prices_file.exists():
            raise FileNotFoundError(f"Prices fixture not found at {prices_file}")

        df = pd.read_csv(prices_file, index_col=0, parse_dates=True)
        self._bars: dict[str, list[MarketBar]] = {}

        for col in df.columns:
            sym = str(col).strip().upper()
            series = df[col].dropna()
            bars: list[MarketBar] = []
            for ts, val in series.items():
                p = float(val)
                py_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                bars.append(
                    MarketBar(
                        timestamp=py_dt,
                        open=p,
                        high=p,
                        low=p,
                        close=p,
                        volume=10000.0,
                    )
                )
            self._bars[sym] = bars

    @property
    def name(self) -> str:
        return "demo"

    @property
    def supports_intraday(self) -> bool:
        return False

    @property
    def supports_live_ticks(self) -> bool:
        return False

    def universe(self, exchange: str = "NSE") -> Sequence[str]:
        return tuple(self._bars.keys())

    def daily_history(
        self,
        symbol: str,
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Sequence[MarketBar]:
        sym = symbol.strip().upper()
        bars = self._bars.get(sym, [])
        if not bars:
            return ()

        if start_date is not None or end_date is not None:
            if start_date is None and end_date is not None:
                raise ValueError("Cannot specify end_date without start_date; start_date is required")

            from yogi.market.calendar import parse_date_boundary
            dt_start, _ = parse_date_boundary(start_date, "start_date")
            dt_end, _ = parse_date_boundary(end_date, "end_date") if end_date is not None else (None, None)

            if dt_end is not None:
                if (dt_start.tzinfo is None) != (dt_end.tzinfo is None):
                    raise ValueError("Cannot compare timezone-aware and timezone-naive date boundaries")
                if dt_start >= dt_end:
                    raise ValueError(
                        f"Invalid date range: start_date ({start_date}) must be strictly earlier than end_date ({end_date})"
                    )

            filtered = []
            for b in bars:
                ts = b.timestamp
                ts_cmp = ts.replace(tzinfo=None) if hasattr(ts, "tzinfo") and ts.tzinfo is not None else ts
                s_cmp = dt_start.replace(tzinfo=None) if dt_start.tzinfo is not None else dt_start
                if ts_cmp < s_cmp:
                    continue
                if dt_end is not None:
                    e_cmp = dt_end.replace(tzinfo=None) if dt_end.tzinfo is not None else dt_end
                    if ts_cmp >= e_cmp:
                        continue
                filtered.append(b)
            return tuple(filtered)

        if years >= 10:
            return tuple(bars)
        # Approximate 252 trading days per year
        cutoff_bars = max(20, years * 252)
        return tuple(bars[-cutoff_bars:])

    def batch_daily_history(
        self,
        symbols: Sequence[str],
        exchange: str = "NSE",
        years: int = 10,
        start_date: Optional[Union[datetime, date, str]] = None,
        end_date: Optional[Union[datetime, date, str]] = None,
    ) -> Mapping[str, Sequence[MarketBar]]:
        return {
            s: self.daily_history(
                s,
                exchange=exchange,
                years=years,
                start_date=start_date,
                end_date=end_date,
            )
            for s in symbols
        }

    def last_price(self, symbol: str, exchange: str = "NSE") -> Optional[float]:
        bars = self.daily_history(symbol, exchange=exchange)
        return bars[-1].close if bars else None

    def intraday(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5minute",
        days: int = 5,
    ) -> Sequence[MarketBar]:
        return ()

    def subscribe_ticks(
        self,
        symbols: Sequence[str],
        on_tick: Callable[[TickData], None],
        exchange: str = "NSE",
    ) -> Any:
        raise NotImplementedError("DemoDataProvider does not support live tick subscriptions.")

    def trading_holidays(self, year: Optional[int] = None) -> Sequence[str]:
        return ()

    def health(self) -> ProviderHealth:
        first_sym = next(iter(self._bars.keys()), None)
        sample = self.last_price(first_sym) if first_sym else None
        return ProviderHealth(provider="demo", ok=True, sample_price=sample)

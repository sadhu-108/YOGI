"""Tests for data normalization modules (bars and universe)."""

from datetime import datetime
import json
from pathlib import Path
import pandas as pd
import pytest

from yogi.core.contracts.market_data import MarketBar, TickData
from yogi.data.normalization.bars import (
    normalize_yfinance_bars,
    normalize_yfinance_batch,
    normalize_zerodha_history,
    normalize_zerodha_tick,
)
from yogi.data.normalization.universe import (
    DEFAULT_NSE_FALLBACK,
    fetch_bse_universe,
    fetch_nse_universe,
    parse_bse_scrip_json,
    parse_nse_equity_csv,
)


class TestNormalizeYFinanceBars:
    def test_single_symbol_dataframe(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        df = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 101.0],
                "High": [105.0, 106.0, 104.0],
                "Low": [99.0, 101.0, 100.0],
                "Close": [103.0, 104.0, 102.5],
                "Volume": [1000, 1500, 1200],
            },
            index=dates,
        )

        bars = normalize_yfinance_bars(df)

        assert len(bars) == 3
        assert all(isinstance(b, MarketBar) for b in bars)
        assert bars[0].timestamp == datetime(2024, 1, 1, 0, 0)
        assert bars[0].open == 100.0
        assert bars[0].high == 105.0
        assert bars[0].low == 99.0
        assert bars[0].close == 103.0
        assert bars[0].volume == 1000.0
        assert bars[1].close == 104.0
        assert bars[2].close == 102.5

    def test_missing_volume_and_nan(self):
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        df = pd.DataFrame(
            {
                "Close": [100.0, 105.0],
            },
            index=dates,
        )

        bars = normalize_yfinance_bars(df)
        assert len(bars) == 2
        assert bars[0].volume is None
        assert bars[0].open == 100.0  # Fallback to close
        assert bars[1].close == 105.0

    def test_empty_and_invalid_inputs(self):
        assert normalize_yfinance_bars(None) == ()
        assert normalize_yfinance_bars("not a df") == ()
        assert normalize_yfinance_bars(pd.DataFrame()) == ()

    def test_chronological_ordering_and_deduplication(self):
        # Unordered dates with duplicate
        dates = [
            pd.Timestamp("2024-01-05"),
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2024-01-03"),
        ]
        df = pd.DataFrame(
            {
                "Close": [50.0, 10.0, 12.0, 30.0],
            },
            index=dates,
        )

        bars = normalize_yfinance_bars(df)
        assert len(bars) == 3
        assert [b.timestamp for b in bars] == [
            datetime(2024, 1, 1),
            datetime(2024, 1, 3),
            datetime(2024, 1, 5),
        ]
        # Duplicate timestamp replaced with later value or preserved deterministically
        assert bars[0].close in (10.0, 12.0)
        assert bars[1].close == 30.0
        assert bars[2].close == 50.0

    def test_multiindex_price_level_0_ticker_level_1(self):
        """Verify modern yfinance default MultiIndex (Price, Ticker) extracts accurate OHLCV."""
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        cols = pd.MultiIndex.from_tuples([
            ("Close", "RELIANCE.NS"),
            ("Open", "RELIANCE.NS"),
            ("High", "RELIANCE.NS"),
            ("Low", "RELIANCE.NS"),
            ("Volume", "RELIANCE.NS"),
        ])
        df = pd.DataFrame([
            [2500.0, 2490.0, 2510.0, 2480.0, 10000.0],
            [2520.0, 2505.0, 2530.0, 2500.0, 12000.0],
            [2515.0, 2520.0, 2525.0, 2510.0, 8000.0],
        ], index=dates, columns=cols)

        bars = normalize_yfinance_bars(df)
        assert len(bars) == 3
        assert all(isinstance(b, MarketBar) for b in bars)
        assert bars[0].timestamp == datetime(2024, 1, 1)
        assert bars[0].open == 2490.0
        assert bars[0].high == 2510.0
        assert bars[0].low == 2480.0
        assert bars[0].close == 2500.0
        assert bars[0].volume == 10000.0
        assert bars[2].close == 2515.0

    def test_multiindex_ticker_level_0_price_level_1(self):
        """Verify inverted MultiIndex (Ticker, Price) extracts accurate OHLCV."""
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        cols = pd.MultiIndex.from_tuples([
            ("TCS.NS", "Open"),
            ("TCS.NS", "High"),
            ("TCS.NS", "Low"),
            ("TCS.NS", "Close"),
            ("TCS.NS", "Volume"),
        ])
        df = pd.DataFrame([
            [3500.0, 3550.0, 3490.0, 3540.0, 50000.0],
            [3545.0, 3560.0, 3520.0, 3530.0, 45000.0],
        ], index=dates, columns=cols)

        bars = normalize_yfinance_bars(df)
        assert len(bars) == 2
        assert bars[0].open == 3500.0
        assert bars[0].high == 3550.0
        assert bars[0].low == 3490.0
        assert bars[0].close == 3540.0
        assert bars[0].volume == 50000.0
        assert bars[1].close == 3530.0

    def test_multiindex_without_price_fields_returns_empty(self):
        """Verify MultiIndex with no recognizable price fields returns empty tuple."""
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        cols = pd.MultiIndex.from_tuples([
            ("Sector", "RELIANCE.NS"),
            ("Industry", "RELIANCE.NS"),
        ])
        df = pd.DataFrame([[1, 2], [3, 4]], index=dates, columns=cols)
        assert normalize_yfinance_bars(df) == ()


class TestNormalizeYFinanceBatch:
    def test_multiindex_metric_first(self):
        # Level 0 = Metric ("Close", "Volume"), Level 1 = Ticker ("INFY.NS", "TCS.NS")
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        cols = pd.MultiIndex.from_tuples(
            [
                ("Close", "INFY.NS"),
                ("Close", "TCS.NS"),
                ("Open", "INFY.NS"),
                ("Open", "TCS.NS"),
                ("Volume", "INFY.NS"),
                ("Volume", "TCS.NS"),
            ]
        )
        df = pd.DataFrame(
            [
                [1500.0, 3800.0, 1490.0, 3790.0, 10000, 20000],
                [1520.0, 3850.0, 1505.0, 3810.0, 12000, 25000],
            ],
            index=dates,
            columns=cols,
        )

        res = normalize_yfinance_batch(df, symbols=["INFY", "TCS", "MISSING"], exchange="NSE")

        assert "INFY" in res
        assert "TCS" in res
        assert "MISSING" in res
        assert len(res["INFY"]) == 2
        assert len(res["TCS"]) == 2
        assert res["MISSING"] == ()

        assert res["INFY"][0].close == 1500.0
        assert res["INFY"][1].close == 1520.0
        assert res["TCS"][0].close == 3800.0

    def test_multiindex_ticker_first(self):
        # Level 0 = Ticker ("INFY.NS"), Level 1 = Metric ("Close", "Open")
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        cols = pd.MultiIndex.from_tuples(
            [
                ("INFY.NS", "Close"),
                ("INFY.NS", "Open"),
                ("TCS.NS", "Close"),
                ("TCS.NS", "Open"),
            ]
        )
        df = pd.DataFrame(
            [
                [1500.0, 1490.0, 3800.0, 3790.0],
                [1520.0, 1505.0, 3850.0, 3810.0],
            ],
            index=dates,
            columns=cols,
        )

        res = normalize_yfinance_batch(df, symbols=["INFY", "TCS"], exchange="NSE")
        assert len(res["INFY"]) == 2
        assert len(res["TCS"]) == 2
        assert res["INFY"][0].close == 1500.0
        assert res["TCS"][1].close == 3850.0


class TestNormalizeZerodha:
    def test_normalize_zerodha_history(self):
        records = [
            {
                "date": "2024-01-02 09:15:00",
                "open": 2500.0,
                "high": 2520.0,
                "low": 2490.0,
                "close": 2510.0,
                "volume": 50000,
            },
            {
                "date": "2024-01-01 09:15:00",
                "open": 2480.0,
                "high": 2500.0,
                "low": 2470.0,
                "close": 2495.0,
                "volume": 45000,
            },
        ]

        bars = normalize_zerodha_history(records)
        assert len(bars) == 2
        # Chronological ascending
        assert bars[0].timestamp == datetime(2024, 1, 1, 9, 15)
        assert bars[0].close == 2495.0
        assert bars[0].volume == 45000.0
        assert bars[1].timestamp == datetime(2024, 1, 2, 9, 15)
        assert bars[1].close == 2510.0

    def test_normalize_zerodha_tick(self):
        tick = {
            "instrument_token": 738561,
            "last_price": 2505.5,
            "last_traded_quantity": 25,
            "timestamp": "2024-01-02 11:30:00",
        }

        tick_dto = normalize_zerodha_tick(symbol="RELIANCE", tick=tick)
        assert isinstance(tick_dto, TickData)
        assert tick_dto.symbol == "RELIANCE"
        assert tick_dto.last_price == 2505.5
        assert tick_dto.last_quantity == 25
        assert tick_dto.timestamp == datetime(2024, 1, 2, 11, 30)


class TestUniverseParsers:
    def test_parse_nse_equity_csv(self):
        csv_data = """SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10
TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1
SGBMAY29,GOVERNMENT OF INDIA,GB,25-MAY-2021,1,1,IN0020210037,1
INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5
"""
        symbols = parse_nse_equity_csv(csv_data)
        assert symbols == ("INFY", "RELIANCE", "TCS")
        assert "SGBMAY29" not in symbols  # Non-EQ filtered out

    def test_parse_bse_scrip_json_table(self):
        data = {
            "Table": [
                {"SCRIP_CD": "500325", "Scrip_Name": "RELIANCE INDS", "Status": "Active"},
                {"SCRIP_CD": "532540", "Scrip_Name": "TCS", "Status": "Active"},
                {"SCRIP_CD": "INVALID", "Scrip_Name": "NON_NUMERIC"},
            ]
        }
        codes = parse_bse_scrip_json(data)
        assert codes == ("500325", "532540")

    def test_fetch_universe_fallbacks(self, tmp_path):
        # Test NSE offline fallback from CSV file
        csv_file = tmp_path / "test_nse.csv"
        csv_file.write_text(
            "SYMBOL,SERIES\nINFY,EQ\nWIPRO,EQ\n",
            encoding="utf-8",
        )
        symbols = fetch_nse_universe(session=None, fallback_csv_path=csv_file)
        assert "INFY" in symbols
        assert "WIPRO" in symbols

        # Test static fallback when file doesn't exist and network is disabled/fails
        static = fetch_nse_universe(
            session=None,
            fallback_csv_path="nonexistent_file.csv",
            use_network=False,
        )
        assert static == DEFAULT_NSE_FALLBACK

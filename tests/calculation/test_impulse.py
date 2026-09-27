"""Unit tests for ImpulseCalculator and Ram's 50% recovery rule."""

from datetime import datetime
import pandas as pd
import pytest

from yogi.calculation.impulse import ImpulseCalculator, impulse_correction
from yogi.calculation.impulse.calculator import _zigzag
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext


def bd(vals, end="2026-08-13"):
    return pd.Series(vals, index=pd.bdate_range(end=end, periods=len(vals)), dtype=float)


@pytest.mark.parametrize(
    "vals,expected",
    [
        ([100 - 2.5 * i for i in range(21)] + [50 + 6.875 * i for i in range(1, 9)], "IP"),  # 40% of fall time
        ([100 - 2.5 * i for i in range(21)] + [50 + 3.06 * i for i in range(1, 19)], "up"),  # 90% - too slow
        ([100 - 2.5 * i for i in range(21)] + [50 + 5.0 * i for i in range(1, 7)], "up"),    # fast, no full recovery
        ([50 + 2.5 * i for i in range(21)] + [100 - 4.0 * i for i in range(1, 11)], "CR"),   # falling now
    ],
)
def test_impulse_rule(vals, expected):
    assert impulse_correction(bd(vals))["state"] == expected


def test_yearly_impulse_fires():
    yearly = pd.Series(
        [50, 80, 120, 160, 200, 170, 140, 110, 80, 160, 250, 255, 260],
        index=pd.date_range("2014-12-31", periods=13, freq="YE"),
    )
    r = impulse_correction(yearly, pct=15.0)
    assert r["state"] == "IP"
    assert r["ratio"] is not None and r["ratio"] <= 0.5


def test_insufficient_history():
    short = bd([100.0, 101.0, 102.0])
    r = impulse_correction(short)
    assert r["state"] == "na"
    assert r["legPct"] is None


def test_zigzag_short_series():
    assert _zigzag(pd.Series([100.0, 105.0])) == []


def test_impulse_calculator_contract_and_calculation():
    calc = ImpulseCalculator()
    assert isinstance(calc, ICalcModule)
    assert calc.name == "impulse"
    assert calc.required_timeframes == ("D",)

    # Impulse pattern: fall from 100 to 50 in 20 bars, then rise from 50 to 105 in 8 bars
    prices = [100.0 - 2.5 * i for i in range(21)] + [50.0 + 6.875 * i for i in range(1, 9)]
    daily_bars = [
        MarketBar(
            timestamp=datetime(2026, 1, 1) + pd.Timedelta(days=i),
            open=p,
            high=p + 1.0,
            low=p - 1.0,
            close=p,
            volume=1000.0,
        )
        for i, p in enumerate(prices)
    ]
    market_ctx = MarketContext(
        symbol="IMP",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("IMP", calc_ctx)
    assert isinstance(res, CalculationResult)
    assert res.symbol == "IMP"
    assert res.module_name == "impulse"

    m = res.metrics
    assert m["IC"] == "IP"
    assert m["IC_BARS"] is not None
    assert m["IC_PCT"] is not None
    assert m["IC_RATIO"] is not None


def test_impulse_calculator_empty_context():
    calc = ImpulseCalculator()
    market_ctx = MarketContext(symbol="EMPTY", exchange="NSE", bars_by_timeframe={})
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("EMPTY", calc_ctx)
    m = res.metrics
    assert m["IC"] == "na"
    assert m["IC_PCT"] is None

"""GOLDEN REGRESSION TEST — Step 8 Calculation Pillars.

Replays FROZEN historical prices for MANYAVAR, SBCL, EMIL, MOREPENLAB, and SHILPAMED,
and verifies that all four calculation pillars (Bands, Velocity, Impulse, Trend)
produce the exact mathematical results locked in the golden expected.json fixture (< 1e-6 precision).
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
import pandas as pd
import pytest

from yogi.calculation.bands import BandsCalculator
from yogi.calculation.impulse import ImpulseCalculator
from yogi.calculation.trend import TrendCalculator
from yogi.calculation.velocity import VelocityCalculator
from yogi.core.contracts.calculation import CalculationContext
from yogi.core.contracts.market_data import MarketBar, MarketContext
from yogi.timeframe.engine import TimeframeEngine

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(scope="module")
def expected_data() -> Mapping[str, Any]:
    with open(FIXTURES_DIR / "expected.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def bands_seed_data() -> Mapping[str, Mapping[str, float]]:
    df = pd.read_csv(FIXTURES_DIR / "bands_seed.csv")
    out: dict[str, dict[str, float]] = {}
    for _, row in df.iterrows():
        sym = str(row["symbol"]).strip().upper()
        out[sym] = {}
        for tf in ("D", "W", "M", "Q", "H", "Y"):
            v = row.get(tf)
            if pd.notna(v):
                out[sym][tf] = float(v)
    return out


@pytest.fixture(scope="module")
def computed_data(bands_seed_data: Mapping[str, Mapping[str, float]]) -> Mapping[str, Mapping[str, Any]]:
    px = pd.read_csv(FIXTURES_DIR / "prices.csv", index_col=0, parse_dates=True)
    tf_engine = TimeframeEngine()
    bands_calc = BandsCalculator()
    velocity_calc = VelocityCalculator()
    impulse_calc = ImpulseCalculator()
    trend_calc = TrendCalculator()

    computed: dict[str, dict[str, Any]] = {}

    for sym in px.columns:
        s = px[sym].dropna()
        daily_bars = [
            MarketBar(
                timestamp=ts.to_pydatetime(),
                open=float(val),
                high=float(val),
                low=float(val),
                close=float(val),
                volume=0.0,
            )
            for ts, val in s.items()
        ]

        market_ctx = tf_engine.build_context(
            symbol=sym,
            exchange="NSE",
            daily_bars=daily_bars,
            timeframes=("D", "W", "M", "Q", "H", "Y"),
        )

        bands_lookup = bands_seed_data.get(sym)
        calc_ctx = CalculationContext(
            market_context=market_ctx,
            bands_lookup=bands_lookup,
        )

        res_bands = bands_calc.calculate(sym, calc_ctx)
        res_vel = velocity_calc.calculate(sym, calc_ctx)
        res_imp = impulse_calc.calculate(sym, calc_ctx)
        res_trend = trend_calc.calculate(sym, calc_ctx)

        merged: dict[str, Any] = {}
        merged.update(res_bands.metrics)
        merged.update(res_vel.metrics)
        merged.update(res_imp.metrics)
        merged.update(res_trend.metrics)

        computed[sym] = merged

    return computed


def test_all_five_stocks_present(computed_data, expected_data):
    assert set(computed_data.keys()) == set(expected_data.keys())


@pytest.mark.parametrize("symbol", ["MANYAVAR", "SBCL", "EMIL", "MOREPENLAB", "SHILPAMED"])
def test_golden_metrics_match_expected(computed_data, expected_data, symbol):
    row = computed_data[symbol]
    exp = expected_data[symbol]
    drift = []

    for k, want in exp.items():
        if k.startswith("RANK_"):
            # Ranks are added in Step 9 screening/ranking stage, not in pure calculation modules
            continue

        got = row.get(k)
        if want is None:
            if got is not None and pd.notna(got):
                drift.append(f"{k}: expected blank, got {got}")
            continue

        if isinstance(want, str):
            if str(got) != want:
                drift.append(f"{k}: expected {want!r}, got {str(got)!r}")
        else:
            if got is None or pd.isna(got) or abs(float(got) - want) > 1e-6:
                drift.append(f"{k}: expected {want}, got {got}")

    assert not drift, f"CALCULATION DRIFT for {symbol}:\n  " + "\n  ".join(drift)

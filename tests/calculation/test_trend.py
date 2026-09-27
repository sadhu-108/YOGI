"""Unit tests for TrendCalculator, ROCs, EMAs, CAGRs, and DMI/ADX."""

from datetime import datetime
import numpy as np
import pandas as pd
import pytest

from yogi.calculation.trend import (
    TrendCalculator,
    all_rocs,
    ath_diff,
    cagr_trailing,
    cagrs,
    calendar_years,
    dmi,
    dmi_block,
    dmi_settings,
    dmi_state,
    ema_status,
    half_block,
    monthly_block,
    per_tf_ema,
    quarter_block,
    roc_trailing,
)
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar, MarketContext


def bd(vals, end="2026-08-13"):
    return pd.Series(vals, index=pd.bdate_range(end=end, periods=len(vals)), dtype=float)


def dmi_bars(closes):
    idx = pd.bdate_range(end="2026-08-13", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": c * 0.998, "high": c * 1.01, "low": c * 0.99, "close": c},
        index=idx,
    )


# ---------------- ROC ----------------
def test_roc_one_bar():
    assert round(roc_trailing(bd([100, 110, 121]), 1), 6) == 10.0


def test_roc_two_bars():
    assert round(roc_trailing(bd([100, 110, 121]), 2), 6) == 21.0


def test_roc_no_data():
    assert np.isnan(roc_trailing(bd([100]), 5))


# ---------------- EMA 3/5 ----------------
def test_ema_rising_is_yes():
    assert ema_status(bd(list(range(1, 40)))) == "yes"


def test_ema_falling_is_no():
    assert ema_status(bd(list(range(40, 1, -1)))) == "no"


def test_ema_fresh_cross_is_upcut():
    assert ema_status(bd([10] * 10 + [9, 8, 7, 6, 5, 20])) == "upcut"


# ---------------- CAGR ----------------
def test_cagr_5y_doubling():
    idx = pd.bdate_range("2021-08-13", "2026-08-13")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    assert abs(cagr_trailing(s, 5) - 14.8698) < 0.05


# ---------------- ATH ----------------
def test_ath_diff_is_negative_or_zero():
    assert round(ath_diff(bd([50, 150, 75])), 4) == -50.0


def test_ath_at_peak_is_zero():
    assert round(ath_diff(bd([50, 100, 150])), 4) == 0.0


# ---------------- Calendar Months ----------------
def test_month_keys_are_calendar_numbers():
    idx = pd.bdate_range("2024-01-01", "2026-08-13")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    mb = monthly_block(s)
    assert mb["M_CUR_KEY"] == "M8"
    assert mb["M_KEYS"].split(",") == ["M8", "M7", "M6", "M5"]


def test_month_rolls_to_september():
    idx = pd.bdate_range("2024-01-01", "2026-09-02")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    mb = monthly_block(s)
    assert mb["M_CUR_KEY"] == "M9"
    assert "M8" in mb["M_KEYS"]


def test_month_rolls_to_january():
    idx = pd.bdate_range("2024-01-01", "2027-01-05")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    mb = monthly_block(s)
    assert mb["M_CUR_KEY"] == "M1"
    assert mb["M_KEYS"].split(",")[1] == "M12"


# ---------------- Calendar Quarters / Halves ----------------
def test_quarter_is_q3_in_august():
    idx = pd.bdate_range("2022-01-01", "2026-08-13")
    s = pd.Series(np.linspace(100, 300, len(idx)), index=idx)
    assert quarter_block(s)["Q_CUR_KEY"] == "Q3"


def test_half_is_h2_in_august():
    idx = pd.bdate_range("2022-01-01", "2026-08-13")
    s = pd.Series(np.linspace(100, 300, len(idx)), index=idx)
    assert half_block(s)["H_CUR_KEY"] == "H2"


# ---------------- Calendar Years ----------------
def test_calendar_year_returns_exact():
    idx = pd.date_range("2019-01-01", "2026-08-13", freq="D")
    px = pd.Series(index=idx, dtype=float)

    def setp(a, b, v):
        px.loc[a:b] = v

    setp("2019-01-01", "2020-12-31", 100)
    setp("2021-01-01", "2021-12-31", 110)
    setp("2022-01-01", "2022-12-31", 121)
    setp("2023-01-01", "2023-12-31", 100)
    setp("2024-01-01", "2024-12-31", 150)
    setp("2025-01-01", "2025-12-31", 200)
    setp("2026-01-01", "2026-08-13", 300)

    y = calendar_years(px.dropna(), 2026)
    assert round(y["Y2021"], 4) == 10.0
    assert round(y["Y2022"], 4) == 10.0
    assert round(y["Y2023"], 4) == -17.3554
    assert round(y["Y2024"], 4) == 50.0
    assert round(y["Y2025"], 4) == 33.3333
    assert round(y["Y2026"], 4) == 50.0
    assert "YTD" not in y


# ---------------- DMI / ADX ----------------
def test_uptrend_plus_di_dominates():
    r = dmi(dmi_bars(np.linspace(100, 300, 200)))
    assert r["plus_di"] > r["minus_di"]
    assert r["adx"] > 25


def test_downtrend_minus_di_dominates():
    r = dmi(dmi_bars(np.linspace(300, 100, 200)))
    assert r["minus_di"] > r["plus_di"]
    assert r["adx"] > 25


def test_too_little_history_returns_blank():
    r = dmi(dmi_bars(np.linspace(100, 110, 5)))
    assert r["plus_di"] is None and r["adx"] is None


@pytest.mark.parametrize(
    "p,m,a,expect",
    [
        (30, 10, 45, "STRONG UP"),
        (30, 10, 30, "UP TREND"),
        (30, 10, 15, "up, weak"),
        (10, 30, 45, "STRONG DOWN"),
        (10, 30, 30, "DOWN TREND"),
        (10, 30, 15, "down, weak"),
        (None, 10, 20, "na"),
    ],
)
def test_dmi_state_wording(p, m, a, expect):
    assert dmi_state(p, m, a) == expect


def test_dmi_settings_defaults():
    """Default DMI lookback period and ADX smoothing must be (5, 5) across all timeframes."""
    cfg = dmi_settings()
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        assert cfg[tf] == (5, 5)


def test_dmi_settings_explicit_overrides():
    """Explicit parameters override defaults globally and per-timeframe."""
    cfg = dmi_settings({"DMI_period": 14, "DMI_adx_smooth": 14})
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        assert cfg[tf] == (14, 14)

    cfg_tf = dmi_settings(
        {
            "DMI_period": 5,
            "DMI_adx_smooth": 5,
            "DMI_di_len_W": 10,
            "DMI_adx_smooth_W": 8,
        }
    )
    assert cfg_tf["D"] == (5, 5)
    assert cfg_tf["W"] == (10, 8)
    assert cfg_tf["M"] == (5, 5)


def test_standalone_dmi_default_is_14():
    """Standalone dmi() retains Wilder's default period=14 when history allows."""
    b = dmi_bars(np.linspace(100, 400, 100))
    r = dmi(b)
    assert r["period"] == 14
    assert r["adx_period"] == 14
    assert r["adx"] is not None


def test_dmi_block_covers_all_timeframes():
    idx = pd.bdate_range("2018-01-01", "2026-08-13")
    c = 100 * np.exp(np.cumsum(np.random.default_rng(4).normal(0.0006, 0.02, len(idx))))
    df = pd.DataFrame(
        {"open": c * 0.99, "high": c * 1.02, "low": c * 0.98, "close": c, "volume": 5e5},
        index=idx,
    )
    out = dmi_block(df, {"W": "W", "M": "ME", "Q": "QE", "H": "2QE", "Y": "YE"})
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        for pre in ("DMIP_", "DMIA_", "DIP_", "DIM_", "ADX_", "DMI_"):
            assert pre + tf in out, f"{pre}{tf} missing"


def test_dmi_short_daily_history_populates_all_timeframes():
    """When daily bars are < 6 but OHLC is varied, all 6 timeframes get None/'na'."""
    calc = TrendCalculator()
    daily_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 1) + pd.Timedelta(days=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=102.0,
            volume=1000.0,
        )
        for i in range(4)  # 4 bars < 6
    ]
    market_ctx = MarketContext(
        symbol="SHORT_DAILY",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)
    res = calc.calculate("SHORT_DAILY", calc_ctx)
    m = res.metrics
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        assert m[f"DMIP_{tf}"] is None
        assert m[f"DMIA_{tf}"] is None
        assert m[f"DIP_{tf}"] is None
        assert m[f"DIM_{tf}"] is None
        assert m[f"ADX_{tf}"] is None
        assert m[f"DMI_{tf}"] == "na"


def test_dmi_short_higher_timeframe_history():
    """Higher timeframes with < 6 bars get None/'na' while sufficient timeframes calculate normally."""
    calc = TrendCalculator()
    daily_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 1) + pd.Timedelta(days=i),
            open=100.0 + i * 0.5,
            high=102.0 + i * 0.5,
            low=99.0 + i * 0.5,
            close=101.0 + i * 0.5,
            volume=1000.0,
        )
        for i in range(50)
    ]
    weekly_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 7) + pd.Timedelta(weeks=i),
            open=100.0 + i * 2.5,
            high=103.0 + i * 2.5,
            low=99.0 + i * 2.5,
            close=102.0 + i * 2.5,
            volume=5000.0,
        )
        for i in range(15)
    ]
    monthly_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 31) + pd.Timedelta(days=30 * i),
            open=100.0 + i * 10.0,
            high=105.0 + i * 10.0,
            low=98.0 + i * 10.0,
            close=104.0 + i * 10.0,
            volume=20000.0,
        )
        for i in range(2)  # only 2 bars < 6
    ]
    market_ctx = MarketContext(
        symbol="PARTIAL",
        exchange="NSE",
        bars_by_timeframe={
            "D": tuple(daily_bars),
            "W": tuple(weekly_bars),
            "M": tuple(monthly_bars),
        },
    )
    calc_ctx = CalculationContext(market_context=market_ctx)
    res = calc.calculate("PARTIAL", calc_ctx)
    m = res.metrics

    # D and W (>= 6 bars) calculate normally with default 5/5
    assert m["DIP_D"] is not None
    assert m["ADX_D"] is not None
    assert m["DMI_D"] != "na"
    assert m["DMIP_D"] == 5
    assert m["DMIA_D"] == 5

    assert m["DIP_W"] is not None
    assert m["ADX_W"] is not None
    assert m["DMI_W"] != "na"
    assert m["DMIP_W"] == 5
    assert m["DMIA_W"] == 5

    # M (< 6 bars), Q, H, Y (no bars) have None and "na"
    for tf in ("M", "Q", "H", "Y"):
        assert m[f"DMIP_{tf}"] is None
        assert m[f"DMIA_{tf}"] is None
        assert m[f"DIP_{tf}"] is None
        assert m[f"DIM_{tf}"] is None
        assert m[f"ADX_{tf}"] is None
        assert m[f"DMI_{tf}"] == "na"


def test_dmi_close_only_data_omits_dmi():
    """When high == low across all bars (Close-only Bhavcopy), DMI keys are omitted."""
    calc = TrendCalculator()
    daily_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 1) + pd.Timedelta(days=i),
            open=100.0 + i,
            high=100.0 + i,
            low=100.0 + i,
            close=100.0 + i,
            volume=1000.0,
        )
        for i in range(50)
    ]
    market_ctx = MarketContext(
        symbol="CLOSE_ONLY",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)
    res = calc.calculate("CLOSE_ONLY", calc_ctx)
    m = res.metrics
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        assert f"DMI_{tf}" not in m
        assert f"ADX_{tf}" not in m


# ---------------- Calculator Contract ----------------
def test_trend_calculator_contract_and_calculation():
    calc = TrendCalculator()
    assert isinstance(calc, ICalcModule)
    assert calc.name == "trend"
    assert calc.required_timeframes == ("D", "W", "M", "Q", "H", "Y")

    daily_bars = [
        MarketBar(
            timestamp=datetime(2024, 1, 1) + pd.Timedelta(days=i),
            open=100.0 + i * 0.2,
            high=102.0 + i * 0.2,
            low=99.0 + i * 0.2,
            close=100.0 + i * 0.2,
            volume=1000.0,
        )
        for i in range(600)
    ]
    market_ctx = MarketContext(
        symbol="TRD",
        exchange="NSE",
        bars_by_timeframe={"D": tuple(daily_bars)},
    )
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("TRD", calc_ctx)
    assert isinstance(res, CalculationResult)
    assert res.symbol == "TRD"
    assert res.module_name == "trend"

    m = res.metrics
    assert "DROC" in m
    assert "M_CUR" in m
    assert "Q_CUR" in m
    assert "H_CUR" in m
    assert "CAGR_1" in m
    assert "EMA_D" in m
    assert "EMA_W" in m
    assert "SUSPECT" in m
    assert m["SUSPECT"] in ("Y", "N")

    # DMI checks
    assert m["DMIP_D"] == 5
    assert m["DMIA_D"] == 5
    assert m["DMI_D"] != "na"
    assert m["DMI_W"] == "na"
    assert m["DMI_Y"] == "na"


def test_trend_calculator_empty_context():
    calc = TrendCalculator()
    market_ctx = MarketContext(symbol="EMPTY", exchange="NSE", bars_by_timeframe={})
    calc_ctx = CalculationContext(market_context=market_ctx)

    res = calc.calculate("EMPTY", calc_ctx)
    m = res.metrics
    assert np.isnan(m["DROC"])
    assert m["M_CUR"] is None
    assert m["SUSPECT"] == "N"

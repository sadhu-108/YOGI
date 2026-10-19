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
    calculate_dynamic_ema_signal,
    calculate_ema_up_count,
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


# ---------------- EMA UP COUNT ----------------
def test_ema_up_count_all_six_yes():
    # Requirement 1: Six "yes" states produce 6
    states = {tf: "yes" for tf in ("D", "W", "M", "Q", "H", "Y")}
    assert calculate_ema_up_count(states) == 6
    # Full 'EMA_*' keys must also resolve and yield 6
    full_states = {f"EMA_{tf}": "yes" for tf in ("D", "W", "M", "Q", "H", "Y")}
    assert calculate_ema_up_count(full_states) == 6


def test_ema_up_count_mixed_yes_and_upcut():
    # Requirement 2: Mixed "yes" and "upcut" states count both correctly
    states = {"D": "upcut", "W": "yes", "M": "upcut", "Q": "yes", "H": "upcut", "Y": "yes"}
    assert calculate_ema_up_count(states) == 6

    states_part = {"EMA_D": "upcut", "EMA_W": "upcut", "EMA_M": "yes", "EMA_Q": "no", "EMA_H": "downcut", "EMA_Y": "no"}
    assert calculate_ema_up_count(states_part) == 3


def test_ema_up_count_downcut_and_no_do_not_count():
    # Requirement 3: "downcut" and "no" states do not count
    states = {"D": "downcut", "W": "no", "M": "downcut", "Q": "no", "H": "downcut", "Y": "no"}
    assert calculate_ema_up_count(states) == 0


def test_ema_up_count_na_and_missing_do_not_count():
    # Requirement 4: "na" and missing timeframe results do not count
    states = {"D": "na", "W": None, "M": "na"}
    assert calculate_ema_up_count(states) == 0
    assert calculate_ema_up_count({}) == 0


def test_ema_up_count_all_non_up_states_produce_zero():
    # Requirement 5: All non-UP states produce 0
    states = {"D": "downcut", "W": "no", "M": "na", "Q": "unknown", "H": None, "Y": ""}
    assert calculate_ema_up_count(states) == 0


def test_ema_up_count_mixed_bullish_and_non_up_exact():
    # Requirement 6: A mixture of bullish and non-UP states produces exact expected count
    # 3 bullish ('yes', 'upcut'), 1 'na', 2 non-UP ('downcut', 'no')
    states = {
        "D": "yes",
        "W": "upcut",
        "M": "yes",
        "Q": "na",
        "H": "downcut",
        "Y": "no",
    }
    assert calculate_ema_up_count(states) == 3

    # 4 bullish, 2 completely omitted from mapping
    states_omitted = {
        "EMA_D": "yes",
        "EMA_W": "yes",
        "EMA_M": "yes",
        "EMA_Q": "upcut",
    }
    assert calculate_ema_up_count(states_omitted) == 4


# ---------------- CAGR ----------------
def test_cagr_5y_doubling():
    idx = pd.bdate_range("2021-08-13", "2026-08-13")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    assert abs(cagr_trailing(s, 5) - 14.8698) < 0.05


def test_cagr_n_zero_or_negative():
    idx = pd.bdate_range("2021-08-13", "2026-08-13")
    s = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    assert cagr_trailing(s, 0) is None
    assert cagr_trailing(s, -1) is None
    assert cagr_trailing(s, -5) is None


def test_cagr_none_or_empty_series():
    assert cagr_trailing(None, 3) is None
    assert cagr_trailing(pd.Series([], dtype=float), 3) is None
    empty_with_idx = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
    assert cagr_trailing(empty_with_idx, 1) is None


def test_cagr_insufficient_history():
    idx = pd.date_range("2025-01-01", "2025-06-01", freq="D")
    s = pd.Series(np.linspace(100, 150, len(idx)), index=idx)
    # Requested 3 years, but only 5 months exist
    assert cagr_trailing(s, 3) is None
    assert cagr_trailing(s, 1) is None


def test_cagr_negative_prices_safe():
    dates = pd.to_datetime(["2020-01-01", "2023-01-01"])
    # 1. Negative starting price
    s_neg_start = pd.Series([-100.0, 150.0], index=dates)
    assert cagr_trailing(s_neg_start, 3) is None

    # 2. Negative ending price with object dtype (Python float) -> must not raise TypeError
    s_neg_end_obj = pd.Series([100.0, -50.0], index=dates, dtype=object)
    assert cagr_trailing(s_neg_end_obj, 3) is None

    # 3. Negative ending price with float64 dtype -> must not return NaN or warn
    s_neg_end_np = pd.Series([100.0, -50.0], index=dates, dtype=float)
    assert cagr_trailing(s_neg_end_np, 3) is None


def test_cagr_zero_prices():
    dates = pd.to_datetime(["2020-01-01", "2023-01-01"])
    # Zero starting price -> division by zero avoidance -> None
    s_zero_start = pd.Series([0.0, 100.0], index=dates)
    assert cagr_trailing(s_zero_start, 3) is None

    # Zero ending price -> represents 100% total loss (-100.0%)
    s_zero_end = pd.Series([100.0, 0.0], index=dates)
    assert cagr_trailing(s_zero_end, 3) == -100.0
    assert cagr_trailing(s_zero_end, 1) == -100.0


def test_cagr_non_finite_inputs():
    dates = pd.to_datetime(["2020-01-01", "2023-01-01"])
    s_inf_start = pd.Series([np.inf, 100.0], index=dates)
    assert cagr_trailing(s_inf_start, 3) is None

    s_inf_end = pd.Series([100.0, np.inf], index=dates)
    assert cagr_trailing(s_inf_end, 3) is None

    s_nan_end = pd.Series([100.0, np.nan], index=dates)
    assert cagr_trailing(s_nan_end, 3) is None


def test_cagr_invalid_duration_types():
    """Verify non-integer, non-finite, boolean, or non-numeric n return None safely."""
    dates = pd.to_datetime(["2020-01-01", "2023-01-01"])
    s = pd.Series([100.0, 150.0], index=dates)

    assert cagr_trailing(s, float("nan")) is None
    assert cagr_trailing(s, float("inf")) is None
    assert cagr_trailing(s, -float("inf")) is None
    assert cagr_trailing(s, 2.5) is None
    assert cagr_trailing(s, "3") is None
    assert cagr_trailing(s, None) is None
    assert cagr_trailing(s, True) is None
    assert cagr_trailing(s, False) is None

    # NumPy integer must be accepted as valid integer duration
    np_cagr = cagr_trailing(s, np.int64(3))
    assert np_cagr is not None
    assert round(np_cagr, 2) == 14.47


def test_cagr_non_datetime_index():
    """Verify series with RangeIndex or string index return None safely without TypeError."""
    assert cagr_trailing(pd.Series([100.0, 150.0]), 1) is None
    assert cagr_trailing(pd.Series([100.0, 150.0], index=["A", "B"]), 1) is None
    assert cagr_trailing([100.0, 150.0], 1) is None


def test_cagr_single_element_series():
    """Verify single-element series returns None without crash."""
    s = pd.Series([100.0], index=pd.to_datetime(["2020-01-01"]))
    assert cagr_trailing(s, 1) is None


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


def test_half_block_prototype_vs_calendar_policies():
    """Verify half_block semantics under both prototype and calendar policies."""
    idx = pd.date_range("2024-01-01", "2026-08-13", freq="D")
    s = pd.Series(index=idx, dtype=float)

    # Set known prices across boundaries:
    # 2024: 100
    # 2025 H1 (Jun 30): 110
    # 2025 H2 (Dec 31): 120
    # 2026 H1 (Jun 30): 150
    # 2026 H2 to date (Aug 13): 180
    s.loc["2024-01-01":"2024-12-31"] = 100.0
    s.loc["2025-01-01":"2025-06-30"] = 110.0
    s.loc["2025-07-01":"2025-12-31"] = 120.0
    s.loc["2026-01-01":"2026-06-30"] = 150.0
    s.loc["2026-07-01":"2026-08-13"] = 180.0

    # Under Calendar policy:
    # Current date is August 2026 -> H2
    # Current H2 to date return: 180 / 150 (Jun 30 close) - 1 = +20.0%
    # H_P1 (H1 2026 return): 150 / 120 (Dec 31 close) - 1 = +25.0%
    # H_P2 (H2 2025 return): 120 / 110 (Jun 30 close) - 1 = +9.09%
    cal_res = half_block(s, policy="calendar")
    assert cal_res["H_CUR_KEY"] == "H2"
    assert cal_res["H_KEYS"] == "H2,H1,H2"
    assert round(cal_res["H_CUR"], 2) == 20.0
    assert round(cal_res["H_P1"], 2) == 25.0
    assert round(cal_res["H_P2"], 2) == 9.09
    assert round(cal_res["H2"], 2) == 20.0
    assert round(cal_res["H1"], 2) == 25.0

    # Under Prototype policy (2QE):
    proto_res = half_block(s, policy="prototype")
    assert proto_res["H_CUR_KEY"] == "H2"
    assert "H_CUR" in proto_res
    assert "H_P1" in proto_res


def test_half_block_calendar_h1_date():
    """Verify calendar half_block when evaluated inside H1 (e.g. March)."""
    idx = pd.date_range("2024-01-01", "2026-03-15", freq="D")
    s = pd.Series(index=idx, dtype=float)
    s.loc["2024-01-01":"2024-06-30"] = 100.0
    s.loc["2024-07-01":"2024-12-31"] = 110.0
    s.loc["2025-01-01":"2025-06-30"] = 120.0
    s.loc["2025-07-01":"2025-12-31"] = 130.0
    s.loc["2026-01-01":"2026-03-15"] = 143.0

    cal_res = half_block(s, policy="calendar")
    assert cal_res["H_CUR_KEY"] == "H1"
    assert cal_res["H_KEYS"] == "H1,H2,H1"
    # H_CUR: 143 / 130 (Dec 31 close) - 1 = +10.0%
    assert round(cal_res["H_CUR"], 2) == 10.0
    # H_P1: 130 / 120 (Jun 30 close) - 1 = +8.33%
    assert round(cal_res["H_P1"], 2) == 8.33
    # H_P2: 120 / 110 (Dec 31 close) - 1 = +9.09%
    assert round(cal_res["H_P2"], 2) == 9.09
    assert round(cal_res["H1"], 2) == 10.0
    assert round(cal_res["H2"], 2) == 8.33


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
    assert "EMA_UP_COUNT" in m
    assert isinstance(m["EMA_UP_COUNT"], int)
    assert 0 <= m["EMA_UP_COUNT"] <= 6
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
    assert m["EMA_UP_COUNT"] == 0


# ---------------- Dynamic EMA Condition Builder Tests ----------------

def _make_bars(closes, freq="D"):
    idx = pd.date_range(end="2026-08-15", periods=len(closes), freq=freq)
    return [
        MarketBar(
            timestamp=ts.to_pydatetime(),
            open=c * 0.99,
            high=c * 1.01,
            low=c * 0.98,
            close=float(c),
            volume=1000.0,
        )
        for ts, c in zip(idx, closes)
    ]


def test_dynamic_ema_signal_basic_up_and_down():
    # Monotonically rising prices: EMA(3) > EMA(5)
    rising_bars = _make_bars(list(range(10, 60)))
    res_up = calculate_dynamic_ema_signal(rising_bars, p1=3, p2=5, timeframe="D")
    assert res_up["is_up"] is True
    assert res_up["is_down"] is False
    assert res_up["ema_fast"] > res_up["ema_slow"]
    assert res_up["spread_pct"] > 0.0

    # Monotonically falling prices: EMA(3) < EMA(5)
    falling_bars = _make_bars(list(range(60, 10, -1)))
    res_down = calculate_dynamic_ema_signal(falling_bars, p1=3, p2=5, timeframe="D")
    assert res_down["is_up"] is False
    assert res_down["is_down"] is True
    assert res_down["ema_fast"] < res_down["ema_slow"]
    assert res_down["spread_pct"] < 0.0


def test_dynamic_ema_signal_upcut_and_downcut():
    # Build series where EMA3 was below EMA5, then crosses above on the final bar
    # 20 flat/falling bars at 100, then jump sharply to 150 on the final bar
    cross_up_closes = [100.0] * 30 + [95.0, 90.0, 85.0, 120.0]
    bars_up = _make_bars(cross_up_closes)
    res_upcut = calculate_dynamic_ema_signal(bars_up, p1=3, p2=5, timeframe="D")
    assert res_upcut["is_upcut"] is True
    assert res_upcut["is_up"] is True  # UPCUT mathematically satisfies UP
    assert res_upcut["is_down"] is False
    assert res_upcut["is_downcut"] is False

    # Reverse: series where EMA3 was above EMA5, then drops sharply on the final bar
    cross_down_closes = [100.0] * 30 + [105.0, 110.0, 115.0, 80.0]
    bars_down = _make_bars(cross_down_closes)
    res_downcut = calculate_dynamic_ema_signal(bars_down, p1=3, p2=5, timeframe="D")
    assert res_downcut["is_downcut"] is True
    assert res_downcut["is_down"] is True  # DOWNCUT mathematically satisfies DOWN
    assert res_downcut["is_up"] is False
    assert res_downcut["is_upcut"] is False


def test_dynamic_ema_signal_validation_distinct_and_positive_periods():
    bars = _make_bars(list(range(10, 40)))

    # Equal periods disallowed (Decision Gate A3)
    with pytest.raises(ValueError, match="must be distinct"):
        calculate_dynamic_ema_signal(bars, p1=5, p2=5)

    # Non-positive periods disallowed
    with pytest.raises(ValueError, match="positive integers"):
        calculate_dynamic_ema_signal(bars, p1=0, p2=5)

    with pytest.raises(ValueError, match="positive integers"):
        calculate_dynamic_ema_signal(bars, p1=5, p2=-1)


def test_dynamic_ema_signal_closed_candle_policy():
    # On higher timeframes (e.g. 'W'), iloc[-1] is the forming candle, iloc[-2] is the closed candle.
    # Case A: Cross occurred on closed candle iloc[-2], but iloc[-1] collapsed
    # Under closed_candle_only=True, is_upcut should be TRUE because iloc[-2] crossed!
    closes = [100.0] * 30 + [90.0, 85.0, 120.0, 50.0]
    # iloc[-4] = 90.0, iloc[-3] = 85.0, iloc[-2] = 120.0 (cross up occurred!), iloc[-1] = 50.0 (forming)
    bars = _make_bars(closes, freq="W")

    res_closed = calculate_dynamic_ema_signal(bars, p1=3, p2=5, timeframe="W", closed_candle_only=True)
    assert res_closed["is_upcut"] is True
    assert res_closed["is_up"] is True

    # Under closed_candle_only=False (evaluating forming bar iloc[-1] vs iloc[-2]), cross would be false
    res_forming = calculate_dynamic_ema_signal(bars, p1=3, p2=5, timeframe="W", closed_candle_only=False)
    assert res_forming["is_upcut"] is False


def test_dynamic_ema_signal_insufficient_bars():
    empty_res = calculate_dynamic_ema_signal([], p1=3, p2=5)
    assert empty_res["is_up"] is False
    assert empty_res["is_down"] is False
    assert empty_res["is_upcut"] is False
    assert empty_res["is_downcut"] is False
    assert empty_res["ema_fast"] is None

    single_res = calculate_dynamic_ema_signal(_make_bars([100.0]), p1=3, p2=5)
    assert single_res["is_up"] is False
    assert single_res["is_down"] is False


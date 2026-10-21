"""Trend Calculation Module — Multi-timeframe trend analysis, ROCs, EMAs, CAGRs, and DMI/ADX."""

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping, Optional, Sequence, Union
import numpy as np
import pandas as pd

from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule

ROC_DAYS = {"DROC": 1, "WROC": 5, "MROC": 21, "QROC": 63, "HROC": 126, "YROC": 252}
EMA_FAST, EMA_SLOW = 3, 5
EMA_TIMEFRAMES: tuple[str, ...] = ("D", "W", "M", "Q", "H", "Y")
EMA_UP_STATES: frozenset[str] = frozenset({"upcut", "yes"})
TF_RULES = {"W": "W", "M": "ME", "Q": "QE", "H": "2QE", "Y": "YE"}


def roc_trailing(close: pd.Series, n: int) -> float:
    """Calculate trailing Rate of Change over n trading bars: (cur / prev - 1) * 100."""
    c = close.dropna()
    if len(c) <= n:
        return np.nan
    prev, cur = c.iloc[-1 - n], c.iloc[-1]
    if pd.isna(prev) or prev == 0:
        return np.nan
    return float((cur / prev - 1.0) * 100.0)


def all_rocs(close: pd.Series) -> dict[str, float]:
    """Calculate trailing ROCs for standard windows: DROC, WROC, MROC, QROC, HROC, YROC."""
    return {k: roc_trailing(close, n) for k, n in ROC_DAYS.items()}


@dataclass(frozen=True)
class ROCResult:
    """Authoritative rolling Rate of Change (ROC) calculation result."""
    roc: pd.Series
    days: int = 21
    last_roc: Optional[float] = None


def calculate_roc_curve(
    close: pd.Series,
    days: int = 21,
) -> ROCResult:
    """Calculate rolling Rate of Change over time (% change over trailing n bars).

    Preserves verified prototype mathematics from yogi.core_math.formulas.roc_series:
    - c = close.dropna()
    - roc = ((c / c.shift(days) - 1.0) * 100.0)
    - If len(c) <= days or days <= 0: returns empty series and None last_roc.
    """
    if close is None or close.empty or days <= 0:
        empty_s = pd.Series([], dtype=float)
        return ROCResult(roc=empty_s, days=days, last_roc=None)

    c = close.dropna()
    if len(c) <= days:
        empty_s = pd.Series([], dtype=float, index=c.index[:0])
        return ROCResult(roc=empty_s, days=days, last_roc=None)

    shifted = c.shift(days)
    denom = shifted.copy()
    denom[denom <= 0] = np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        roc_series_full = (c / denom - 1.0) * 100.0

    valid = roc_series_full.dropna()
    last_val = float(valid.iloc[-1]) if not valid.empty else None

    return ROCResult(
        roc=roc_series_full,
        days=days,
        last_roc=last_val,
    )


def roc_series(close: pd.Series, days: int = 21) -> pd.Series:
    """Prototype-parity function returning dropped pd.Series matching formulas.py:roc_series."""
    return calculate_roc_curve(close, days=days).roc.dropna()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average matching TradingView/prototype convention (adjust=False)."""
    return series.ewm(span=span, adjust=False).mean()


def ema_status(bars: pd.Series, fast: int = EMA_FAST, slow: int = EMA_SLOW) -> str:
    """Determine EMA 3/5 cross status: 'upcut', 'downcut', 'yes', 'no', or 'na'."""
    b = bars.dropna()
    f, s = ema(b, fast).dropna(), ema(b, slow).dropna()
    n = min(len(f), len(s))
    if n < 2:
        return "na"
    cur, prev = float(f.iloc[-1] - s.iloc[-1]), float(f.iloc[-2] - s.iloc[-2])
    if prev <= 0 < cur:
        return "upcut"
    if prev >= 0 > cur:
        return "downcut"
    return "yes" if cur > 0 else "no"


def calculate_dynamic_ema_signal(
    bars: Union[Sequence[Any], pd.Series],
    p1: int,
    p2: int,
    timeframe: str = "D",
    closed_candle_only: Optional[bool] = None,
) -> dict[str, Any]:
    """Calculate dynamic EMA relationship, crossover signals, and strength spread.

    Parameters:
        bars: OHLCV MarketBar sequence, or pandas Series of closing prices.
        p1: First EMA period (positive integer).
        p2: Second EMA period (positive integer, p1 != p2).
        timeframe: Standard timeframe code ('D', 'W', 'M', 'Q', 'H', 'Y').
        closed_candle_only: If True, evaluates on completed candle (iloc[-2] vs iloc[-3]).
                           Defaults to True for higher timeframes (W, M, Q, H, Y) per
                           ADR-017 Decision A2, and False for Daily ('D').

    Returns:
        Dictionary containing:
        - state: Primary state label ("UP", "DOWN", "UPCUT", "DOWNCUT", or "na")
        - is_up: bool, True if EMA_P1 > EMA_P2 on evaluation bar (includes UPCUT)
        - is_down: bool, True if EMA_P1 < EMA_P2 on evaluation bar (includes DOWNCUT)
        - is_upcut: bool, True if EMA_P1 crossed from at-or-below to above EMA_P2
        - is_downcut: bool, True if EMA_P1 crossed from at-or-above to below EMA_P2
        - cur_diff: float, EMA_P1 - EMA_P2 on evaluation bar
        - prev_diff: float, EMA_P1 - EMA_P2 on previous bar
        - p1_val: float, EMA_P1 on evaluation bar
        - p2_val: float, EMA_P2 on evaluation bar
        - spread_pct: float, ((EMA_P1 - EMA_P2) / EMA_P2) * 100 on evaluation bar
    """
    empty_result = {
        "state": "na",
        "is_up": False,
        "is_down": False,
        "is_upcut": False,
        "is_downcut": False,
        "cur_diff": None,
        "prev_diff": None,
        "p1_val": None,
        "p2_val": None,
        "ema_fast": None,
        "ema_slow": None,
        "spread_pct": None,
    }

    if p1 <= 0 or p2 <= 0:
        raise ValueError(f"Both p1 and p2 must be positive integers >= 1 (got p1={p1}, p2={p2})")
    if p1 == p2:
        raise ValueError(f"P1 and P2 must be distinct positive integers (got p1={p1}, p2={p2})")

    if bars is None:
        return empty_result

    # Convert bars to closing series
    if isinstance(bars, pd.Series):
        c = bars.dropna()
    elif isinstance(bars, (list, tuple)):
        if not bars:
            return empty_result
        if hasattr(bars[0], "close"):
            c = pd.Series([float(b.close) for b in bars if b.close is not None and not pd.isna(b.close)])
        else:
            c = pd.Series([float(x) for x in bars if x is not None and not pd.isna(x)])
    else:
        return empty_result

    tf = (timeframe or "D").strip().upper()
    if closed_candle_only is None:
        closed_candle_only = (tf != "D")

    # Required bar count: need at least max(p1, p2) bars, plus lookback
    min_required = 3 if closed_candle_only else 2
    if len(c) < min_required:
        return empty_result

    # Compute exponential moving averages with adjust=False
    f_series = ema(c, p1).dropna()
    s_series = ema(c, p2).dropna()
    n = min(len(f_series), len(s_series))
    if n < min_required:
        return empty_result

    if closed_candle_only:
        # Last closed/completed candle is iloc[-2], candle before is iloc[-3]
        f_cur, s_cur = float(f_series.iloc[-2]), float(s_series.iloc[-2])
        f_prev, s_prev = float(f_series.iloc[-3]), float(s_series.iloc[-3])
    else:
        # Latest available candle is iloc[-1], candle before is iloc[-2]
        f_cur, s_cur = float(f_series.iloc[-1]), float(s_series.iloc[-1])
        f_prev, s_prev = float(f_series.iloc[-2]), float(s_series.iloc[-2])

    cur = f_cur - s_cur
    prev = f_prev - s_prev

    is_upcut = (prev <= 0.0 < cur)
    is_downcut = (prev >= 0.0 > cur)
    is_up = (cur > 0.0)
    is_down = (cur < 0.0)

    if is_upcut:
        state = "UPCUT"
    elif is_downcut:
        state = "DOWNCUT"
    elif is_up:
        state = "UP"
    elif is_down:
        state = "DOWN"
    else:
        state = "na"

    spread_pct = ((cur / s_cur) * 100.0) if s_cur != 0 else None

    return {
        "state": state,
        "is_up": is_up,
        "is_down": is_down,
        "is_upcut": is_upcut,
        "is_downcut": is_downcut,
        "cur_diff": cur,
        "prev_diff": prev,
        "p1_val": f_cur,
        "p2_val": s_cur,
        "ema_fast": f_cur,
        "ema_slow": s_cur,
        "spread_pct": spread_pct,
    }


VALID_ROC_TIMEFRAMES: dict[str, str] = {
    "current_month": "current_month",
    "last_month": "last_month",
    "last_to_last_month": "last_to_last_month",
    "current_quarter": "current_quarter",
    "last_quarter": "last_quarter",
    "current_half_year": "current_half_year",
    "ytd": "ytd",
    "current_year": "ytd",
    "last_year": "last_year",
    "preceding_last_4_years": "preceding_last_4_years",
    "last_4_years": "preceding_last_4_years",
    "4y": "preceding_last_4_years",
    "preceding_last_5_years": "preceding_last_5_years",
    "last_5_years": "preceding_last_5_years",
    "5y": "preceding_last_5_years",
    "avg_preceding_last_5_years": "avg_preceding_last_5_years",
    "avg_last_5_years": "avg_preceding_last_5_years",
    "avg5y": "avg_preceding_last_5_years",
    "3m": "current_quarter",
    "last_3_years": "last_3_years",
    "3y": "last_3_years",
}


def roc_trailing_years(close: pd.Series, n: int) -> Optional[float]:
    """Calculate ordinary Rate of Change (ROC) over trailing n calendar years."""
    if close is None or not isinstance(close, pd.Series):
        return None
    c = close.replace([np.inf, -np.inf], np.nan).dropna()
    if len(c) < 2 or not isinstance(c.index, pd.DatetimeIndex):
        return None
    try:
        latest = c.index[-1]
        target = latest - pd.DateOffset(years=int(n))
        past = c[c.index <= target]
        if len(past) == 0:
            return None
        start = float(past.iloc[-1])
        end = float(c.iloc[-1])
        if start <= 0 or not (np.isfinite(start) and np.isfinite(end)):
            return None
        val = ((end - start) / start) * 100.0
        return round(float(val), 2) if np.isfinite(val) else None
    except Exception:
        return None


def calculate_dynamic_roc(
    bars: Union[Sequence[Any], pd.Series],
    period: str,
) -> dict[str, Any]:
    """Calculate ordinary Rate of Change (ROC) percentage for a specified timeframe option.

    Formula:
        ROC(%) = ((P_end - P_start) / P_start) * 100.0

    Pricing convention:
        Uses daily closing prices, not opening prices.
        - Ongoing periods (current_month, current_quarter, current_half_year, ytd):
          P_start is the closing price of the first trading day of that period.
          P_end is the latest available daily closing price.
        - Completed periods (last_month, last_to_last_month, last_quarter, last_year):
          P_start is the closing price of the first trading day of that period.
          P_end is the closing price of the last trading day of that same period.
        - Preceding last 4 years (preceding_last_4_years):
          Single ordinary ROC from the first trading day close of (latest_year - 4)
          to the last trading day close of (latest_year - 1). Requires trading history
          in each completed year.
        - Average of preceding last 5 years (avg_preceding_last_5_years):
          Arithmetic mean of individual annual ROCs across the 5 completed calendar years
          (latest_year - 5 to latest_year - 1). If any year's ROC is unavailable, returns None.

    Returns:
        dict with keys:
            - roc: float or None
            - period: canonical period string
            - p_start: float or None
            - p_end: float or None
    """
    canon_period = VALID_ROC_TIMEFRAMES.get(str(period).strip().lower())
    if not canon_period:
        return {"roc": None, "period": period, "p_start": None, "p_end": None}

    # Normalize bars into chronological list of (timestamp, close)
    bar_tuples: list[tuple[datetime, float]] = []
    if isinstance(bars, pd.Series):
        for idx, val in bars.dropna().items():
            ts = pd.to_datetime(idx).to_pydatetime()
            try:
                c_val = float(val)
                if math.isfinite(c_val):
                    bar_tuples.append((ts, c_val))
            except (ValueError, TypeError):
                continue
    else:
        for b in bars:
            ts = getattr(b, "timestamp", None)
            c = getattr(b, "close", None)
            if ts is not None and c is not None:
                if not isinstance(ts, datetime):
                    ts = pd.to_datetime(ts).to_pydatetime()
                try:
                    c_val = float(c)
                    if math.isfinite(c_val):
                        bar_tuples.append((ts, c_val))
                except (ValueError, TypeError):
                    continue

    if not bar_tuples:
        return {"roc": None, "period": canon_period, "p_start": None, "p_end": None}

    bar_tuples.sort(key=lambda x: x[0])
    latest_ts, latest_close = bar_tuples[-1]
    ly = latest_ts.year
    lm = latest_ts.month

    def _calc_ordinary_roc(p_s: Optional[float], p_e: Optional[float]) -> Optional[float]:
        if p_s is None or p_e is None:
            return None
        if p_s <= 0.0 or not math.isfinite(p_s) or not math.isfinite(p_e):
            return None
        r = ((p_e - p_s) / p_s) * 100.0
        return round(r, 4) if math.isfinite(r) else None

    p_start: Optional[float] = None
    p_end: Optional[float] = None
    roc_val: Optional[float] = None

    if canon_period == "current_month":
        # Ongoing: first trading day close of current month -> latest close
        m_bars = [b for b in bar_tuples if b[0].year == ly and b[0].month == lm]
        if m_bars:
            p_start = m_bars[0][1]
            p_end = latest_close
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "last_month":
        # Completed: previous calendar month
        target_y = ly - 1 if lm == 1 else ly
        target_m = 12 if lm == 1 else lm - 1
        m_bars = [b for b in bar_tuples if b[0].year == target_y and b[0].month == target_m]
        if m_bars:
            p_start = m_bars[0][1]
            p_end = m_bars[-1][1]
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "last_to_last_month":
        # Completed: 2 calendar months ago
        if lm == 1:
            target_y = ly - 1
            target_m = 11
        elif lm == 2:
            target_y = ly - 1
            target_m = 12
        else:
            target_y = ly
            target_m = lm - 2
        m_bars = [b for b in bar_tuples if b[0].year == target_y and b[0].month == target_m]
        if m_bars:
            p_start = m_bars[0][1]
            p_end = m_bars[-1][1]
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "current_quarter":
        # Ongoing: first trading day close of current quarter -> latest close
        cur_q = (lm - 1) // 3 + 1
        q_bars = [b for b in bar_tuples if b[0].year == ly and (b[0].month - 1) // 3 + 1 == cur_q]
        if q_bars:
            p_start = q_bars[0][1]
            p_end = latest_close
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "last_quarter":
        # Completed: previous calendar quarter
        cur_q = (lm - 1) // 3 + 1
        target_y = ly - 1 if cur_q == 1 else ly
        target_q = 4 if cur_q == 1 else cur_q - 1
        q_bars = [b for b in bar_tuples if b[0].year == target_y and (b[0].month - 1) // 3 + 1 == target_q]
        if q_bars:
            p_start = q_bars[0][1]
            p_end = q_bars[-1][1]
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "current_half_year":
        # Ongoing: first trading day close of current half -> latest close
        cur_h = 1 if lm <= 6 else 2
        h_bars = [b for b in bar_tuples if b[0].year == ly and (1 if b[0].month <= 6 else 2) == cur_h]
        if h_bars:
            p_start = h_bars[0][1]
            p_end = latest_close
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "ytd":
        # Ongoing: first trading day close of current calendar year -> latest close
        y_bars = [b for b in bar_tuples if b[0].year == ly]
        if y_bars:
            p_start = y_bars[0][1]
            p_end = latest_close
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "last_year":
        # Completed: previous calendar year (ly - 1)
        target_y = ly - 1
        y_bars = [b for b in bar_tuples if b[0].year == target_y]
        if y_bars:
            p_start = y_bars[0][1]
            p_end = y_bars[-1][1]
            roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "preceding_last_4_years":
        # Completed: 4 calendar years preceding latest year: [ly - 4, ly - 1]
        start_y = ly - 4
        end_y = ly - 1
        has_all_years = True
        for yr in range(start_y, end_y + 1):
            if not any(b[0].year == yr for b in bar_tuples):
                has_all_years = False
                break
        if has_all_years:
            start_bars = [b for b in bar_tuples if b[0].year == start_y]
            end_bars = [b for b in bar_tuples if b[0].year == end_y]
            if start_bars and end_bars:
                p_start = start_bars[0][1]
                p_end = end_bars[-1][1]
                roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "preceding_last_5_years":
        # Completed: 5 calendar years preceding latest year: [ly - 5, ly - 1]
        # Preserves the distinction of 5Y total-period return over 5 completed years
        start_y = ly - 5
        end_y = ly - 1
        has_all_years = True
        for yr in range(start_y, end_y + 1):
            if not any(b[0].year == yr for b in bar_tuples):
                has_all_years = False
                break
        if has_all_years:
            start_bars = [b for b in bar_tuples if b[0].year == start_y]
            end_bars = [b for b in bar_tuples if b[0].year == end_y]
            if start_bars and end_bars:
                p_start = start_bars[0][1]
                p_end = end_bars[-1][1]
                roc_val = _calc_ordinary_roc(p_start, p_end)

    elif canon_period == "last_3_years":
        # 3 years: trailing or completed 3 calendar years [ly - 3, ly - 1]
        start_y = ly - 3
        end_y = ly - 1
        has_all_years = True
        for yr in range(start_y, end_y + 1):
            if not any(b[0].year == yr for b in bar_tuples):
                has_all_years = False
                break
        if has_all_years:
            start_bars = [b for b in bar_tuples if b[0].year == start_y]
            end_bars = [b for b in bar_tuples if b[0].year == end_y]
            if start_bars and end_bars:
                p_start = start_bars[0][1]
                p_end = end_bars[-1][1]
                roc_val = _calc_ordinary_roc(p_start, p_end)
        if roc_val is None:
            # Fallback to trailing 3 years from latest bar
            try:
                target_ts = latest_ts - timedelta(days=3 * 365)
                past_bars = [b for b in bar_tuples if b[0] <= target_ts]
                if past_bars:
                    p_start = past_bars[-1][1]
                    p_end = latest_close
                    roc_val = _calc_ordinary_roc(p_start, p_end)
            except Exception:
                pass

    elif canon_period == "avg_preceding_last_5_years":
        # Completed: 5 calendar years preceding latest year: [ly - 5, ly - 1]
        target_years = [ly - 5, ly - 4, ly - 3, ly - 2, ly - 1]
        annual_rocs: list[float] = []
        for yr in target_years:
            yr_bars = [b for b in bar_tuples if b[0].year == yr]
            if not yr_bars:
                annual_rocs = []
                break
            y_start = yr_bars[0][1]
            y_end = yr_bars[-1][1]
            y_roc = _calc_ordinary_roc(y_start, y_end)
            if y_roc is None:
                annual_rocs = []
                break
            annual_rocs.append(y_roc)

        if len(annual_rocs) == 5:
            roc_val = round(sum(annual_rocs) / 5.0, 4)
            p_start = None
            p_end = None

    return {
        "roc": roc_val,
        "period": canon_period,
        "p_start": p_start,
        "p_end": p_end,
    }


def per_tf_ema(close: pd.Series, bars_cache: Optional[Mapping[str, pd.Series]] = None) -> dict[str, str]:
    """Determine EMA 3/5 cross status for each standard timeframe."""
    out: dict[str, str] = {}
    c = close.dropna()
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        if bars_cache and tf in bars_cache and bars_cache[tf] is not None and not bars_cache[tf].empty:
            b = bars_cache[tf]
        elif tf == "D":
            b = c
        else:
            rule = TF_RULES.get(tf)
            b = c.resample(rule).last().dropna() if rule else c
        out[tf] = ema_status(b)
    return out


def calculate_ema_up_count(ema_states: Mapping[str, Any]) -> int:
    """Count the number of standard timeframes (D, W, M, Q, H, Y) in an EMA UP state.

    A timeframe counts as UP when its existing signal state is either:
      - 'upcut': a fresh bullish crossover
      - 'yes': an established bullish state

    Non-UP states ('downcut', 'no', 'na', None, missing, or any other value)
    contribute zero.

    Parameters:
        ema_states: Mapping containing timeframe states, keyed either by timeframe
                    code ('D', 'W', 'M', 'Q', 'H', 'Y') or by full metric name
                    ('EMA_D', 'EMA_W', 'EMA_M', 'EMA_Q', 'EMA_H', 'EMA_Y').

    Returns:
        Integer count from 0 through 6, inclusive.
    """
    count = 0
    for tf in EMA_TIMEFRAMES:
        state = ema_states.get(f"EMA_{tf}") if f"EMA_{tf}" in ema_states else ema_states.get(tf)
        if state is not None and str(state).strip().lower() in EMA_UP_STATES:
            count += 1
    return count


def monthly_block(close: pd.Series, bars: Optional[pd.Series] = None) -> dict[str, Any]:
    """Calculate month ROCs named by calendar month number (e.g. M8 = August) and stable aliases."""
    c = close.dropna()
    monthly = bars if bars is not None and not bars.empty else c.resample("ME").last().dropna()
    out: dict[str, Any] = {
        "M_CUR": None, "M_P1": None, "M_P2": None, "M_P3": None,
        "UPCUT": "na", "M_CUR_KEY": None, "M_KEYS": None,
    }
    if len(monthly) < 5:
        return out

    cur = float(c.iloc[-1])
    m = monthly
    last_dt = c.index[-1]

    def r(a, b):
        return None if (b is None or b == 0 or pd.isna(b)) else float((a / b - 1.0) * 100.0)

    vals = [
        r(cur, m.iloc[-2]),
        r(m.iloc[-2], m.iloc[-3]),
        r(m.iloc[-3], m.iloc[-4]),
        r(m.iloc[-4], m.iloc[-5]),
    ]
    out["M_CUR"], out["M_P1"], out["M_P2"], out["M_P3"] = vals

    keys = []
    for i in range(4):
        d = last_dt - pd.DateOffset(months=i)
        k = "M" + str(d.month)
        keys.append(k)
        out[k] = vals[i]
    out["M_CUR_KEY"] = keys[0]
    out["M_KEYS"] = ",".join(keys)

    e3 = ema(monthly, EMA_FAST).iloc[-1]
    e5 = ema(monthly, EMA_SLOW).iloc[-1]
    out["UPCUT"] = "YES" if e3 > e5 else "NO"
    return out


def quarter_block(close: pd.Series, bars: Optional[pd.Series] = None) -> dict[str, Any]:
    """Calculate quarter ROCs named by calendar quarter number (Q1..Q4) and stable aliases."""
    c = close.dropna()
    qb = bars if bars is not None and not bars.empty else c.resample("QE").last().dropna()
    out: dict[str, Any] = {
        "Q_CUR": None, "Q_P1": None, "Q_P2": None, "Q_P3": None,
        "Q_CUR_KEY": None, "Q_KEYS": None,
    }
    if len(qb) < 5:
        return out

    cur = float(c.iloc[-1])
    last_dt = c.index[-1]

    def r(a, b):
        return None if (b is None or b == 0 or pd.isna(b)) else float((a / b - 1.0) * 100.0)

    vals = [
        r(cur, qb.iloc[-2]),
        r(qb.iloc[-2], qb.iloc[-3]),
        r(qb.iloc[-3], qb.iloc[-4]),
        r(qb.iloc[-4], qb.iloc[-5]),
    ]
    out["Q_CUR"], out["Q_P1"], out["Q_P2"], out["Q_P3"] = vals

    keys = []
    for i in range(4):
        d = last_dt - pd.DateOffset(months=3 * i)
        k = "Q" + str((d.month - 1) // 3 + 1)
        keys.append(k)
        out[k] = vals[i]
    out["Q_CUR_KEY"] = keys[0]
    out["Q_KEYS"] = ",".join(keys)
    return out


def half_block(
    close: pd.Series,
    bars: Optional[pd.Series] = None,
    policy: str = "prototype",
) -> dict[str, Any]:
    """Calculate half-year ROCs named by calendar half (H1, H2) and stable aliases.

    Supported policies:
    - 'prototype' (default): Uses 2QE resampling (ending Mar 31 and Sep 30) for prototype parity.
    - 'calendar': Uses Calendar Half-Year (H1 = Jan–Jun ending Jun 30; H2 = Jul–Dec ending Dec 31).
    """
    c = close.dropna()
    if bars is not None and not bars.empty:
        hb = bars
    elif policy == "calendar":
        def _to_half_end(ts: Any) -> pd.Timestamp:
            pdt = pd.to_datetime(ts)
            return pd.Timestamp(year=pdt.year, month=6, day=30) if pdt.month <= 6 else pd.Timestamp(year=pdt.year, month=12, day=31)
        half_ends = c.index.map(_to_half_end)
        hb = c.groupby(half_ends).last().dropna()
    else:
        hb = c.resample("2QE").last().dropna()

    out: dict[str, Any] = {
        "H_CUR": None, "H_P1": None, "H_P2": None,
        "H_CUR_KEY": None, "H_KEYS": None,
    }
    if len(hb) < 4:
        return out

    cur = float(c.iloc[-1])
    last_dt = c.index[-1]

    def r(a, b):
        return None if (b is None or b == 0 or pd.isna(b)) else float((a / b - 1.0) * 100.0)

    vals = [
        r(cur, hb.iloc[-2]),
        r(hb.iloc[-2], hb.iloc[-3]),
        r(hb.iloc[-3], hb.iloc[-4]),
    ]
    out["H_CUR"], out["H_P1"], out["H_P2"] = vals

    keys = []
    for i in range(3):
        d = last_dt - pd.DateOffset(months=6 * i)
        k = "H1" if d.month <= 6 else "H2"
        keys.append(k)
        if k not in out or out[k] is None:
            out[k] = vals[i]
    out["H_CUR_KEY"] = keys[0]
    out["H_KEYS"] = ",".join(keys)
    return out


def year_return(close: pd.Series, year: int) -> Optional[float]:
    """Calculate calendar-year return (or YTD for current year)."""
    c = close.dropna()
    yr = c[c.index.year == year]
    if len(yr) == 0:
        return None
    prev = c[c.index.year == year - 1]
    base = prev.iloc[-1] if len(prev) else yr.iloc[0]
    if base == 0:
        return None
    return float((yr.iloc[-1] / base - 1.0) * 100.0)


def calendar_years(close: pd.Series, latest_year: int) -> dict[str, Any]:
    """Calculate returns for latest year and 5 prior years, plus Y_OLDER."""
    out: dict[str, Any] = {}
    for y in range(latest_year - 5, latest_year + 1):
        out["Y" + str(y)] = year_return(close, y)
    c = close.dropna()
    cut = pd.Timestamp(year=latest_year - 5, month=1, day=1)
    older = c[c.index < cut]
    if len(older) >= 2 and float(older.iloc[0]) > 0:
        out["Y_OLDER"] = round(float((older.iloc[-1] / older.iloc[0] - 1.0) * 100.0), 2)
    else:
        out["Y_OLDER"] = None
    return out


def cagr_trailing(close: pd.Series, n: int) -> Optional[float]:
    """Calculate annualized Compound Annual Growth Rate over trailing n years.

    Safely handles edge cases:
    - n <= 0, None, non-integer, non-finite, or non-numeric durations return None.
    - None, empty series, non-DatetimeIndex series, or insufficient history return None.
    - Negative starting or ending prices return None.
    - Non-finite inputs or intermediate calculations return None.
    - Zero ending price returns -100.0 (representing a 100% total loss).
    """
    if close is None or not isinstance(close, pd.Series):
        return None
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)):
        return None
    if n <= 0:
        return None

    c = close.replace([np.inf, -np.inf], np.nan).dropna()
    if len(c) < 2:
        return None
    if not isinstance(c.index, pd.DatetimeIndex):
        return None

    try:
        latest = c.index[-1]
        target = latest - pd.DateOffset(years=int(n))
    except (TypeError, ValueError, OverflowError):
        return None

    past = c[c.index <= target]
    if len(past) == 0:
        return None
    start = past.iloc[-1]
    end = c.iloc[-1]
    if not (np.isfinite(start) and np.isfinite(end)):
        return None
    if start <= 0 or end < 0:
        return None
    if end == 0:
        return -100.0
    try:
        val = ((end / start) ** (1.0 / float(n)) - 1.0) * 100.0
        return float(val) if np.isfinite(val) else None
    except (TypeError, ValueError, OverflowError):
        return None


def cagrs(close: pd.Series) -> dict[str, Optional[float]]:
    """Calculate trailing CAGRs for standard windows: 1, 3, 5, 7, 10 years."""
    return {"CAGR_" + str(n): cagr_trailing(close, n) for n in (1, 3, 5, 7, 10)}


def ath_diff(close: pd.Series) -> Optional[float]:
    """Calculate % drawdown from All-Time High: (current / max - 1) * 100."""
    c = close.dropna()
    if len(c) == 0:
        return None
    ath = c.max()
    return None if ath == 0 else float((c.iloc[-1] / ath - 1.0) * 100.0)


# ============================================================
# DMI / ADX — J. Welles Wilder Jr., 1978
# ============================================================

def _rma(x: pd.Series, period: int) -> pd.Series:
    """Wilder's running moving average, seeded with simple average of first period values."""
    v = x.astype("float64").to_numpy()
    n = len(v)
    out = np.full(n, np.nan)
    if n < period:
        return pd.Series(out, index=x.index, dtype="float64")
    head = v[:period]
    if not np.isfinite(head).any():
        return pd.Series(out, index=x.index, dtype="float64")
    seed = float(np.nanmean(head))
    out[period - 1] = seed
    run = seed
    for i in range(period, n):
        cur = v[i]
        if np.isnan(cur):
            cur = 0.0
        run = (run * (period - 1) + cur) / period
        out[i] = run
    return pd.Series(out, index=x.index, dtype="float64")


def dmi(bars: pd.DataFrame, period: int = 14, adx_period: Optional[int] = None) -> dict[str, Any]:
    """Wilder's DMI / ADX computed with TradingView ta.dmi / Pine Script RMA seeding.

    Scales down periods gracefully when bar history is short (e.g. yearly bars).
    """
    empty: dict[str, Any] = {
        "plus_di": None, "minus_di": None, "adx": None, "adxr": None,
        "period": None, "adx_period": None,
        "series": {
            "plus": pd.Series(dtype=float),
            "minus": pd.Series(dtype=float),
            "adx": pd.Series(dtype=float),
        },
    }
    if bars is None or len(bars) < 6:
        return empty
    if not {"high", "low", "close"} <= set(bars.columns):
        return empty
    if adx_period is None:
        adx_period = period

    room = max(2, (len(bars) - 2) // 2)
    period = min(period, room)
    adx_period = min(adx_period, room)

    h = bars["high"].astype("float64")
    l = bars["low"].astype("float64")
    c = bars["close"].astype("float64")

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=bars.index,
        dtype="float64",
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=bars.index,
        dtype="float64",
    )
    prev_c = c.shift()
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan

    atr = _rma(tr.iloc[1:], period)
    p_sm = _rma(plus_dm.iloc[1:], period)
    m_sm = _rma(minus_dm.iloc[1:], period)

    av = atr.to_numpy()
    pv = p_sm.to_numpy()
    mv = m_sm.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        p_arr = np.where(av > 0, 100.0 * pv / av, np.nan)
        m_arr = np.where(av > 0, 100.0 * mv / av, np.nan)
        den = p_arr + m_arr
        dx_arr = np.where(den > 0, 100.0 * np.abs(p_arr - m_arr) / den, np.nan)

    p_di = pd.Series(p_arr, index=atr.index, dtype="float64")
    m_di = pd.Series(m_arr, index=atr.index, dtype="float64")
    dx = pd.Series(dx_arr, index=atr.index, dtype="float64")
    adx = _rma(dx.dropna(), adx_period).reindex(atr.index)
    adxr = (adx + adx.shift(adx_period)) / 2.0

    last = lambda s: None if s.dropna().empty else round(float(s.dropna().iloc[-1]), 2)
    return {
        "plus_di": last(p_di),
        "minus_di": last(m_di),
        "adx": last(adx),
        "adxr": last(adxr),
        "period": int(period),
        "adx_period": int(adx_period),
        "series": {"plus": p_di.dropna(), "minus": m_di.dropna(), "adx": adx.dropna()},
    }


def dmi_state(
    plus_di: Optional[float],
    minus_di: Optional[float],
    adx: Optional[float],
    trend_min: float = 25.0,
    strong_min: float = 40.0,
) -> str:
    """Verbal classification of DMI/ADX strength: 'STRONG UP', 'UP TREND', 'up, weak', etc."""
    if plus_di is None or minus_di is None or adx is None:
        return "na"
    trending = adx >= trend_min
    strong = adx >= strong_min
    if plus_di > minus_di:
        return "STRONG UP" if strong else ("UP TREND" if trending else "up, weak")
    if minus_di > plus_di:
        return "STRONG DOWN" if strong else ("DOWN TREND" if trending else "down, weak")
    return "flat"


def dmi_settings(params: Optional[Mapping[str, Any]] = None) -> dict[str, tuple[int, int]]:
    """Determine DMI period and ADX smoothing settings per timeframe.

    Default is (5, 5) matching prototype candle_rules.DEFAULTS, overridable via parameters.
    """
    cfg = params or {}
    base_di = int(cfg.get("DMI_period", 5) or 5)
    base_adx = int(cfg.get("DMI_adx_smooth", base_di) or base_di)
    out: dict[str, tuple[int, int]] = {}
    for tf in ("D", "W", "M", "Q", "H", "Y"):
        di = int(cfg.get(f"DMI_di_len_{tf}", base_di) or base_di)
        ax = int(cfg.get(f"DMI_adx_smooth_{tf}", base_adx) or base_adx)
        out[tf] = (di, ax)
    return out


def dmi_block(daily: pd.DataFrame, rules: Mapping[str, str], period: Optional[int] = None) -> dict[str, Any]:
    """Calculate DMI metrics across multiple timeframes from daily OHLC bars."""
    cfg = dmi_settings()
    if period is not None:
        cfg = {k: (period, period) for k in cfg}
    out: dict[str, Any] = {}
    if daily is None or not {"high", "low", "close"} <= set(daily.columns):
        return out
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in daily.columns:
        agg["volume"] = "sum"

    def put(tf: str, bars: pd.DataFrame) -> None:
        di, ax = cfg.get(tf, (5, 5))
        d = dmi(bars, di, ax)
        out[f"DMIP_{tf}"] = d.get("period")
        out[f"DMIA_{tf}"] = d.get("adx_period")
        out[f"DIP_{tf}"] = d["plus_di"]
        out[f"DIM_{tf}"] = d["minus_di"]
        out[f"ADX_{tf}"] = d["adx"]
        out[f"DMI_{tf}"] = dmi_state(d["plus_di"], d["minus_di"], d["adx"])

    put("D", daily)
    for tf, rule in rules.items():
        if rule is None:
            continue
        try:
            put(tf, daily.resample(rule).agg(agg).dropna(subset=["close"]))
        except Exception:
            continue
    return out


class TrendCalculator(ICalcModule):
    """Calculates multi-timeframe trailing ROCs, calendar returns, EMAs, CAGRs, and DMI/ADX.

    Registered under key "trend" in RegistryHub.calculations.
    """

    name: str = "trend"
    required_timeframes: Sequence[str] = ("D", "W", "M", "Q", "H", "Y")

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute trend calculations on market bars."""
        daily_bars = context.market_context.get_bars("D")
        if not daily_bars:
            metrics: dict[str, Any] = {
                "DROC": np.nan, "WROC": np.nan, "MROC": np.nan,
                "QROC": np.nan, "HROC": np.nan, "YROC": np.nan,
                "M_CUR": None, "M_P1": None, "M_P2": None, "M_P3": None,
                "Q_CUR": None, "Q_P1": None, "Q_P2": None, "Q_P3": None,
                "H_CUR": None, "H_P1": None, "H_P2": None,
                "UPCUT": "na", "ATH_DIFF": None, "SUSPECT": "N",
                "EMA_UP_COUNT": 0,
            }
            return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

        close = pd.Series([b.close for b in daily_bars], index=[b.timestamp for b in daily_bars])
        ly = close.index[-1].year

        # Pre-extract timeframe closing series from MarketContext
        bars_cache: dict[str, pd.Series] = {"D": close}
        half_policy = str(context.parameters.get("half_year_policy", "prototype"))
        for tf in ("W", "M", "Q", "H", "Y"):
            tf_b = context.market_context.get_bars(tf)
            if tf_b:
                bars_cache[tf] = pd.Series([b.close for b in tf_b], index=[b.timestamp for b in tf_b])
            elif tf == "H" and half_policy == "calendar":
                def _to_h_end(ts: Any) -> pd.Timestamp:
                    pdt = pd.to_datetime(ts)
                    return pd.Timestamp(year=pdt.year, month=6, day=30) if pdt.month <= 6 else pd.Timestamp(year=pdt.year, month=12, day=31)
                h_ends = close.index.map(_to_h_end)
                bars_cache[tf] = close.groupby(h_ends).last().dropna()
            else:
                rule = TF_RULES.get(tf)
                bars_cache[tf] = close.resample(rule).last().dropna() if rule else close

        metrics: dict[str, Any] = {}

        # Trailing ROCs
        metrics.update(all_rocs(close))

        # Monthly calendar block
        mb = monthly_block(close, bars_cache.get("M"))
        for k, v in mb.items():
            if k.startswith("M") or k == "UPCUT":
                metrics[k] = v
        metrics["M_CUR"] = mb.get("M_CUR")
        metrics["M_P1"] = mb.get("M_P1")
        metrics["M_P2"] = mb.get("M_P2")
        metrics["M_P3"] = mb.get("M_P3")

        # Quarter and Half calendar blocks
        metrics.update(quarter_block(close, bars_cache.get("Q")))
        metrics.update(half_block(close, bars_cache.get("H"), policy=half_policy))

        # Calendar years & CAGRs
        metrics.update(calendar_years(close, ly))
        metrics.update(cagrs(close))
        metrics["ATH_DIFF"] = ath_diff(close)

        # 12 Canonical Ranking Periods (returns populated on all records):
        # 1. D: DROC
        # 2. W: WROC
        # 3. M: M_CUR (fallback MROC)
        # 4. Q: Q_CUR (fallback QROC)
        # 5. H: H_CUR (fallback HROC)
        # 6. Y: YROC
        # 7. YTD: Year to date return
        ytd_val = metrics.get(f"Y{ly}")
        if ytd_val is None:
            ytd_calc = calculate_dynamic_roc(daily_bars, "ytd")
            ytd_val = ytd_calc.get("roc")
        metrics["YTD"] = ytd_val
        metrics["ROC_YTD"] = ytd_val

        # 8. 3M: Last 3 months return (~63 trading days, matching QROC)
        metrics["3M"] = metrics.get("QROC")
        metrics["ROC_3M"] = metrics.get("QROC")

        # 9. 3Y: Last 3 years total return
        r_3y = roc_trailing_years(close, 3)
        metrics["3Y"] = r_3y
        metrics["ROC_3Y"] = r_3y

        # 10. 4Y: Preceding 4 completed calendar years
        res_4y = calculate_dynamic_roc(daily_bars, "preceding_last_4_years")
        metrics["4Y"] = res_4y.get("roc")
        metrics["ROC_4Y"] = metrics["4Y"]

        # 11. 5Y: Preceding 5 completed calendar years (total-period return)
        res_5y = calculate_dynamic_roc(daily_bars, "preceding_last_5_years")
        metrics["5Y"] = res_5y.get("roc") if res_5y.get("roc") is not None else roc_trailing_years(close, 5)
        metrics["ROC_5Y"] = metrics["5Y"]

        # 12. AVG5Y: Average of 5 completed calendar years
        res_avg5y = calculate_dynamic_roc(daily_bars, "avg_preceding_last_5_years")
        metrics["AVG5Y"] = res_avg5y.get("roc")
        metrics["ROC_AVG5Y"] = metrics["AVG5Y"]

        # Per-timeframe EMA 3/5
        tf_ema = per_tf_ema(close, bars_cache)
        for tf, st in tf_ema.items():
            metrics[f"EMA_{tf}"] = st
        metrics["EMA_UP_COUNT"] = calculate_ema_up_count(tf_ema)

        # Data Sanity flag: SUSPECT
        bad = False
        for k in ("DROC", "WROC", "M_CUR", "Q1", "H1", "YROC"):
            v = metrics.get(k)
            try:
                if v is not None and abs(float(v)) > 500:
                    bad = True
                    break
            except Exception:
                pass
        metrics["SUSPECT"] = "Y" if bad else "N"

        # DMI / ADX across timeframes (if OHLC available and not explicitly disabled)
        include_dmi = context.parameters.get("include_dmi", True)
        if include_dmi and daily_bars:
            # Check if high/low differ from close across daily bars
            has_varied_ohlc = any(b.high != b.low for b in daily_bars)
            if has_varied_ohlc:
                dmi_cfg = dmi_settings(context.parameters)
                for tf in self.required_timeframes:
                    tf_bars = context.market_context.get_bars(tf)
                    if tf_bars and len(tf_bars) >= 6:
                        tf_df = pd.DataFrame(
                            {
                                "high": [b.high for b in tf_bars],
                                "low": [b.low for b in tf_bars],
                                "close": [b.close for b in tf_bars],
                            },
                            index=[b.timestamp for b in tf_bars],
                        )
                        di_len, adx_len = dmi_cfg.get(tf, (5, 5))
                        d_res = dmi(tf_df, period=di_len, adx_period=adx_len)
                        metrics[f"DMIP_{tf}"] = d_res.get("period")
                        metrics[f"DMIA_{tf}"] = d_res.get("adx_period")
                        metrics[f"DIP_{tf}"] = d_res.get("plus_di")
                        metrics[f"DIM_{tf}"] = d_res.get("minus_di")
                        metrics[f"ADX_{tf}"] = d_res.get("adx")
                        metrics[f"DMI_{tf}"] = dmi_state(
                            d_res.get("plus_di"), d_res.get("minus_di"), d_res.get("adx")
                        )
                    else:
                        metrics[f"DMIP_{tf}"] = None
                        metrics[f"DMIA_{tf}"] = None
                        metrics[f"DIP_{tf}"] = None
                        metrics[f"DIM_{tf}"] = None
                        metrics[f"ADX_{tf}"] = None
                        metrics[f"DMI_{tf}"] = "na"

        return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

    def supports_condition(self, condition_type: str) -> bool:
        """Return True if this calculation module supports the specified dynamic condition type."""
        return condition_type in ("ema", "roc")

    def calculate_dynamic(
        self,
        symbol: str,
        rule: Any,
        context: CalculationContext,
    ) -> Any:
        """Execute on-demand dynamic indicator calculation for a symbol and rule."""
        c_type = getattr(rule, "condition_type", None)
        if c_type == "ema":
            tf = getattr(rule, "timeframe", None)
            p1 = getattr(rule, "p1", None)
            p2 = getattr(rule, "p2", None)
            params = getattr(rule, "params", {}) or {}
            if tf is None:
                tf = params.get("timeframe", "D")
            if p1 is None:
                p1 = params.get("p1")
            if p2 is None:
                p2 = params.get("p2")

            if p1 is None or p2 is None:
                return None

            tf_str = (tf or "D").strip().upper()
            bars = context.market_context.get_bars(tf_str)
            if not bars:
                return {
                    "state": "na",
                    "is_up": False,
                    "is_down": False,
                    "is_upcut": False,
                    "is_downcut": False,
                    "cur_diff": None,
                    "prev_diff": None,
                    "p1_val": None,
                    "p2_val": None,
                    "ema_fast": None,
                    "ema_slow": None,
                    "spread_pct": None,
                }
            return calculate_dynamic_ema_signal(bars, p1=int(p1), p2=int(p2), timeframe=tf_str)

        elif c_type == "roc":
            period = getattr(rule, "period", None)
            params = getattr(rule, "params", {}) or {}
            if period is None:
                period = params.get("period")
            if period is None and getattr(rule, "field", None):
                f = str(rule.field).strip()
                if f.upper().startswith("ROC_"):
                    period = f[4:].lower()

            if not period:
                return {"roc": None, "period": None, "p_start": None, "p_end": None}

            daily_bars = context.market_context.get_bars("D")
            if not daily_bars:
                return {"roc": None, "period": str(period), "p_start": None, "p_end": None}
            return calculate_dynamic_roc(daily_bars, period=str(period))

        return None



# =============================================================================
# Volume-Weighted & Price-Level Capabilities (VWAP, Average Price)
# =============================================================================

def calculate_vwap(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    close: Sequence[float] | pd.Series,
    volume: Optional[Sequence[Optional[float]] | pd.Series] = None,
) -> pd.Series:
    """Calculate cumulative Volume-Weighted Average Price matching prototype (routes.py:143-144):
        tp = (high + low + close) / 3.0
        vwap = cumsum(tp * volume) / cumsum(volume)
    Over the visible chart history window.
    """
    if volume is None:
        return pd.Series([], dtype=float)

    h = pd.Series(high, dtype=float) if not isinstance(high, pd.Series) else high.astype(float)
    l = pd.Series(low, dtype=float) if not isinstance(low, pd.Series) else low.astype(float)
    c = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    v = pd.Series(volume, dtype=float) if not isinstance(volume, pd.Series) else volume.astype(float)

    if len(c) == 0 or len(v) == 0:
        return pd.Series([], dtype=float)

    # Missing volume / zeros handled cleanly without division by zero
    v = v.fillna(0.0)
    if v.sum() == 0:
        return pd.Series([np.nan] * len(c), index=c.index, dtype=float)

    tp = (h + l + c) / 3.0
    cum_vol = v.cumsum()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = (tp * v).cumsum() / cum_vol.replace(0.0, np.nan)

    return vwap.astype(float)


def average_price(close: Sequence[float] | pd.Series) -> Optional[float]:
    """Calculate simple mean of close prices matching prototype (routes.py:232):
        avg = float(close.mean()) if len(close) else None
    """
    s = pd.Series(close, dtype=float).dropna()
    if len(s) == 0:
        return None
    return float(s.mean())


# =============================================================================
# Technical Oscillators (RSI, MACD, OBV, MFI)
# =============================================================================

@dataclass(frozen=True)
class RSIResult:
    """Authoritative Relative Strength Index computation result."""
    rsi: pd.Series
    last_rsi: Optional[float]


def calculate_rsi(
    close: Sequence[float] | pd.Series,
    period: int = 14,
) -> RSIResult:
    """Calculate Relative Strength Index matching prototype convention (routes.py:125-128):
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / loss))
    Uses simple rolling mean of gains and losses matching prototype.
    """
    s = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    if len(s) < period + 1 or period <= 0:
        empty = pd.Series([], dtype=float, index=s.index[:0])
        return RSIResult(rsi=empty, last_rsi=None)

    delta = s.diff()
    gain = delta.clip(lower=0.0).rolling(period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = gain / loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    last_val = float(rsi.iloc[-1]) if (not rsi.empty and not pd.isna(rsi.iloc[-1])) else None
    return RSIResult(rsi=rsi, last_rsi=last_val)


@dataclass(frozen=True)
class MACDResult:
    """Authoritative Moving Average Convergence Divergence computation result."""
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series
    last_macd: Optional[float]
    last_signal: Optional[float]
    last_histogram: Optional[float]


def calculate_macd(
    close: Sequence[float] | pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """Calculate MACD matching prototype convention (routes.py:129-130):
        macd = ema(close, fast_period) - ema(close, slow_period)
        signal = ema(macd, signal_period)
        histogram = macd - signal
    Reuses authoritative ema() function with adjust=False.
    """
    s = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    if len(s) < 2 or fast_period <= 0 or slow_period <= 0 or signal_period <= 0:
        empty = pd.Series([], dtype=float, index=s.index[:0])
        return MACDResult(
            macd=empty, signal=empty, histogram=empty,
            last_macd=None, last_signal=None, last_histogram=None,
        )

    fast_ema = ema(s, span=fast_period)
    slow_ema = ema(s, span=slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, span=signal_period)
    hist = macd_line - signal_line

    lm = float(macd_line.iloc[-1]) if (not macd_line.empty and not pd.isna(macd_line.iloc[-1])) else None
    ls = float(signal_line.iloc[-1]) if (not signal_line.empty and not pd.isna(signal_line.iloc[-1])) else None
    lh = float(hist.iloc[-1]) if (not hist.empty and not pd.isna(hist.iloc[-1])) else None

    return MACDResult(
        macd=macd_line,
        signal=signal_line,
        histogram=hist,
        last_macd=lm,
        last_signal=ls,
        last_histogram=lh,
    )


@dataclass(frozen=True)
class OBVResult:
    """Authoritative On-Balance Volume computation result."""
    obv: pd.Series
    last_obv: Optional[float]


def calculate_obv(
    close: Sequence[float] | pd.Series,
    volume: Optional[Sequence[Optional[float]] | pd.Series] = None,
) -> OBVResult:
    """Calculate On-Balance Volume matching prototype convention (routes.py:145-146):
        direction = 1 if diff > 0 else (-1 if diff < 0 else 0)
        obv = cumsum(direction * volume)
    """
    if volume is None:
        empty = pd.Series([], dtype=float)
        return OBVResult(obv=empty, last_obv=None)

    c = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    v = pd.Series(volume, dtype=float) if not isinstance(volume, pd.Series) else volume.astype(float)

    if len(c) == 0 or len(v) == 0:
        empty = pd.Series([], dtype=float)
        return OBVResult(obv=empty, last_obv=None)

    if v.isna().all():
        empty = pd.Series([np.nan] * len(c), index=c.index, dtype=float)
        return OBVResult(obv=empty, last_obv=None)

    diff = c.diff().fillna(0.0)
    direction = np.sign(diff)
    obv = (direction * v.fillna(0.0)).cumsum()

    lo = float(obv.iloc[-1]) if (not obv.empty and not pd.isna(obv.iloc[-1])) else None
    return OBVResult(obv=obv, last_obv=lo)


@dataclass(frozen=True)
class MFIResult:
    """Authoritative Money Flow Index computation result."""
    mfi: pd.Series
    last_mfi: Optional[float]


def calculate_mfi(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    close: Sequence[float] | pd.Series,
    volume: Optional[Sequence[Optional[float]] | pd.Series] = None,
    period: int = 14,
) -> MFIResult:
    """Calculate Money Flow Index matching prototype convention (formulas.py:597-606):
        tp = (high + low + close) / 3.0
        mf = tp * volume
        up = mf.where(tp > tp.shift(), 0.0).rolling(period).sum()
        dn = mf.where(tp < tp.shift(), 0.0).rolling(period).sum()
        ratio = up / dn
        mfi = 100 - (100 / (1 + ratio))
    """
    if volume is None:
        empty = pd.Series([], dtype=float)
        return MFIResult(mfi=empty, last_mfi=None)

    h = pd.Series(high, dtype=float) if not isinstance(high, pd.Series) else high.astype(float)
    l = pd.Series(low, dtype=float) if not isinstance(low, pd.Series) else low.astype(float)
    c = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    v = pd.Series(volume, dtype=float) if not isinstance(volume, pd.Series) else volume.astype(float)

    if len(c) < period or period <= 0 or len(v) == 0:
        empty = pd.Series([], dtype=float, index=c.index[:0])
        return MFIResult(mfi=empty, last_mfi=None)

    if v.isna().all() or (v.fillna(0.0).sum() == 0):
        empty = pd.Series([np.nan] * len(c), index=c.index, dtype=float)
        return MFIResult(mfi=empty, last_mfi=None)

    tp = (h + l + c) / 3.0
    mf = tp * v.fillna(0.0)
    up = mf.where(tp > tp.shift(), 0.0).rolling(period).sum()
    dn = mf.where(tp < tp.shift(), 0.0).rolling(period).sum()

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = up / dn
        mfi = 100.0 - (100.0 / (1.0 + ratio))

    lm = float(mfi.iloc[-1]) if (not mfi.empty and not pd.isna(mfi.iloc[-1])) else None
    return MFIResult(mfi=mfi, last_mfi=lm)

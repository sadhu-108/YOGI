"""Trend Calculation Module — Multi-timeframe trend analysis, ROCs, EMAs, CAGRs, and DMI/ADX."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
import numpy as np
import pandas as pd

from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule

ROC_DAYS = {"DROC": 1, "WROC": 5, "MROC": 21, "QROC": 63, "HROC": 126, "YROC": 252}
EMA_FAST, EMA_SLOW = 3, 5
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


def half_block(close: pd.Series, bars: Optional[pd.Series] = None) -> dict[str, Any]:
    """Calculate half-year ROCs named by calendar half (H1, H2) and stable aliases."""
    c = close.dropna()
    hb = bars if bars is not None and not bars.empty else c.resample("2QE").last().dropna()
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
    """Calculate annualized Compound Annual Growth Rate over trailing n years."""
    c = close.dropna()
    if len(c) == 0:
        return None
    latest = c.index[-1]
    target = latest - pd.DateOffset(years=n)
    past = c[c.index <= target]
    if len(past) == 0:
        return None
    start = past.iloc[-1]
    if start <= 0:
        return None
    return float(((c.iloc[-1] / start) ** (1.0 / n) - 1.0) * 100.0)


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
            }
            return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

        close = pd.Series([b.close for b in daily_bars], index=[b.timestamp for b in daily_bars])
        ly = close.index[-1].year

        # Pre-extract timeframe closing series from MarketContext
        bars_cache: dict[str, pd.Series] = {"D": close}
        for tf in ("W", "M", "Q", "H", "Y"):
            tf_b = context.market_context.get_bars(tf)
            if tf_b:
                bars_cache[tf] = pd.Series([b.close for b in tf_b], index=[b.timestamp for b in tf_b])
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
        metrics.update(half_block(close, bars_cache.get("H")))

        # Calendar years & CAGRs
        metrics.update(calendar_years(close, ly))
        metrics.update(cagrs(close))
        metrics["ATH_DIFF"] = ath_diff(close)

        # Per-timeframe EMA 3/5
        for tf, st in per_tf_ema(close, bars_cache).items():
            metrics[f"EMA_{tf}"] = st

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

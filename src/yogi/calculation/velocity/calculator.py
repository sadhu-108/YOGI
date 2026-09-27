"""Velocity Calculation Module — Momentum speeds, acceleration differentials, and sprint races."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
import numpy as np
import pandas as pd

from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule

SPRINT_WINDOWS = {"S4": 20, "S13": 63, "S26": 126, "S52": 252}  # trading days


def rolling_speed(close: pd.Series, days: int) -> Optional[float]:
    """Calculate % gain per week over a fixed trailing window (5 trading days per week)."""
    c = close.dropna()
    if len(c) <= days:
        return None
    past, now = c.iloc[-1 - days], c.iloc[-1]
    if past <= 0:
        return None
    gain = (now / past - 1.0) * 100.0
    return float(gain / (days / 5.0))


def faster(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Calculate how much faster price is moving vs its longer pace (%-points per week)."""
    if a is None or b is None:
        return None
    return round(a - b, 3)


def sprint_v2(close: pd.Series, weekly_closes: Optional[pd.Series] = None) -> dict[str, Any]:
    """Calculate rolling speeds (S4..S52), acceleration differentials, and weekly consistency."""
    out: dict[str, Any] = {}
    for k, d in SPRINT_WINDOWS.items():
        sp = rolling_speed(close, d)
        out[k] = None if sp is None else round(sp, 3)

    out["ACCEL_S"] = faster(out.get("S4"), out.get("S13"))
    out["ACCEL_L"] = faster(out.get("S4"), out.get("S52"))

    if weekly_closes is not None and len(weekly_closes.dropna()) >= 13:
        w = weekly_closes.dropna()
    else:
        w = close.dropna().resample("W").last().dropna()

    if len(w) >= 13:
        last12 = w.pct_change().dropna().iloc[-12:]
        out["SPR_CONSIST"] = round(float((last12 > 0).mean() * 100.0), 1)
    else:
        out["SPR_CONSIST"] = None

    return out


def _period_start(close: pd.Series, key: str, asof=None) -> Optional[pd.Timestamp]:
    """Determine the start timestamp of calendar period for sprint gain/speed."""
    close = close.dropna()
    if len(close) == 0:
        return None
    last = asof or close.index[-1]
    y, m = last.year, last.month
    if key == "M":
        start = pd.Timestamp(y, m, 1)
    elif key == "Q":
        start = pd.Timestamp(y, 3 * ((m - 1) // 3) + 1, 1)
    elif key == "H":
        start = pd.Timestamp(y, 1 if m <= 6 else 7, 1)
    elif key in ("Y", "YTD"):
        start = pd.Timestamp(y, 1, 1)
    elif key == "W":
        start = last - pd.Timedelta(days=last.weekday())
    else:
        return None
    return start


def sprint(close: pd.Series, key: str = "M") -> dict[str, Any]:
    """Calculate gain % since period start, weeks elapsed, and speed (%/week)."""
    close = close.dropna()
    if len(close) < 2:
        return {"gain": None, "weeks": None, "speed": None}
    start = _period_start(close, key)
    if start is None:
        return {"gain": None, "weeks": None, "speed": None}
    before = close[close.index < start]
    base = before.iloc[-1] if len(before) else close[close.index >= start].iloc[0]
    if base is None or base == 0 or pd.isna(base):
        return {"gain": None, "weeks": None, "speed": None}
    cur = close.iloc[-1]
    gain = (cur / base - 1.0) * 100.0
    days = max((close.index[-1] - start).days, 1)
    weeks = max(days / 7.0, 0.2)
    return {
        "gain": float(gain),
        "weeks": round(weeks, 2),
        "speed": float(gain / weeks),
    }


def sprint_block(close: pd.Series) -> dict[str, Any]:
    """Calculate sprint gain and speed for each standard timeframe."""
    out: dict[str, Any] = {}
    for k in ("W", "M", "Q", "H", "Y"):
        s = sprint(close, k)
        out["SPR_" + k] = None if s["gain"] is None else round(s["gain"], 2)
        out["SPD_" + k] = None if s["speed"] is None else round(s["speed"], 3)
    return out


def anchors_for(latest_year: int) -> dict[str, str]:
    """Derive anchor years from data date: current year + 5 preceding."""
    return {
        f"A{str(y)[-2:]}": f"{y}-01-01"
        for y in range(latest_year - 5, latest_year + 1)
    }


def anchored_sprint(close: pd.Series, anchor_date: str) -> Optional[float]:
    """Calculate cumulative % from a fixed anchor date."""
    c = close.dropna()
    if len(c) == 0:
        return None
    a = pd.Timestamp(anchor_date)
    before = c[c.index < a]
    if len(before) == 0:
        return None
    base = float(before.iloc[-1])
    if base <= 0:
        return None
    return round((float(c.iloc[-1]) / base - 1.0) * 100.0, 2)


def anchored_block(close: pd.Series) -> dict[str, Any]:
    """Calculate anchored sprint % for current year and 5 preceding years."""
    c = close.dropna()
    ly = c.index[-1].year if len(c) else pd.Timestamp.today().year
    out: dict[str, Any] = {}
    for k, d in anchors_for(ly).items():
        out["SPA_" + k] = anchored_sprint(c, d)
    return out


def calculate_anchored_curve(
    close: pd.Series,
    anchor_date: str,
    weekly: bool = True,
) -> list[dict[str, Any]]:
    """The race line: cumulative % return from fixed anchor date, week-by-week.

    Preserves verified prototype semantics from formulas.py:anchored_curve:
    - Base price is the last available close strictly prior to anchor_date.
    - If stock listed after anchor_date or base price <= 0, returns empty list [].
    - Weekly points are resampled from weekly close (last trading day of week).
    - Returns list of {"time": "YYYY-MM-DD", "value": cumulative_pct_return}.
    """
    c = close.dropna()
    if len(c) == 0:
        return []
    if weekly:
        c = c.resample("W").last().dropna()
    a = pd.Timestamp(anchor_date)
    before = c[c.index < a]
    if len(before) == 0:
        return []
    base = float(before.iloc[-1])
    if base <= 0:
        return []
    run = c[c.index >= a]
    return [
        {
            "time": str(t.date()),
            "value": round((float(v) / base - 1.0) * 100.0, 2),
        }
        for t, v in run.items()
    ]


anchored_curve = calculate_anchored_curve


@dataclass(frozen=True)
class SprintSpeedResult:
    """Authoritative rolling sprint speed calculation result."""
    speed: pd.Series
    weeks: int = 4
    last_speed: Optional[float] = None


def calculate_sprint_speed_curve(
    close: pd.Series,
    weeks: int = 4,
) -> SprintSpeedResult:
    """Calculate rolling sprint speed over time (%/week on a rolling window of weeks*5 trading days).

    Preserves verified prototype mathematics from yogi.core_math.formulas.sprint_series:
    - d = weeks * 5 (trading days)
    - If len(close.dropna()) <= d or weeks <= 0: returns empty series and None last_speed.
    - speed = ((c / c.shift(d) - 1.0) * 100.0) / weeks
    - First d elements are NaN; subsequent elements are %/week.
    """
    if close is None or close.empty or weeks <= 0:
        empty_s = pd.Series([], dtype=float)
        return SprintSpeedResult(speed=empty_s, weeks=weeks, last_speed=None)

    c = close.dropna()
    d = weeks * 5
    if len(c) <= d:
        empty_s = pd.Series([], dtype=float, index=c.index[:0])
        return SprintSpeedResult(speed=empty_s, weeks=weeks, last_speed=None)

    shifted = c.shift(d)
    denom = shifted.copy()
    denom[denom <= 0] = np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        ret = (c / denom - 1.0) * 100.0
        speed_series = ret / float(weeks)

    valid = speed_series.dropna()
    last_val = float(valid.iloc[-1]) if not valid.empty else None

    return SprintSpeedResult(
        speed=speed_series,
        weeks=weeks,
        last_speed=last_val,
    )


def sprint_series(close: pd.Series, weeks: int = 4) -> pd.Series:
    """Prototype-parity function returning pd.Series matching formulas.py:sprint_series."""
    return calculate_sprint_speed_curve(close, weeks=weeks).speed


@dataclass(frozen=True)
class AccelerationResult:
    """Authoritative rolling acceleration calculation result."""
    accel: pd.Series
    short_weeks: int = 4
    long_weeks: int = 52
    last_accel: Optional[float] = None


def calculate_acceleration_curve(
    close: pd.Series,
    short_weeks: int = 4,
    long_weeks: int = 52,
) -> AccelerationResult:
    """Calculate rolling acceleration over time (short-window speed minus long-window speed).

    Preserves verified prototype mathematics from yogi.core_math.formulas.accel_series:
    - a = sprint_series(close, short_weeks)
    - b = sprint_series(close, long_weeks)
    - accel = a - b
    """
    if close is None or close.empty or short_weeks <= 0 or long_weeks <= 0:
        empty_s = pd.Series([], dtype=float)
        return AccelerationResult(
            accel=empty_s,
            short_weeks=short_weeks,
            long_weeks=long_weeks,
            last_accel=None,
        )

    res_short = calculate_sprint_speed_curve(close, weeks=short_weeks)
    res_long = calculate_sprint_speed_curve(close, weeks=long_weeks)

    if res_short.speed.empty or res_long.speed.empty:
        empty_s = pd.Series([], dtype=float, index=close.index[:0])
        return AccelerationResult(
            accel=empty_s,
            short_weeks=short_weeks,
            long_weeks=long_weeks,
            last_accel=None,
        )

    accel_series_full = res_short.speed - res_long.speed
    valid = accel_series_full.dropna()
    last_val = float(valid.iloc[-1]) if not valid.empty else None

    return AccelerationResult(
        accel=accel_series_full,
        short_weeks=short_weeks,
        long_weeks=long_weeks,
        last_accel=last_val,
    )


def accel_series(close: pd.Series, short_w: int = 4, long_w: int = 52) -> pd.Series:
    """Prototype-parity function returning dropped pd.Series matching formulas.py:accel_series."""
    res = calculate_acceleration_curve(close, short_weeks=short_w, long_weeks=long_w)
    return res.accel.dropna()


class VelocityCalculator(ICalcModule):
    """Calculates rolling speeds, acceleration, period sprints, and anchored sprints.

    Registered under key "velocity" in RegistryHub.calculations.
    """

    name: str = "velocity"
    required_timeframes: Sequence[str] = ("D", "W")

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute velocity calculation on market bars."""
        daily_bars = context.market_context.get_bars("D")
        if not daily_bars or len(daily_bars) < 2:
            metrics: dict[str, Any] = {
                "S4": None, "S13": None, "S26": None, "S52": None,
                "ACCEL_S": None, "ACCEL_L": None, "SPR_CONSIST": None,
                "SPR_W": None, "SPD_W": None, "SPR_M": None, "SPD_M": None,
                "SPR_Q": None, "SPD_Q": None, "SPR_H": None, "SPD_H": None,
                "SPR_Y": None, "SPD_Y": None,
            }
            return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

        close = pd.Series([b.close for b in daily_bars], index=[b.timestamp for b in daily_bars])
        weekly_bars = context.market_context.get_bars("W")
        weekly_closes = (
            pd.Series([b.close for b in weekly_bars], index=[b.timestamp for b in weekly_bars])
            if weekly_bars
            else None
        )

        metrics = {}
        metrics.update(sprint_block(close))
        metrics.update(sprint_v2(close, weekly_closes=weekly_closes))
        metrics.update(anchored_block(close))

        return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

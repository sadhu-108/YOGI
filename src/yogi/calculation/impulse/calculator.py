"""Impulse Calculation Module — Ram's 50% recovery rule and swing analysis."""

from typing import Any, Mapping, Optional, Sequence
import numpy as np
import pandas as pd

from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule


def _zigzag(close: pd.Series, pct: float = 3.0) -> list[tuple[int, float, str]]:
    """Identify swing pivots via a percentage reversal filter.

    Returns a list of tuples: [(pos_idx, price, 'H'|'L'), ...].
    """
    v = [float(x) for x in close.values]
    n = len(v)
    if n < 3:
        return []
    piv: list[tuple[int, float, str]] = []
    direction = 0  # 0 unknown, +1 rising, -1 falling
    hi_i = lo_i = 0
    hi_v = lo_v = v[0]

    for i in range(1, n):
        x = v[i]
        if x > hi_v:
            hi_v, hi_i = x, i
        if x < lo_v:
            lo_v, lo_i = x, i
        if direction >= 0 and hi_v > 0 and (hi_v - x) / hi_v * 100.0 >= pct:
            piv.append((hi_i, hi_v, "H"))
            direction = -1
            lo_v, lo_i = x, i
        elif direction <= 0 and lo_v > 0 and (x - lo_v) / lo_v * 100.0 >= pct:
            piv.append((lo_i, lo_v, "L"))
            direction = 1
            hi_v, hi_i = x, i

    # provisional final pivot = the running extreme of the leg in progress
    if direction >= 0:
        piv.append((hi_i, hi_v, "H"))
    else:
        piv.append((lo_i, lo_v, "L"))

    # drop duplicates / keep alternating
    out: list[tuple[int, float, str]] = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == "H" and p[1] >= out[-1][1]) or (p[2] == "L" and p[1] <= out[-1][1]):
                out[-1] = p
            continue
        out.append(p)
    return out


def impulse_correction(close: pd.Series, lookback: int = 120, pct: float = 3.0) -> dict[str, Any]:
    """Calculate Impulse (IP) vs Correction (CR) according to Ram's 50% recovery rule.

    IMPULSE (IP): After a fall, price climbs back to prior high in <= 50% of the fall's duration.
    Rising but slower than 50% = 'up'.
    Falling now = 'CR'.
    Insufficient history = 'na'.
    """
    c = close.dropna()
    if len(c) < 10:
        return {"state": "na", "legPct": None, "legBars": None, "ratio": None}

    w = c.iloc[-lookback:] if len(c) > lookback else c
    piv = _zigzag(w, pct)
    if len(piv) < 2:
        return {"state": "na", "legPct": None, "legBars": None, "ratio": None}

    (si, sv, _), (ei, ev, _) = piv[-2], piv[-1]
    legBars = max(ei - si, 1)
    legPct = (ev / sv - 1.0) * 100.0 if sv else None

    if ev < sv:  # falling now -> correction
        return {
            "state": "CR",
            "legPct": None if legPct is None else round(legPct, 2),
            "legBars": int(legBars),
            "ratio": None,
        }

    if len(piv) < 3:
        return {
            "state": "up",
            "legPct": None if legPct is None else round(legPct, 2),
            "legBars": int(legBars),
            "ratio": None,
        }

    pi, pv, _ = piv[-3]  # the high before the fall
    fallBars = max(si - pi, 1)
    seg = w.iloc[si : ei + 1]
    recov = seg[seg >= pv]  # first bar back at the old high

    if len(recov) == 0:
        return {
            "state": "up",
            "legPct": None if legPct is None else round(legPct, 2),
            "legBars": int(legBars),
            "ratio": None,
            "fallPct": round((sv / pv - 1.0) * 100.0, 2) if pv else None,
            "fallBars": int(fallBars),
        }

    recovBars = max(w.index.get_loc(recov.index[0]) - si, 1)
    ratio = recovBars / fallBars
    return {
        "state": "IP" if ratio <= 0.5 else "up",
        "legPct": None if legPct is None else round(legPct, 2),
        "legBars": int(legBars),
        "recovBars": int(recovBars),
        "ratio": round(ratio, 2),
        "fallPct": round((sv / pv - 1.0) * 100.0, 2) if pv else None,
        "fallBars": int(fallBars),
    }


class ImpulseCalculator(ICalcModule):
    """Calculates impulse/correction states, swing recovery speed, and leg metrics.

    Registered under key "impulse" in RegistryHub.calculations.
    """

    name: str = "impulse"
    required_timeframes: Sequence[str] = ("D",)

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute impulse/correction evaluation on daily market bars."""
        lookback = int(context.parameters.get("impulse_lookback", 120))
        pct = float(context.parameters.get("impulse_pct", 3.0))

        daily_bars = context.market_context.get_bars("D")
        if not daily_bars or len(daily_bars) < 10:
            metrics: dict[str, Any] = {
                "IC": "na",
                "IC_PCT": None,
                "IC_BARS": None,
                "IC_RATIO": None,
                "IC_FALL_PCT": None,
                "IC_FALL_BARS": None,
                "IC_RECOV_BARS": None,
            }
            return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

        close = pd.Series([b.close for b in daily_bars], index=[b.timestamp for b in daily_bars])
        ic = impulse_correction(close, lookback=lookback, pct=pct)

        metrics = {
            "IC": ic.get("state", "na"),
            "IC_PCT": ic.get("legPct"),
            "IC_BARS": ic.get("legBars"),
            "IC_RATIO": ic.get("ratio"),
            "IC_FALL_PCT": ic.get("fallPct"),
            "IC_FALL_BARS": ic.get("fallBars"),
            "IC_RECOV_BARS": ic.get("recovBars"),
        }
        return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

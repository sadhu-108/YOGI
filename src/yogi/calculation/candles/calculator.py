"""Candlestick Theory / Pattern Engine — Multi-timeframe shape & pattern recognition.

Ported with strict parity from prototype yogi/theories/candles.py.
Computes 38 fields per timeframe (with volume, 35 without) across 6 standard timeframes:
CD_ (Daily), CW_ (Weekly), CM_ (Monthly), CQ_ (Quarterly), CH_ (Half-Yearly), CY_ (Yearly).
Total: 228 fields (210 without volume).
"""

import math
from typing import Any, Mapping, Optional, Sequence

from yogi.calculation.candles.rules import DEFAULT_CANDLE_RULES
from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule
from yogi.core.contracts.market_data import MarketBar
from yogi.timeframe.engine import resample_bars

TIMEFRAME_PREFIXES: Mapping[str, str] = {
    "D": "CD_",
    "W": "CW_",
    "M": "CM_",
    "Q": "CQ_",
    "H": "CH_",
    "Y": "CY_",
}


def calculate_candle_fields(
    bars: Optional[Sequence[MarketBar]],
    prefix: str = "",
    rules: Optional[Mapping[str, float]] = None,
) -> dict[str, Any]:
    """Calculate single-timeframe candle shape metrics and pattern flags.

    Strictly preserves prototype yogi/theories/candles.py:candle_fields semantics:
    - Minimum 3 valid bars required; otherwise returns empty dict {}.
    - Bars with null/NaN in open, high, low, close are ignored.
    - Produces 35 price-action fields + 3 volume fields (if volume present).
    - Pattern flags are formatted as uppercase strings 'Y' or 'N'.
    """
    p = prefix
    out: dict[str, Any] = {}
    R = dict(DEFAULT_CANDLE_RULES)
    if rules is not None:
        R.update(rules)

    if bars is None or len(bars) < 3:
        return out

    # Filter bars with valid OHLC
    valid_bars: list[MarketBar] = []
    for b in bars:
        if (
            b.open is not None
            and not math.isnan(b.open)
            and b.high is not None
            and not math.isnan(b.high)
            and b.low is not None
            and not math.isnan(b.low)
            and b.close is not None
            and not math.isnan(b.close)
        ):
            valid_bars.append(b)

    if len(valid_bars) < 3:
        return out

    c = valid_bars[-1]
    prev = valid_bars[-2]
    prev2 = valid_bars[-3]

    o, h, l, cl = float(c.open), float(c.high), float(c.low), float(c.close)
    rng = h - l
    body = abs(cl - o)
    up_wick = h - max(o, cl)
    dn_wick = min(o, cl) - l

    out[p + "O"] = round(o, 2)
    out[p + "H"] = round(h, 2)
    out[p + "L"] = round(l, 2)
    out[p + "C"] = round(cl, 2)
    out[p + "BODY"] = round(body, 2)
    out[p + "UPWICK"] = round(up_wick, 2)
    out[p + "DNWICK"] = round(dn_wick, 2)
    out[p + "RANGE_PCT"] = round(rng / l * 100.0, 2) if l != 0 else None
    out[p + "BODY_PCT"] = round(body / rng * 100.0, 2) if rng != 0 else None
    out[p + "UPWICK_PCT"] = round(up_wick / rng * 100.0, 2) if rng != 0 else None
    out[p + "DNWICK_PCT"] = round(dn_wick / rng * 100.0, 2) if rng != 0 else None
    out[p + "GAP_PCT"] = (
        round((o / float(prev.close) - 1.0) * 100.0, 2)
        if float(prev.close) != 0
        else None
    )
    out[p + "CLOSE_POS"] = round((cl - l) / rng * 100.0, 2) if rng != 0 else None  # 100 = closed at high
    out[p + "PREV_H"] = round(float(prev.high), 2)
    out[p + "PREV_L"] = round(float(prev.low), 2)
    out[p + "GREEN"] = "Y" if cl > o else "N"

    # ---- pattern flags (Y/N so rules read plainly) ----
    ph, pl = float(prev.high), float(prev.low)
    po, pc = float(prev.open), float(prev.close)
    prng = ph - pl

    out[p + "BREAKOUT"] = "Y" if cl > ph else "N"  # closed above prior high
    out[p + "BREAKDOWN"] = "Y" if cl < pl else "N"
    out[p + "INSIDE"] = "Y" if (h <= ph and l >= pl) else "N"  # inside bar
    out[p + "OUTSIDE"] = "Y" if (h > ph and l < pl) else "N"  # outside/engulfing range

    full = R.get("ENGULF_require_full_body", 1.0) >= 1.0
    if full:
        out[p + "BULL_ENGULF"] = "Y" if (cl > o and pc < po and cl >= po and o <= pc) else "N"
        out[p + "BEAR_ENGULF"] = "Y" if (cl < o and pc > po and cl <= po and o >= pc) else "N"
    else:
        out[p + "BULL_ENGULF"] = "Y" if (cl > o and h > ph and l < pl) else "N"
        out[p + "BEAR_ENGULF"] = "Y" if (cl < o and h > ph and l < pl) else "N"

    out[p + "DOJI"] = "Y" if (rng != 0 and body / rng * 100.0 < R["DOJI_body_pct_max"]) else "N"

    # Hammer / shooting star measured against the RANGE (works even when the body
    # is zero, which the naive body-multiple rule cannot handle).
    out[p + "HAMMER"] = (
        "Y"
        if (
            rng != 0
            and dn_wick / rng * 100.0 >= R["HAMMER_dnwick_pct_min"]
            and up_wick / rng * 100.0 <= R["HAMMER_upwick_pct_max"]
        )
        else "N"
    )
    out[p + "SHOOTSTAR"] = (
        "Y"
        if (
            rng != 0
            and up_wick / rng * 100.0 >= R["SHOOTSTAR_upwick_pct_min"]
            and dn_wick / rng * 100.0 <= R["SHOOTSTAR_dnwick_pct_max"]
        )
        else "N"
    )
    out[p + "MARUBOZU"] = "Y" if (rng != 0 and body / rng * 100.0 > R["MARUBOZU_body_pct_min"]) else "N"
    out[p + "NR"] = "Y" if (prng != 0 and rng < prng) else "N"  # narrower range than before
    out[p + "WR"] = "Y" if (prng != 0 and rng > prng) else "N"  # wider range
    out[p + "HIGHER_HIGH"] = "Y" if h > ph else "N"
    out[p + "HIGHER_LOW"] = "Y" if l > pl else "N"
    out[p + "THREE_UP"] = "Y" if (cl > o and pc > po and float(prev2.close) > float(prev2.open)) else "N"
    out[p + "THREE_DN"] = "Y" if (cl < o and pc < po and float(prev2.close) < float(prev2.open)) else "N"

    cp = out.get(p + "CLOSE_POS")
    out[p + "CLOSE_STRONG"] = "Y" if (cp is not None and cp >= R["CLOSE_STRONG_pct"]) else "N"
    out[p + "CLOSE_WEAK"] = "Y" if (cp is not None and cp <= R["CLOSE_WEAK_pct"]) else "N"
    rp = out.get(p + "RANGE_PCT")
    out[p + "BIG_RANGE"] = "Y" if (rp is not None and rp >= R["BIG_RANGE_pct"]) else "N"

    # Volume metrics if available on the latest candle
    if c.volume is not None and not (isinstance(c.volume, float) and math.isnan(c.volume)):
        v = float(c.volume)
        vol_bars = [
            float(b.volume)
            for b in valid_bars[-20:]
            if b.volume is not None and not math.isnan(float(b.volume))
        ]
        av = sum(vol_bars) / len(vol_bars) if vol_bars else 0.0
        out[p + "VOL"] = round(v, 0)
        out[p + "VOL_X"] = round(v / av, 2) if av > 0 else None  # volume vs 20-bar average
        out[p + "VOL_SPIKE"] = "Y" if (av > 0 and v / av >= R["VOL_SPIKE_x"]) else "N"

    return out


class CandleCalculator(ICalcModule):
    """Calculates candlestick shape metrics and pattern flags across all standard timeframes.

    Registered under key "candles" in RegistryHub.calculations.
    """

    name: str = "candles"
    required_timeframes: Sequence[str] = ("D", "W", "M", "Q", "H", "Y")

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute candlestick theory calculations across all configured timeframes."""
        rules_override = context.parameters.get("candle_rules") if context.parameters else None

        metrics: dict[str, Any] = {}
        daily_bars = context.market_context.get_bars("D")

        for tf in self.required_timeframes:
            prefix = TIMEFRAME_PREFIXES.get(tf, f"C{tf}_")
            bars = context.market_context.get_bars(tf)

            # If higher-timeframe bars are not pre-synthesized in MarketContext, resample daily bars
            if (not bars or len(bars) == 0) and tf != "D" and daily_bars and len(daily_bars) > 0:
                try:
                    bars = resample_bars(daily_bars, tf)
                except Exception:
                    bars = ()

            tf_fields = calculate_candle_fields(bars, prefix=prefix, rules=rules_override)
            metrics.update(tf_fields)

        return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)

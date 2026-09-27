"""Bands Calculation Module — Envelope and price boundary analysis."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
import numpy as np
import pandas as pd

from yogi.core.contracts.calculation import CalculationContext, CalculationResult, ICalcModule


@dataclass(frozen=True)
class BandEnvelopeResult:
    """Authoritative rolling band envelope computation result."""
    basis: pd.Series
    upper: Optional[pd.Series]
    lower: Optional[pd.Series]
    last_basis: Optional[float]
    last_upper: Optional[float]
    last_lower: Optional[float]


def calculate_band_envelope(
    closes: Sequence[float],
    band_frac: Optional[float] = None,
    basis_window: int = 20,
) -> BandEnvelopeResult:
    """Calculate authoritative rolling band envelope series and latest levels.

    Preserves verified YOGI band envelope mathematics:
    - If len(closes) < 3: returns empty/None series and levels.
    - Basis window: bw = basis_window if len(closes) >= basis_window else max(3, len(closes) // 2)
    - Min periods: min_periods = max(2, bw // 2)
    - Basis = SMA(closes, bw, min_periods=min_periods)
    - If band_frac is valid and > 0:
        Upper = Basis * (1.0 + band_frac)
        Lower = Basis * (1.0 - band_frac)
    - Otherwise:
        Upper = None, Lower = None
    """
    n_bars = len(closes)
    if n_bars < 3:
        empty_s = pd.Series([], dtype=float)
        return BandEnvelopeResult(
            basis=empty_s,
            upper=None,
            lower=None,
            last_basis=None,
            last_upper=None,
            last_lower=None,
        )

    bw = basis_window if n_bars >= basis_window else max(3, n_bars // 2)
    s = pd.Series(closes, dtype=float)
    basis_series = s.rolling(bw, min_periods=max(2, bw // 2)).mean()

    last_val = basis_series.iloc[-1]
    last_basis = float(last_val) if not pd.isna(last_val) else None

    if band_frac is not None and band_frac > 0 and last_basis is not None:
        upper_series = basis_series * (1.0 + band_frac)
        lower_series = basis_series * (1.0 - band_frac)
        last_up = float(upper_series.iloc[-1]) if not pd.isna(upper_series.iloc[-1]) else None
        last_lo = float(lower_series.iloc[-1]) if not pd.isna(lower_series.iloc[-1]) else None
        return BandEnvelopeResult(
            basis=basis_series,
            upper=upper_series,
            lower=lower_series,
            last_basis=last_basis,
            last_upper=last_up,
            last_lower=last_lo,
        )

    return BandEnvelopeResult(
        basis=basis_series,
        upper=None,
        lower=None,
        last_basis=last_basis,
        last_upper=None,
        last_lower=None,
    )


def band_state(
    bars: Sequence[float],
    band_frac: Optional[float],
    basis_window: int = 20,
) -> dict[str, Any]:
    """Calculate envelope position, state, and distance beyond the band edge.

    Preserves verified prototype mathematics from yogi.core_math.formulas.band_state:
    - BD > 0: price is above the upper edge by that %
    - BD < 0: price is below the lower edge by that %
    - BD = 0: price is inside the band
    - Basis window scales down to max(3, len(bars)//2) when history < basis_window
    - If band_frac is None/0 or len(bars) < 3, returns state="na" and None values
    """
    if band_frac in (None, 0) or len(bars) < 3:
        return {
            "pos": None,
            "state": "na",
            "bd": None,
            "up": None,
            "lo": None,
            "basis": None,
        }

    envelope = calculate_band_envelope(bars, band_frac=band_frac, basis_window=basis_window)
    if envelope.last_basis is None or pd.isna(envelope.last_basis):
        return {
            "pos": None,
            "state": "na",
            "bd": None,
            "up": None,
            "lo": None,
            "basis": None,
        }

    basis = envelope.last_basis
    upper = envelope.last_upper
    lower = envelope.last_lower
    c = float(bars[-1])
    pos = None if (upper is None or lower is None or upper == lower) else (c - lower) / (upper - lower)

    if upper is not None and c > upper:
        state, bd = "ABOVE", (c / upper - 1.0) * 100.0
    elif lower is not None and c < lower:
        state, bd = "BELOW", (c / lower - 1.0) * 100.0
    else:
        state, bd = "IN", 0.0

    return {
        "pos": None if pos is None else round(pos, 3),
        "state": state,
        "bd": round(float(bd), 2),
        "up": round(float(upper), 2) if upper is not None else None,
        "lo": round(float(lower), 2) if lower is not None else None,
        "basis": round(float(basis), 2),
    }


@dataclass(frozen=True)
class BandDistanceResult:
    """Authoritative rolling band distance calculation result."""
    distance: pd.Series
    basis_window: int = 20
    band_frac: Optional[float] = None
    last_distance: Optional[float] = None


def calculate_band_distance_curve(
    close: pd.Series,
    band_frac: Optional[float],
    basis_window: int = 20,
) -> BandDistanceResult:
    """Calculate rolling band distance over time (% beyond envelope edge: + above, - below, 0 inside).

    Preserves verified prototype mathematics from yogi.core_math.formulas.band_distance_series:
    - If not band_frac or band_frac <= 0: returns empty series and None last_distance.
    - If len(close.dropna()) < 3: returns empty series and None last_distance.
    - bw = basis_window if len(b) >= basis_window else max(3, len(b) // 2)
    - basis = b.rolling(bw, min_periods=max(2, bw // 2)).mean()
    - up, lo = basis * (1 + band_frac), basis * (1 - band_frac)
    - out = pd.Series(0.0, index=b.index)
    - out[b > up] = (b / up - 1) * 100
    - out[b < lo] = (b / lo - 1) * 100
    """
    if close is None or close.empty or band_frac in (None, 0) or band_frac <= 0:
        empty_s = pd.Series([], dtype=float)
        return BandDistanceResult(
            distance=empty_s,
            basis_window=basis_window,
            band_frac=band_frac,
            last_distance=None,
        )

    b = close.dropna()
    if len(b) < 3:
        empty_s = pd.Series([], dtype=float, index=b.index[:0])
        return BandDistanceResult(
            distance=empty_s,
            basis_window=basis_window,
            band_frac=band_frac,
            last_distance=None,
        )

    envelope = calculate_band_envelope(closes=b.tolist(), band_frac=band_frac, basis_window=basis_window)
    if envelope.upper is None or envelope.lower is None or envelope.basis.empty:
        empty_s = pd.Series([], dtype=float, index=b.index[:0])
        return BandDistanceResult(
            distance=empty_s,
            basis_window=basis_window,
            band_frac=band_frac,
            last_distance=None,
        )

    up = pd.Series(envelope.upper.values, index=b.index)
    lo = pd.Series(envelope.lower.values, index=b.index)

    out = pd.Series(0.0, index=b.index, dtype=float)
    mask_up = (b > up) & up.notna()
    mask_lo = (b < lo) & lo.notna()

    with np.errstate(divide="ignore", invalid="ignore"):
        out[mask_up] = (b[mask_up] / up[mask_up] - 1.0) * 100.0
        out[mask_lo] = (b[mask_lo] / lo[mask_lo] - 1.0) * 100.0

    last_val = float(out.iloc[-1]) if not out.empty else None

    return BandDistanceResult(
        distance=out,
        basis_window=basis_window,
        band_frac=band_frac,
        last_distance=last_val,
    )


def band_distance_series(
    close: pd.Series,
    band_frac: Optional[float],
    bars: Optional[pd.Series] = None,
    basis_window: int = 20,
) -> pd.Series:
    """Prototype-parity function returning pd.Series matching formulas.py:band_distance_series."""
    src = bars if bars is not None else close
    return calculate_band_distance_curve(src, band_frac=band_frac, basis_window=basis_window).distance


class BandsCalculator(ICalcModule):
    """Calculates band positions, states, distances, and multi-timeframe summaries.

    Registered under key "bands" in RegistryHub.calculations.
    """

    name: str = "bands"
    required_timeframes: Sequence[str] = ("D", "W", "M", "Q", "H", "Y")

    def calculate(self, symbol: str, context: CalculationContext) -> CalculationResult:
        """Execute bands calculation across all standard timeframes."""
        bw = int(context.parameters.get("basis_window", 20))
        metrics: dict[str, Any] = {}

        for tf in self.required_timeframes:
            w = context.bands_lookup.get(tf) if context.bands_lookup else None
            bars = context.market_context.get_bars(tf)
            closes = [b.close for b in bars] if bars else []
            bs = band_state(closes, w, basis_window=bw)

            metrics[f"BAND_{tf}"] = w
            metrics[f"BANDPOS_{tf}"] = bs["pos"]
            metrics[f"BANDST_{tf}"] = bs["state"]
            metrics[f"BD_{tf}"] = bs["bd"]
            metrics[f"BANDUP_{tf}"] = bs["up"]
            metrics[f"BANDLO_{tf}"] = bs["lo"]

        above = [tf for tf in self.required_timeframes if metrics.get(f"BANDST_{tf}") == "ABOVE"]
        below = [tf for tf in self.required_timeframes if metrics.get(f"BANDST_{tf}") == "BELOW"]
        metrics["OUT_ABOVE"] = ",".join(above)
        metrics["OUT_BELOW"] = ",".join(below)
        metrics["N_ABOVE"] = len(above)
        metrics["N_BELOW"] = len(below)

        return CalculationResult(symbol=symbol, module_name=self.name, metrics=metrics)


# =============================================================================
# Price & Volatility Envelopes (Bollinger, Donchian, ATR Volatility Bands)
# =============================================================================

@dataclass(frozen=True)
class BollingerBandsResult:
    """Authoritative Bollinger Bands computation result."""
    basis: pd.Series
    upper: pd.Series
    lower: pd.Series
    last_basis: Optional[float]
    last_upper: Optional[float]
    last_lower: Optional[float]


def calculate_bollinger_bands(
    close: Sequence[float] | pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> BollingerBandsResult:
    """Calculate Bollinger Bands matching prototype formulas (routes.py:131-133):
        basis = rolling_mean(20)
        sd = rolling_std(20)
        upper = basis + num_std * sd
        lower = basis - num_std * sd
    """
    s = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    if len(s) < window or window <= 0:
        empty = pd.Series([], dtype=float, index=s.index[:0])
        return BollingerBandsResult(
            basis=empty, upper=empty, lower=empty,
            last_basis=None, last_upper=None, last_lower=None,
        )

    basis = s.rolling(window).mean()
    sd = s.rolling(window).std()
    upper = basis + num_std * sd
    lower = basis - num_std * sd

    lb = float(basis.iloc[-1]) if not pd.isna(basis.iloc[-1]) else None
    lu = float(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else None
    ll = float(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else None

    return BollingerBandsResult(
        basis=basis,
        upper=upper,
        lower=lower,
        last_basis=lb,
        last_upper=lu,
        last_lower=ll,
    )


@dataclass(frozen=True)
class DonchianChannelsResult:
    """Authoritative Donchian Channels computation result."""
    upper: pd.Series
    lower: pd.Series
    middle: pd.Series
    last_upper: Optional[float]
    last_lower: Optional[float]
    last_middle: Optional[float]


def calculate_donchian_channels(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    window: int = 20,
) -> DonchianChannelsResult:
    """Calculate Donchian Channels matching prototype formulas (routes.py:139-140):
        upper = rolling_max(high, 20)
        lower = rolling_min(low, 20)
        middle = (upper + lower) / 2.0
    """
    h = pd.Series(high, dtype=float) if not isinstance(high, pd.Series) else high.astype(float)
    l = pd.Series(low, dtype=float) if not isinstance(low, pd.Series) else low.astype(float)
    if len(h) < window or len(l) < window or window <= 0:
        empty = pd.Series([], dtype=float, index=h.index[:0])
        return DonchianChannelsResult(
            upper=empty, lower=empty, middle=empty,
            last_upper=None, last_lower=None, last_middle=None,
        )

    upper = h.rolling(window).max()
    lower = l.rolling(window).min()
    middle = (upper + lower) / 2.0

    lu = float(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else None
    ll = float(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else None
    lm = float(middle.iloc[-1]) if not pd.isna(middle.iloc[-1]) else None

    return DonchianChannelsResult(
        upper=upper,
        lower=lower,
        middle=middle,
        last_upper=lu,
        last_lower=ll,
        last_middle=lm,
    )


def calculate_true_range(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    close: Sequence[float] | pd.Series,
) -> pd.Series:
    """Calculate True Range matching prototype convention (routes.py:134-136):
        TR = max(high - low, |high - prev_close|, |low - prev_close|)
    """
    h = pd.Series(high, dtype=float) if not isinstance(high, pd.Series) else high.astype(float)
    l = pd.Series(low, dtype=float) if not isinstance(low, pd.Series) else low.astype(float)
    c = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)

    if len(h) == 0:
        return pd.Series([], dtype=float)

    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr


def calculate_atr(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    close: Sequence[float] | pd.Series,
    period: int = 14,
) -> pd.Series:
    """Calculate Average True Range using simple rolling mean matching prototype (routes.py:137):
        atr = tr.rolling(14).mean()
    """
    tr = calculate_true_range(high, low, close)
    if len(tr) < period or period <= 0:
        return pd.Series([], dtype=float, index=tr.index[:0])
    return tr.rolling(period).mean()


@dataclass(frozen=True)
class ATRBandsResult:
    """Authoritative ATR Volatility Bands computation result."""
    upper: pd.Series
    lower: pd.Series
    atr: pd.Series
    last_upper: Optional[float]
    last_lower: Optional[float]
    last_atr: Optional[float]


def calculate_atr_bands(
    high: Sequence[float] | pd.Series,
    low: Sequence[float] | pd.Series,
    close: Sequence[float] | pd.Series,
    period: int = 14,
    multiplier: float = 2.0,
) -> ATRBandsResult:
    """Calculate ATR Volatility Bands matching prototype formulas (routes.py:138):
        atr = tr.rolling(14).mean()
        upper = close + multiplier * atr
        lower = close - multiplier * atr
    """
    c = pd.Series(close, dtype=float) if not isinstance(close, pd.Series) else close.astype(float)
    atr = calculate_atr(high, low, close, period=period)
    if len(c) < period or period <= 0 or atr.empty:
        empty = pd.Series([], dtype=float, index=c.index[:0])
        return ATRBandsResult(
            upper=empty, lower=empty, atr=empty,
            last_upper=None, last_lower=None, last_atr=None,
        )

    upper = c + multiplier * atr
    lower = c - multiplier * atr

    lu = float(upper.iloc[-1]) if not pd.isna(upper.iloc[-1]) else None
    ll = float(lower.iloc[-1]) if not pd.isna(lower.iloc[-1]) else None
    la = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else None

    return ATRBandsResult(
        upper=upper,
        lower=lower,
        atr=atr,
        last_upper=lu,
        last_lower=ll,
        last_atr=la,
    )

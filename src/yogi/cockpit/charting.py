"""Cockpit Charting Service — Multi-timeframe candlestick and trader band presentation service.

Decouples chart payload synthesis from HTTP route controllers without turning the router
into a mini-orchestrator.
Adheres strictly to the verified YOGI band envelope mathematics:
    Basis = SMA(Close, bw) where bw = 20 (scaled to max(3, N // 2) if N < 20)
    Upper = Basis * (1 + w)
    Lower = Basis * (1 - w)
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
import logging
import threading
import time
from typing import Optional, Sequence
import numpy as np
import pandas as pd

from yogi.cockpit.schemas import (
    ATRBandsSeriesOut,
    BandCurvePointOut,
    BandLevelOut,
    BollingerSeriesOut,
    CandleBarOut,
    CandleSeriesOut,
    DMISeriesOut,
    DMISummaryOut,
    DonchianSeriesOut,
    MACDSeriesOut,
    MFISeriesOut,
    OBVSeriesOut,
    RSISeriesOut,
    VolumePointOut,
    YAccelSeriesOut,
    YBandSeriesOut,
    YRocSeriesOut,
    YSprintSeriesOut,
)
from yogi.calculation.bands.calculator import (
    band_state,
    calculate_atr_bands,
    calculate_band_distance_curve,
    calculate_band_envelope,
    calculate_bollinger_bands,
    calculate_donchian_channels,
)
from yogi.calculation.trend.calculator import (
    ath_diff,
    average_price,
    calculate_macd,
    calculate_mfi,
    calculate_obv,
    calculate_roc_curve,
    calculate_rsi,
    calculate_vwap,
    dmi,
    dmi_state,
    ema,
)
from yogi.calculation.velocity.calculator import (
    calculate_acceleration_curve,
    calculate_sprint_speed_curve,
)
from yogi.core.contracts.bands import IBandsRepository
from yogi.core.contracts.market_data import MarketBar
from yogi.core.contracts.provider import IDataProvider
from yogi.core.contracts.storage import IBarsCache
from yogi.core.contracts.timeframe import ITimeframeEngine
from yogi.timeframe.engine import TimeframeEngine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ChartCacheEntry:
    """Bounded cache entry storing raw historical bars and monotonic ingestion timestamp."""
    bars: Sequence[MarketBar]
    created_at: float


class ChartDataService:
    """Application presentation service building candlestick and envelope curves for charting."""

    def __init__(
        self,
        provider: IDataProvider,
        timeframe_engine: Optional[ITimeframeEngine] = None,
        bands_repo: Optional[IBandsRepository] = None,
        max_entries: int = 100,
        ttl_seconds: Optional[float] = 300.0,
        bars_cache: Optional[IBarsCache] = None,
    ) -> None:
        self.provider = provider
        self.timeframe_engine = timeframe_engine if timeframe_engine is not None else TimeframeEngine()
        self.bands_repo = bands_repo
        self.max_entries: int = max_entries
        self.ttl_seconds: Optional[float] = ttl_seconds
        self.bars_cache = bars_cache
        self._provider_name: str = getattr(self.provider, "name", "")
        self._cache: OrderedDict[tuple[str, str, int], _ChartCacheEntry] = OrderedDict()
        self._cache_lock: threading.Lock = threading.Lock()

    @staticmethod
    def _slice_bars_for_years(bars: Sequence[MarketBar], years: int = 2) -> Sequence[MarketBar]:
        """Slice chronological daily bars for the requested years range while preserving lookback."""
        if not bars:
            return ()
        sorted_bars = tuple(sorted(bars, key=lambda b: b.timestamp))
        try:
            y = int(years)
        except (ValueError, TypeError):
            y = 2

        if y <= 0 or y >= 10:
            return sorted_bars

        latest_dt = sorted_bars[-1].timestamp
        cutoff_dt = latest_dt - timedelta(days=int(y * 365.25))
        sliced = [b for b in sorted_bars if b.timestamp >= cutoff_dt]

        # Preserve minimum lookback of 20 bars (or all available if < 20) for indicators
        min_required = min(len(sorted_bars), 20)
        if len(sliced) < min_required:
            sliced = list(sorted_bars[-min_required:])

        return tuple(sliced)

    def _get_cached(self, key: tuple[str, str, int]) -> Optional[Sequence[MarketBar]]:
        """Retrieve cached daily bars if present, valid, and not expired."""
        with self._cache_lock:
            # Invalidate cache if provider switched on this service instance
            current_provider = getattr(self.provider, "name", "")
            if current_provider != self._provider_name:
                self._cache.clear()
                self._provider_name = current_provider
                return None

            entry = self._cache.get(key)
            if entry is None:
                return None

            # Check TTL expiration
            if self.ttl_seconds is not None and self.ttl_seconds > 0:
                if (time.monotonic() - entry.created_at) > self.ttl_seconds:
                    del self._cache[key]
                    return None

            # Cache hit: record access for LRU eviction order
            self._cache.move_to_end(key)
            return entry.bars

    def _put_cached(self, key: tuple[str, str, int], bars: Sequence[MarketBar]) -> None:
        """Store daily bars in the bounded cache, evicting the oldest entry if capacity exceeded."""
        if self.max_entries <= 0 or not bars:
            return

        with self._cache_lock:
            current_provider = getattr(self.provider, "name", "")
            if current_provider != self._provider_name:
                self._cache.clear()
                self._provider_name = current_provider

            now = time.monotonic()
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = _ChartCacheEntry(bars=tuple(bars), created_at=now)
            else:
                if len(self._cache) >= self.max_entries:
                    self._cache.popitem(last=False)
                self._cache[key] = _ChartCacheEntry(bars=tuple(bars), created_at=now)

    def clear_cache(self) -> None:
        """Clear all entries from the chart data cache."""
        with self._cache_lock:
            self._cache.clear()

    def invalidate_symbol(self, symbol: str) -> None:
        """Evict all cached entries for the specified symbol."""
        sym_u = symbol.strip().upper()
        with self._cache_lock:
            keys_to_remove = [k for k in self._cache if k[0] == sym_u]
            for k in keys_to_remove:
                del self._cache[k]

    @property
    def cache_size(self) -> int:
        """Return the current number of valid entries in the cache."""
        with self._cache_lock:
            return len(self._cache)

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "D",
        band_timeframe: Optional[str] = None,
        exchange: str = "NSE",
        years: int = 2,
    ) -> CandleSeriesOut:
        """Fetch historical bars, synthesize requested timeframe, and compute band envelope curves."""
        sym = symbol.strip().upper()
        tf = timeframe.strip().upper()
        ex = (exchange or "NSE").strip().upper()

        # Resolve active band timeframe and handle suppression
        effective_btf: Optional[str] = None
        if band_timeframe is None:
            effective_btf = tf
        else:
            raw_btf = str(band_timeframe).strip().upper()
            if raw_btf in ("", "NONE", "OFF"):
                effective_btf = None
            elif raw_btf in ("D", "W", "M", "Q", "H", "Y"):
                effective_btf = raw_btf
            else:
                raise ValueError(
                    f"Unsupported band timeframe '{band_timeframe}'. Supported timeframes: ('D', 'W', 'M', 'Q', 'H', 'Y') or 'NONE'/'OFF'."
                )

        # 1. Fetch raw daily bars from presentation cache, persistent cache, or provider
        cache_key = (sym, ex, years)
        daily_bars = self._get_cached(cache_key)
        if daily_bars is None:
            # 1a. Attempt to load canonical bars from persistent MarketBarsCache
            if self.bars_cache is not None:
                try:
                    pv_name = getattr(self.provider, "name", "yfinance")
                    found, _ = self.bars_cache.get_bars_for_symbols(
                        symbols=[sym],
                        exchange=ex,
                        provider=pv_name,
                        min_bars=3,
                    )
                    cached_raw = found.get(sym)
                    if cached_raw:
                        daily_bars = self._slice_bars_for_years(cached_raw, years=years)
                except Exception as cache_err:
                    logger.debug(
                        "ChartDataService: persistent bar cache lookup failed for '%s': %s",
                        sym,
                        cache_err,
                    )

            # 1b. Fall back to configured provider if persistent cache had no usable data
            if not daily_bars:
                daily_bars = self.provider.daily_history(symbol=sym, exchange=ex, years=years)

            if daily_bars:
                self._put_cached(cache_key, daily_bars)

        if not daily_bars:
            return CandleSeriesOut(
                symbol=sym,
                exchange=exchange,
                timeframe=tf,
                candles=[],
                band_upper_curve=[],
                band_lower_curve=[],
                latest_band=None,
            )

        # 2. Resample to requested timeframe via TimeframeEngine
        if tf == "D":
            bars = tuple(daily_bars)
        else:
            bars = self.timeframe_engine.resample(bars=daily_bars, timeframe=tf)

        if not bars:
            return CandleSeriesOut(
                symbol=sym,
                exchange=exchange,
                timeframe=tf,
                candles=[],
                band_upper_curve=[],
                band_lower_curve=[],
                latest_band=None,
            )

        # 3. Format candles for Lightweight Charts
        candles: list[CandleBarOut] = []
        for b in bars:
            time_str = b.timestamp.strftime("%Y-%m-%d")
            candles.append(
                CandleBarOut(
                    time=time_str,
                    open=round(float(b.open), 2),
                    high=round(float(b.high), 2),
                    low=round(float(b.low), 2),
                    close=round(float(b.close), 2),
                    volume=float(b.volume) if b.volume is not None else None,
                )
            )

        # 4. Authoritative YOGI Band Semantics
        # Basis = SMA(Close of candle timeframe, bw) where bw = 20 (scaled to max(3, N // 2) if N < 20)
        # Upper = Basis * (1 + w from band timeframe)
        # Lower = Basis * (1 - w from band timeframe)
        band_upper_curve: list[BandCurvePointOut] = []
        band_lower_curve: list[BandCurvePointOut] = []
        basis_curve: list[BandCurvePointOut] = []
        latest_band: Optional[BandLevelOut] = None

        closes = [float(b.close) for b in bars]
        n_bars = len(closes)

        w: Optional[float] = None
        if effective_btf is not None and self.bands_repo is not None:
            w = self.bands_repo.get_band(symbol=sym, timeframe=effective_btf)

        if n_bars >= 3:
            envelope = calculate_band_envelope(closes=closes, band_frac=w, basis_window=20)

            # Basis curve (20-bar SMA)
            if envelope.basis is not None and not envelope.basis.empty:
                for i, b in enumerate(bars):
                    bv = envelope.basis.iloc[i]
                    if not pd.isna(bv):
                        basis_curve.append(
                            BandCurvePointOut(
                                time=b.timestamp.strftime("%Y-%m-%d"),
                                value=round(float(bv), 2),
                            )
                        )

            # Band distance / state from BandsCalculator
            bs = band_state(bars=closes, band_frac=w, basis_window=20)

            if envelope.upper is not None and envelope.lower is not None:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    up_val = envelope.upper.iloc[i]
                    lo_val = envelope.lower.iloc[i]
                    if not pd.isna(up_val):
                        band_upper_curve.append(BandCurvePointOut(time=t_str, value=round(float(up_val), 2)))
                    if not pd.isna(lo_val):
                        band_lower_curve.append(BandCurvePointOut(time=t_str, value=round(float(lo_val), 2)))

                latest_band = BandLevelOut(
                    timeframe=tf,
                    band_timeframe=effective_btf,
                    width=w,
                    basis=round(envelope.last_basis, 2) if envelope.last_basis is not None else None,
                    upper=round(envelope.last_upper, 2) if envelope.last_upper is not None else None,
                    lower=round(envelope.last_lower, 2) if envelope.last_lower is not None else None,
                    band_distance=bs.get("bd"),
                    band_state=bs.get("state"),
                )
            elif envelope.last_basis is not None:
                latest_band = BandLevelOut(
                    timeframe=tf,
                    band_timeframe=effective_btf,
                    width=w,
                    basis=round(envelope.last_basis, 2),
                    upper=None,
                    lower=None,
                    band_distance=bs.get("bd"),
                    band_state=bs.get("state"),
                )

        # 5. Volume Series (preserving missing values without fabrication)
        volume_curve: list[VolumePointOut] = [
            VolumePointOut(
                time=b.timestamp.strftime("%Y-%m-%d"),
                value=float(b.volume) if b.volume is not None else None,
            )
            for b in bars
        ]

        # 6. Moving Average Curves (EMA3, EMA5) via TrendCalculator.ema
        ema3_curve: list[BandCurvePointOut] = []
        ema5_curve: list[BandCurvePointOut] = []
        close_series = pd.Series(closes, index=[b.timestamp for b in bars]) if n_bars > 0 else pd.Series(dtype=float)
        high_series = (
            pd.Series([float(b.high) for b in bars], index=[b.timestamp for b in bars])
            if n_bars > 0
            else pd.Series(dtype=float)
        )
        low_series = (
            pd.Series([float(b.low) for b in bars], index=[b.timestamp for b in bars])
            if n_bars > 0
            else pd.Series(dtype=float)
        )
        volume_series = (
            pd.Series([float(b.volume) if b.volume is not None else np.nan for b in bars], index=[b.timestamp for b in bars])
            if n_bars > 0
            else pd.Series(dtype=float)
        )
        if n_bars > 0:
            e3_s = ema(close_series, span=3)
            e5_s = ema(close_series, span=5)
            for i, b in enumerate(bars):
                t_str = b.timestamp.strftime("%Y-%m-%d")
                e3_val = e3_s.iloc[i]
                e5_val = e5_s.iloc[i]
                if not pd.isna(e3_val):
                    ema3_curve.append(BandCurvePointOut(time=t_str, value=round(float(e3_val), 2)))
                if not pd.isna(e5_val):
                    ema5_curve.append(BandCurvePointOut(time=t_str, value=round(float(e5_val), 2)))

        # 7. DMI / ADX Time Series & Summary via TrendCalculator.dmi
        dmi_series_out: Optional[DMISeriesOut] = None
        dmi_summary_out: Optional[DMISummaryOut] = None
        if n_bars >= 6 and any(b.high != b.low for b in bars):
            dmi_df = pd.DataFrame(
                {
                    "high": [float(b.high) for b in bars],
                    "low": [float(b.low) for b in bars],
                    "close": closes,
                },
                index=[b.timestamp for b in bars],
            )
            dmi_res = dmi(dmi_df, period=14, adx_period=14)
            p_s = dmi_res.get("series", {}).get("plus")
            m_s = dmi_res.get("series", {}).get("minus")
            a_s = dmi_res.get("series", {}).get("adx")

            plus_pts: list[BandCurvePointOut] = []
            minus_pts: list[BandCurvePointOut] = []
            adx_pts: list[BandCurvePointOut] = []

            if p_s is not None and not p_s.empty:
                plus_pts = [
                    BandCurvePointOut(
                        time=t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10],
                        value=round(float(v), 2),
                    )
                    for t, v in p_s.items()
                    if not pd.isna(v)
                ]
            if m_s is not None and not m_s.empty:
                minus_pts = [
                    BandCurvePointOut(
                        time=t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10],
                        value=round(float(v), 2),
                    )
                    for t, v in m_s.items()
                    if not pd.isna(v)
                ]
            if a_s is not None and not a_s.empty:
                adx_pts = [
                    BandCurvePointOut(
                        time=t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10],
                        value=round(float(v), 2),
                    )
                    for t, v in a_s.items()
                    if not pd.isna(v)
                ]

            dmi_series_out = DMISeriesOut(plus=plus_pts, minus=minus_pts, adx=adx_pts)
            dmi_summary_out = DMISummaryOut(
                plus_di=dmi_res.get("plus_di"),
                minus_di=dmi_res.get("minus_di"),
                adx=dmi_res.get("adx"),
                adxr=dmi_res.get("adxr"),
                state=dmi_state(dmi_res.get("plus_di"), dmi_res.get("minus_di"), dmi_res.get("adx")),
                period=dmi_res.get("period"),
                adx_period=dmi_res.get("adx_period"),
            )

        # 8. All-Time High Drawdown via TrendCalculator.ath_diff
        latest_ath_diff = ath_diff(close_series) if n_bars > 0 else None
        if latest_ath_diff is not None:
            latest_ath_diff = round(float(latest_ath_diff), 2)

        # 9. Bollinger Bands (20-period, 2.0 std dev) via calculate_bollinger_bands
        bollinger_out: Optional[BollingerSeriesOut] = None
        if n_bars >= 20:
            bb_res = calculate_bollinger_bands(close_series, window=20, num_std=2.0)
            if not bb_res.basis.empty:
                bb_up_pts: list[BandCurvePointOut] = []
                bb_lo_pts: list[BandCurvePointOut] = []
                bb_basis_pts: list[BandCurvePointOut] = []
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    u_val = bb_res.upper.iloc[i]
                    l_val = bb_res.lower.iloc[i]
                    b_val = bb_res.basis.iloc[i]
                    if not pd.isna(u_val):
                        bb_up_pts.append(BandCurvePointOut(time=t_str, value=round(float(u_val), 2)))
                    if not pd.isna(l_val):
                        bb_lo_pts.append(BandCurvePointOut(time=t_str, value=round(float(l_val), 2)))
                    if not pd.isna(b_val):
                        bb_basis_pts.append(BandCurvePointOut(time=t_str, value=round(float(b_val), 2)))
                bollinger_out = BollingerSeriesOut(
                    upper=bb_up_pts,
                    lower=bb_lo_pts,
                    basis=bb_basis_pts,
                    last_upper=round(bb_res.last_upper, 2) if bb_res.last_upper is not None else None,
                    last_lower=round(bb_res.last_lower, 2) if bb_res.last_lower is not None else None,
                    last_basis=round(bb_res.last_basis, 2) if bb_res.last_basis is not None else None,
                )

        # 10. Donchian Channels (20-period) via calculate_donchian_channels
        donchian_out: Optional[DonchianSeriesOut] = None
        if n_bars >= 20:
            dc_res = calculate_donchian_channels(high_series, low_series, window=20)
            if not dc_res.upper.empty:
                dc_up_pts: list[BandCurvePointOut] = []
                dc_lo_pts: list[BandCurvePointOut] = []
                dc_mid_pts: list[BandCurvePointOut] = []
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    u_val = dc_res.upper.iloc[i]
                    l_val = dc_res.lower.iloc[i]
                    m_val = dc_res.middle.iloc[i]
                    if not pd.isna(u_val):
                        dc_up_pts.append(BandCurvePointOut(time=t_str, value=round(float(u_val), 2)))
                    if not pd.isna(l_val):
                        dc_lo_pts.append(BandCurvePointOut(time=t_str, value=round(float(l_val), 2)))
                    if not pd.isna(m_val):
                        dc_mid_pts.append(BandCurvePointOut(time=t_str, value=round(float(m_val), 2)))
                donchian_out = DonchianSeriesOut(
                    upper=dc_up_pts,
                    lower=dc_lo_pts,
                    middle=dc_mid_pts,
                    last_upper=round(dc_res.last_upper, 2) if dc_res.last_upper is not None else None,
                    last_lower=round(dc_res.last_lower, 2) if dc_res.last_lower is not None else None,
                    last_middle=round(dc_res.last_middle, 2) if dc_res.last_middle is not None else None,
                )

        # 11. ATR Volatility Bands (14-period, 2.0 multiplier) via calculate_atr_bands
        atr_bands_out: Optional[ATRBandsSeriesOut] = None
        if n_bars >= 14:
            atr_res = calculate_atr_bands(high_series, low_series, close_series, period=14, multiplier=2.0)
            if not atr_res.upper.empty:
                atr_up_pts: list[BandCurvePointOut] = []
                atr_lo_pts: list[BandCurvePointOut] = []
                atr_val_pts: list[BandCurvePointOut] = []
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    u_val = atr_res.upper.iloc[i]
                    l_val = atr_res.lower.iloc[i]
                    a_val = atr_res.atr.iloc[i]
                    if not pd.isna(u_val):
                        atr_up_pts.append(BandCurvePointOut(time=t_str, value=round(float(u_val), 2)))
                    if not pd.isna(l_val):
                        atr_lo_pts.append(BandCurvePointOut(time=t_str, value=round(float(l_val), 2)))
                    if not pd.isna(a_val):
                        atr_val_pts.append(BandCurvePointOut(time=t_str, value=round(float(a_val), 2)))
                atr_bands_out = ATRBandsSeriesOut(
                    upper=atr_up_pts,
                    lower=atr_lo_pts,
                    atr=atr_val_pts,
                    last_upper=round(atr_res.last_upper, 2) if atr_res.last_upper is not None else None,
                    last_lower=round(atr_res.last_lower, 2) if atr_res.last_lower is not None else None,
                    last_atr=round(atr_res.last_atr, 2) if atr_res.last_atr is not None else None,
                )

        # 12. Cumulative VWAP via calculate_vwap
        vwap_curve: list[BandCurvePointOut] = []
        if n_bars > 0:
            vwap_s = calculate_vwap(high_series, low_series, close_series, volume_series)
            if not vwap_s.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    vw_val = vwap_s.iloc[i]
                    if not pd.isna(vw_val):
                        vwap_curve.append(BandCurvePointOut(time=t_str, value=round(float(vw_val), 2)))

        # 13. Average Price via average_price
        avg_price_val: Optional[float] = None
        if n_bars > 0:
            raw_avg = average_price(close_series)
            if raw_avg is not None:
                avg_price_val = round(float(raw_avg), 2)

        # 14. Relative Strength Index (14-period) via calculate_rsi
        rsi_out: Optional[RSISeriesOut] = None
        rsi_curve: list[BandCurvePointOut] = []
        if n_bars >= 15:
            rsi_res = calculate_rsi(close_series, period=14)
            if not rsi_res.rsi.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    r_val = rsi_res.rsi.iloc[i]
                    if not pd.isna(r_val):
                        rsi_curve.append(BandCurvePointOut(time=t_str, value=round(float(r_val), 2)))
                if rsi_curve:
                    rsi_out = RSISeriesOut(
                        points=rsi_curve,
                        last_rsi=round(rsi_res.last_rsi, 2) if rsi_res.last_rsi is not None else None,
                    )

        # 15. Moving Average Convergence Divergence (12, 26, 9) via calculate_macd
        macd_out: Optional[MACDSeriesOut] = None
        if n_bars >= 2:
            macd_res = calculate_macd(close_series, fast_period=12, slow_period=26, signal_period=9)
            if not macd_res.macd.empty:
                m_pts: list[BandCurvePointOut] = []
                s_pts: list[BandCurvePointOut] = []
                h_pts: list[BandCurvePointOut] = []
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    m_val = macd_res.macd.iloc[i]
                    s_val = macd_res.signal.iloc[i]
                    h_val = macd_res.histogram.iloc[i]
                    if not pd.isna(m_val):
                        m_pts.append(BandCurvePointOut(time=t_str, value=round(float(m_val), 2)))
                    if not pd.isna(s_val):
                        s_pts.append(BandCurvePointOut(time=t_str, value=round(float(s_val), 2)))
                    if not pd.isna(h_val):
                        h_pts.append(BandCurvePointOut(time=t_str, value=round(float(h_val), 2)))
                macd_out = MACDSeriesOut(
                    macd=m_pts,
                    signal=s_pts,
                    histogram=h_pts,
                    last_macd=round(macd_res.last_macd, 2) if macd_res.last_macd is not None else None,
                    last_signal=round(macd_res.last_signal, 2) if macd_res.last_signal is not None else None,
                    last_histogram=round(macd_res.last_histogram, 2) if macd_res.last_histogram is not None else None,
                )

        # 16. On-Balance Volume via calculate_obv
        obv_out: Optional[OBVSeriesOut] = None
        obv_curve: list[BandCurvePointOut] = []
        if n_bars > 0:
            obv_res = calculate_obv(close_series, volume_series)
            if not obv_res.obv.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    o_val = obv_res.obv.iloc[i]
                    if not pd.isna(o_val):
                        obv_curve.append(BandCurvePointOut(time=t_str, value=round(float(o_val), 2)))
                if obv_curve:
                    obv_out = OBVSeriesOut(
                        points=obv_curve,
                        last_obv=round(obv_res.last_obv, 2) if obv_res.last_obv is not None else None,
                    )

        # 17. Money Flow Index (14-period) via calculate_mfi
        mfi_out: Optional[MFISeriesOut] = None
        mfi_curve: list[BandCurvePointOut] = []
        if n_bars >= 15:
            mfi_res = calculate_mfi(high_series, low_series, close_series, volume_series, period=14)
            if not mfi_res.mfi.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    mf_val = mfi_res.mfi.iloc[i]
                    if not pd.isna(mf_val):
                        mfi_curve.append(BandCurvePointOut(time=t_str, value=round(float(mf_val), 2)))
                if mfi_curve:
                    mfi_out = MFISeriesOut(
                        points=mfi_curve,
                        last_mfi=round(mfi_res.last_mfi, 2) if mfi_res.last_mfi is not None else None,
                    )

        # 18. YOGI Sprint Speed (4 weeks) via calculate_sprint_speed_curve
        y_sprint_out: Optional[YSprintSeriesOut] = None
        y_sprint_curve: list[BandCurvePointOut] = []
        if n_bars > 20:
            sprint_res = calculate_sprint_speed_curve(close_series, weeks=4)
            if not sprint_res.speed.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    sp_val = sprint_res.speed.iloc[i]
                    if not pd.isna(sp_val):
                        y_sprint_curve.append(BandCurvePointOut(time=t_str, value=round(float(sp_val), 2)))
                if y_sprint_curve:
                    y_sprint_out = YSprintSeriesOut(
                        points=y_sprint_curve,
                        weeks=4,
                        last_speed=round(sprint_res.last_speed, 2) if sprint_res.last_speed is not None else None,
                    )

        # 19. YOGI Acceleration (4w vs 52w) via calculate_acceleration_curve
        y_accel_out: Optional[YAccelSeriesOut] = None
        y_accel_curve: list[BandCurvePointOut] = []
        if n_bars > 260:
            accel_res = calculate_acceleration_curve(close_series, short_weeks=4, long_weeks=52)
            if not accel_res.accel.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    ac_val = accel_res.accel.iloc[i]
                    if not pd.isna(ac_val):
                        y_accel_curve.append(BandCurvePointOut(time=t_str, value=round(float(ac_val), 2)))
                if y_accel_curve:
                    y_accel_out = YAccelSeriesOut(
                        points=y_accel_curve,
                        short_weeks=4,
                        long_weeks=52,
                        last_accel=round(accel_res.last_accel, 2) if accel_res.last_accel is not None else None,
                    )

        # 20. YOGI Band Distance via calculate_band_distance_curve
        y_band_out: Optional[YBandSeriesOut] = None
        y_band_curve: list[BandCurvePointOut] = []
        if n_bars >= 3 and w is not None and w > 0:
            band_dist_res = calculate_band_distance_curve(close_series, band_frac=w, basis_window=20)
            if not band_dist_res.distance.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    bd_val = band_dist_res.distance.iloc[i]
                    if not pd.isna(bd_val):
                        y_band_curve.append(BandCurvePointOut(time=t_str, value=round(float(bd_val), 2)))
                if y_band_curve:
                    y_band_out = YBandSeriesOut(
                        points=y_band_curve,
                        basis_window=20,
                        band_frac=w,
                        last_distance=round(band_dist_res.last_distance, 2) if band_dist_res.last_distance is not None else None,
                    )

        # 21. YOGI ROC (21 days) via calculate_roc_curve
        y_roc_out: Optional[YRocSeriesOut] = None
        y_roc_curve: list[BandCurvePointOut] = []
        if n_bars > 21:
            roc_res = calculate_roc_curve(close_series, days=21)
            if not roc_res.roc.empty:
                for i, b in enumerate(bars):
                    t_str = b.timestamp.strftime("%Y-%m-%d")
                    rc_val = roc_res.roc.iloc[i]
                    if not pd.isna(rc_val):
                        y_roc_curve.append(BandCurvePointOut(time=t_str, value=round(float(rc_val), 2)))
                if y_roc_curve:
                    y_roc_out = YRocSeriesOut(
                        points=y_roc_curve,
                        days=21,
                        last_roc=round(roc_res.last_roc, 2) if roc_res.last_roc is not None else None,
                    )

        return CandleSeriesOut(
            symbol=sym,
            exchange=exchange,
            timeframe=tf,
            candles=candles,
            band_upper_curve=band_upper_curve,
            band_lower_curve=band_lower_curve,
            latest_band=latest_band,
            basis_curve=basis_curve,
            ema3_curve=ema3_curve,
            ema5_curve=ema5_curve,
            volume_curve=volume_curve,
            dmi_series=dmi_series_out,
            dmi_summary=dmi_summary_out,
            ath_diff=latest_ath_diff,
            bollinger=bollinger_out,
            donchian=donchian_out,
            atr_bands=atr_bands_out,
            vwap_curve=vwap_curve,
            avg_price=avg_price_val,
            rsi=rsi_out,
            macd=macd_out,
            obv=obv_out,
            mfi=mfi_out,
            rsi_curve=rsi_curve,
            obv_curve=obv_curve,
            mfi_curve=mfi_curve,
            y_sprint=y_sprint_out,
            y_accel=y_accel_out,
            y_band=y_band_out,
            y_roc=y_roc_out,
            y_sprint_curve=y_sprint_curve,
            y_accel_curve=y_accel_curve,
            y_band_curve=y_band_curve,
            y_roc_curve=y_roc_curve,
        )

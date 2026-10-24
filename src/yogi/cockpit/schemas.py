"""Cockpit Transport Schemas — Pydantic v2 DTOs for the HTTP API layer.

Decouples external HTTP payloads from frozen internal Core domain contracts.
Strictly separates screening intent (ScreeningQuery) from presentation column projection.
"""

from typing import Any, Mapping, Optional, Sequence, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from yogi.core.configuration.query import ScreeningQuery
from yogi.core.contracts.filter import FilterGroupSpec, FilterOperator, FilterRuleSpec
from yogi.core.contracts.ranking import RankingOrder
from yogi.core.contracts.results import ColumnDefinition, ExportFormat, QueryResultPayload
from yogi.core.contracts.selection import RankCutoffSpec, SelectionMode


# -----------------------------------------------------------------------------
# Input DTOs (Screening & Strategy)
# -----------------------------------------------------------------------------

class FilterRuleIn(BaseModel):
    """Specification for a single filtering condition."""
    field: str = ""
    op: FilterOperator = FilterOperator.EQ
    value: Any = None
    field2: Optional[str] = None
    is_negated: bool = False
    condition_type: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    timeframe: Optional[str] = None
    p1: Optional[int] = None
    p2: Optional[int] = None
    state: Optional[str] = None
    lookback: Optional[int] = None
    period: Optional[str] = None
    bucket: Optional[str] = None

    @model_validator(mode="after")
    def validate_ema_rule(self) -> "FilterRuleIn":
        if self.condition_type == "ema":
            tf_caps = {"D": 31, "W": 52, "M": 12, "Q": 4, "H": 2, "Y": 1}

            # Reconcile / populate timeframe
            param_tf = self.params.get("timeframe") if self.params else None
            if self.timeframe is not None and param_tf is not None:
                if str(self.timeframe).strip().upper() != str(param_tf).strip().upper():
                    raise ValueError(
                        f"Conflicting 'timeframe' parameter: legacy '{self.timeframe}' != params['timeframe'] '{param_tf}'"
                    )
            elif self.timeframe is None and param_tf is not None:
                self.timeframe = param_tf

            if not isinstance(self.timeframe, str):
                raise ValueError(f"Invalid timeframe '{self.timeframe}'. Must be one of {tuple(tf_caps.keys())}")
            tf = self.timeframe.strip().upper()
            if tf not in tf_caps:
                raise ValueError(f"Invalid timeframe '{self.timeframe}'. Must be one of {tuple(tf_caps.keys())}")
            self.timeframe = tf

            # Reconcile / populate p1 and p2
            param_p1 = self.params.get("p1") if self.params else None
            if self.p1 is not None and param_p1 is not None:
                if self.p1 != param_p1:
                    raise ValueError(f"Conflicting 'p1' parameter: legacy '{self.p1}' != params['p1'] '{param_p1}'")
            elif self.p1 is None and param_p1 is not None:
                self.p1 = param_p1

            param_p2 = self.params.get("p2") if self.params else None
            if self.p2 is not None and param_p2 is not None:
                if self.p2 != param_p2:
                    raise ValueError(f"Conflicting 'p2' parameter: legacy '{self.p2}' != params['p2'] '{param_p2}'")
            elif self.p2 is None and param_p2 is not None:
                self.p2 = param_p2

            if self.p1 is None or self.p2 is None:
                raise ValueError("Both p1 and p2 must be provided for EMA condition")
            if (
                isinstance(self.p1, bool)
                or isinstance(self.p2, bool)
                or not isinstance(self.p1, int)
                or not isinstance(self.p2, int)
                or self.p1 < 1
                or self.p2 < 1
            ):
                raise ValueError("Both p1 and p2 must be positive integers >= 1")
            max_p = tf_caps[tf]
            if self.p1 > max_p or self.p2 > max_p:
                raise ValueError(f"EMA periods for timeframe '{tf}' cannot exceed maximum {max_p} (got p1={self.p1}, p2={self.p2})")
            if self.p1 == self.p2:
                raise ValueError(f"P1 and P2 must be distinct positive integers (got p1={self.p1}, p2={self.p2})")

            # Reconcile / populate state
            param_st = None
            if self.params:
                param_st = self.params.get("state") if "state" in self.params else self.params.get("value")

            raw_legacy_st = self.state if self.state is not None else self.value
            if raw_legacy_st is not None and param_st is not None:
                if str(raw_legacy_st).strip().upper() != str(param_st).strip().upper():
                    raise ValueError(
                        f"Conflicting 'state' parameter: legacy '{raw_legacy_st}' != params['state'] '{param_st}'"
                    )
            elif self.state is None and param_st is not None:
                self.state = param_st

            valid_states = ("UP", "DOWN", "UPCUT", "DOWNCUT")
            st_val = self.state if self.state is not None else self.value
            if not isinstance(st_val, str):
                raise ValueError(f"Invalid EMA state '{self.state}'. Must be one of {valid_states}")
            st = st_val.strip().upper()
            if st not in valid_states:
                raise ValueError(f"Invalid EMA state '{self.state}'. Must be one of {valid_states}")
            self.state = st

            # Reconcile / populate lookback
            param_lb = self.params.get("lookback") if self.params else None
            if self.lookback is not None and param_lb is not None:
                if self.lookback != param_lb:
                    raise ValueError(
                        f"Conflicting 'lookback' parameter: legacy '{self.lookback}' != params['lookback'] '{param_lb}'"
                    )
            elif self.lookback is None and param_lb is not None:
                self.lookback = param_lb

            if self.lookback is not None:
                if isinstance(self.lookback, bool) or not isinstance(self.lookback, int) or self.lookback < 1:
                    raise ValueError("lookback must be a positive integer >= 1")

            if not self.field:
                self.field = f"EMA_{tf}_{self.p1}_{self.p2}"
            if self.value is None:
                self.value = st

            # Synchronize normalized values into params dict
            self.params["timeframe"] = tf
            self.params["p1"] = self.p1
            self.params["p2"] = self.p2
            self.params["state"] = st
            if self.lookback is not None:
                self.params["lookback"] = self.lookback

        elif self.condition_type == "roc":
            period_map = {
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
                "avg_preceding_last_5_years": "avg_preceding_last_5_years",
                "avg_last_5_years": "avg_preceding_last_5_years",
            }
            bucket_map = {
                "lt_10": "lt_10",
                "less_than_10": "lt_10",
                "<10": "lt_10",
                "less than 10%": "lt_10",
                "10_to_20": "10_to_20",
                "10-20": "10_to_20",
                "10% to 20%": "10_to_20",
                "20_to_30": "20_to_30",
                "20-30": "20_to_30",
                "20% to 30%": "20_to_30",
                "30_to_40": "30_to_40",
                "30-40": "30_to_40",
                "30% to 40%": "30_to_40",
                "40_to_50": "40_to_50",
                "40-50": "40_to_50",
                "40% to 50%": "40_to_50",
                "50_to_60": "50_to_60",
                "50-60": "50_to_60",
                "50% to 60%": "50_to_60",
                "60_to_70": "60_to_70",
                "60-70": "60_to_70",
                "60% to 70%": "60_to_70",
                "70_to_80": "70_to_80",
                "70-80": "70_to_80",
                "70% to 80%": "70_to_80",
                "80_to_90": "80_to_90",
                "80-90": "80_to_90",
                "80% to 90%": "80_to_90",
                "90_to_100": "90_to_100",
                "90-100": "90_to_100",
                "90% to 100%": "90_to_100",
                "gt_100": "gt_100",
                "more_than_100": "gt_100",
                ">100": "gt_100",
                "more than 100%": "gt_100",
            }

            # 1. Period extraction & validation
            raw_p = self.period or (self.params.get("period") if self.params else None)
            if not raw_p and self.field and self.field.upper().startswith("ROC_"):
                raw_p = self.field[4:].lower()

            if not raw_p or not isinstance(raw_p, str) or raw_p.strip().lower() not in period_map:
                valid_p_names = (
                    "current_month", "last_month", "last_to_last_month",
                    "current_quarter", "last_quarter", "current_half_year",
                    "ytd", "last_year", "preceding_last_4_years", "avg_preceding_last_5_years"
                )
                raise ValueError(
                    f"Invalid ROC period '{raw_p}'. Must be one of {valid_p_names}"
                )
            canon_p = period_map[raw_p.strip().lower()]
            self.period = canon_p

            # 2. Bucket extraction & validation (default to gt_100)
            raw_b = self.bucket or (self.params.get("bucket") if self.params else None) or self.value or self.state
            if raw_b is None:
                raw_b = "gt_100"

            if not isinstance(raw_b, str) or raw_b.strip().lower() not in bucket_map:
                valid_b_names = (
                    "lt_10", "10_to_20", "20_to_30", "30_to_40", "40_to_50",
                    "50_to_60", "60_to_70", "70_to_80", "80_to_90", "90_to_100", "gt_100"
                )
                raise ValueError(
                    f"Invalid ROC bucket '{raw_b}'. Must be one of {valid_b_names}"
                )
            canon_b = bucket_map[raw_b.strip().lower()]
            self.bucket = canon_b

            # 3. Bar timeframe separation: for PipelineOrchestrator bar retrieval, timeframe must be "D"
            self.timeframe = "D"
            if not self.field:
                self.field = f"ROC_{canon_p.upper()}"
            self.value = canon_b
            self.op = FilterOperator.EQ

            self.params["period"] = canon_p
            self.params["bucket"] = canon_b
            self.params["timeframe"] = "D"

        return self

    def to_core_spec(self) -> FilterRuleSpec:
        """Convert this FilterRuleIn DTO to the frozen Core FilterRuleSpec."""
        p_dict = dict(self.params) if self.params else {}
        if self.timeframe is not None and "timeframe" not in p_dict:
            p_dict["timeframe"] = self.timeframe
        if self.p1 is not None and "p1" not in p_dict:
            p_dict["p1"] = self.p1
        if self.p2 is not None and "p2" not in p_dict:
            p_dict["p2"] = self.p2
        if self.state is not None and "state" not in p_dict:
            p_dict["state"] = self.state
        if self.lookback is not None and "lookback" not in p_dict:
            p_dict["lookback"] = self.lookback
        if self.period is not None and "period" not in p_dict:
            p_dict["period"] = self.period
        if self.bucket is not None and "bucket" not in p_dict:
            p_dict["bucket"] = self.bucket

        return FilterRuleSpec(
            field=self.field,
            op=self.op,
            value=self.value,
            field2=self.field2,
            is_negated=self.is_negated,
            condition_type=self.condition_type,
            params=p_dict,
            timeframe=self.timeframe,
            p1=self.p1,
            p2=self.p2,
            state=self.state,
            lookback=self.lookback,
        )


class FilterGroupIn(BaseModel):
    """Specification for a composite boolean group of filter rules."""
    match: str = Field(default="all", pattern="^(all|any)$")
    rules: Sequence[Union[FilterRuleIn, "FilterGroupIn"]] = Field(default_factory=list)
    is_negated: bool = False


FilterGroupIn.model_rebuild()


class RankCutoffIn(BaseModel):
    """Specification for an ordinal survival threshold."""
    metric: str
    max_rank: int = Field(gt=0)
    min_periods: int = Field(default=1, ge=1)


class ScreenRequestIn(BaseModel):
    """HTTP request specification for dynamic screening.
    
    Contains screening specification (mapped to ScreeningQuery) AND presentation
    column projection (passed strictly to ResultAssembler).
    """
    request_id: Optional[str] = None

    # Screening intent -> mapped to ScreeningQuery
    filter_group: Optional[FilterGroupIn] = None
    ranking_metric: Optional[str] = None
    ranking_order: RankingOrder = RankingOrder.DESCENDING
    selection_cutoffs: Sequence[RankCutoffIn] = Field(default_factory=list)
    selection_mode: SelectionMode = SelectionMode.ALL
    limit: Optional[int] = Field(default=None, gt=0)

    # Presentation column projection -> passed exclusively to ResultAssembler
    columns: Optional[Sequence[str]] = None

    @field_validator("selection_mode", mode="before")
    @classmethod
    def _normalize_selection_mode(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_clean = v.strip().lower()
            if v_clean in ("all", "any"):
                return SelectionMode(v_clean)
        return v


class StrategyRunIn(BaseModel):
    """HTTP request specification for executing a named strategy recipe."""
    strategy_name: str
    limit: Optional[int] = Field(default=None, gt=0)
    columns: Optional[Sequence[str]] = None


class ExportRequestIn(BaseModel):
    """HTTP request specification for exporting screening results to XLSX, CSV, or JSON."""
    strategy_name: Optional[str] = None
    filter_group: Optional[FilterGroupIn] = None
    ranking_metric: Optional[str] = None
    ranking_order: RankingOrder = RankingOrder.DESCENDING
    selection_cutoffs: Sequence[RankCutoffIn] = Field(default_factory=list)
    selection_mode: SelectionMode = SelectionMode.ALL
    limit: Optional[int] = Field(default=None, gt=0)
    columns: Optional[Sequence[str]] = None
    format: ExportFormat = ExportFormat.XLSX

    @field_validator("selection_mode", mode="before")
    @classmethod
    def _normalize_selection_mode(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_clean = v.strip().lower()
            if v_clean in ("all", "any"):
                return SelectionMode(v_clean)
        return v


class RefreshRequestIn(BaseModel):
    """HTTP request specification for rebuilding the in-memory feature dataset."""
    symbols: Optional[Sequence[str]] = None
    symbol_limit: Optional[int] = Field(default=None, gt=0)
    provider: Optional[str] = None
    background: Optional[bool] = None
    force_refresh_bars: bool = False


# -----------------------------------------------------------------------------
# Input DTOs (Bands)
# -----------------------------------------------------------------------------

class BandUpdateIn(BaseModel):
    """HTTP request specification for updating a symbol's band width fraction."""
    timeframe: str = Field(pattern="^(D|W|M|Q|H|Y)$")
    value: float = Field(ge=0.0, le=1.0)


# -----------------------------------------------------------------------------
# Output DTOs (Presentation & Results)
# -----------------------------------------------------------------------------

class ColumnDefinitionOut(BaseModel):
    """Metadata for an exported or rendered display column."""
    key: str
    label: str
    category: str
    is_numeric: bool = True
    format_string: Optional[str] = None

    @classmethod
    def from_core(cls, col: ColumnDefinition) -> "ColumnDefinitionOut":
        return cls(
            key=col.key,
            label=col.label,
            category=col.category,
            is_numeric=col.is_numeric,
            format_string=col.format_string,
        )


class QueryResultOut(BaseModel):
    """HTTP presentation payload returned for table views and screening runs."""
    universe_count: int
    qualified_count: int
    selected_count: int
    columns: Sequence[ColumnDefinitionOut]
    rows: Sequence[Mapping[str, Any]]
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_core(cls, payload: QueryResultPayload) -> "QueryResultOut":
        return cls(
            universe_count=payload.universe_count,
            qualified_count=payload.qualified_count,
            selected_count=payload.selected_count,
            columns=[ColumnDefinitionOut.from_core(c) for c in payload.columns],
            rows=payload.rows,
            metadata=payload.metadata,
        )


class ScreenProgressOut(BaseModel):
    """Real-time progress reporting for an active or completed screening operation."""
    request_id: str
    status: str = Field(description="Task status: idle, running, cancelling, cancelled, completed, failed")
    progress: float = Field(ge=0.0, le=100.0, description="Percentage completion from 0.0 to 100.0")
    stage: str = Field(description="Current execution stage identifier")
    message: str = Field(description="Human-readable progress description")
    processed_count: int = Field(default=0, ge=0)
    total_count: int = Field(default=0, ge=0)


class ScreenCancelOut(BaseModel):
    """Response payload for screening cancellation request."""
    request_id: str
    status: str = Field(description="Cancellation status: cancelling, cancelled, completed, not_found")
    message: str = Field(description="Status description")


class StrategySummaryOut(BaseModel):
    """Summary of a registered strategy recipe or mentor preset."""
    name: str
    description: str
    is_mentor_preset: bool
    target_ranking_metric: Optional[str] = None


class StrategyDetailOut(BaseModel):
    """Detailed specification of a registered strategy recipe or mentor preset."""
    name: str
    description: Optional[str] = None
    is_mentor_preset: bool = False
    target_ranking_metric: Optional[str] = None
    target_cutoff_limit: Optional[int] = None
    ranking_metric: Optional[str] = None
    ranking_order: Optional[str] = "desc"
    limit: Optional[int] = None
    columns: Optional[Sequence[str]] = None
    filter_group: Optional[FilterGroupIn] = None
    selection_cutoffs: Sequence[RankCutoffIn] = Field(default_factory=list)


class UserPresetIn(BaseModel):
    """Payload to save or update a user-defined screening preset."""
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    filter_group: Optional[FilterGroupIn] = None
    ranking_metric: Optional[str] = None
    ranking_order: RankingOrder = RankingOrder.DESCENDING
    selection_cutoffs: Sequence[RankCutoffIn] = Field(default_factory=list)
    limit: Optional[int] = Field(default=None, gt=0)
    columns: Optional[Sequence[str]] = None


class UserPresetOut(BaseModel):
    """Serialized representation of a saved user preset."""
    name: str
    description: Optional[str] = None
    filter_group: Optional[FilterGroupIn] = None
    ranking_metric: Optional[str] = None
    ranking_order: RankingOrder = RankingOrder.DESCENDING
    selection_cutoffs: Sequence[RankCutoffIn] = Field(default_factory=list)
    limit: Optional[int] = None
    columns: Optional[Sequence[str]] = None
    created_at: Optional[str] = None


class TimeframeRowOut(BaseModel):
    """Multi-timeframe row metric for the drawer detail panel."""
    timeframe: str
    ema_state: Optional[str] = None
    band_state: Optional[str] = None
    band_distance: Optional[float] = None
    band_width: Optional[float] = None
    roc: Optional[float] = None
    speed: Optional[float] = None
    band_upper: Optional[float] = None
    band_lower: Optional[float] = None


class StockDetailPanelOut(BaseModel):
    """Authoritative multi-timeframe panel payload for the selected stock."""
    symbol: str
    exchange: Optional[str] = None
    price: Optional[float] = None
    name: Optional[str] = None
    sector: Optional[str] = None
    grade: Optional[str] = None
    mcap: Optional[float] = None
    fno: Optional[str] = None
    instr: Optional[str] = None
    grp: Optional[str] = None
    ic: Optional[str] = None
    ic_ratio: Optional[float] = None
    accel_l: Optional[float] = None
    accel_s: Optional[float] = None
    spr_consist: Optional[float] = None
    ath_diff: Optional[float] = None
    timeframes: Sequence[TimeframeRowOut] = Field(default_factory=list)
    key_metrics: Mapping[str, Any] = Field(default_factory=dict)


class BandUpdateOut(BaseModel):
    """Confirmation payload for a discretionary band update."""
    symbol: str
    timeframe: str
    value: float
    success: bool = True


class BandsResponseOut(BaseModel):
    """Full set of multi-timeframe band width fractions for a symbol."""
    symbol: str
    bands: Mapping[str, Optional[float]]


class CandleBarOut(BaseModel):
    """A single OHLCV candlestick bar formatted for financial charting."""
    time: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class BandCurvePointOut(BaseModel):
    """A single point on an envelope curve at a specific timestamp."""
    time: str  # YYYY-MM-DD
    value: float


class BandLevelOut(BaseModel):
    """Summary band parameters for the active chart timeframe."""
    timeframe: str
    band_timeframe: Optional[str] = None
    width: Optional[float] = None
    basis: Optional[float] = None
    upper: Optional[float] = None
    lower: Optional[float] = None
    band_distance: Optional[float] = None
    band_state: Optional[str] = None


class VolumePointOut(BaseModel):
    """Chronological volume data point."""
    time: str  # YYYY-MM-DD
    value: Optional[float] = None


class DMISeriesOut(BaseModel):
    """Wilder's DMI/ADX chronological time series."""
    plus: Sequence[BandCurvePointOut] = Field(default_factory=list)
    minus: Sequence[BandCurvePointOut] = Field(default_factory=list)
    adx: Sequence[BandCurvePointOut] = Field(default_factory=list)


class DMISummaryOut(BaseModel):
    """Summary DMI / ADX metrics for the active chart timeframe."""
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    adx: Optional[float] = None
    adxr: Optional[float] = None
    state: Optional[str] = None
    period: Optional[int] = None
    adx_period: Optional[int] = None


class BollingerSeriesOut(BaseModel):
    """Bollinger Bands chronological curves and latest values."""
    upper: Sequence[BandCurvePointOut] = Field(default_factory=list)
    lower: Sequence[BandCurvePointOut] = Field(default_factory=list)
    basis: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_upper: Optional[float] = None
    last_lower: Optional[float] = None
    last_basis: Optional[float] = None


class DonchianSeriesOut(BaseModel):
    """Donchian Channels chronological curves and latest values."""
    upper: Sequence[BandCurvePointOut] = Field(default_factory=list)
    lower: Sequence[BandCurvePointOut] = Field(default_factory=list)
    middle: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_upper: Optional[float] = None
    last_lower: Optional[float] = None
    last_middle: Optional[float] = None


class ATRBandsSeriesOut(BaseModel):
    """ATR Volatility Bands chronological curves and latest values."""
    upper: Sequence[BandCurvePointOut] = Field(default_factory=list)
    lower: Sequence[BandCurvePointOut] = Field(default_factory=list)
    atr: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_upper: Optional[float] = None
    last_lower: Optional[float] = None
    last_atr: Optional[float] = None


class RSISeriesOut(BaseModel):
    """Relative Strength Index chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_rsi: Optional[float] = None


class MACDSeriesOut(BaseModel):
    """Moving Average Convergence Divergence chronological curves and latest values."""
    macd: Sequence[BandCurvePointOut] = Field(default_factory=list)
    signal: Sequence[BandCurvePointOut] = Field(default_factory=list)
    histogram: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_macd: Optional[float] = None
    last_signal: Optional[float] = None
    last_histogram: Optional[float] = None


class OBVSeriesOut(BaseModel):
    """On-Balance Volume chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_obv: Optional[float] = None


class MFISeriesOut(BaseModel):
    """Money Flow Index chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    last_mfi: Optional[float] = None


class YSprintSeriesOut(BaseModel):
    """YOGI Sprint Speed chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    weeks: int = 4
    last_speed: Optional[float] = None


class YAccelSeriesOut(BaseModel):
    """YOGI Acceleration chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    short_weeks: int = 4
    long_weeks: int = 52
    last_accel: Optional[float] = None


class YBandSeriesOut(BaseModel):
    """YOGI Band Distance chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    basis_window: int = 20
    band_frac: Optional[float] = None
    last_distance: Optional[float] = None


class YRocSeriesOut(BaseModel):
    """YOGI ROC (21d) chronological curve and latest value."""
    points: Sequence[BandCurvePointOut] = Field(default_factory=list)
    days: int = 21
    last_roc: Optional[float] = None


class CandleSeriesOut(BaseModel):
    """Complete financial charting payload for TradingView Lightweight Charts."""
    symbol: str
    exchange: str
    timeframe: str
    candles: Sequence[CandleBarOut]
    band_upper_curve: Sequence[BandCurvePointOut]
    band_lower_curve: Sequence[BandCurvePointOut]
    latest_band: Optional[BandLevelOut] = None
    basis_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    ema3_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    ema5_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    volume_curve: Sequence[VolumePointOut] = Field(default_factory=list)
    dmi_series: Optional[DMISeriesOut] = None
    dmi_summary: Optional[DMISummaryOut] = None
    ath_diff: Optional[float] = None
    bollinger: Optional[BollingerSeriesOut] = None
    donchian: Optional[DonchianSeriesOut] = None
    atr_bands: Optional[ATRBandsSeriesOut] = None
    vwap_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    avg_price: Optional[float] = None
    rsi: Optional[RSISeriesOut] = None
    macd: Optional[MACDSeriesOut] = None
    obv: Optional[OBVSeriesOut] = None
    mfi: Optional[MFISeriesOut] = None
    rsi_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    obv_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    mfi_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    y_sprint: Optional[YSprintSeriesOut] = None
    y_accel: Optional[YAccelSeriesOut] = None
    y_band: Optional[YBandSeriesOut] = None
    y_roc: Optional[YRocSeriesOut] = None
    y_sprint_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    y_accel_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    y_band_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)
    y_roc_curve: Sequence[BandCurvePointOut] = Field(default_factory=list)


class RacePointOut(BaseModel):
    """Single chronological data point on a sprint race line."""
    time: str
    value: float


class RaceLineOut(BaseModel):
    """Sprint race trajectory line for a single security."""
    symbol: str
    label: str
    points: Sequence[RacePointOut]
    final: float


class RaceResponseOut(BaseModel):
    """Complete sprint race multi-line time-series response."""
    anchor: str
    lines: Sequence[RaceLineOut]
    asked: int
    note: str = ""
    timeframe: str = "W"


class SystemStatusOut(BaseModel):
    """System health and in-memory feature cache status."""
    status: str = "READY"
    universe_count: int
    last_built_at: Optional[str] = None
    exchange: str = "NSE"
    provider: str = "yfinance"
    is_demo: bool = False
    half_year_policy: str = "prototype"
    is_cached: bool = False
    build_status: Optional[str] = None
    progress: Optional[float] = None
    progress_stage: Optional[str] = None
    error: Optional[str] = None


class SystemSettingsOut(BaseModel):
    """System-wide configuration settings."""
    half_year_policy: str = "prototype"


class SystemSettingsUpdateIn(BaseModel):
    """System-wide configuration settings update request."""
    half_year_policy: str


# -----------------------------------------------------------------------------
# Translation Utilities (HTTP DTO -> Core Contracts)
# -----------------------------------------------------------------------------

def to_core_filter_group(group_in: Optional[FilterGroupIn]) -> Optional[FilterGroupSpec]:
    """Convert an incoming FilterGroupIn DTO to the frozen Core FilterGroupSpec."""
    if group_in is None:
        return None
    core_rules = []
    for r in group_in.rules:
        if isinstance(r, FilterGroupIn):
            nested = to_core_filter_group(r)
            if nested is not None:
                core_rules.append(nested)
        elif isinstance(r, FilterRuleIn):
            core_rules.append(r.to_core_spec())
        elif isinstance(r, dict):
            if "rules" in r:
                nested = to_core_filter_group(FilterGroupIn(**r))
                if nested is not None:
                    core_rules.append(nested)
            else:
                core_rules.append(FilterRuleIn(**r).to_core_spec())
    return FilterGroupSpec(
        match=group_in.match,
        rules=core_rules,
        is_negated=group_in.is_negated,
    )


def from_core_filter_group(group_spec: Optional[FilterGroupSpec]) -> Optional[FilterGroupIn]:
    """Convert a frozen Core FilterGroupSpec to a FilterGroupIn DTO for HTTP serialization."""
    if group_spec is None:
        return None
    rules_out: list[Union[FilterRuleIn, FilterGroupIn]] = []
    for r in group_spec.rules:
        if isinstance(r, FilterGroupSpec):
            nested = from_core_filter_group(r)
            if nested is not None:
                rules_out.append(nested)
        elif isinstance(r, FilterRuleSpec):
            rules_out.append(
                FilterRuleIn(
                    field=r.field,
                    op=r.op,
                    value=r.value,
                    field2=r.field2,
                    is_negated=r.is_negated,
                    condition_type=r.condition_type,
                    params=dict(r.params) if r.params else {},
                    timeframe=r.timeframe,
                    p1=r.p1,
                    p2=r.p2,
                    state=r.state,
                    lookback=r.lookback,
                )
            )
    return FilterGroupIn(
        match=group_spec.match,
        rules=rules_out,
        is_negated=group_spec.is_negated,
    )


def to_core_cutoffs(cutoffs_in: Sequence[RankCutoffIn]) -> tuple[RankCutoffSpec, ...]:
    """Convert incoming RankCutoffIn DTOs to frozen Core RankCutoffSpec instances."""
    return tuple(
        RankCutoffSpec(rank_metric=c.metric, max_rank=c.max_rank, min_periods=c.min_periods)
        for c in cutoffs_in
    )


def to_screening_query(
    filter_group: Optional[FilterGroupIn] = None,
    ranking_metric: Optional[str] = None,
    ranking_order: RankingOrder = RankingOrder.DESCENDING,
    selection_cutoffs: Sequence[RankCutoffIn] = (),
    selection_mode: SelectionMode = SelectionMode.ALL,
    limit: Optional[int] = None,
) -> ScreeningQuery:
    """Build a frozen ScreeningQuery free of presentation columns."""
    return ScreeningQuery(
        filter_group=to_core_filter_group(filter_group),
        ranking_metric=ranking_metric,
        ranking_order=ranking_order,
        selection_cutoffs=to_core_cutoffs(selection_cutoffs),
        selection_mode=selection_mode,
        limit=limit,
    )


# -----------------------------------------------------------------------------
# Output DTOs (Band Audit, Backups & Restore)
# -----------------------------------------------------------------------------

class BandAuditItemOut(BaseModel):
    """A single band change audit entry matching prototype log presentation."""
    when: str
    symbol: str
    timeframe: str
    old_pct: str
    new_pct: str
    changed_by: str
    source: str


class BandLogResponseOut(BaseModel):
    """Response containing band change audit history for a single symbol."""
    symbol: str
    changes: Sequence[BandAuditItemOut] = Field(default_factory=list)


class BandGlobalLogResponseOut(BaseModel):
    """Response containing global band change audit history across all symbols."""
    changes: Sequence[BandAuditItemOut] = Field(default_factory=list)


class BandBackupItemOut(BaseModel):
    """Metadata describing an available dated band backup snapshot."""
    file: str
    date: str
    stocks: Optional[int] = None
    size_kb: float


class BandBackupsResponseOut(BaseModel):
    """Response containing available dated band backups."""
    backups: Sequence[BandBackupItemOut] = Field(default_factory=list)


class BandRestoreResponseOut(BaseModel):
    """Response describing the outcome of a band restore operation."""
    ok: bool
    msg: str
    filename: Optional[str] = None
    stocks: Optional[int] = None


# -----------------------------------------------------------------------------
# Output DTOs (Security Metadata)
# -----------------------------------------------------------------------------

class MetadataResponseOut(BaseModel):
    """Canonical security metadata response."""
    symbol: str
    exchange: str = "NSE"
    name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    grade: Optional[str] = None
    is_fno: bool = False
    fno: str = "N"
    mcap: Optional[float] = None
    instrument_type: str = "EQ"
    listing_status: str = "ACTIVE"
    series_or_group: Optional[str] = None
    notes: Optional[str] = None


class MetadataUpdateIn(BaseModel):
    """Specification for updating a single security metadata field."""
    field: str
    value: Any = None


class MetadataUpdateOut(BaseModel):
    """Confirmation payload for a metadata update."""
    symbol: str
    field: str
    value: Any = None
    success: bool = True




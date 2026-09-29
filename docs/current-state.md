# YOGI Current State

## Current State: MVP Backend + Batches 1–5 + Batches U1–U2 Complete & Frozen

**Date**: 2026-09-29  
**Status**: MVP Backend & Analytical Engine + Batches 1–5 + Batch U1 (Stock Detail) + Batch U2 (Unified Screening Workspace) VERIFIED & FROZEN | Master Cockpit UX Prototype Verified | Architectural Parity & Zero JS Math Maintained | Test Suite: 580 passed across unit, integration, live smoke, and golden regression suites.

---

## 1. Implemented & Verified Components

### Step 1: Foundation (FROZEN)
- Standard packaging configured via `pyproject.toml` with `pytest` and `anyio` test runners.
- Canonical directory structure established under `src/yogi/`, `tests/`, and `docs/`.

### Step 2: Core Contracts (`src/yogi/core/contracts/`) (FROZEN)
- Ten authoritative contract modules defining immutable DTOs, protocols, and enums:
  - `market_data.py`: `MarketBar`, `TickData`, `MarketContext`, `Timeframe`.
  - `provider.py`: `IDataProvider`, `ProviderHealth`.
  - `calculation.py`: `ICalcModule`, `CalculationContext`, `CalculationResult`.
  - `bands.py`: `IBandsRepository`, `BandEntry`, `BandAuditEntry`, `BandBackupInfo`, `IBandAuditRepository`, `IBandBackupService`, `BAND_TIMEFRAMES`.
  - `filter.py`: `IFilterRule`, `FilterOperator`, `FilterRuleSpec`, `FilterGroupSpec`, `FilterStepMetric`, `FilterEvaluationResult`.
  - `strategy.py`: `IStrategy`, `StrategySpec`, `StrategyValidationResult`.
  - `ranking.py`: `IRankingRule`, `RankingOrder`, `RankingMethod`, `RankingResult`.
  - `selection.py`: `ISelectionRule`, `SelectionMode`, `RankCutoffSpec`, `SelectionResult`.
  - `results.py`: `IResultAssembler`, `IExportFormatter`, `ColumnDefinition`, `QueryResultPayload`, `ExportFormat`.
  - `security.py`: `SecurityMetadata`, `InstrumentType`, `ListingStatus`, `ISecurityMetadataRepository` (authoritative metadata repository contract added in Batch 5; no independent `ISecurityMaster` registry category exists per [ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution)).
- Verified by `tests/core/test_contracts.py` (7/7 tests passing).

### Step 3: Core Registry (`src/yogi/core/registry/`) (FROZEN)
- `CapabilityRegistry[T]`: Generic, type-safe implementation registry with lazy factory evaluation, instance caching, and collision detection.
- `RegistryHub`: Container exposing strictly the three approved capability categories per [ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution):
  - `providers`: `CapabilityRegistry[IDataProvider]`
  - `calculations`: `CapabilityRegistry[ICalcModule]`
  - `bands`: `CapabilityRegistry[IBandsRepository]`
- Does NOT serve as a universal registry; does not expose categories for filters, rankings, selections, strategies, or results.
- Verified by `tests/core/test_registry.py` (13/13 tests passing).

### Step 4: Core Configuration (`src/yogi/core/configuration/`) (FROZEN)
- `EngineConfig`: Immutable system-level pipeline configuration specifying capability keys (`provider`, `bands_repository`, `calculation_modules`, `exchange`, `timeframes`, limits).
- `ScreeningQuery`: Immutable query intent strictly mapping to `QUALIFY → ORDER → SHOW`. Excludes display column projection per [ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation).
- `StrategyCatalog`: In-memory catalog of named `StrategySpec` recipes (including mentor presets), translating recipes into executable `ScreeningQuery` instances.
- Verified by `tests/core/test_configuration.py` (12/12 tests passing).

### Step 5: Core Orchestration (`src/yogi/core/orchestration/`) (FROZEN)
- `PipelineOrchestrator`: Pure coordinator managing data acquisition, timeframe synthesis, calculation dispatch, and the three-stage screening pipeline.
- Public methods:
  - `build_dataset(config: EngineConfig) -> Mapping[str, Mapping[str, Any]]`
  - `execute_screen(query: ScreeningQuery, records: Mapping[str, Mapping[str, Any]], ...) -> QueryResultPayload`
  - `run(config: EngineConfig, query: Optional[ScreeningQuery] = None) -> QueryResultPayload`
- Resolves capabilities exclusively through `RegistryHub`. Contains zero financial formulas, resampling logic, or filtering math.
- Preserves assigned rank ordering across dynamic cohort rankings.
- Verified by `tests/core/test_orchestration.py` (17/17 tests passing).

### Step 6: Data Providers & Normalization (`src/yogi/data/`) (FROZEN)
- `normalization/bars.py`: Pure normalizers converting raw vendor payloads into frozen `MarketBar` and `TickData` DTOs (including `normalize_twelve_data_bars` and `normalize_twelve_data_batch`).
- `normalization/universe.py`: Pure normalizers discovering NSE equity symbols (strictly filtering `SERIES == 'EQ'`) and BSE scrip codes with offline fallbacks.
- `providers/demo.py`: `DemoDataProvider` implementing `IDataProvider` relocated from `cockpit/` to `src/yogi/data/providers/demo.py` per architectural correction YOGI-F02, providing deterministic offline fixtures for the 5 golden stocks and mock universe.
- `providers/yfinance.py`: `YFinanceDataProvider` implementing `IDataProvider` with daily/intraday history, universe discovery, health checks, and offline injection.
- `providers/zerodha.py`: `ZerodhaDataProvider` implementing `IDataProvider` with Kite Connect 1-year historical chunking, KiteTicker live ticks, and offline test injection.
- `providers/twelve_data.py`: `TwelveDataProvider` implementing `IDataProvider` using Twelve Data REST API (`/time_series`, `/price`, `/stocks`), batching with configurable chunk size, symbol/exchange translation (`twelve_data_symbol`), secret masking, and offline test injection ([ADR-009](decisions.md#adr-009-twelve-data-provider-adapter-integration)). Configured via `TWELVE_DATA_API_KEY` (or `TWELVEDATA_API_KEY`) environment variable or direct instantiation. Registered in `RegistryHub.providers` under `"twelvedata"` / `"twelve_data"`. Free-tier characteristics: 8 credits/min limit; batch requests consume 1 credit per symbol; benchmark equity `INFY` serves as health check.
- `providers/exceptions.py`: `DataProviderError`, `DataProviderAuthenticationError`, and `DataProviderRateLimitError` defining explicit failure boundaries.
- Verified by `tests/data/test_normalization.py` (11/11), `tests/data/test_yfinance_provider.py` (18/18), `tests/data/test_zerodha_provider.py` (18/18), and `tests/data/test_twelve_data_provider.py` (33/33 tests passing, including live smoke test) (80/80 tests passing).

### Step 7: Timeframe Engine (`src/yogi/timeframe/`) (FROZEN)
- `engine.py`: Pure multi-timeframe candle synthesis (`resample_bars`, `build_market_context`, `TimeframeEngine`, `TIMEFRAME_RULES`) ([ADR-007](decisions.md#adr-007-timeframe-engine-bounded-responsibility)).
- Supports `D` $\to$ `W`, `M`, `Q`, `H`, `Y` using verified frequency aliases (`D=None`, `W="W"`, `M="ME"`, `Q="QE"`, `H="2QE"`, `Y="YE"`).
- Preserves OHLCV aggregation semantics (Open=first, High=max, Low=min, Close=last, Volume=sum), period-end boundary timestamps, None volume preservation, chronological pre-sorting, deterministic deduplication (last occurrence), and incomplete period aggregation without padding.
- Verified by `tests/timeframe/test_synthesis.py` (25/25 tests passing).

### Step 8: Calculation Modules (`src/yogi/calculation/`)
- Analytical calculation modules satisfying `ICalcModule` registered in `RegistryHub.calculations` ([ADR-008](decisions.md#adr-008-calculation-engine-modularization--four-mathematical-pillars)):
  - `BandsCalculator` (`"bands"`): Envelope levels, positions, states (`ABOVE`, `BELOW`, `IN`, `na`), distances beyond edge (`BD_*`), and multi-timeframe counts. Authoritative envelope mathematics centralized in `calculate_band_envelope()` returning `BandEnvelopeResult` (YOGI-F03), serving as the single mathematical source of truth across Core feature generation and Cockpit chart curves.
  - `VelocityCalculator` (`"velocity"`): Rolling sprint speeds (`S4`..`S52`), accelerations (`ACCEL_S`, `ACCEL_L`), consistency flags (`SPR_CONSIST`), authoritative anchored sprints (`SPA_A*`), and sprint race cumulative return time-series math via `calculate_anchored_curve` / `anchored_curve`.
  - `ImpulseCalculator` (`"impulse"`): Zigzag swing pivots and Ram's 50% recovery validation (`IC="IP"|"CR"|"up"|"na"`, `IC_PCT`, `IC_BARS`, `IC_RATIO`).
  - `TrendCalculator` (`"trend"`): Trailing ROCs (`DROC`..`YROC`), calendar blocks (Quarter, Half, Year), multi-year CAGRs, ATH diff, EMA 3/5 ribbon states, `SUSPECT` data sanity flag, and DMI/ADX.
  - `CandleCalculator` (`"candles"`): Multi-timeframe candlestick shape metrics and pattern recognition ported with strict prototype parity from `yogi/theories/candles.py`. Computes 38 fields per timeframe (with volume, 35 without) across 6 timeframes (`CD_`, `CW_`, `CM_`, `CQ_`, `CH_`, `CY_`), totaling 228 fields (or 210 without volume). Evaluates 20 distinct pattern flags (`BULL_ENGULF`, `BEAR_ENGULF`, `DOJI`, `HAMMER`, `SHOOTSTAR`, `MARUBOZU`, `INSIDE`, `OUTSIDE`, `BREAKOUT`, `BREAKDOWN`, `HIGHER_HIGH`, `HIGHER_LOW`, `THREE_UP`, `THREE_DN`, `CLOSE_STRONG`, `CLOSE_WEAK`, `BIG_RANGE`, `VOL_SPIKE`), directional `GREEN` categorical flag, and volume ratios (`VOL_X`). Default thresholds configured in `src/yogi/calculation/candles/rules.py` matching prototype `candle_rules.py`, overridable via `context.parameters`.
  - **Batch 3B Pure Price & Volatility Indicators**:
    - `calculate_bollinger_bands()` in `calculation/bands`: 20-period moving average with 2-standard-deviation envelope (`basis +/- 2*sd`).
    - `calculate_donchian_channels()` in `calculation/bands`: 20-period rolling high/low channel with midpoint (`(upper + lower) / 2`).
    - `calculate_true_range()`, `calculate_atr()`, and `calculate_atr_bands()` in `calculation/bands`: 14-period simple rolling mean ATR with 2.0x offset envelope (`close +/- 2*atr`).
    - `calculate_vwap()` in `calculation/trend`: Cumulative Volume-Weighted Average Price across visible chart history window (`cumsum(tp * vol) / cumsum(vol)`).
    - `average_price()` in `calculation/trend`: Mean closing price across the series (`close.mean()`).
  - **Oscillators (Batch 3C Parity)**: Pure mathematical implementations in `src/yogi/calculation/trend/calculator.py` with zero presentation logic:
    - `calculate_rsi()`: Relative Strength Index over 14 periods using simple rolling mean (SMA) of gains and losses (`100 - (100 / (1 + RS))`), matching prototype `routes.py:125-128`.
    - `calculate_macd()`: Moving Average Convergence Divergence reusing authoritative `ema(span=..., adjust=False)` (`macd = ema(12) - ema(26)`, `signal = ema(macd, 9)`, `histogram = macd - signal`), matching prototype `routes.py:129-130`.
    - `calculate_obv()`: On-Balance Volume cumulative volume signed by price delta (`(sign(diff(close)) * volume).cumsum()`), matching prototype `routes.py:145-146`.
    - `calculate_mfi()`: Money Flow Index over 14 periods via typical price money flow ratio (`100 - (100 / (1 + MFR))`), matching prototype `formulas.py:597-606`.
  - **YOGI Custom Analytical Curves (Batch 3D Parity)**: Pure continuous time-series curves implemented strictly within authoritative calculation modules:
    - `calculate_sprint_speed_curve()` in `calculation/velocity`: Rolling sprint speed (%/week over `weeks * 5` trading days, default 4 weeks) matching prototype `formulas.py:559-565`.
    - `calculate_acceleration_curve()` in `calculation/velocity`: Rolling acceleration differential (`short_weeks` speed minus `long_weeks` speed, default 4w vs 52w) matching prototype `formulas.py:568-572`.
    - `calculate_band_distance_curve()` in `calculation/bands`: Rolling band distance (% beyond envelope edge: + above, - below, 0 inside) reusing authoritative envelope math matching prototype `formulas.py:575-588`.
    - `calculate_roc_curve()` in `calculation/trend`: Rolling Rate of Change over trailing `days` trading bars (default 21 days) matching prototype `formulas.py:591-594`.
- **DMI Semantic Fidelity**:
  - `dmi_settings()` defaults to `(5, 5)` matching prototype `candle_rules.DEFAULTS`, overridable via `context.parameters`.
  - Standalone `dmi()` function signature default remains Wilder's `(14, 14)`.
  - When DMI is active, all six timeframes (`D, W, M, Q, H, Y`) are populated in `metrics`; timeframes with $< 6$ bars receive `None` numeric values and `"na"` state.
  - Close-only data (high == low) omits DMI keys, preserving exact parity with golden regression fixtures.
- Verified by:
  - Unit tests: `tests/calculation/test_bands.py` (15/15), `tests/calculation/test_velocity.py` (12/12), `tests/calculation/test_impulse.py` (9/9), `tests/calculation/test_trend.py` (34/34), `tests/calculation/test_candles.py` (10/10), `tests/calculation/test_price_volatility_indicators.py` (12/12), `tests/calculation/test_oscillators.py` (9/9), `tests/calculation/test_custom_curves.py` (15/15) (116/116 tests passing).
  - Golden regression tests: `tests/regression/test_golden_calculations.py` (6/6 tests passing, 0 numerical drift across all 5 golden stocks against `expected.json`).
  - Pipeline integration tests: `tests/pipeline/test_calculation_integration.py` (4/4 tests passing).
  - Total calculation suite: 126/126 tests passing.

### Step 9: Screening Engine (`filter/`, `ranking/`, `selection/`, `strategy/`) (FROZEN)
- **Filter Engine (`src/yogi/filter/`)**:
  - `FilterEngine` implementing `IFilterRule`: pure boolean qualification evaluation ("Does it qualify?").
  - Evaluates leaf rules (`FilterRuleSpec`) across all 12 operators (`>`, `>=`, `<`, `<=`, `==`, `!=`, `in`, `not_in`, `between`, `blank`, `not_blank`, `contains`).
  - Supports cross-column comparisons (`field2`), case-insensitive string operations, missing/NaN safe handling, and rule-level negation (`is_negated`).
  - Evaluates recursive nested groups (`FilterGroupSpec`) supporting `match="all"` (AND) and `match="any"` (OR) logic, group negation, top-level funnel step telemetry (`FilterStepMetric`), and human-readable explanation sentences.
- **Ranking Engine (`src/yogi/ranking/`)**:
  - `RankingEngine` implementing `IRankingRule`: ordinal relative standing evaluation ("Where does it stand?").
  - Supports `RankingOrder.DESCENDING` and `ASCENDING`.
  - Implements `RankingMethod.MIN` (prototype tie standard), `DENSE`, and `AVERAGE`.
  - Secondary deterministic tie-breaker on symbol ascending.
  - Missing/NaN values placed strictly last (`na_position="last"`) without dropping any records.
  - Supports optional cohort partitioning via `group_by`.
  - Computes `rank_changes` deltas (e.g. `M_CUR` rank vs `M_P1` rank, where positive = climbing).
- **Selection Engine (`src/yogi/selection/`)**:
  - `SelectionEngine` implementing `ISelectionRule`: authoritative rank threshold evaluation ("Does its rank qualify?").
  - Evaluates `RankCutoffSpec(rank_metric, max_rank, min_periods)`.
  - Supports `SelectionMode.ALL` (intersection) and `SelectionMode.ANY` (union).
  - Resolves rank columns robustly across dynamic injected columns and timeframe aliases.
  - Strictly preserves the incoming authoritative order established by RankingEngine without performing any sorting or re-ranking.
  - Strict architectural separation: qualifies candidates analytically without presentation row truncation (`query.limit`).
- **Strategy Engine & Presets (`src/yogi/strategy/`)**:
  - `Strategy` implementing `IStrategy`: encapsulates immutable `StrategySpec` recipes and performs structural field/operator validation.
  - **The 21 Verified Mentor Presets** (`presets.py`): Faithful replication of prototype `LISTS_LOGIC.txt` and `verify_lists.py`:
    - Group A (Impulse/Rally): `A1_IMPULSE_CONFIRMED`, `A2_ALL_6_TF_EMA_UP`, `A3_FRESH_MONTHLY_UPCUT`, `A4_FRESH_WEEKLY_UPCUT`.
    - Group B (Sprint/Momentum): `B1_SPRINTERS_MONTH`, `B2_SPRINTERS_QUARTER`, `B3_SPRINTERS_YEAR`, `B4_ACCELERATING`, `B5_ACCEL_AND_EMA_UP`, `B6_CONSISTENT_RUNNERS`, `B7_IN_IMPULSE`, `B8_IN_CORRECTION`.
    - Group C (Band Breakouts): `C1_BROKE_ABOVE_BAND`, `C2_BROKE_BELOW_BAND`, `C3_OUTSIDE_BAND_2PLUS_TF`, `C4_REACTION_TRADE`.
    - Group D (Exit Signals): `D1_EXIT_FNO`, `D2_EXIT_CASH`.
    - Group E (Ranking/Cutoffs): `E1_TOP_100_MONTH`, `E2_TOP_100_YEAR`, `E3_RANK_CLIMBERS`.
  - `load_mentor_presets(catalog)`: Populates `StrategyCatalog` with all 21 verified mentor presets.
- Verified by:
  - `tests/filter/test_filter_engine.py` (13/13 tests passing).
  - `tests/ranking/test_ranking_engine.py` (8/8 tests passing).
  - `tests/selection/test_selection_engine.py` (10/10 tests passing).
  - `tests/strategy/test_strategy_engine.py` (3/3 tests passing).
  - `tests/strategy/test_mentor_presets.py` (7/7 tests passing).
  - `tests/pipeline/test_screening_integration.py` (5/5 tests passing).
  - Total screening suite: 46/46 tests passing.

### Step 10: Results Engine (`src/yogi/results/`) (FROZEN)
- `columns.py`: Strongly typed `ColumnDefinition` factory (`build_column_definition`), category inference (`categorize_column`), human-readable labels (`derive_label`), and curated `DEFAULT_SUMMARY_COLUMNS` adapted from prototype `available_fields`.
- `assembler.py`: `ResultAssembler` implementing `IResultAssembler`:
  - Strictly adheres to presentation packaging: does NOT filter, rank, select, sort, or slice records.
  - Preserves incoming record order from upstream stages.
  - Projects specified or default summary columns, automatically including active dynamic `RANK_*` columns.
  - Normalizes missing and `NaN` values to `None` (RFC 8259 compliant).
  - Handles unknown requested columns gracefully by producing `None` without raising `KeyError`.
  - Attaches summary metadata and column definitions into `QueryResultPayload`.
- `formatter.py`: `ExportFormatter` implementing `IExportFormatter`:
  - Strictly produces in-memory bytes without writing files to disk.
  - `ExportFormat.CSV`: RFC 4180 standard CSV bytes via `csv.writer`, empty string for `None`.
  - `ExportFormat.JSON`: Formatted UTF-8 JSON bytes with `NaN` sanitized to `null` and `allow_nan=False`.
  - `ExportFormat.XLSX`: Styled Excel workbook bytes using `openpyxl` with dark headers (`#1F2430` fill, `#FFB055` font), auto-filter, freeze panes at `B2`, and cell number formatting (`"0"` for ranks, `"0.00"` for floats).
- Verified by:
  - `tests/results/test_assembler.py` (8/8 tests passing).
  - `tests/results/test_formatter.py` (6/6 tests passing).
  - `tests/pipeline/test_results_integration.py` (2/2 tests passing).
  - Total results suite: 16/16 tests passing.

### Step 11: Cockpit & API Layer (`src/yogi/cockpit/`) — Unified UX Redesign & Architectural Remediation (FROZEN)
- Interactive web Cockpit, FastAPI transport controllers, and presentation application services redesigned around "Full Control Without Complexity":
  - `app.py`: FastAPI application factory (`create_app`) configuring CORS middleware, async startup lifespan for dataset pre-warming, API router mounting, and static assets delivery.
  - `router.py`: Fourteen pure HTTP transport endpoints (`/api/status`, `/api/dataset/refresh`, `/api/table`, `/api/screen`, `/api/strategies`, `/api/strategies/{name}`, `/api/user-presets`, `/api/user-presets/{name}`, `/api/strategy/run`, `/api/bands/{symbol}`, `/api/candles/{symbol}`, `/api/panel/{symbol}`, `/api/race`, `/api/export`).
    - Handlers contain ZERO analytical business or filtering math; all logic delegates to Core or application services.
    - Explicit HTTP status mappings: 401 for provider authentication/authorization failures, 429 for provider rate-limit exhaustion, 503 for provider unavailability / service outage, and 404 for unknown or unavailable symbols.
  - `state.py`: `AppState` container managing the in-memory feature dataset cache with `freeze_dataset()` enforcing recursive deep immutability via `types.MappingProxyType`.
    - **Stock Detail Drawer Resolution (YOGI-F05)**: When a requested symbol is absent from `self._dataset`, on-demand calculation is resolved through the canonical pipeline `PipelineOrchestrator.build_dataset(EngineConfig(symbols=[sym]))`. Zero mutations or merges into `self._dataset`.
    - **Bounded Ephemeral Panel Cache (YOGI-F05)**: Successful on-demand panel records are cached in a thread-safe, bounded LRU cache `_panel_cache` (max 100 entries). Purged on provider switch to enforce Demo/Live isolation.
    - User preset persistence (`list_user_presets`, `get_user_preset`, `save_user_preset`, `delete_user_preset`) with disk fallback (`data/user_presets.json`).
    - Declarative strategy detail extraction (`get_strategy_detail`).
    - Multi-timeframe stock panel synthesis (`get_stock_panel`).
  - `charting.py`: `ChartDataService` presentation service synthesizing OHLCV candlestick bars and rolling envelope curves for TradingView Lightweight Charts:
    - Delegates rolling band envelope math directly to Core `calculate_band_envelope()`, eliminating formula duplication (YOGI-F03).
    - **Cross-Timeframe Band Envelope Synthesis (Batch 2 Parity)**: Decoupled `band_timeframe` parameter in `get_candles()` supporting cross-timeframe envelope scaling (e.g., Daily candles with Monthly band width) and envelope suppression (`"", "NONE", "OFF"`). Adheres strictly to prototype semantics: the 20-bar basis is always computed on the candle timeframe closing prices, while the width fraction is looked up from the selected band timeframe.
    - **Existing Technical-Series Exposure (Batch 3A Parity)**: Exposes existing authoritative backend calculations cleanly to `CandleSeriesOut` without new financial formulas in Cockpit: EMA3, EMA5, SMA20 basis curve, volume curve, Wilder's DMI/ADX chronological time series (`plus`, `minus`, `adx`) and summary state, and ATH drawdown.
    - **Price / Volatility Technical Indicators (Batch 3B Parity)**: Exposes pure mathematical indicator series cleanly through `ChartDataService` without domain logic or financial formulas in the presentation layer:
      - Bollinger Bands (20, 2): `bollinger` (`upper`, `lower`, `basis`, `last_upper`, `last_lower`, `last_basis`).
      - Donchian Channels (20): `donchian` (`upper`, `lower`, `middle`, `last_upper`, `last_lower`, `last_middle`).
      - ATR Volatility Bands (14, 2.0): `atr_bands` (`upper`, `lower`, `atr`, `last_upper`, `last_lower`, `last_atr`).
      - Cumulative VWAP: `vwap_curve` (`BandCurvePointOut` sequence matching visible chart window).
      - Average Price Line: `avg_price` (mean close level matching `routes.py:232`).
    - **Oscillators Presentation Exposure (Batch 3C Parity)**: Exposes pure mathematical oscillator series cleanly through `ChartDataService` without domain logic or financial formulas in the presentation layer:
      - RSI (14): `rsi` (`RSISeriesOut` with `curve`, `period`, `last_rsi`, `overbought=70`, `oversold=30`) and `rsi_curve`.
      - MACD (12, 26, 9): `macd` (`MACDSeriesOut` with `macd_curve`, `signal_curve`, `histogram_curve`, `fast=12`, `slow=26`, `signal=9`, `last_macd`, `last_signal`, `last_histogram`).
      - OBV: `obv` (`OBVSeriesOut` with `curve`, `last_obv`) and `obv_curve`.
      - MFI (14): `mfi` (`MFISeriesOut` with `curve`, `period`, `last_mfi`, `overbought=80`, `oversold=20`) and `mfi_curve`.
    - **YOGI Custom Analytical Curves Presentation Exposure (Batch 3D Parity)**: Exposes pure mathematical continuous curves cleanly through `ChartDataService` without domain logic or financial formulas in the presentation layer:
      - YOGI Sprint Speed (4w): `y_sprint` (`YSprintSeriesOut` with `points`, `weeks=4`, `last_speed`) and `y_sprint_curve`.
      - YOGI Acceleration (4w vs 52w): `y_accel` (`YAccelSeriesOut` with `points`, `short_weeks=4`, `long_weeks=52`, `last_accel`) and `y_accel_curve`.
      - YOGI Band Distance: `y_band` (`YBandSeriesOut` with `points`, `basis_window=20`, `band_frac`, `last_distance`) and `y_band_curve`.
      - YOGI ROC (21d): `y_roc` (`YRocSeriesOut` with `points`, `days=21`, `last_roc`) and `y_roc_curve`.
    - **Bounded Chart Data Cache (YOGI-F04)**: Thread-safe bounded LRU cache (`max_entries=100`, `ttl_seconds=300.0`, `_cache_lock`), deterministic LRU eviction (`OrderedDict.popitem(last=False)`), TTL staleness check, and automatic invalidation on provider switch.
  - `services/race.py`: `RaceDataService` presentation service orchestrating sprint race time-series curve generation from fixed anchor dates across multiple stocks:
    - Auto-picks leading candidates from `_dataset` (excluding `SUSPECT == 'Y'` or corrupt returns) when symbols are omitted, or computes for explicitly passed symbols.
    - Fetches daily history via `IDataProvider` and executes authoritative `calculate_anchored_curve()`.
    - Implements bounded LRU caching (`max_entries=50`, `ttl_seconds=300.0`) with thread lock and provider-switch clearance.
  - `schemas.py`: Pydantic v2 DTOs supporting recursive arbitrary Boolean trees (`FilterGroupIn` with nested rules and `is_negated`), column-to-column comparisons (`field2`), preset inspection (`StrategyDetailOut`), user preset persistence (`UserPresetIn`, `UserPresetOut`), multi-timeframe drawer responses (`StockDetailPanelOut`, `TimeframeRowOut`), sprint race responses (`RacePointOut`, `RaceLineOut`, `RaceResponseOut`), cross-timeframe charting metadata (`BandLevelOut` with `band_timeframe`), technical-series curve models (`VolumePointOut`, `DMISeriesOut`, `DMISummaryOut`), Batch 3B indicator models (`BollingerSeriesOut`, `DonchianSeriesOut`, `ATRBandsSeriesOut`), Batch 3C oscillator models (`RSISeriesOut`, `MACDSeriesOut`, `OBVSeriesOut`, `MFISeriesOut`), Batch 3D custom curve models (`YSprintSeriesOut`, `YAccelSeriesOut`, `YBandSeriesOut`, `YRocSeriesOut`), and `CandleSeriesOut`.
  - `static/*`: Dark-theme Single-Page Application (HTML5 / CSS3 / ES6 JS):
    - **One Unified Cockpit**: Progressive disclosure workbench replacing separate Quick/Custom/Advanced modes.
    - **Presets as Starting Configurations**: Instant 1-click loading of all 21 verified mentor presets and user presets into editable form controls, active setup breadcrumb banner tracking modified state, and preset modal (Save/Save As/Delete).
    - **Condition Builder**: Human-readable metric catalog, recursive nested AND/OR groups, NOT negation toggle, column comparison mode, and 1-click 6-timeframe EMA shortcut ribbon.
    - **Screening vs Chart Decoupling**: Screening conditions carry multi-timeframe semantics (D, W, M, Q, H, Y) while chart timeframe buttons toggle visual candlestick view independently without altering screen query.
    - **High-Density Results Table**: Interactive sortable columns, visual prototype pill strips (6-TF EMA ribbon, 6-TF Band state, Impulse badges, ROC heat colors), row selection highlight, and funnel telemetry.
    - **Stock Detail Drawer**: Synchronized 6-timeframe inspection matrix directly beneath the chart showing EMA, band state, band width, band upper/lower levels, ROC%, and speed, plus comprehensive key metrics block (Sprint consistency, Impulse `IC`/`IC_RATIO`, Accelerations, ATH diff, DMI/ADX, and Out-of-band counts).
    - **Batch U1: Stock Detail — Coherent Technical Analysis Workspace**:
      - Professional investor workspace exposing the 19+ backend-calculated financial series without creating a button farm ("Full Control Without Complexity").
      - Grouped Overlays Popover (`#overlaysDropdown`): Trend overlays (EMA 3, EMA 5, SMA 20 / Basis, Average Price), Volatility / Channels (Bollinger Bands, Donchian Channels, ATR Bands, VWAP), YOGI Bands envelope toggle, and Volume toggle.
      - Grouped Analytical Sub-Panel Popover (`#panelsDropdown`): Single-active analytical pane beneath the price chart supporting RSI (with 70/30 thresholds), MACD (MACD line, Signal line, Histogram series), DMI/ADX (+DI, -DI, ADX), OBV, MFI (with 80/20 thresholds), and YOGI custom curves (Sprint Speed, Acceleration, Band Distance, YOGI ROC). Synchronized time scale with main price chart.
      - Independent Band Timeframe Selector: Decoupled chart timeframe vs band timeframe via `band_tf` API query parameter (`[Same as Chart ▾]`, Daily, Weekly, Monthly, Quarterly, Half-Yearly, Yearly, None/Off).
      - Stock Identity Badges in Drawer Header: Symbol, Name, Price, Sector, Grade, Market Cap Group, and F&O eligibility.
      - Categorized Multi-Timeframe Matrix: Organized into Trend & Alignment (EMA, Bands, DMI State), Momentum & Returns (ROC, Sprint Speed, Acceleration), Strength (DMI/ADX), and Bands & Volatility (Band Width, Band Distance, Upper/Lower levels).
      - Async Race Safety: Request ID token guard (`currentStockDrawerRequestId`) preventing stale out-of-order responses from overwriting rapid stock selections.
      - Session state persistence for user overlay selections, active panel, and band timeframe.
    - **Batch U2: Unified Screening / Configuration Workspace**:
      - One unified professional screening workspace exposing the entire frozen screening engine without mode fragmentation (no separate Quick/Custom/Advanced modes).
      - Structured Left Workbench into 5 distinct progressive disclosure cards:
        1. **Universe & Presets**: Exchange (`NSE`, `BSE`, `BOTH`), Segment (`ALL`, `FNO`, `CASH`), Presets recipe dropdown with instant automatic loading, Revert button restoring pristine snapshot upon modification, Save As user preset dialog, Delete user preset, Quick stock find.
        2. **Conditions (QUALIFY)**: Root Match (`ALL`/`ANY`), Root `NOT` toggle, Quick EMA Uptrend ribbon `[D..Y]`, Quick Band position buttons, Dynamic Condition Rows with Metric Family and inline timeframe segmented buttons `[D] [W] [M] [Q] [H] [Y]`, `vs Col` cross-field comparison (`field2`), context-sensitive value inputs, Visually nested groups with tree connectors, group-level `NOT` inversion, arbitrary subgroup nesting.
        3. **Ranking (ORDER)**: Primary ranking metric dropdown, direction `desc`/`asc`, progressive disclosure for secondary tie-breaker metric.
        4. **Selection (SHOW)**: Top N limit with quick pills `[10] [20] [50] [100] [All]`, Rank Survival Cutoffs builder exposing `RankCutoffSpec` (`RANK_M`..`RANK_D` <= threshold).
        5. **Display Columns & Actions**: Column presets (`summary`, `returns`, `sprint`, `bands`, `emas`, `strength`, `all`), custom projection input, primary `[ 🚀 RUN SCREEN ]` action, multi-format exports (`XLSX`, `CSV`, `JSON`).
      - Right Viewport:
        - Reactively updating Active Configuration / Setup Summary Banner reflecting universe, preset (with modified indicator `(Modified)`), conditions (with `NOT` prefix), ranking, selection cutoff counts.
        - Funnel Telemetry: `Universe → Qualified → Selected`.
        - Dense Results Grid with multi-timeframe DMI and candlestick pattern badge rendering.
        - Full preservation of Batch U1 Stock Detail Workspace.
    - Operates with zero Node/NPM build toolchain dependencies.
  - **Presentation Boundary & Mentor Review Status**:
    - The current Cockpit UI in `src/yogi/cockpit/static/*` operates as a verified functional prototype workbench for validating analytical calculations, multi-timeframe synthesis, screening queries, and drawer telemetry.
    - All UX and presentation decisions (layout, control ergonomics, workflow progression, visualization density) are intentionally deferred to the mentor-review phase.
    - The UX may be redesigned in future phases without requiring changes to the frozen Core engine, contracts, calculations, or pipeline orchestration.
- Verified by:
  - `tests/cockpit/test_cockpit_state.py` (7/7 tests passing).
  - `tests/cockpit/test_cockpit_charting.py` (8/8 tests passing).
  - `tests/cockpit/test_cockpit_chart_cache_f04.py` (9/9 tests passing).
  - `tests/cockpit/test_cockpit_panel_f05.py` (15/15 tests passing).
  - `tests/cockpit/test_cockpit_demo.py` (5/5 tests passing).
  - `tests/cockpit/test_cockpit_api.py` (23/23 tests passing).
  - `tests/cockpit/test_cockpit_twelve_data.py` (4/4 tests passing, verifying provider selection, demo/live isolation, error propagation without silent demo fallback, and end-to-end live screening/charting).
  - `tests/cockpit/test_race.py` (6/6 tests passing, verifying explicit and auto-picked sprint race curves, candidate filtering, and HTTP /api/race endpoint).
  - `tests/cockpit/test_batch_3a_technical_series.py` (16/16 tests passing).
  - `tests/cockpit/test_batch_3b_indicators.py` (10/10 tests passing).
  - `tests/cockpit/test_batch_3c_oscillators.py` (10/10 tests passing).
  - `tests/cockpit/test_batch_3d_custom_curves.py` (8/8 tests passing).
  - `tests/cockpit/test_cockpit_stock_drawer.py` (12/12 tests passing).
  - `tests/cockpit/test_batch_u1_stock_detail.py` (11/11 tests passing).
  - `tests/cockpit/test_batch_u2_screener.py` (12/12 tests passing).
  - Total Cockpit test suite: 173/173 tests passing (100%).

---

## 2. Test Suite Status Baseline

```text
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Yogi Investing\My_version
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collected 580 items

tests\calculation\ (8 files, 116 tests) ........................................ [ 20%]
tests\cockpit\ (18 files, 173 tests) .......................................... [ 50%]
tests\core\ (4 files, 51 tests) ............................................... [ 59%]
tests\data\ (6 files, 105 tests) .............................................. [ 77%]
tests\filter\ (1 file, 13 tests) .............................................. [ 79%]
tests\pipeline\ (4 files, 13 tests) ........................................... [ 81%]
tests\ranking\ (1 file, 8 tests) .............................................. [ 83%]
tests\regression\ (1 file, 6 tests) ........................................... [ 84%]
tests\results\ (2 files, 14 tests) ............................................ [ 86%]
tests\selection\ (1 file, 10 tests) ........................................... [ 88%]
tests\storage\ (4 files, 36 tests) ............................................ [ 94%]
tests\strategy\ (2 files, 10 tests) ........................................... [ 96%]
tests\timeframe\ (1 file, 25 tests) ........................................... [100%]

======================== 580 passed, 2 warnings in ~160s ========================
```
Total tests: **580 passed, 0 failures** (100% pass rate across Core, Providers, Calculations, Pipeline, Storage, Cockpit, Batches 1–5, Batch U1, and Batch U2).

---

## 3. Comprehensive Implementation Status Breakdown

| Subsystem / Feature | Classification | Details |
|---|---|---|
| **Core Contracts** | **IMPLEMENTED** | All 10 contract modules, DTOs, and protocols frozen (including `ISecurityMetadataRepository`). |
| **Capability Registry** | **IMPLEMENTED** | `RegistryHub` and `CapabilityRegistry[T]` frozen with 3 categories. |
| **Core Configuration** | **IMPLEMENTED** | `EngineConfig`, `ScreeningQuery`, `StrategyCatalog` frozen. |
| **Core Orchestration** | **IMPLEMENTED** | `PipelineOrchestrator` (`build_dataset`, `execute_screen`, `run`) frozen with metadata enrichment. |
| **Data Normalization** | **IMPLEMENTED** | Pure normalizers for bars, ticks, universes, instrument classification, and NSE F&O lots frozen. |
| **Data Providers** | **IMPLEMENTED** | Yahoo, Zerodha, Twelve Data, and Demo providers frozen with offline test injection. |
| **Timeframe Engine** | **IMPLEMENTED** | Multi-timeframe synthesis (D $\to$ W, M, Q, H, Y) frozen. |
| **Calculation Engine** | **IMPLEMENTED** | Five analytical pillars (Bands, Candles, Impulse, Trend, Velocity) frozen with centralized band envelope math, 204 candlestick shape metrics, technical indicators (Bollinger, Donchian, ATR, VWAP, Avg Price), oscillators (RSI, MACD, OBV, MFI), and custom momentum curves. |
| **Golden Fixture Verification** | **IMPLEMENTED** | 5-stock golden regression suite verified to 0 drift against `expected.json`. |
| **Filter Engine (`src/yogi/filter/`)** | **IMPLEMENTED** | `FilterEngine` evaluating all 12 operators, cross-column, and nested groups (Step 9). |
| **Ranking Engine (`src/yogi/ranking/`)** | **IMPLEMENTED** | `RankingEngine` with deterministic ties, na_position='last', and rank_changes (Step 9). |
| **Selection Engine (`src/yogi/selection/`)** | **IMPLEMENTED** | `SelectionEngine` evaluating rank thresholds and sustained duration (Step 9). |
| **Strategy Engine (`src/yogi/strategy/`)** | **IMPLEMENTED** | `Strategy` engine and the 21 Verified Mentor Presets (Step 9). |
| **Results Engine (`src/yogi/results/`)** | **IMPLEMENTED** | `ResultAssembler` and `ExportFormatter` for XLSX, CSV, JSON byte streams (Step 10). |
| **Cockpit UI & Master UX** | **IMPLEMENTED & FROZEN (Batch U1)** | Interactive workspace, Coherent Stock Detail Technical Analysis Workspace (grouped overlays, single-active sub-panels, independent band timeframe, metadata badges, categorized 6-TF matrix, async race protection), AppState cache, metadata endpoints, and REST APIs (Step 11 & Batch U1). |
| **Market Metadata & Classification** | **IMPLEMENTED (Batch 5)** | Pure classification normalizer (`classification.py`), pure NSE F&O universe normalizer (`fno.py`), resilient dual-mirror NSE source adapter (`sources/nse.py`), pipeline base record enrichment (`name, sector, grade, mcap, fno, instr, grp`), and Cockpit metadata APIs (`GET /api/meta/{symbol}`, `POST /api/meta/{symbol}`) with demo isolation. |
| **Architectural Findings (F01–F06)** | **RESOLVED** | All 6 findings (F01 Timeframe protocol injection in pipeline orchestrator, F02 Demo provider location in `data/providers/`, F03 Centralized band envelope math in `calculator.py`, F04 Bounded chart data cache with LRU/TTL in `charting.py`, F05 Stock-Panel on-demand resolution with bounded LRU cache in `state.py`, F06 Documentation synchronization) are fully resolved and verified. |
| **Mentor Review & UX Definition** | **PENDING NEXT PHASE** | Mentor will evaluate presentation of calculations, options, strategies, filters, rankings, and analytical metrics to define final user-facing UX. |
| **Live In-Memory Hot Path** | **PLANNED** | Real-time tick aggregation and streaming calculation updates (Step 12). |
| **Persistent Storage & History** | **PARTIALLY IMPLEMENTED (Batch 4 & 5)** | Authoritative `data/bands.csv`, append-only `data/band_changes.csv`, daily `data/band_backups/bands_YYYY-MM-DD.csv`, and atomic restore implemented via `CsvBandsRepository`. Authoritative `data/metadata.csv` and `data/fno_list.csv` implemented via `CsvMetadataRepository` with atomic updates and legacy migration. Cold price database deferred to operations phase. |
| **Universal Stage Registry** | **EXPLICITLY EXCLUDED** | Rejected per [ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution); registry limited to providers, calculations, and bands. |
| **LLM-Based Data Normalization** | **EXPLICITLY EXCLUDED** | External market data must be transformed strictly by pure, deterministic normalizers. |
| **Presentation Columns in Query** | **EXPLICITLY EXCLUDED** | `ScreeningQuery` excludes display column projection per [ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation). |
| **UI-Owned Financial Calculations** | **EXPLICITLY EXCLUDED** | All calculations belong exclusively to the analytical engine; Cockpit is purely presentation. |
| **Vendor Object Leakage** | **EXPLICITLY EXCLUDED** | Raw DataFrames, dicts, or Kite SDK types must not cross provider boundaries. |
| **Live Database Engine** | **NOT YET DECIDED** | Choice of database for cold persistence (PostgreSQL, SQLite, DuckDB, Parquet) deferred to operations phase. |
| **Broker Order Execution API** | **NOT YET DECIDED** | Live order routing and trading execution boundaries deferred to broker integration milestone. |
| **Mobile Application Interface** | **NOT YET DECIDED** | Dedicated mobile client architecture deferred. |

---

## 3.1 Categorical Parity & Scope Ledger

The system strictly distinguishes between different categories of capability status:

### A. BACKEND & COCKPIT COMPLETE & FROZEN
- 100% of mathematical algorithms, formulas, and metric calculations across all 5 pillars (Bands, Candles, Impulse, Trend, Velocity).
- 204 candlestick shape dimensions, patterns, and structural relationship flags.
- Complete technical indicator and oscillator suite: Bollinger Bands, Donchian Channels, ATR Volatility Bands, VWAP, Average Price, RSI (Wilder 14), MACD (12/26/9), OBV, MFI (14).
- Continuous momentum curves: YOGI Sprint Speed, Acceleration, Band Distance, YOGI ROC.
- Sprint Race anchored performance curve engine (/api/race).
- Multi-timeframe synthesis (D -> W, M, Q, H, Y).
- Canonical screening pipeline (QUALIFY → ORDER → SHOW → LIMIT → RESULTS) with metadata enrichment.
- Crash-resilient atomic persistence for manual bands (CsvBandsRepository, audit trail, daily backups, restore).
- Security Master & classification (InstrumentClassifier, official NSE F&O universe discovery NseFnoUniverse, CsvMetadataRepository).
- Cockpit HTTP transport layer and ChartDataService packaging 19+ financial series into CandleSeriesOut.
- **Batch U1 Technical Analysis Workspace**:
  - TradingView chart sub-panes for RSI, MACD, DMI, OBV, MFI, and YOGI custom curves (Sprint Speed, Acceleration, Band Distance, ROC) in `chart.js` with synchronized time scales and fallback.
  - Grouped Overlays popover for Bollinger Bands, Donchian Channels, ATR Volatility Bands, VWAP, SMA20 basis, EMA3, EMA5, and Average Price.
  - Independent band timeframe selector (`band_tf` query parameter).
  - Compact volume histogram overlay with auto-margin scaling.
  - Security metadata badges (Sector, Grade, Mcap, F&O) in Stock Detail Drawer header.
  - Categorized Multi-Timeframe Matrix (Trend & Alignment, Momentum & Speed, Strength, Bands & Volatility).
  - Async race safety on rapid stock switching (`currentStockDrawerRequestId`).

### B. UI NOT YET EXPOSED (Remaining Minor Presentation Backlog)
- Advanced filter builder UI controls for cross-field comparison (`field2`) and condition negation (`NOT`).
- Band snapshot restore trigger button in Cockpit workbench.

### C. REMAINING MINOR BACKEND GAPS
1. **Multi-Month Historical Rank Trajectory Disk Archive (/api/rankhistory/{symbol})**: Scanning disk archive dumps (data/history/*.csv) to return a multi-year rank trajectory curve. *(Current YOGI dynamically computes current-vs-prior month rank change RANK_CHG in-memory within the screening pipeline).*
2. **Persistent Custom DMI Parameter Endpoint (/api/dmi/settings)**: REST API endpoint allowing users to modify global DMI/ADX period lengths and persist them to disk.

### D. DELIBERATELY DEFERRED (Architectural Decisions)
- Bi-Weekly (2W) and Bi-Monthly (2M) timeframes (deferred per ADR-007).
- Production operations, automated background cron schedulers (/api/schedule), and real-time hot path (Step 12).
- Cold database price storage (SQL / TimescaleDB) (Step 12).
- Automated brokerage order execution (excluded by core system scope).

### E. PRODUCT / MENTOR DECISIONS (UX Direction)
- Information density model: 1-click header quick-tick ribbon vs clean consolidated strategy presets.
- Oscillator layout: stacked sub-panes vs active oscillator dropdown selector.
- Sprint Race visualizer placement: full-screen modal workbench vs drawer panel.

---

## 4. Current Phase Boundary: MVP Backend Freeze & Transition to Mentor/UX Review

The YOGI MVP backend and analytical engine are considered **COMPLETE and FROZEN** for this phase:

1. **Backend Engine Frozen**:
   - All Core contracts, pipeline orchestration, data providers (Yahoo, Zerodha, Twelve Data, Demo), timeframe synthesis, analytical calculations (Bands, Candles, Impulse, Trend, Velocity), screening stages (QUALIFY → ORDER → SHOW → LIMIT → RESULTS), and results formatters are complete, verified, and frozen.
   - All architectural findings (YOGI-F01 through YOGI-F06) are fully resolved and covered by 557 passing tests (100% pass rate).
   - No new analytical capabilities or mathematical calculations are being developed now.
   - No backend or Core architectural redesign is planned before mentor review.

2. **UX & Presentation Model Deferred for Mentor Review**:
   - The MVP is now entering a mentor-review / UX-definition phase.
   - The mentor will evaluate the system to determine how the existing calculations, options, strategies, filters, rankings, and analytical capabilities should ultimately be structured and presented to end users.
   - Future UX implementations must build upon and expose the existing engine capabilities rather than prematurely changing Core contracts or domain calculations.

3. **Engineering Roadmap & Subsequent Milestones**:
   - Step 12 (Production Operations, Real-Time Hot Path, Tick Infrastructure, Streaming) and cold database persistence have **NOT** been started. They remain scheduled for future operational phases.

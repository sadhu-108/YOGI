# YOGI Technical Architecture

This document defines the stable architectural structure, subsystem boundaries, contracts, data flow, and dependency principles for the YOGI platform per [`AGENTS.md`](../AGENTS.md).

---

## 1. Architectural Foundations

### Core Architectural Principle
YOGI is engineered around a single fundamental philosophy:

> **Stable Core • Replaceable Modules • Contract-Based Connections**

- **Stable Core**: The center of the system coordinates execution through contracts, registries, configurations, and pipeline orchestration without containing domain-specific implementations.
- **Replaceable Modules**: Every concrete capability (market data providers, analytical calculators, storage repositories) is an isolated module that can be replaced without forcing changes to unrelated modules or the pipeline core.
- **Contract-Based Connections**: Modules communicate exclusively through strongly typed, frozen abstract interfaces. Core depends on contracts, not concrete classes.

### The Mental Model
The platform processes user intent into analytical screening results through a disciplined hierarchy:

```text
UI / User Choices (Cockpit Presentation Facade)
       ↓
Configuration       (What does YOGI want to do? ScreeningConfig, ScreeningQuery)
       ↓
Orchestration       (PipelineOrchestrator: QUALIFY → ORDER → SHOW → LIMIT → RESULTS)
       ↓
Registry            (RegistryHub: Which implementation provides each capability?)
       ↓
Implementations     (Data providers, calculation engines, storage repositories)
       ↓
Results / UI        (Assembled QueryResult payload projected to Cockpit Workbench)
```

---

## 2. Target Repository Structure

```text
src/yogi/
├── core/                         # [FROZEN] Invariant platform center
│   ├── contracts/                # Authoritative interfaces and canonical DTOs (10 modules)
│   ├── registry/                 # Capability mapping and RegistryHub (3 pillars)
│   ├── configuration/            # ScreeningConfig, ScreeningQuery, StrategyCatalog
│   └── orchestration/            # PipelineOrchestrator coordinator
│
├── data/                         # [FROZEN] Market data acquisition & normalization
│   ├── ingestion/                # MarketDataIngestionService (acquisition, freshness planning, caching)
│   ├── providers/                # External adapters (Demo, Twelve Data, Yahoo, Zerodha)
│   ├── normalization/            # Pure normalizers (bars, classification, F&O universe)
│   └── sources/                  # Resilient external data sources (official NSE downloads)
│
├── storage/                      # [FROZEN] Crash-resilient atomic file persistence
│   ├── bands.py                  # CsvBandsRepository, audit trail, daily backups, restore
│   └── metadata.py               # CsvMetadataRepository (security master metadata)
│
├── timeframe/                    # [FROZEN] Multi-timeframe synthesis (D -> W, M, Q, H, Y)
│
├── calculation/                  # [FROZEN] Five Analytical Mathematical Pillars
│   ├── bands/                    # Volatility envelope, Bollinger, Donchian, ATR, band distance
│   ├── candles/                  # Candlestick recognition theory (204 shapes/patterns)
│   ├── impulse/                  # Zigzag reversal pivots & Ram's 50% recovery validation
│   ├── trend/                    # Trailing ROC, 3/5 EMA, CAGRs, ATH, DMI/ADX, VWAP, RSI, MACD, OBV, MFI
│   └── velocity/                 # Rolling speed (S4..S52), acceleration, sprint consistency, race curves
│
├── filter/                       # [FROZEN] Qualification criteria & boolean composition (QUALIFY)
├── ranking/                      # [FROZEN] Multi-key sorting & dynamic cohort ranking (ORDER)
├── selection/                    # [FROZEN] Top N cutoffs & cohort survival limits (LIMIT)
├── strategy/                     # [FROZEN] Declarative recipes & 21 Verified Mentor Presets
├── results/                      # [FROZEN] Column projection, formatting & Excel exports (SHOW/RESULTS)
├── pipeline/                     # [FROZEN] End-to-end screening orchestrator implementation
└── cockpit/                      # [FROZEN] Presentation workbench, REST API & TradingView charting
    ├── app.py                    # FastAPI application factory
    ├── router.py                 # REST API route handlers
    ├── schemas.py                # Strongly typed Pydantic response models
    ├── app_state.py              # In-memory coordination & bounded LRU caches
    ├── services/                 # ChartDataService (19+ series), RaceVisualizerService
    └── static/                   # HTML5 single-page workbench, JS, CSS
```

---

## 3. Authoritative Contracts (`src/yogi/core/contracts/`)

Every cross-module boundary is governed by an explicit, frozen contract:

| Contract Module | Key Classes / Protocols | Primary Responsibility | Anti-Responsibility (What it must NOT do) | Lifecycle Status |
|---|---|---|---|---|
| **`market_data.py`** | `MarketBar`, `TickData`, `MarketContext`, `IMarketDataProvider`, `ITickDataProvider` | Invariant representation of price, volume, and multi-timeframe bar containers. | Transforming vendor formats or computing indicators. | **FROZEN** |
| **`provider.py`** | `IDataProvider`, `ProviderHealth` | Common protocol for external vendor adapters. | Business logic, filtering, or caching. | **FROZEN** |
| **`timeframe.py`** | `ITimeframeEngine` | Contract for aggregating base bars into higher timeframes and constructing `MarketContext`. | Ranking, screening, or indicator calculation. | **FROZEN** |
| **`calculation.py`** | `CalculationResult`, `ICalcModule`, `CalculationContext` | Contract for numerical calculation modules and polymorphic dynamic indicator calculation (`supports_condition`, `calculate_dynamic`). | Network requests, storage I/O, or presentation. | **FROZEN** |
| **`bands.py`** | `IBandsRepository`, `BandEntry`, `BandAuditEntry`, `BandBackupInfo`, `BAND_TIMEFRAMES` | Contract for retrieving and persisting user-defined volatility band levels. | Computing band positions or pricing envelopes. | **FROZEN** |
| **`security.py`** | `SecurityMetadata`, `InstrumentType`, `TradingGroup`, `ISecurityMetadataRepository` | Contract for instrument classification, trading groups, and metadata storage. | External network fetching or price calculation. | **FROZEN** |
| **`filter.py`** | `IFilterRule`, `IConditionEvaluator`, `FilterOperator`, `FilterRuleSpec`, `FilterGroupSpec` | Contract for boolean candidate qualification (`QUALIFY`) and modular condition evaluation (`IConditionEvaluator`). | Sorting, relative ranking, or record truncation. | **FROZEN** |
| **`ranking.py`** | `IRankingRule`, `RankingOrder`, `RankingMethod`, `RankingResult` | Contract for relative metric sorting across surviving candidates (`ORDER`). | Filtering candidates or truncating output sets. | **FROZEN** |
| **`selection.py`** | `ISelectionRule`, `SelectionMode`, `RankCutoffSpec`, `SelectionResult` | Contract for applying rank cutoffs and cohort survival limits (`LIMIT`). | Calculating metric ranks or filtering records. | **FROZEN** |
| **`strategy.py`** | `IStrategy`, `StrategySpec`, `StrategyValidationResult` | Contract for declarative screening recipe composition. | Direct calculation or data mutation. | **FROZEN** |
| **`results.py`** | `IResultAssembler`, `IExportFormatter`, `ColumnDefinition`, `QueryResultPayload` | Contract for presentation column projection and serialization (`SHOW`/`RESULTS`). | Filtering, ranking, or metric calculation. | **FROZEN** |

---

## 4. Registry Architecture (`src/yogi/core/registry/`)

The core coordinates modular extensions through a strongly typed, three-pillar capability registry ([ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution)):

```python
class RegistryHub:
    # Explicitly scoped capability container exposing strictly three approved categories.
    providers: CapabilityRegistry[IDataProvider]
    calculations: CapabilityRegistry[ICalcModule]
    bands: CapabilityRegistry[IBandsRepository]
```

### Registry Invariants
1. **Three Pillars Only**: `RegistryHub` manages strictly `providers`, `calculations`, and `bands`. It does not expose registries for filters, rankings, selections, strategies, or presentation formatters.
2. **Deterministic Discovery**: Capabilities are registered via explicit code registration, preserving transparency and deterministic testing over magic reflection.
3. **Immutability & Safety**: Registry registration is thread-safe and prevents accidental duplicate key collisions.

---

## 5. Configuration Architecture (`src/yogi/core/configuration/`)

System execution is governed by two cleanly separated configuration models ([ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation)):

- **`EngineConfig`**: Invariant system-level settings (active data provider key, active bands repository key, active calculation module keys, active exchange, required timeframes, data limits).
- **`ScreeningQuery`**: Dynamic user screening intent strictly mapping to `QUALIFY → ORDER → SHOW → LIMIT`. It specifies filter conditions, ranking rules, limit constraints, and requested columns.
- **`StrategyCatalog`**: Immutable in-memory catalog translating named recipes (e.g. the 21 Verified Mentor Presets) into executable `ScreeningQuery` instances.

---

## 6. Core Orchestration (`src/yogi/core/orchestration/`)

`PipelineOrchestrator` coordinates the data ingestion, calculation, and screening lifecycle without taking on domain logic:

```mermaid
flowchart TD
    Config["EngineConfig + ScreeningQuery"] --> Orchestrator["PipelineOrchestrator"]
    Orchestrator --> Ingestion["MarketDataIngestionService"]
    Ingestion --> Provider["Data Provider (via RegistryHub)"]
    Ingestion --> Storage["MarketBarsCache (IBarsCache)"]
    Orchestrator --> Synthesizer["Timeframe Synthesizer (D -> W, M, Q, H, Y)"]
    Synthesizer --> Context["MarketContext Container"]
    Context --> Calcs["Calculation Modules (5 Pillars)"]
    Calcs --> Metadata["Metadata Enrichment (SecurityMetadata)"]
    Metadata --> Qualify["QUALIFY (FilterEngine)"]
    Qualify --> Order["ORDER (RankingEngine)"]
    Show --> Limit["LIMIT (SelectionEngine Slicing)"]
    Order --> Show["SHOW (ResultAssembler Columns)"]
    Limit --> Results["RESULTS (QueryResult)"]
```

---

## 7. Data Layer & Normalization (`src/yogi/data/`)

The data layer ingests vendor data and converts it into pure, canonical YOGI domain objects ([ADR-006](decisions.md#adr-006-data-providers--normalization-boundaries)):

- **Ingestion Service (`src/yogi/data/ingestion/`)**:
  - `MarketDataIngestionService`: Evaluates cache freshness, plans incremental/backfill requests, executes batched or individual provider queries, merges updates with cached history, and persists newly downloaded bars via `IBarsCache`.
- **Provider Adapters (`src/yogi/data/providers/`)**:
  - `DemoProvider`: 100% offline, deterministic synthetic data generator for testing and demo mode.
  - `TwelveDataProvider`: Production REST client for Twelve Data Indian equities with rate limiting and exponential backoff ([ADR-009](decisions.md#adr-009-twelve-data-provider-adapter-integration)).
  - `YFinanceProvider`: Primary live/fallback provider for historical daily OHLCV bars.
  - `ZerodhaProvider`: Webhook and API adapter for Zerodha Kite Connect.
- **Instrument Classification (`src/yogi/data/normalization/classification.py`)**:
  - `InstrumentClassifier`: Pure deterministic classifier mapping symbols to `InstrumentType` (`EQUITY`, `ETF`, `INDEX`, `DEBT`, `HYBRID`, `PREFERENCE`, `UNKNOWN`) and `TradingGroup` (`LARGE_CAP`, `MID_CAP`, `SMALL_CAP`, `MICRO_CAP`, `SME`, etc.).
- **Official NSE F&O Universe Discovery (`src/yogi/data/normalization/fno.py` & `sources/nse.py`)**:
  - `NseFnoUniverse`: Resilient official NSE underlying securities list downloader with local caching and offline fallback.

---

## 8. Timeframe Engine (`src/yogi/timeframe/`)

The Timeframe Engine aggregates base daily bars into higher calendar timeframes ([ADR-007](decisions.md#adr-007-timeframe-engine-bounded-responsibility), [ADR-016](decisions.md#adr-016-timeframe-engine-contract-itimeframeengine-adoption--reconciliation)):

- **Authoritative Contract**: Implements the frozen `ITimeframeEngine` abstract contract (`src/yogi/core/contracts/timeframe.py`) providing `resample` and `build_context` methods. Enables Core Orchestration dependency inversion and mock isolation without adding dynamic registry overhead ([ADR-016](decisions.md#adr-016-timeframe-engine-contract-itimeframeengine-adoption--reconciliation)).
- **Supported Timeframes**: `D` (Daily), `W` (Weekly), `M` (Monthly), `Q` (Quarterly), `H` (Half-Yearly), `Y` (Yearly).
- **Synthesis Rules**: Strictly bounded OHLCV aggregation preserving standard financial invariants (Open=first open, High=max high, Low=min low, Close=last close, Volume=sum volume).
- **Metric Decoupling**: Screening conditions specify their own timeframe (e.g. `ROC_63[D]`, `EMA_CROSS[W]`, `BD[M]`), evaluated concurrently across the multi-timeframe context.
- **Explicitly Deferred Timeframes**: Bi-Weekly (`2W`) and Bi-Monthly (`2M`) remain explicitly deferred per ADR-007.

---

## 9. Calculation Engine (`src/yogi/calculation/`)

The Calculation Engine executes pure analytical mathematics across market data ([ADR-008](decisions.md#adr-008-calculation-engine-modularization--four-mathematical-pillars)).

### The Five Mathematical Pillars
Every pillar implements the frozen `ICalcModule` contract:

| Pillar | Capability Key | Required Timeframes | Analytical Outputs & Features |
|---|---|---|---|
| **Bands** | `"bands"` | `("W", "M", "Q", "H", "Y")` | Volatility envelope levels (`BANDUP_*`, `BANDLO_*`), position distances (`BD_*`), position states (`ABOVE`, `BELOW`, `IN`, `na`), Bollinger Bands ($\mu \pm k\sigma$), Donchian Channels ($N$-period High/Low), ATR Volatility Bands ($SMA \pm k \cdot ATR$), continuous Band Distance curve, and cross-timeframe envelope synthesis. |
| **Candles** | `"candles"` | `("D", "W", "M")` | 204 candlestick shape metrics and pattern recognition flags per bar: body/shadow dimensions (`BODY_PCT`, `UPPER_SHADOW_PCT`, `RANGE_PCT`), classic patterns (`BULL_ENGULF`, `BEAR_ENGULF`, `DOJI`, `MARUBOZU`, `HAMMER`, `SHOOTING_STAR`), and structural bar dynamics (`INSIDE_BAR`, `OUTSIDE_BAR`, `NR7`, `WR7`, `THREE_UP`, `THREE_DN`, `GAP_UP`, `GAP_DN`). |
| **Impulse** | `"impulse"` | `("D",)` | Zigzag swing reversal pivots and Ram's 50% recovery validation (`IC="IP"|"CR"|"up"|"na"`, `IC_PCT`, `IC_BARS`, `IC_RATIO`, `IC_START`, `IC_END`, `IC_AGE`). |
| **Trend** | `"trend"` | `("D", "W", "M", "Q", "H", "Y")` | Trailing ROCs (`DROC`..`YROC`), calendar blocks (Quarter, Half, Year), multi-year CAGRs (`CAGR_1`..`CAGR_10`), ATH drawdown (`ATH_DIFF`), EMA 3/5 ribbon states, DMI/ADX ($+DI, -DI, ADX$), Average Price, VWAP, Relative Strength Index (RSI 14), Moving Average Convergence Divergence (MACD 12/26/9), On-Balance Volume (OBV), Money Flow Index (MFI 14), and continuous ROC curves. |
| **Velocity** | `"velocity"` | `("D",)` | Rolling speeds across windows (`S4`, `S13`, `S26`, `S52`), linear accelerations (`ACCEL_S`, `ACCEL_L`), sprint consistency (`SPR_CONSIST`), anchored sprint race curves indexed to 100 (`/api/race`), continuous sprint speed curve, and continuous acceleration curve. |

---

## 10. Persistent Storage Subsystem (`src/yogi/storage/`)

Persistent state is managed by dedicated, crash-resilient file repositories implementing atomic file replacement:

1. **Persistent Bands (`src/yogi/storage/bands.py`)**:
   - `CsvBandsRepository`: Thread-safe CSV persistence for manual band boundaries (`UB, LB, WIDTH`).
   - `BandAuditLogger`: Append-only structured audit trail (`data/bands/bands_audit.log`) tracking timestamp, symbol, timeframe, old values, new values, user, and reason.
   - `BandBackupManager`: Automated daily snapshot archives stored in `data/bands/backups/`.
   - `restore_backup`: Point-in-time restoration from any historical snapshot with automated pre-restore safety backups.
2. **Persistent Security Metadata (`src/yogi/storage/metadata.py`)**:
   - `CsvMetadataRepository`: Thread-safe CSV persistence for symbol master data (`name`, `sector`, `grade`, `mcap`, `fno`, `instr`, `grp`).
3. **Atomic File Write Semantics**:
   - All write operations create a temporary staging file (`.tmp`) and perform an atomic `os.replace`, guaranteeing that unexpected power loss or crashes never corrupt storage.

---

## 11. Screening Architecture: QUALIFY → ORDER → SHOW → LIMIT → RESULTS

YOGI enforces a strict separation between user-facing simplicity and internal architectural stages ([ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results), [ADR-015](decisions.md#adr-015-ema-band-roc-filtering-and-multi-period-ranking-contract-separation)):

$$\mathbf{QUALIFY} \longrightarrow \mathbf{ORDER} \longrightarrow \mathbf{SHOW} \longrightarrow \mathbf{LIMIT} \longrightarrow \mathbf{RESULTS}$$

### 11.1 Stage Responsibility Boundaries

1. **QUALIFY (`FilterEngine`)**: Evaluates boolean qualification conditions against record metrics (`IFilterRule`, `FilterGroupSpec`). Disqualifies non-matching securities. Answers: *"Does it qualify?"*
   - **EMA Filter**: Evaluates configured EMA conditions only.
   - **Band Filter**: Evaluates a security's position relative to the configured band envelope only.
   - **ROC Filter**: Evaluates configured rate-of-change conditions only.
   - **Boundary Invariant**: Filter rules evaluate qualification only. Filters must **never** own, perform, or implement ranking.
2. **ORDER (`RankingEngine`)**: Orders qualified records by specified ranking criteria (`ranking_metric`, `RankingOrder`). Injects dynamic cohort ranks (`RANK_{metric}`) and rank change (`RANK_CHG`). Answers: *"Where does it stand?"*
   - **Boundary Invariant**: Ranking establishes relative ordering across eligible securities independently. Ranking must never change filter meaning, disqualify records, or force filter redesigns.
3. **SHOW (`ResultAssembler`)**: Projects requested presentation columns and enriches records with metadata (`name`, `sector`, `grade`, `mcap`, `fno`, `instr`, `grp`). Answers: *"What should be displayed?"*
   - **Boundary Invariant**: Projects columns and formats output payloads without filtering, ranking, or selection.
4. **LIMIT (`SelectionEngine`)**: Applies top $N$ cutoffs and cohort survival limits (`RankCutoffSpec`). Answers: *"Does its rank qualify?"*
   - **Boundary Invariant**: Evaluates rank thresholds and sustained duration without altering incoming ranking order.
5. **RESULTS (`PipelineOrchestrator`)**: Packages records into an immutable `QueryResult` with execution timing and metadata.
6. **Cockpit UI**: Collects user configuration and displays results; contains **zero** financial formulas, filtering logic, or ranking algorithms.

### 11.2 EMA Filter Design & Interaction Specification

The EMA filter enables multi-timeframe moving average qualification according to mentor-defined ergonomics and constraints:

1. **Interaction Sequence**:
   - **Step 1: Timeframe Selection FIRST**: The user selects the timeframe (`D`, `W`, `M`, `Q`, `H`, `Y`) before period controls become active.
   - **Step 2: Period Selection**: The user specifies the first ($P_1$) and second ($P_2$) EMA periods.
   - **Step 3: State Selection**: The user selects the desired categorical state (`UP`, `DOWN`, `UPCUT`, `DOWNCUT`).
   - **Step 4: Add Condition**: The user can click an "Add Condition" control to append additional EMA conditions into the screening query.

2. **Explicit Period Caps by Timeframe**:
   | Timeframe | Code | Maximum Permitted Period | Basis / Rationale |
   |---|---|---|---|
   | **Daily** | `D` | **Max 31** | Approximately 1–1.5 months of trading sessions |
   | **Weekly** | `W` | **Max 52** | Exactly 1 calendar year of weekly bars |
   | **Monthly** | `M` | **Max 12** | Exactly 1 calendar year of monthly bars |
   | **Quarterly** | `Q` | **Max 4** | Exactly 1 calendar year of quarterly bars |
   | **Half-yearly** | `H` | **Max 2** | Exactly 1 calendar year of half-yearly bars |
   | **Yearly** | `Y` | **Max 1** | Exactly 1 annual bar |

   > [!IMPORTANT]
   > **Product Constraint, Not Mathematical Limit**: These period caps are mentor-specified product constraints, **not** mathematical limitations of the exponential moving average. The Cockpit UI must update available period options dynamically whenever the timeframe changes, and actively clamp or invalidate out-of-range period inputs.

3. **Desired EMA States & Intended Semantics**:
   - `UP` (Green): First EMA > Second EMA ($EMA_{P1} > EMA_{P2}$).
   - `DOWN` (Red): First EMA < Second EMA ($EMA_{P1} < EMA_{P2}$).
   - `UPCUT` (Green): First EMA crosses above Second EMA on the current bar ($EMA_{P1, t} > EMA_{P2, t}$ and $EMA_{P1, t-1} \le EMA_{P2, t-1}$).
   - `DOWNCUT` (Red): First EMA crosses below Second EMA on the current bar ($EMA_{P1, t} < EMA_{P2, t}$ and $EMA_{P1, t-1} \ge EMA_{P2, t-1}$).

4. **Modular Architecture & Execution Model ([ADR-018](decisions.md#adr-018-modular-condition-evaluators--calculation-registry-dynamic-dispatch-for-filtering))**:
   - **Contract-Based Condition Evaluators**: `FilterEngine` in `src/yogi/filter/engine.py` delegates domain-specific condition evaluations to modular `IConditionEvaluator` instances (`src/yogi/core/contracts/filter.py`). `EmaConditionEvaluator` in `src/yogi/filter/evaluators.py` owns EMA status checking and human-readable explanation generation.
   - **Polymorphic Calculation Dispatch**: `PipelineOrchestrator` in `src/yogi/core/orchestration/pipeline.py` maintains zero module-level imports from concrete calculation packages. It dispatches dynamic indicator calculations via `RegistryHub.calculations` using `ICalcModule.supports_condition(rule.condition_type)` and `ICalcModule.calculate_dynamic(symbol, rule, context)`.
   - **Open/Closed Extensibility**: New filter criteria (Bands, ROC, Ranking, RSI) are plugged in by registering an `IConditionEvaluator` with `FilterEngine` and implementing `calculate_dynamic` in the relevant `ICalcModule` without modifying Core pipeline or engine code.
   - **Yearly Cap & Constraint Clarification**: The Yearly cap of `1` alongside $P_1 \ne P_2 \ge 1$ precludes 2-period crossover evaluation on Yearly bars, which is strictly preserved as a documented product constraint.
   - **Preserved Fixed Metrics**: Legacy fixed 3/5 EMA fields (`EMA_D`..`EMA_Y`, `EMA_UP_COUNT`, legacy `UPCUT`) remain precomputed in `_dataset` for backward compatibility with table strips, stock detail drawer, and all 21 mentor presets.

5. **Multiple Condition Composition**:
   - Multiple conditions compose seamlessly via the existing `FilterGroupSpec` contract with `match="all"` (AND) or `match="any"` (OR) logic, with optional group-level negation (`is_negated`).


### 11.3 Band Filter Design

The Band filter evaluates security positions relative to authoritative band boundaries:

1. **Configuration**: The user selects or configures the band envelope via the existing `IBandsRepository` and `calculate_band_envelope()` model.
2. **Position Categories**:
   - `Above`: Price is above the upper band ($Close > UpperBand$).
   - `Within`: Price is within the band envelope ($LowerBand \le Close \le UpperBand$).
   - `Below`: Price is below the lower band ($Close < LowerBand$).
3. **Multi-Selection**: The user can select 1, 2, or all 3 position categories simultaneously (e.g., `Above` OR `Within`).
4. **Qualification Only**: The Band filter evaluates qualification only (`QUALIFY`), reusing authoritative band calculations (`calculate_band_envelope()`, `BD_*`); it contains zero duplicate envelope mathematics.

### 11.4 ROC Filter vs Multi-Period ROC Ranking

The architecture strictly distinguishes boolean ROC qualification from ordinal ROC ranking:

1. **ROC Filter (`QUALIFY`)**:
   - Evaluates boolean rate-of-change conditions against single or multiple timeframes (e.g., `MROC > 0`, `DROC >= 2.5`).
   - Answers strictly: *"Does this security meet the required rate-of-change threshold?"*

2. **ROC Ranking (`ORDER`)**:
   - Independently establishes relative performance standings across eligible securities.
   - Answers strictly: *"Where does this qualifying security stand relative to its peers?"*

3. **Mentor Ranking Capabilities**:
   - **Standard Timeframe Rankings**: `D`, `W`, `M`, `Q`, `H`, `Y`.
   - **Year-to-Date (`YTD`) Ranking**: Relative performance from the beginning of the current calendar year.
   - **Extended 5-Year Ranking**: Trailing multi-year performance.
   - **Combined 5-Year Average Ranking**: Multi-year aggregated ranking (*exact mathematical aggregation formula recorded as an open product decision*).
   - **Multiple Selectable Periods**: The user may select multiple ranking periods simultaneously (e.g., 3-month and 3-year), preserving separate ranks and metric values per period (e.g., `RANK_ROC_3M` and `RANK_ROC_3Y`) in output records.
   - **No Silent Merging**: Separate ranking periods must **never** be silently merged or collapsed into a single composite score without an explicitly documented aggregation formula.
   - **Directional Sorting**:
     - **Leaders**: Highest-first (`RankingOrder.DESCENDING`).
     - **Backbenchers**: Lowest-first (`RankingOrder.ASCENDING`).

### 11.5 Composition Examples & Ordering

The decoupled architecture allows modular composition of filters and ranking:

- **Example A (Multi-Filter + Single Ranking)**:
  - **QUALIFY**: Weekly EMA UP (`W_EMA_UP == True`) AND Band Above (`M_BAND_POS == 'ABOVE'`) AND Daily ROC condition (`DROC > 0`).
  - **ORDER**: Rank by 3-Month ROC descending (Leaders).
  - **SHOW**: Project summary and momentum columns.
- **Example B (Multi-Timeframe EMA Filter + Multi-Period Ranking & Cutoff)**:
  - **QUALIFY**: Weekly EMA UP (`W_EMA_UP == True`) AND Daily EMA UPCUT (`D_EMA_STATE == 'UPCUT'`).
  - **ORDER**: Rank by YTD ROC descending.
  - **LIMIT**: Rank survival cutoff Top 50 (`RankCutoffSpec(rank_metric="RANK_YTD_ROC", max_rank=50)`).
  - **SHOW**: Project summary and ranking columns.
- **EMA-Based Ordering**:
  - Mentor specification requires ordering securities in EMA `UP` / `UPCUT` states strongest-first, and `DOWN` / `DOWNCUT` states weakest-first (*exact strength metric recorded as an open product decision*).

### 11.6 Architectural Decisions & Open Product Questions Ledger

| Topic | Status | Architectural / Design Specification |
|---|---|---|
| **Pipeline Separation** | **DECIDED** | Strict `QUALIFY → ORDER → SHOW → LIMIT → RESULTS` execution order ([ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results), [ADR-015](decisions.md#adr-015-ema-band-roc-filtering-and-multi-period-ranking-contract-separation)). |
| **EMA Configuration Sequence** | **DECIDED** | Timeframe FIRST (`D`, `W`, `M`, `Q`, `H`, `Y`) $\to$ Periods $(P_1, P_2)$ $\to$ State $\to$ Add Condition. |
| **EMA Period Caps** | **DECIDED** | `D`: 31, `W`: 52, `M`: 12, `Q`: 4, `H`: 2, `Y`: 1 enforced as product constraints with dynamic UI validation. |
| **EMA States** | **DECIDED** | `UP`, `DOWN`, `UPCUT`, `DOWNCUT` with explicit crossing semantics. |
| **Band Position Filter** | **DECIDED** | `Above`, `Within`, `Below` with multi-select support reusing `calculate_band_envelope()`. |
| **ROC Filter vs Ranking** | **DECIDED** | ROC Filter evaluates qualification only; ROC Ranking orders independently. Separate periods preserve separate ranks. |
| **Ranking Directions** | **DECIDED** | Leaders (highest-first) and Backbenchers (lowest-first). |
| **Combined 5-Year Average Formula** | **OPEN DECISION** | Exact aggregation formula (arithmetic mean $\frac{1}{5}\sum Y_i$, 5Y CAGR, or 5Y rolling cumulative ROC) pending mentor direction. |
| **EMA Strength Ordering Metric** | **OPEN DECISION** | Quantitative metric for strongest-first / weakest-first EMA ordering (percentage spread $\frac{EMA_{fast} - EMA_{slow}}{EMA_{slow}} \times 100$, raw delta, or spread slope) pending mentor direction. |
| **Dynamic EMA Calculation Architecture** | **OPEN DECISION** | Evaluation model for arbitrary $(P_1, P_2)$ EMAs (precomputed at dataset build vs calculated on-demand per screening query in `PipelineOrchestrator`) to be determined during implementation design. |

---

## 12. Cockpit Presentation Workbench (`src/yogi/cockpit/`)

Cockpit operates strictly as a presentation facade and HTTP REST server ([ADR-010](decisions.md#adr-010-cockpit-live-twelve-data-provider-connection--demo-isolation)):

- **Zero Financial Math in UI**: All mathematical calculations, screening filters, and rankings execute in backend engines. Cockpit JavaScript (`app.js`, `chart.js`, `table.js`) handles DOM presentation only.
- **`ChartDataService` (`cockpit/services/charting.py`)**: Synthesizes and packages 19+ financial series into `CandleSeriesOut` for TradingView charting (Candles, Bands, Bollinger, Donchian, ATR, VWAP, RSI, MACD, OBV, MFI, Volume, EMA3/5, DMI/ADX, Sprint, Accel, Band Distance, YOGI ROC).
- **`RaceVisualizerService` (`cockpit/services/race.py`)**: Packages multi-symbol anchored performance curves for `/api/race`.
- **`AppState` (`cockpit/app_state.py`)**: Coordinates runtime providers, repositories, and bounded LRU caches with TTL (chart data cache, stock panel cache).
- **Demo Mode Isolation**: In Demo mode, network requests are completely blocked, and write operations to bands or metadata are rejected with HTTP 403 Forbidden.

---

## 13. Developer Extension Map

*"If I want to change something, where should I do it?"*

| If you want to... | Look in package | Relevant Contracts / Classes |
|---|---|---|
| Add or modify an external market data provider | `src/yogi/data/providers/` | `IMarketDataProvider`, `IDataProvider`, `ProviderHealth` |
| Change instrument classification or F&O rules | `src/yogi/data/normalization/` | `InstrumentClassifier`, `NseFnoUniverse` |
| Change timeframe resampling or calendar math | `src/yogi/timeframe/` | `TimeframeSynthesizer`, `aggregate_candles` |
| Add or change an analytical calculation | `src/yogi/calculation/` | `ICalcModule`, `CalculationContext`, `CalculationResult` |
| Add or modify persistent storage engines | `src/yogi/storage/` | `IBandsRepository`, `ISecurityMetadataRepository` |
| Define or update a stable system interface | `src/yogi/core/contracts/` | Canonical contracts in `src/yogi/core/contracts/` |
| Register a new provider, calculation, or bands repository | `src/yogi/core/registry/` | `RegistryHub`, `CapabilityRegistry` |
| Change system-level execution settings | `src/yogi/core/configuration/` | `EngineConfig`, `ScreeningQuery`, `StrategyCatalog` |
| Change pipeline coordination or stage sequencing | `src/yogi/core/orchestration/` | `PipelineOrchestrator` |
| Modify boolean qualification logic | `src/yogi/filter/` | `IFilterEngine`, `FilterRuleSpec`, `FilterGroupSpec` |
| Modify relative metric ordering | `src/yogi/ranking/` | `IRankingEngine`, `RankingOrder` |
| Modify rank cutoffs or cohort survival rules | `src/yogi/selection/` | `ISelectionEngine`, `RankCutoffSpec` |
| Add or modify reusable screening recipes or mentor presets | `src/yogi/strategy/` | `StrategyEngine`, `StrategySpec`, `MENTOR_PRESETS` |
| Modify presentation column projection or exports | `src/yogi/results/` | `IResultAssembler`, `IExportFormatter` |
| Modify UI presentation, charting, or API facade | `src/yogi/cockpit/` | `router.py`, `schemas.py`, `services/`, `static/` |

---

## 14. Architectural Anti-Responsibilities ("Do Not Put It Here")

To preserve the architectural integrity of YOGI, developers and AI agents must obey these strict prohibitions:

1. **Do NOT put external network calls in Core**: `src/yogi/core/` must never import `requests`, `urllib`, `yfinance`, or vendor SDKs.
2. **Do NOT put financial calculations in Cockpit**: `src/yogi/cockpit/` must never contain `.rolling()`, `.ewm()`, or formula logic.
3. **Do NOT put screening or filtering in JavaScript**: Frontend code must never filter or rank dataset rows.
4. **Do NOT bypass the screening pipeline**: Never execute screening outside of `QUALIFY → ORDER → SHOW → LIMIT → RESULTS`.
5. **Do NOT write unversioned temporary files to the package tree**: Never commit source dumps or scratch notes into `src/`.
6. **Do NOT perform non-atomic persistence**: Storage write operations must always stage in `.tmp` before atomic replacement.

---

## 15. Verification Strategy & Backend Freeze Status

- **Automated Test Baseline**: **557 tests passing** across 13 test suites (unit, integration, golden regression).
- **Backend Status**: **FROZEN**. All backend calculation pillars, screening engines, persistent storage, and API contracts are feature-complete and frozen.
- **Next Phase**: **Mentor Review & UX/Product Design**. Presentation controls, chart sub-panes, and workbench layouts will be refined without altering the frozen backend analytical engine.

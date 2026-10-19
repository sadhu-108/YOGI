# Architecture Decisions

This file records significant architectural, technical, and design decisions per [`AGENTS.md`](../AGENTS.md).

---

## ADR-001: Stable Core with Contract-Based Connections

- **Status**: Adopted
- **Decision**: Establish `src/yogi/core/` with four distinct elements: `contracts`, `registry`, `configuration`, and `orchestration`. All cross-module communication must depend on contracts rather than concrete implementations.
- **Reason**: Enables implementations (e.g. data providers, calculations, storage engines) to be replaced without forcing changes to unrelated modules or the pipeline core.

---

## ADR-002: Separation of Filter, Strategy, Ranking, Selection, and Results

- **Status**: Adopted
- **Decision**: Maintain strict structural separation between Filter (qualification), Strategy (combination), Ranking (relative order), Selection (rank cutoff), Results (assembly), and Cockpit (presentation).
- **Reason**: Eliminates ambiguous coupling of analysis, ranking, and display logic while keeping the internal responsibilities modular and independently testable.

---

## ADR-003: Preservation of Verified Financial Mathematics

- **Status**: Adopted
- **Decision**: Existing verified financial calculations from the prototype serve as the source of truth. Refactoring follows: **Preserve → Refactor → Extend**.
- **Reason**: Prevents silent alteration or drift of verified formulas during modularization.

---

## ADR-004: RegistryHub Scope and Capability Resolution

- **Status**: Adopted
- **Decision**: Restrict `RegistryHub` strictly to three replaceable capability categories: `providers` (`IDataProvider`), `calculations` (`ICalcModule`), and `bands` (`IBandsRepository`). Security and instrument metadata is absorbed into the Provider → Normalization pipeline (`src/yogi/data/`), retaining `SecurityMetadata` as an invariant DTO without an independent `ISecurityMaster` registry category. Do not create registry categories for `securities`, `filters`, `strategies`, `rankings`, `selections`, `assemblers`, or `formatters`.
- **Reason**: 
  1. `IDataProvider.universe()` is the single authority for tradable symbols, avoiding dual-universe conflicts.
  2. Exchange reference lists (F&O, series) and trader annotations (grade, sector) are standardized during data normalization, not dynamically swappable core capabilities.
  3. Filters, rankings, selections, and results assembly represent single fixed engines driven by configuration data specifications (`FilterGroupSpec`, `RankCutoffSpec`), while strategies represent declarative composition recipes (presets).

---

## ADR-005: Core Configuration Scope and ScreeningQuery Separation

- **Status**: Adopted
- **Decision**: Structure `src/yogi/core/configuration/` into three focused components:
  1. `EngineConfig`: Immutable system-level pipeline configuration referencing stable Registry capability keys (`provider`, `bands_repository`, `calculation_modules`, `exchange`, `timeframes`, limits).
  2. `ScreeningQuery`: Immutable analytical query intent composed strictly of existing contract types (`FilterGroupSpec`, `RankingOrder`, `RankCutoffSpec`) adhering strictly to `QUALIFY → ORDER → SHOW`. Column projection is excluded from `ScreeningQuery` and owned exclusively by `IResultAssembler` in the Results engine.
  3. `StrategyCatalog`: A declarative catalog managing named `StrategySpec` compositions (mentor presets and user saved strategies) and converting them into executable `ScreeningQuery` instances. `target_cutoff_limit` maps strictly to `RankCutoffSpec` (Selection stage); `ScreeningQuery.limit` remains `None` to ensure `ISelectionRule` remains authoritative and decoupled from presentation display truncation.
- **Reason**: Maintains clean separation between Configuration ("WHAT is wanted"), Registry ("WHICH implementation provides it"), and Orchestration ("WHEN/HOW it runs"). Eliminates presentation leaks (column projection and display truncation) from analytical screening filters and strategy recipes.

---

## ADR-006: Data Providers & Normalization Boundaries

- **Status**: Adopted
- **Decision**: Structure `src/yogi/data/` into two distinct subpackages: `normalization/` and `providers/`.
  1. `IDataProvider` remains the single authoritative contract defined in `src/yogi/core/contracts/provider.py`. Do NOT create redundant intermediate base classes (e.g. `providers/base.py`).
  2. Concrete providers (`YFinanceDataProvider`, `ZerodhaDataProvider`) directly implement `IDataProvider` and return canonical contract types (`Sequence[MarketBar]`, `Mapping[str, Sequence[MarketBar]]`, `TickData`, `ProviderHealth`). Raw pandas DataFrames and proprietary API dictionaries are never exposed across the provider boundary.
  3. Market data and security master transformations are encapsulated in pure, deterministic normalizers (`normalization/bars.py`, `normalization/universe.py`).
  4. Timeframe resampling and candle aggregation are strictly excluded from the data ingestion layer and owned exclusively by Step 7 (`src/yogi/timeframe/`).
  5. Both providers support offline dependency injection (`download_fn` for Yahoo, `kite_client` and `ticker_client` for Zerodha), enabling 100% network-independent, deterministic testing.
- **Reason**: Prevents vendor API leakage into the core calculation pipeline, guarantees language-independent DTOs at system boundaries, and isolates volatile external network/protocol changes from the analytical engine.

---

## ADR-007: Timeframe Engine Bounded Responsibility

- **Status**: Adopted (Clause 7 amended by ADR-016 / YOGI-F01)
- **Decision**: Encapsulate multi-timeframe candle synthesis in `src/yogi/timeframe/` (`TimeframeEngine`, `resample_bars`, `build_market_context`, `TIMEFRAME_RULES`). Keep timeframe synthesis strictly outside Data Providers (`src/yogi/data/`) and outside Core Orchestration (`src/yogi/core/orchestration/`).
  1. Preserve verified prototype frequency mappings: `D=None`, `W="W"`, `M="ME"`, `Q="QE"`, `H="2QE"`, `Y="YE"`.
  2. Preserve OHLCV aggregation semantics: Open=first, High=max, Low=min, Close=last, Volume=sum. Missing volume (`None`) must never cause valid price bars to be discarded.
  3. Period timestamps must represent period-end boundaries using timezone-naive `datetime` objects.
  4. Unsorted input is chronologically ordered before synthesis; duplicate timestamps are resolved deterministically by retaining the last occurrence.
  5. Incomplete current periods aggregate available daily bars without artificial padding or future-peeking.
  6. Empty periods produce no synthetic bars; recent listings/IPOs produce whatever higher-timeframe bars are possible without artificial minimum-history gates.
  7. Do NOT create a dynamic registry category in `RegistryHub` for timeframes; `TimeframeEngine` is a bounded internal engine producing canonical `MarketContext` instances. *(Note: Clause 7's original prohibition against creating an abstract contract was formally superseded by ADR-016 following architectural finding YOGI-F01, which established ITimeframeEngine in src/yogi/core/contracts/timeframe.py for Core dependency inversion and mock isolation).*
- **Reason**:
  1. *Separation of Concerns*: Data providers focus exclusively on ingestion; orchestration coordinates execution; Timeframe Engine handles calendar math and resampling.
  2. *Minimalism*: Avoids creating speculative interfaces or registry categories where no requirement for multiple swappable implementations exists.
  3. *Mathematical Invariants*: Guarantees consistent bar boundaries and pricing inputs for downstream calculation modules.

---

## ADR-008: Calculation Engine Modularization & Four Mathematical Pillars

- **Status**: Adopted
- **Decision**: Structure analytical calculations in `src/yogi/calculation/` across four distinct mathematical pillars (`bands`, `velocity`, `impulse`, `trend`), each implementing the canonical frozen `ICalcModule` contract (`calculate(symbol, context) -> CalculationResult`).
  1. Register the four modules under keys `"bands"`, `"velocity"`, `"impulse"`, and `"trend"` in `RegistryHub.calculations`.
  2. Decouple calculation execution completely from qualification (filtering), ranking, selection, and results presentation. Calculation modules compute analytical metrics into `CalculationResult.metrics` without filtering or sorting candidates.
  3. Preserve verified prototype mathematics exactly:
     - **Bands**: Upper/lower envelope levels, positions, states (`ABOVE`, `BELOW`, `IN`, `na`), distances beyond edge, and multi-timeframe counts.
     - **Velocity**: Rolling sprint speeds (`S4`..`S52`), accelerations (`ACCEL_S`, `ACCEL_L`), consistency flags (`SPR_CONSIST`), and anchored sprints (`SPA_A*`).
     - **Impulse**: Pure zigzag swing detection and Ram's 50% recovery rule (`IC="IP"|"CR"|"up"|"na"`, `IC_PCT`, `IC_BARS`, `IC_RATIO`).
     - **Trend**: Trailing ROCs (`DROC`..`YROC`), calendar blocks (Quarter, Half, Year), multi-year CAGRs, ATH diff, EMA 3/5 ribbon states, `SUSPECT` data sanity flag, and multi-timeframe DMI/ADX.
  4. *Prototype as Evidence, Not Immutable Authority*:
     - Pipeline DMI default is `(5, 5)` matching prototype `candle_rules.DEFAULTS`, fully overridable via `context.parameters`.
     - Standalone `dmi()` function signature default remains Wilder's `(14, 14)` for direct mathematical use.
     - When DMI is active, all six timeframes (`D, W, M, Q, H, Y`) are populated in `metrics`; timeframes with $< 6$ bars receive `None` numeric values and `"na"` state, guaranteeing schema consistency.
     - Close-only data (e.g. Bhavcopy fixtures) where high == low omits DMI keys, preserving exact parity with golden regression fixtures.
- **Reason**:
  1. *Fidelity*: Eliminates mathematical drift against verified prototype behavior while achieving 100% precision on golden regression fixtures.
  2. *Modularity*: Replaces monolithic prototype procedural scripts with four isolated, independently testable, replaceable calculation pillars.
  3. *Clean Architecture*: Keeps business logic, screening criteria, and presentation concerns completely out of mathematical engines.
---

## ADR-009: Twelve Data Provider Adapter Integration

- **Status**: Adopted
- **Decision**: Implement `TwelveDataProvider` strictly as an external market-data adapter satisfying the frozen `IDataProvider` contract (`src/yogi/core/contracts/provider.py`).
  1. Implementation placed in `src/yogi/data/providers/twelve_data.py` and exported via `src/yogi/data/providers/__init__.py`.
  2. Normalization functions placed in `src/yogi/data/normalization/bars.py` (`normalize_twelve_data_bars`, `normalize_twelve_data_batch`).
  3. Credentials resolved via `TWELVE_DATA_API_KEY` (or `TWELVEDATA_API_KEY`) environment variable or constructor argument; secret masking (`_mask_api_key`) enforced on all error strings and logs.
  4. Symbol translation (`twelve_data_symbol`) strips `.NS`/`.BO` suffixes and handles exchange colons without altering canonical YOGI symbol representations.
  5. Registered in `RegistryHub.providers` under `"twelvedata"` and `"twelve_data"`.
  6. Plan Gating & Health Check Benchmark: Twelve Data gates certain equities (e.g., `RELIANCE` on NSE/BSE) behind paid tiers ('Grow' or 'Venture'), returning HTTP 404 with a JSON payload (`This symbol is available starting with the Grow or Venture plan`). Universally accessible benchmark equity `INFY` is used as the default health check symbol (`DEFAULT_HEALTH_SYMBOL = "INFY"`) with automatic fallback in `health()`, and JSON error decoding handles HTTP 400/404 rich error payloads gracefully.
- **Reason**:
  1. Preserves Stable Core: zero changes to analytical calculations, filters, ranking, selection, or Core contracts.
  2. Fulfills the Replaceable Module principle: Twelve Data is a swappable adapter alongside Yahoo Finance and Zerodha.
  3. Ensures complete offline deterministic testability without network dependencies or hardcoded credentials.

---

## ADR-010: Cockpit Live Twelve Data Provider Connection & Demo Isolation

- **Status**: Adopted
- **Decision**: Connect `TwelveDataProvider` directly to the Cockpit's application layer (`src/yogi/cockpit/state.py`) through the canonical `RegistryHub` and `PipelineOrchestrator` path, strictly isolating DEMO mode from LIVE mode:
  1. **Provider Resolution**: The Cockpit routes live data requests through the existing `CapabilityRegistry[IDataProvider]` under key `"twelvedata"`.
  2. **Demo Mode Isolation**: When LIVE mode is active, `DemoDataProvider` is completely disconnected and excluded from dataset construction. Provider failures bubble up directly as live-provider errors (HTTP 500) and NEVER silently fall back to `DemoDataProvider`.
  3. **Preservation of Demo Mode**: `DemoDataProvider` remains intact and accessible when `provider="demo"` is explicitly requested, loading the verified 5 golden stocks dataset. Switching between Demo and Live atomically replaces the dataset reference, preventing data mixing.
  4. **Rate-Limit & Free-Tier Safety**: For Twelve Data, unconstrained refresh requests default safely to confirmed accessible benchmark equity `("INFY",)` instead of downloading the entire 3,792 stock NSE universe, strictly respecting the 8 credits/min free-tier limit.
  5. **Presentation Chart Caching**: `ChartDataService` caches daily bars in-memory for the active chart stock across timeframe toggles (`D`, `W`, `M`, `Q`, `H`, `Y`), preventing redundant vendor API hits while allowing local multi-timeframe resampling via `TimeframeEngine`.
- **Reason**:
  1. *Architectural Integrity*: Maintains the single-pipeline architecture without secondary data paths or duplicated calculation logic.
  2. *Operational Clarity*: Transparently differentiates DEMO mode from LIVE mode in the Cockpit UI (`MODE: LIVE (TWELVE DATA / NSE)` vs `MODE: DEMO (5 STOCKS)`).
---

## ADR-011: Replacement of LIVE Market Data Provider with Yahoo Finance (yfinance) for Full Universe Screening

- **Status**: Adopted (Supersedes ADR-009 & ADR-010 for LIVE feed)
- **Decision**: Replace Twelve Data with `YFinanceDataProvider` as the primary LIVE market-data provider for full Indian equities universes (NSE & BSE) through the existing `IDataProvider` contract and dynamic `RegistryHub` resolution:
  1. **Provider Resolution**: The Cockpit routes live requests through `CapabilityRegistry[IDataProvider]` under key `"yfinance"`.
  2. **Full Live Universe Pass-Through**: Completely eliminate the Twelve Data-specific 1-stock (`INFY`) workaround and 8 credits/min rate limit constraints. When unconstrained LIVE dataset refresh is initiated (`symbols=None`), `PipelineOrchestrator` triggers `provider.universe(config.exchange)`, discovering and passing through the full configured/discovered market universe with NO artificial caps or truncations.
  3. **Strict Demo Mode Isolation**: DEMO mode remains 100% offline, deterministic, and isolated (5 golden stocks: `MANYAVAR`, `SBCL`, `EMIL`, `MOREPENLAB`, `JUBLINGREA`). Live provider failures bubble up directly as explicit errors (HTTP 500) and NEVER silently fall back to `DemoDataProvider`. Switching between Demo and Live clears presentation caches and atomically replaces the dataset pointer.
  4. **Strict Test Isolation**: All offline unit and integration tests inject deterministic mock providers or pass explicit symbols to prevent unintended external internet requests to Yahoo Finance servers during automated CI/test execution.
  5. **Zero Core Invariant Changes**: No modifications to analytical calculations, timeframe synthesis, qualification rules, ranking, selection, or Core contracts.
- **Reason**:
  1. *Complete Market Coverage*: Yahoo Finance provides free, unthrottled historical coverage for Indian equities without the 8 credits/min rate limits or paid-plan gating inherent to Twelve Data free tier.
  2. *Architectural Modularity*: Confirms YOGI's founding principle ("Stable Core • Replaceable Modules • Contract-Based Connections") by swapping vendors purely through the `IDataProvider` adapter interface without touching Core math or pipeline logic.
  3. *Zero Vendor Credential Burden*: Enables immediate out-of-the-box live screening and chart viewing without requiring user API keys or subscription setups.

---

## ADR-012: Configurable Half-Year (H) Policy & Robust CAGR Calculation Safety

- **Status**: Adopted
- **Decision**: 
  1. **Configurable Half-Year (`H`) Timeframe Policy**:
     - Introduce a persisted configuration option supporting two modes:
       - `prototype` (Default): Preserves existing pandas `2QE` resampling (periods ending March 31 and September 30), maintaining exact 0.000000 drift parity with the prototype and golden fixtures.
       - `calendar`: Resamples to true calendar half-years: H1 (January 1 – June 30, ending June 30) and H2 (July 1 – December 31, ending December 31).
     - Persist the selection in `data/settings.json` via Cockpit Settings API (`GET /api/settings`, `POST /api/settings`).
     - Expose the setting in the Cockpit UI Sidebar Card 1 with radio buttons (`Prototype-Compatible` vs `Calendar Half-Year`).
     - Propagate the policy through `EngineConfig`, `TimeframeEngine`, `MarketContext`, `TrendCalculator` (`half_block`, `bars_cache`), and Chart presentation services.
  2. **Robust `cagr_trailing()` Edge-Case Safety**:
     - In `src/yogi/calculation/trend/calculator.py`, guard `cagr_trailing(close, years)` against:
       - Empty, `None`, or insufficient close price series (`len < 2`).
       - Non-positive period count (`n <= 0`).
       - Non-finite price inputs (`inf`, `-inf`, `NaN`).
       - Negative starting price or negative ending price (`start <= 0`, `end < 0`), safely returning `None`.
       - Total capital loss (`start > 0` and `end == 0.0`), returning `-100.0` percent.
       - Non-finite calculation results, returning `None`.
     - Standard valid positive equity price formula `((end / start) ** (1.0 / n) - 1.0) * 100.0` is strictly preserved.
- **Reason**:
  1. *Prototype Parity vs Calendar Correctness*: Allows users and mentors to toggle between calendar-accurate H1/H2 boundaries and legacy prototype fidelity without breaking golden regression fixtures.
  2. *Mathematical Soundness*: Prevents `ZeroDivisionError`, `ValueError: negative number to a fractional power` (complex numbers), and `inf` contamination in screening cohorts, while accurately reflecting complete capital write-downs (-100%).

---

## ADR-013: Fast Startup, Persistent Local Cache & Non-Blocking Background Rebuild

- **Status**: Adopted
- **Decision**:
  1. **Persistent Local Storage (`DatasetCache` & `MarketBarsCache`)**:
     - Place storage implementations in `src/yogi/storage/cache.py` and export via `src/yogi/storage/__init__.py`.
     - Persist calculated multi-timeframe feature datasets (`data/cache/dataset_<EXCHANGE>_<PROVIDER>.pkl`) with cache schema versioning (`CACHE_VERSION = 1`), creation timestamps, half-year policy tags, and sample integrity checks.
     - Persist raw historical daily market bars partitioned by symbol (`data/cache/bars_<EXCHANGE>_<PROVIDER>.pkl`) with thread-safe incremental merge capabilities (`save_bars`, `load_bars`, `get_bars_for_symbols`).
     - Enforce atomic file operations (write to `.tmp` file, `flush()`, `os.fsync()`, and `os.replace()`) to prevent corrupted partial writes during abrupt termination or power failure.
  2. **Fast Startup (<100ms)**:
     - On Cockpit startup, `AppState.load_persisted_cache()` checks for a valid local dataset matching the active exchange, provider, and half-year policy. If present, it deserializes and activates the dataset instantly in <100ms.
     - Results are immediately available for screening, ranking, drawer inspection, and presentation table rendering without awaiting network requests.
     - Status endpoint and UI badges clearly indicate `is_cached=True` (`MODE: LIVE (YFINANCE / NSE) (CACHED)`).
  3. **First-Run Behavior & Non-Blocking Rebuilds**:
     - If no valid local dataset exists on startup, FastAPI `lifespan` triggers an initial background rebuild on a dedicated daemon thread without blocking HTTP request acceptance or delaying server availability.
     - Full-universe rebuilds initiated via `POST /api/dataset/refresh` with `background=True` return HTTP 200 immediately with `status="BUILDING"`, decoupling long-running downloads from HTTP gateway/client timeouts.
     - Granular job lifecycle state (`IDLE`, `BUILDING`, `READY`, `FAILED`) is exposed via `GET /api/status`, including numeric progress (0.0 to 1.0), descriptive stage labels, and failure diagnostics.
     - Concurrency locks reject duplicate concurrent rebuild requests, safely returning the in-flight job status without spawning duplicate background threads.
  4. **Incremental Market Bar Reuse**:
     - In `PipelineOrchestrator.build_dataset()`, evaluate `bars_cache` before vendor querying. Symbols with valid historical depth ($\ge 60$ daily bars) are loaded locally; only new or missing symbols are retrieved from the provider.
     - Freshly downloaded bars are merged and persisted back to `MarketBarsCache`, turning subsequent rebuilds into fast local feature computations rather than repetitive 15-minute network downloads.
     - An explicit bypass flag `force_refresh_bars=True` is provided for scheduled or user-commanded full history refreshes.
  5. **Atomic Swap & Failure Recovery**:
     - The background rebuild process constructs the replacement dataset completely in an isolated workspace.
     - After verifying data integrity and non-emptiness, `AppState` swaps the `self._dataset` pointer atomically under a mutex lock.
     - If a rebuild fails (due to network timeout, DNS failure, or vendor error), `AppState` records `build_status="FAILED"` and the exception message while retaining the prior valid active dataset completely intact.
  6. **Strict Demo & LIVE Isolation**:
     - Ephemeral Demo mode (5 golden stocks) is strictly isolated from disk persistence. Demo refreshes never write to or overwrite `data/cache/dataset_*.pkl`.
     - Switching between Demo and Live remains clean and idempotent without cross-contamination.
- **Reason**:
  1. *Immediate Responsiveness*: Eliminates the multi-minute startup lag, delivering the instant usability observed in the prototype while keeping YOGI's modular architecture intact.
  2. *Resilience & Fault Tolerance*: Eliminates UI freezes and gateway timeout errors during full-universe builds (~2,100 NSE equities), and protects users from data loss when network drops occur.
  3. *Network Efficiency*: Drastically minimizes external Yahoo Finance API consumption by reusing verified daily market bars across indicator updates and strategy recalculations.

---

## ADR-014: Deterministic Ingestion Planning, Timestamp Bar Merging & Safe Incremental Ingestion

- **Status**: Adopted
- **Decision**:
  1. **Timestamp-Based Bar Merging (`merge_market_bars`)**:
     - When saving daily bars into `MarketBarsCache`, merge incoming bars with existing historical bars by `timestamp` rather than replacing a symbol's entire history.
     - Deduplicate bars on timestamp collisions retaining the incoming bar's values, preserve strict chronological ordering, and treat empty/None updates non-destructively.
  2. **Backward-Compatible Date-Range Provider Contract**:
     - Extend `IDataProvider.daily_history` and `IDataProvider.batch_daily_history` with optional `start_date` and `end_date` parameters.
     - Enforce exclusive end-date semantics (`start_date <= timestamp < end_date`) matching standard vendor API and datetime interval conventions.
     - Validate boundaries: reject `start_date >= end_date`, reject specifying `end_date` without `start_date`, and forbid mixing naive with timezone-aware datetimes.
  3. **Deterministic Ingestion Planning (`IngestionPlanner`)**:
     - Evaluate cached bars against target evaluation timestamp and classify each requested symbol into one of three deterministic actions:
       - `UP_TO_DATE`: Symbol contains adequate historical depth (>= 60 bars) and its latest bar matches or exceeds the expected last trading session. Zero network requests triggered.
       - `INCREMENTAL_UPDATE`: Symbol contains valid historical depth but latest bar predates the target session. Plan bounded date range fetching only missing candles (`start_date = last_bar.date + 1 day`, `end_date = target_date + 1 day`).
       - `FULL_BACKFILL`: Symbol is uncached, has corrupt/unsorted/duplicate bars, or insufficient depth (< 60 bars). Plan full historical backfill (`years=config.historical_years`).
     - Freshness evaluation incorporates `INDIAN_TRADING_HOLIDAYS` and handles weekends, multi-day holidays, and market close cutoff times (`16:00 IST`).
  4. **Pipeline Integration & Fault Tolerance**:
     - In `PipelineOrchestrator.build_dataset()`, partition requested universe into the three cohorts.
     - Group incremental updates by date range and fetch in chunked batches (size 100) using `provider.batch_daily_history()`.
     - Automatically fall back to per-symbol `provider.daily_history()` if a batch fails or omits requested symbols.
     - Failures are recorded in `failed_symbols`. If all requested symbols fail, or if `require_all_symbols=True` / `required_symbols` includes a failed ticker, raise `DataProviderError`. For broad universe scans, individual symbol failures exclude the symbol from calculations while logging diagnostics without aborting the universe run.
  5. **Persistence vs Publication Separation**:
     - Ingestion writes to disk bar cache during execution via `bars_cache.save_bars()`.
     - Active dataset publication in Cockpit (`AppState.refresh`) is atomic: `self._dataset` is swapped only after all stages succeed and non-empty records are produced. A failed rebuild preserves the previous active dataset intact.
  6. **Known Limitations & Boundary Observations**:
     - *Internal Historical Gaps*: Planner inspects latest bar timestamp and total count; internal mid-history missing trading days without count deficit are not detected.
     - *Holiday Calendar Bound*: `INDIAN_TRADING_HOLIDAYS` is a hardcoded set currently covering 2024–2026. Dates beyond 2026 require calendar maintenance.
     - *Corporate Actions & Delistings*: Ticker symbol renames and delisted stocks are not automatically reconciled by the planner.
     - *Non-Transactional Bar Cache*: Disk cache writes use merge-on-save rather than transactional ACID rollbacks; however, merge operations are idempotent across retries.
     - *Architectural Coupling (Resolved)*: Originally `PipelineOrchestrator` directly imported planning types (`IngestionCohort`, `IngestionPlan`, `plan_ingestion`) from `yogi.storage.cache`. In Prompt B, this ingestion loop, freshness planning, and cache persistence were extracted into `MarketDataIngestionService` (`src/yogi/data/ingestion/`), restoring `PipelineOrchestrator` as a pure coordinator.
- **Reason**:
  1. *Bandwidth & Time Optimization*: Rebuilding a 2,345-stock universe reduces network payload from ~330MB of historical data to a few daily bars, accelerating daily refreshes by orders of magnitude.
  2. *Historical Data Protection*: Prevents incremental partial updates from truncating years of pre-existing daily market bars.
  3. *Zero-Interruption Resilience*: Retains active screening datasets during network or vendor outages.

---

## ADR-015: EMA, Band, ROC Filtering and Multi-Period Ranking Contract Separation

- **Status**: Adopted (Architectural Design Contract for Upcoming Features)
- **Decision**:
  1. **Screening Architecture Boundaries (`QUALIFY → ORDER → SHOW → LIMIT → RESULTS`)**:
     - Maintain strict separation of responsibilities across the screening pipeline ([ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results)):
       - **Filter Engine (`QUALIFY`)**: Evaluates boolean qualification conditions against candidate records (`IFilterRule`, `FilterGroupSpec`). Disqualifies non-matching securities. Answers: *"Does it qualify?"*
         - **EMA Filter**: Evaluates configured EMA conditions only.
         - **Band Filter**: Evaluates a security's position relative to the configured band envelope only.
         - **ROC Filter**: Evaluates configured rate-of-change conditions only.
         - *Boundary Invariant*: Filter rules evaluate qualification only. Filters must **never** own, perform, or implement ranking.
       - **Ranking Engine (`ORDER`)**: Independently establishes ordinal relative standings across qualified securities (`IRankingRule`, `RankingOrder`). Injects dynamic cohort ranks (`RANK_{metric}`) and rank changes (`RANK_CHG`). Answers: *"Where does it stand?"*
         - *Boundary Invariant*: Ranking must never alter filter definitions, disqualify records, or force filter redesigns.
       - **Selection Engine (`LIMIT`)**: Authoritatively applies rank-based cutoffs and cohort survival limits (`ISelectionRule`, `RankCutoffSpec`). Answers: *"Does its rank qualify?"*
       - **Results Layer (`SHOW` / `RESULTS`)**: Projects requested presentation columns and packages immutable output payloads (`IResultAssembler`) without filtering, ranking, or selection. Answers: *"What should be displayed?"*
       - **Cockpit UI**: Gathers user query configuration and renders results; contains **zero** financial formulas, filtering logic, or ranking algorithms.
  2. **EMA UI & Configuration Design**:
     - **Interaction Sequence**:
       1. *Timeframe Selection FIRST*: The user selects the timeframe (`D`, `W`, `M`, `Q`, `H`, `Y`) before period inputs become active.
       2. *Period Selection*: The user chooses the first ($P_1$) and second ($P_2$) EMA periods.
       3. *State Selection*: The user selects the desired EMA state (`UP`, `DOWN`, `UPCUT`, `DOWNCUT`).
       4. *Add Condition*: The user can click an "Add Condition" control to append additional EMA conditions into the screening specification.
     - **Explicit Period Caps by Timeframe**:
       - Daily (`D`): Max 31
       - Weekly (`W`): Max 52
       - Monthly (`M`): Max 12
       - Quarterly (`Q`): Max 4
       - Half-yearly (`H`): Max 2
       - Yearly (`Y`): Max 1
       - *Contract Invariant*: These period caps are mentor-specified product constraints, **not** mathematical limitations of the exponential moving average. The Cockpit UI must update dynamically when the timeframe changes, actively invalidating or clamping out-of-range period inputs.
     - **EMA States & Intended Semantics**:
       - `UP` (Green): First EMA > Second EMA ($EMA_{P1} > EMA_{P2}$).
       - `DOWN` (Red): First EMA < Second EMA ($EMA_{P1} < EMA_{P2}$).
       - `UPCUT` (Green): First EMA crosses above Second EMA on the current bar ($EMA_{P1, t} > EMA_{P2, t}$ and $EMA_{P1, t-1} \le EMA_{P2, t-1}$).
       - `DOWNCUT` (Red): First EMA crosses below Second EMA on the current bar ($EMA_{P1, t} < EMA_{P2, t}$ and $EMA_{P1, t-1} \ge EMA_{P2, t-1}$).
     - **Distinction from Current Backend Implementation**:
       - *Current Implementation*: In `TrendCalculator`, EMA calculation is currently hardcoded to fixed periods `EMA_FAST=3` and `EMA_SLOW=5` across the 6 timeframes, producing discrete categorical states `'yes'`, `'no'`, `'upcut'`, `'downcut'`, or `'na'`, alongside the composite `EMA_UP_COUNT` metric (0–6).
       - *Agreed Future Contract*: The upcoming capability introduces arbitrary user-configurable period pairs $(P_1, P_2)$ per timeframe within the documented period caps. Dynamic periods will be supported through parameterized calculation contracts while preserving the legacy fixed 3/5 metrics for backward compatibility with established mentor presets (e.g., `A2_ALL_6_TF_EMA_UP`).
     - **Multiple EMA Conditions Composition**:
       - Multiple EMA conditions are composed into the query using the existing `FilterGroupSpec` contract with `match="all"` (AND) or `match="any"` (OR) logic, with optional group-level negation (`is_negated`).
  3. **Band Filter Design**:
     - **Configuration**: The user selects or configures the band envelope via the existing `IBandsRepository` and `calculate_band_envelope()` model.
     - **Position Categories**:
       - `Above`: Price is above the upper band ($Close > UpperBand$).
       - `Within`: Price is within the band envelope ($LowerBand \le Close \le UpperBand$).
       - `Below`: Price is below the lower band ($Close < LowerBand$).
     - **Multi-Selection**: The user can select 1, 2, or all 3 position categories simultaneously (e.g., `Above` OR `Within`).
     - **Qualification Only**: The Band filter evaluates qualification only (`QUALIFY`), reusing authoritative band calculations (`calculate_band_envelope()`, `BD_*`); it contains zero duplicate envelope mathematics.
  4. **ROC Filter vs Multi-Period ROC Ranking**:
     - **ROC Filter (`QUALIFY`)**: Evaluates boolean rate-of-change thresholds (e.g., `MROC > 0`, `DROC >= 2.5`).
     - **ROC Ranking (`ORDER`)**: Independently establishes relative performance standings across eligible securities.
     - **Ranking Capabilities**:
       - Standard timeframe rankings across `D`, `W`, `M`, `Q`, `H`, `Y`.
       - Year-to-Date (`YTD`) ranking.
       - Extended 5-year ranking.
       - Combined 5-year average ranking (*exact mathematical aggregation formula recorded as an open product decision*).
       - Multiple selectable periods (e.g., 3-month and 3-year), preserving separate ranks and metric values per period (e.g., `RANK_ROC_3M` and `RANK_ROC_3Y`) in output records.
       - Separate ranking periods must **never** be silently merged or collapsed into a single composite score without an explicitly documented aggregation formula.
       - Directional sorting: **Leaders** (highest-first, `RankingOrder.DESCENDING`) and **Backbenchers** (lowest-first, `RankingOrder.ASCENDING`).
  5. **Composition Examples & Ordering**:
     - *Example A (Multi-Filter + Single Ranking)*:
       - **QUALIFY**: Weekly EMA UP (`W_EMA_UP == True`) AND Band Above (`M_BAND_POS == 'ABOVE'`) AND Daily ROC condition (`DROC > 0`).
       - **ORDER**: Rank by 3-Month ROC descending (Leaders).
       - **SHOW**: Project summary and momentum columns.
     - *Example B (Multi-Timeframe EMA Filter + Multi-Period Ranking & Cutoff)*:
       - **QUALIFY**: Weekly EMA UP (`W_EMA_UP == True`) AND Daily EMA UPCUT (`D_EMA_STATE == 'UPCUT'`).
       - **ORDER**: Rank by YTD ROC descending.
       - **LIMIT**: Rank survival cutoff Top 50 (`RankCutoffSpec(rank_metric="RANK_YTD_ROC", max_rank=50)`).
       - **SHOW**: Project summary and ranking columns.
     - *EMA-Based Ordering*:
       - Mentor specification requires ordering securities in EMA `UP` / `UPCUT` states strongest-first, and `DOWN` / `DOWNCUT` states weakest-first (*exact strength metric recorded as an open product decision*).
  6. **Ledger of Decided vs Open Product Decisions**:
     - **Decided Contracts**:
       - Strict pipeline separation: `QUALIFY → ORDER → SHOW → LIMIT → RESULTS`.
       - EMA configuration interaction sequence: Timeframe selection FIRST.
       - Exact period caps per timeframe (`D`: 31, `W`: 52, `M`: 12, `Q`: 4, `H`: 2, `Y`: 1) as mentor product constraints with dynamic UI validation.
       - Four EMA states (`UP`, `DOWN`, `UPCUT`, `DOWNCUT`) and semantic definitions.
       - Three Band position categories (`Above`, `Within`, `Below`) with multi-select support.
       - Separation of ROC qualification filtering from ROC ranking.
       - Multi-period ranking preserving distinct ranks and values per period.
       - Directional ranking modes: Leaders (highest-first) and Backbenchers (lowest-first).
     - **Open Product Decisions & Assumptions (Pending Mentor Direction)**:
       - *Combined 5-Year Average ROC Formula*: The precise mathematical aggregation formula across the 5 years (e.g., arithmetic mean of 5 individual calendar year percentage returns $\frac{1}{5}\sum_{i=1}^5 Y_i$, 5-year compound annual growth rate CAGR, or 5-year cumulative rolling ROC) remains an open product decision.
       - *EMA Strength Ordering Metric*: The quantitative metric used to order EMA states strongest-first / weakest-first (e.g., percentage spread $\frac{EMA_{fast} - EMA_{slow}}{EMA_{slow}} \times 100$, raw price delta $EMA_{fast} - EMA_{slow}$, or rate of spread expansion) remains an open product decision.
       - *Dynamic EMA Calculation Architecture*: The operational approach for dynamic $(P_1, P_2)$ calculations (precomputed in dataset build vs computed on-demand per screening query in `TrendCalculator` / `PipelineOrchestrator`) remains an open architectural decision to be finalized during implementation design.
- **Reason**:
  - Preserves YOGI's non-negotiable architectural invariant: *Stable Core • Replaceable Modules • Contract-Based Connections*.
  - Eliminates coupling between boolean qualification and ordinal ranking, ensuring each engine has a single responsibility.
  - Documents mentor product constraints explicitly distinct from mathematical limits, ensuring predictable UI behavior.
  - Formally identifies unresolved product decisions to prevent unilateral architectural assumptions.

---

## ADR-016: Timeframe Engine Contract (ITimeframeEngine) Adoption & Reconciliation

- **Status**: Adopted (Formalizes YOGI-F01 and supersedes ADR-007 clause 7 contract prohibition)
- **Context**:
  ADR-007 originally established the bounded responsibility of `TimeframeEngine` and prohibited creating an `ITimeframeEngine` contract to prevent unnecessary abstraction layers or adding a dynamic timeframe registry category to `RegistryHub`.
  However, during Step 5 implementation and the subsequent architectural audit, finding YOGI-F01 identified that without an abstract interface, `PipelineOrchestrator` in `src/yogi/core/orchestration/` was forced to depend directly on the concrete `TimeframeEngine` implementation in `src/yogi/timeframe/engine.py`. This violated Core's fundamental rule: *"Depend on contracts, not concrete implementations."* Furthermore, it prevented testing `PipelineOrchestrator` in isolation without executing concrete pandas aggregations.
- **Decision**:
  1. **Adopt `ITimeframeEngine` Contract**: Formally approve and adopt the `ITimeframeEngine` abstract base class located at `src/yogi/core/contracts/timeframe.py`, exporting it via `src/yogi/core/contracts/__init__.py`.
  2. **Supersede ADR-007 Clause 7 Contract Prohibition**: Clause 7 of ADR-007 is superseded regarding contract creation. `ITimeframeEngine` is recognized as an authoritative Core contract governing multi-timeframe candle synthesis and `MarketContext` construction.
  3. **Preserve ADR-004 Registry Boundaries (Three Pillars Only)**: `ITimeframeEngine` is strictly a contract for dependency injection into `PipelineOrchestrator`, `AppState`, and `ChartDataService`. It is **NOT** added to `RegistryHub` (which remains strictly limited to `providers`, `calculations`, and `bands` per ADR-004).
  4. **Preserve All Other ADR-007 Invariants**: All other clauses of ADR-007 (OHLCV aggregation semantics, frequency mappings, period-end boundary timestamps, unsorted bar handling, missing volume preservation, and incomplete period aggregation) remain active, authoritative, and unchanged.
  5. **Authoritative Naming Reconciliation**: The contract is authoritatively named `ITimeframeEngine` (as implemented in `src/yogi/core/contracts/timeframe.py`). Documentation references to `ITimeframeSynthesizer` in `docs/architecture.md` and `docs/system-overview.md` are reconciled to `ITimeframeEngine`.
- **Reason**:
  1. *Architectural Integrity & Dependency Direction*: Enables Core orchestration (`src/yogi/core/orchestration/pipeline.py`) to depend exclusively on stable abstractions in `src/yogi/core/contracts/` rather than concrete domain modules in `src/yogi/timeframe/`.
  2. *Isolated Testability*: Allows unit and integration tests (e.g. `tests/core/test_orchestration.py`) to inject mock timeframe engines (`MockTimeframeEngine`) without requiring heavy pandas processing.
  3. *Zero Implementation Drift*: Matches the verified, frozen codebase with zero code modifications and 100% test pass rate.
- **Consequences**:
  - `docs/decisions.md`, `docs/architecture.md`, `docs/system-overview.md`, and `docs/current-state.md` are brought into complete consistency with the actual repository code.
  - No code changes are required; existing implementations and tests continue to pass without disruption.
- **Rejected Alternatives**:
  - *Deleting `ITimeframeEngine` (Strict ADR-007 adherence)*: Rejected because it would force `core/orchestration/pipeline.py` to import directly from `timeframe/engine.py`, violating `AGENTS.md` dependency rules, breaking test isolation, and breaking existing tests (`test_orchestration.py:781-817`, `test_half_year_policy.py:175-195`).
  - *Adding `timeframes` to `RegistryHub`*: Rejected because timeframes are not a dynamically swappable plugin capability; doing so would violate ADR-004 (Three Pillars Only). Dependency injection satisfies all architectural needs without registry proliferation.

---

## ADR-017: Dynamic EMA Condition Builder Architecture & Contract Integration

- **Status**: Adopted
- **Context**:
  Prompt 10 introduced the requirement to upgrade YOGI from fixed 3/5 EMA quick toggles (`EMA_D`..`EMA_Y`) to a user-configurable Dynamic EMA Condition Builder. The builder exposes standard timeframes (`D, W, M, Q, H, Y`) with arbitrary integer periods $(P_1, P_2)$ bounded by timeframe-specific maximum caps (`D`: 31, `W`: 52, `M`: 12, `Q`: 4, `H`: 2, `Y`: 1) and 4 directional states (`UP`, `DOWN`, `UPCUT`, `DOWNCUT`). Because 2-period dynamic crossover screening requires distinct positive integer periods ($P_1 \ne P_2 \ge 1$), dynamic screening is supported on timeframes with cap $\ge 2$ (`D, W, M, Q, H`), while Yearly (`Y`, cap 1) is excluded from dynamic 2-period crossover screening.
  Multiple design gates and contracts required formal architectural decision:
  1. Ranking integration vs screening qualification.
  2. Higher-timeframe candle-completion policy for crossover evaluation.
  3. Equal periods constraint ($P_1 == P_2$).
  4. Crossover lookback horizon.
  5. Architecture model: On-demand evaluation vs dataset precomputation.
- **Decision**:
  1. **Decision Gate Resolutions**:
     - **A1 (Ranking Model)**: Defer EMA ranking; implement backend calculation, validation, dynamic filtering, and Cockpit UI now; leave ranking unranked.
     - **A2 (Candle-Completion Policy)**: Closed candle only: evaluate crossovers strictly on the last completed candle (`iloc[-2]` vs `iloc[-3]`) for higher timeframes (`W, M, Q, H, Y`); Daily (`D`) uses latest available bar (`iloc[-1]` vs `iloc[-2]`).
     - **A3 (Equal Periods)**: Disallow $P_1 == P_2$ with validation error: $P_1$ and $P_2$ must be distinct positive integers $\ge 1$.
     - **A4 (Crossover Lookback)**: Latest evaluation candle only (lookback = 1 candle): cross occurred on the current evaluation bar.
  2. **Architectural Model**:
     - *On-Demand Dynamic Evaluation*: Dynamic EMA conditions are evaluated on-demand during the `QUALIFY` stage in `PipelineOrchestrator.execute_screen()`. Daily bars are resolved from `bars_cache` without live provider network calls, resampled to requested timeframes via `ITimeframeEngine.resample()`, and calculated via `calculate_dynamic_ema_signal()`.
     - *Zero Dataset Pollution*: Core feature dataset `_dataset` remains unpolluted with ad-hoc $(P_1, P_2)$ columns.
     - *Backwards Compatibility*: Fixed 3/5 EMA fields (`EMA_D`..`EMA_Y`, `EMA_UP_COUNT`, legacy `UPCUT`) remain precomputed in `_dataset` for existing consumers, table strips, stock detail drawer, and all 21 mentor presets.
  3. **Contract Extensions**:
     - `FilterRuleSpec` and `FilterRuleIn` extended with optional structured fields: `condition_type`, `timeframe`, `p1`, `p2`, `state`, `lookback`.
     - `FilterEngine._eval_leaf` evaluates `condition_type == "ema"`, respecting the mathematical invariant that an `UPCUT` satisfies `UP` ($EMA_{fast} > EMA_{slow}$), and `DOWNCUT` satisfies `DOWN`.
  4. **Cockpit UI Integration**:
     - Dedicated `#emaBuilderSection` with timeframe segmented buttons (`D, W, M, Q, H, Y`), dynamically clamped period dropdowns, 4 styled state buttons (green for UP/UPCUT, red for DOWN/DOWNCUT), and client-side instant live preview without firing premature `/api/screen` network requests.
     - Legacy `#emaQuickToggles` preserved in DOM as hidden compatibility element.
- **Reason**:
  - Adheres strictly to `QUALIFY → ORDER → SHOW → LIMIT → RESULTS`.
  - Preserves immutable dataset contracts and prevents infinite column proliferation.
  - Guarantees complete backwards compatibility across all existing mentor presets and automated test suites.
- **Consequences**:
  - Full support for multi-timeframe dynamic EMA screening with zero regressions.

---

## ADR-018: Modular Condition Evaluators & Calculation Registry Dynamic Dispatch for Filtering

- **Status**: Adopted
- **Context**:
  The EMA Modular Architecture Compliance Audit identified architectural violations in the initial dynamic EMA screener implementation:
  1. `PipelineOrchestrator` directly imported concrete calculation function `calculate_dynamic_ema_signal` from `yogi.calculation.trend`, violating Core dependency inversion (Layer 1 depending on Layer 2).
  2. `FilterEngine` contained hardcoded `if rule.condition_type == "ema":` evaluation and formatting branches, violating the Open/Closed Principle and impeding future filtering capabilities (Ranking, ROC, Bands, RSI, etc.).
  3. `FilterRuleSpec` lacked a generic, extensible dictionary (`params`) to carry non-EMA filter parameters.
  4. Dynamic indicator calculations could not be substituted or mocked via `RegistryHub.calculations`.
  5. The Yearly timeframe cap of `1` alongside the $P_1 \ne P_2 \ge 1$ requirement precluded dynamic 2-period crossover evaluation on Yearly bars.
- **Decision**:
  1. **Calculation Contract Extension (`ICalcModule`)**:
     - Extended `ICalcModule` in `src/yogi/core/contracts/calculation.py` with:
       - `supports_condition(self, condition_type: str) -> bool` (defaults to `False`)
       - `calculate_dynamic(self, symbol: str, rule: Any, context: CalculationContext) -> Any` (defaults to `None`)
     - Implemented both methods in `TrendCalculator` (`src/yogi/calculation/trend/calculator.py`) to support `"ema"`, invoking `calculate_dynamic_ema_signal` on `context.market_context.get_bars(tf)`.
  2. **Core Pipeline Decoupling (`PipelineOrchestrator`)**:
     - Removed top-level import of `calculate_dynamic_ema_signal` and all concrete calculation module imports from `src/yogi/core/orchestration/pipeline.py`.
     - Generalized dynamic rule extraction: `_extract_dynamic_rules(group)` recursively discovers any `FilterRuleSpec` with `condition_type is not None` (aliasing `_extract_dynamic_ema_rules` for backward compatibility).
     - Resolved calculation modules polymorphically via `RegistryHub.calculations`, dispatching to any registered `ICalcModule` where `calc.supports_condition(rule.condition_type)` is True.
     - Preserved the three approved RegistryHub pillars (`providers`, `calculations`, `bands`) without introducing an unapproved 4th pillar.
     - Replaced silent exception swallowing during fallback bar lookup with explicit `logger.warning(...)`.
     - Included `filter_explanation` in `QueryResultPayload.metadata` when filter groups are evaluated.
  3. **Condition Evaluator Contract & FilterEngine Extensibility**:
     - Introduced `IConditionEvaluator` contract in `src/yogi/core/contracts/filter.py` with `evaluate(record, rule) -> bool` and `describe(rule) -> str`.
     - Created `EmaConditionEvaluator(IConditionEvaluator)` in `src/yogi/filter/evaluators.py` encapsulating all EMA status and crossover matching logic.
     - Refactored `FilterEngine` in `src/yogi/filter/engine.py` to maintain an internal evaluator registry (`register_evaluator(condition_type, evaluator)`), pre-registering `"ema"` by default.
     - `FilterEngine._eval_leaf` and `FilterEngine._rule_description` delegate to registered `IConditionEvaluator` instances, removing all hardcoded indicator checks.
  4. **Generic Parameter Extension (`FilterRuleSpec` & `FilterRuleIn`)**:
     - Added `params: Mapping[str, Any]` (frozen as `MappingProxyType`) to `FilterRuleSpec`.
     - Synchronized legacy fields (`timeframe`, `p1`, `p2`, `state`, `lookback`) bi-directionally with `params` in `__post_init__` for complete backward compatibility.
     - Added `params: dict[str, Any]` to `FilterRuleIn` and synchronized in `to_core_spec()`.
  5. **Yearly Timeframe Cap & Constraint Clarification**:
     - Formally documented the Yearly timeframe cap of `1` (reflecting available 1-year trading history) alongside the $P_1 \ne P_2 \ge 1$ requirement. Rather than inventing arbitrary multi-year synthetic aggregations, dynamic 2-period crossover screening is strictly a 2-period capability constrained to timeframes with cap $\ge 2$ (`D, W, M, Q, H`), and is explicitly disabled for Yearly (`Y`). Legacy fixed 3/5 EMA fields (`EMA_D`..`EMA_Y`) remain precomputed in `_dataset` for backward compatibility.
- **Consequences**:
  - The Core pipeline is 100% decoupled from concrete calculation packages.
  - Future screening capabilities (Ranking, ROC, Bands, RSI, etc.) can be introduced simply by implementing `IConditionEvaluator` and `ICalcModule.calculate_dynamic` without modifying `PipelineOrchestrator` or `FilterEngine`.
  - All 21 mentor presets, existing EMA 3/5 fields, and existing automated tests remain fully functional.






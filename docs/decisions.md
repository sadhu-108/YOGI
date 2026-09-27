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

- **Status**: Adopted
- **Decision**: Encapsulate multi-timeframe candle synthesis in `src/yogi/timeframe/` (`TimeframeEngine`, `resample_bars`, `build_market_context`, `TIMEFRAME_RULES`). Keep timeframe synthesis strictly outside Data Providers (`src/yogi/data/`) and outside Core Orchestration (`src/yogi/core/orchestration/`).
  1. Preserve verified prototype frequency mappings: `D=None`, `W="W"`, `M="ME"`, `Q="QE"`, `H="2QE"`, `Y="YE"`.
  2. Preserve OHLCV aggregation semantics: Open=first, High=max, Low=min, Close=last, Volume=sum. Missing volume (`None`) must never cause valid price bars to be discarded.
  3. Period timestamps must represent period-end boundaries using timezone-naive `datetime` objects.
  4. Unsorted input is chronologically ordered before synthesis; duplicate timestamps are resolved deterministically by retaining the last occurrence.
  5. Incomplete current periods aggregate available daily bars without artificial padding or future-peeking.
  6. Empty periods produce no synthetic bars; recent listings/IPOs produce whatever higher-timeframe bars are possible without artificial minimum-history gates.
  7. Do NOT create an `ITimeframeEngine` contract; `TimeframeEngine` is a bounded internal engine producing canonical `MarketContext` instances.
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
  3. *Fail-Fast Reliability*: Prevents misleading analysis caused by silent demo fallback during live vendor degradation.




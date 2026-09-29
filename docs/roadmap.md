# YOGI Roadmap

This document outlines the phased roadmap and current implementation progress for the YOGI platform per [`AGENTS.md`](../AGENTS.md).

---

## 1. Migration Strategy & Status Baseline

YOGI follows a strict phased migration:

> **Stable Core • Replaceable Modules • Contract-Based Connections**
> **Preserve → Refactor → Extend**

Work proceeds strictly one approved layer at a time. Each layer is completed, thoroughly verified with unit and regression tests, and marked **FROZEN** before subsequent layers begin.

### Current Milestone: MVP Backend Complete & Frozen | Transition to Mentor/UX Review

| Step | Milestone / Subsystem | Target Package | Status | ADR Reference |
|---|---|---|---|---|
| **Step 1** | **Repository Foundation** | `pyproject.toml`, `docs/`, `tests/` | **COMPLETED / FROZEN** | [ADR-001](decisions.md#adr-001-stable-core-with-contract-based-connections) |
| **Step 2** | **Core Contracts** | `src/yogi/core/contracts/` | **COMPLETED / FROZEN** | [ADR-001](decisions.md#adr-001-stable-core-with-contract-based-connections), [ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results) |
| **Step 3** | **Core Registry** | `src/yogi/core/registry/` | **COMPLETED / FROZEN** | [ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution) |
| **Step 4** | **Core Configuration** | `src/yogi/core/configuration/` | **COMPLETED / FROZEN** | [ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation) |
| **Step 5** | **Core Orchestration** | `src/yogi/core/orchestration/` | **COMPLETED / FROZEN** | [ADR-001](decisions.md#adr-001-stable-core-with-contract-based-connections), [ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation) |
| **Step 6** | **Data Providers & Normalization** | `src/yogi/data/` | **COMPLETED / FROZEN** | [ADR-006](decisions.md#adr-006-data-providers--normalization-boundaries), [ADR-009](decisions.md#adr-009-twelve-data-provider-adapter-integration) |
| **Step 7** | **Timeframe Engine** | `src/yogi/timeframe/` | **COMPLETED / FROZEN** | [ADR-007](decisions.md#adr-007-timeframe-engine-bounded-responsibility) |
| **Step 8** | **Calculation Modules** | `src/yogi/calculation/` | **COMPLETED / FROZEN** | [ADR-003](decisions.md#adr-003-preservation-of-verified-financial-mathematics), [ADR-008](decisions.md#adr-008-calculation-engine-modularization--four-mathematical-pillars) |
| **Step 9** | **Screening Engine** | `filter/`, `ranking/`, `selection/`, `strategy/` | **COMPLETED / FROZEN** | [ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results), [ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation) |
| **Step 10** | **Results Engine** | `src/yogi/results/` | **COMPLETED / FROZEN** | [ADR-002](decisions.md#adr-002-separation-of-filter-strategy-ranking-selection-and-results) |
| **Step 11** | **Cockpit UI & Master UX** | `src/yogi/cockpit/`, `src/yogi/storage/`, `src/yogi/data/` | **COMPLETED / FROZEN (Prototype)**<br/>• Batch 1 Parity (Candlesticks & Sprint Curve)<br/>• Batch 2 Parity (Cross-Timeframe Bands)<br/>• Batch 3A Parity (Technical-Series Exposure)<br/>• Batch 3B Parity (Price / Volatility Technical Indicators)<br/>• Batch 3C Parity (Oscillators: RSI, MACD, OBV, MFI)<br/>• Batch 3D Parity (YOGI Custom Curves: Sprint Speed, Acceleration, Band Distance, YOGI ROC)<br/>• Batch 4 Parity (Persistent Bands: CsvBandsRepository, Audit Trail, Backups & Restore)<br/>• Batch 5 Parity (Market Metadata, Instrument Classification, NSE F&O Universe, Persistent Security Metadata, Pipeline Enrichment, Cockpit Meta API)<br/>• Batch U1 (Stock Detail Technical Analysis Workspace)<br/>• Batch U2 (Unified Screening / Configuration Workspace)<br/>• Batch U3 (Power Controls & Secondary Investor Workflows) | [ADR-010](decisions.md#adr-010-cockpit-live-twelve-data-provider-connection--demo-isolation) |
| **Phase Boundary** | **Mentor Review & UX Definition** | `docs/` / UI specs | **CURRENT NEXT PHASE** | — |
| **Step 12** | **Production Operations** | `src/yogi/ops/` / cold storage | **FUTURE — NOT STARTED** | — |

---

## 2. Completed Steps (Frozen Baseline)

### Step 1: Foundation (Frozen)
- Standard packaging configured via `pyproject.toml`.
- Verification tooling, pytest infrastructure, and documentation structure established.

### Step 2: Core Contracts (Frozen)
- Defined 10 canonical contract modules (`market_data.py`, `provider.py`, `calculation.py`, `bands.py`, `filter.py`, `strategy.py`, `ranking.py`, `selection.py`, `results.py`, `security.py`).
- Strongly typed, immutable DTOs (`MarketBar`, `TickData`, `MarketContext`, `SecurityMetadata`, `CalculationContext`, `CalculationResult`, `FilterRuleSpec`, `FilterGroupSpec`, `StrategySpec`, `RankCutoffSpec`, `QueryResultPayload`).
- Tested with 7/7 contract unit tests.

### Step 3: Core Registry (Frozen)
- Implemented generic, type-safe `CapabilityRegistry[T]` with lazy factory evaluation and duplicate prevention.
- Implemented `RegistryHub` strictly scoped to 3 capability categories: `providers`, `calculations`, and `bands` ([ADR-004](decisions.md#adr-004-registryhub-scope-and-capability-resolution)).
- Tested with 13/13 registry unit tests.

### Step 4: Core Configuration (Frozen)
- `EngineConfig`: Immutable system-level pipeline configuration referencing stable registry capability keys.
- `ScreeningQuery`: Immutable query intent strictly mapping to `QUALIFY → ORDER → SHOW → LIMIT` ([ADR-005](decisions.md#adr-005-core-configuration-scope-and-screeningquery-separation)).
- `StrategyCatalog`: In-memory catalog of named `StrategySpec` recipes, translating recipes into executable `ScreeningQuery` instances.
- Tested with 12/12 configuration unit tests.

### Step 5: Core Orchestration (Frozen)
- `PipelineOrchestrator`: Coordinates execution across registry capabilities and screening contract stages.
- Public methods: `build_dataset(config)`, `execute_screen(query, records, ...)`, `run(config, query)`.
- Preserves assigned cohort rank order across outputs.
- Tested with 17/17 orchestration unit tests.

### Step 6: Data Providers & Normalization (Frozen)
- Pure deterministic normalizers (`bars.py`, `classification.py`, `fno.py`, `sources/nse.py`) converting vendor feeds into frozen `MarketBar`, `TickData`, and `SecurityMetadata` DTOs.
- `YFinanceDataProvider`: Yahoo Finance adapter with offline injection support.
- `ZerodhaDataProvider`: Kite Connect historical chunking, KiteTicker live ticks, and offline test injection ([ADR-006](decisions.md#adr-006-data-providers--normalization-boundaries)).
- `TwelveDataProvider`: Twelve Data adapter supporting batching, symbol/exchange mapping, and health check ([ADR-009](decisions.md#adr-009-twelve-data-provider-adapter-integration)).
- `DemoDataProvider`: Golden 5-stock deterministic fixtures in `src/yogi/data/providers/demo.py` (YOGI-F02).
- Instrument Classification (`InstrumentClassifier`) and official NSE F&O Universe Discovery (`NseFnoUniverse`).
- Tested with 105/105 provider and normalization unit tests.

### Step 7: Timeframe Engine (Frozen)
- `TimeframeSynthesizer`: Pure multi-timeframe candle synthesis (`resample_bars`, `build_market_context`, `aggregate_candles`) ([ADR-007](decisions.md#adr-007-timeframe-engine-bounded-responsibility)).
- Supports `D` $\to$ `W`, `M`, `Q`, `H`, `Y` preserving OHLCV invariants, period-end boundary timestamps, None volume preservation, chronological pre-sorting, deduplication, and incomplete period aggregation without padding.
- Tested with 25/25 timeframe unit tests.

### Step 8: Calculation Modules (Frozen)
- Five analytical pillars satisfying `ICalcModule`:
  - `BandsCalculator`: Volatility envelopes, boundary levels, band distances, states (`ABOVE`, `BELOW`, `IN`, `na`), Bollinger Bands, Donchian Channels, ATR Volatility Bands, and continuous Band Distance curve. Authoritative envelope formula centralized in `calculate_band_envelope()` (YOGI-F03).
  - `CandleCalculator`: Candlestick pattern recognition ported from `theories/candles.py` computing 204 dimensions and pattern flags (`BULL_ENGULF`, `DOJI`, `HAMMER`, `MARUBOZU`, `INSIDE_BAR`, `NR7`, `WR7`, etc.).
  - `ImpulseCalculator`: Zigzag reversal swings and Ram's 50% recovery validation (`IC="IP"|"CR"|"up"|"na"`, `IC_PCT`, `IC_BARS`, `IC_RATIO`).
  - `TrendCalculator`: Trailing ROCs (`DROC`..`YROC`), calendar blocks (Quarter, Half, Year), multi-year CAGRs, ATH diff, EMA 3/5 ribbon states, DMI/ADX, VWAP, Average Price, RSI (Wilder 14), MACD (12/26/9), OBV, MFI (14), and continuous ROC curve ([ADR-008](decisions.md#adr-008-calculation-engine-modularization--four-mathematical-pillars)).
  - `VelocityCalculator`: Rolling sprint speeds (`S4`..`S52`), accelerations (`ACCEL_S`, `ACCEL_L`), sprint consistency, anchored sprint race curves, continuous sprint speed curve, and continuous acceleration curve.
- Semantic fidelity verified: pipeline DMI default `(5, 5)`, short-history complete six-timeframe schema (`None`/`"na"`).
- Tested with 116 unit tests and 6 golden regression tests with 0 drift across 5 stocks against `expected.json` (122 tests passing).

### Step 9: Screening Engine (Frozen)
- Four modular screening components strictly adhering to `QUALIFY → ORDER → SHOW → LIMIT → RESULTS`:
  - `FilterEngine` (`src/yogi/filter/`): Implements `IFilterRule`, evaluating 12 operators, cross-column comparisons (`field2`), nested groups (`all`/`any`), negation, and funnel telemetry.
  - `RankingEngine` (`src/yogi/ranking/`): Implements `IRankingRule`, evaluating relative standing across metrics (ASC/DESC, MIN/DENSE/AVERAGE), deterministic tie-breaking, `na_position="last"`, and `rank_changes`.
  - `SelectionEngine` (`src/yogi/selection/`): Implements `ISelectionRule`, evaluating rank threshold cutoffs (`RankCutoffSpec`) and sustained rank duration without display row truncation.
  - `Strategy` & Presets (`src/yogi/strategy/`): Implements `IStrategy`, StrategySpec validation, and all 21 Verified Mentor Presets (Groups A, B, C, D, E) per `LISTS_LOGIC.txt`.
- Tested with 41 screening, ranking, selection, and strategy tests.

### Step 10: Results Engine (Frozen)
- Presentation assembly and export formatting decoupling presentation packaging from analytical screening logic:
  - `ResultAssembler` (`src/yogi/results/assembler.py`): Implements `IResultAssembler`, projecting specified or default summary columns, including active dynamic `RANK_*` columns, normalizing missing/NaN values to `None`, preserving input rank order, and packaging `QueryResultPayload`.
  - `ExportFormatter` (`src/yogi/results/formatter.py`): Implements `IExportFormatter`, serializing payloads to in-memory bytes for `XLSX` (via `openpyxl` with dark headers, auto-filter, freeze panes, number formats), `CSV` (RFC 4180), and `JSON` (RFC 8259 compliant).
  - Column metadata and categorization (`src/yogi/results/columns.py`): Provides `ColumnDefinition` factory, categorization, readable labels, and `DEFAULT_SUMMARY_COLUMNS`.
- Tested with 14 unit and integration tests.

### Step 11: Cockpit & API Layer (Frozen)
- Interactive web Cockpit, FastAPI transport controllers, application presentation services, and single-page dashboard:
  - `AppState` (`src/yogi/cockpit/app_state.py`): In-memory feature cache with `freeze_dataset()` enforcing deep immutability (`MappingProxyType` at outer and inner levels), atomic reference swap, canonical on-demand single-stock resolution via `PipelineOrchestrator.build_dataset(EngineConfig(symbols=[sym]))` (YOGI-F05), and bounded LRU `_panel_cache` (max 100 entries).
  - `ChartDataService` (`src/yogi/cockpit/services/charting.py`): Multi-timeframe candlestick synthesis and rolling envelope curve generation adhering to verified band mathematics via `calculate_band_envelope()` (YOGI-F03), equipped with cross-timeframe band envelope synthesis (Batch 2 Parity), 19+ financial series packaging via `CandleSeriesOut`, and thread-safe bounded LRU/TTL cache `_cache` (YOGI-F04).
  - `RaceVisualizerService` (`src/yogi/cockpit/services/race.py`): Packaging multi-symbol anchored performance curves for `/api/race`.
  - `router.py` & `schemas.py`: REST HTTP transport endpoints with Pydantic v2 validation cleanly separating analytical screening intent from presentation column projection, with explicit HTTP status mapping (401, 429, 503, 404).
  - Single-Page Application (`src/yogi/cockpit/static/*`): Dark-theme financial cockpit dashboard featuring TradingView Lightweight Charts, interactive tabular results grid, Stock Detail Drawer with 6-timeframe matrix, discretionary band width adjustment, live Twelve Data provider toggle ([ADR-010](decisions.md#adr-010-cockpit-live-twelve-data-provider-connection--demo-isolation)), and one-click XLSX/CSV export.
- Tested with 188 Cockpit unit and integration tests across Batches 1–5, U1, U2, and U3.

### Persistent Storage Engine (Batches 4 & 5 Frozen)
- `src/yogi/storage/bands.py`: `CsvBandsRepository` managing manual band levels, append-only audit trail `data/bands/bands_audit.log`, automated daily backups in `data/bands/backups/`, and point-in-time restore.
- `src/yogi/storage/metadata.py`: `CsvMetadataRepository` managing symbol metadata (`name, sector, grade, mcap, fno, instr, grp`) with atomic `.tmp` staging and crash resilience.
- Tested with 36 storage unit and integration tests.

**Total Test Baseline:** **595 tests passing** across all suites.

---

## 3. Current Phase: Mentor Review & UX Definition

### Phase Status: MVP Backend Engine Frozen
The current YOGI MVP backend engine is complete, verified, and **frozen**:
- **Core Engine & Architecture**: Contracts, Registry, Configuration, and Pipeline Orchestrator are invariant.
- **Data Layer**: Yahoo Finance, Zerodha Kite, Twelve Data live provider ([ADR-009](decisions.md#adr-009-twelve-data-provider-adapter-integration)), and Demo provider in `data/providers/demo.py` (YOGI-F02) with strict Demo/Live isolation ([ADR-010](decisions.md#adr-010-cockpit-live-twelve-data-provider-connection--demo-isolation)).
- **Timeframe Engine**: Pure multi-timeframe synthesis (`D` $\to$ `W`, `M`, `Q`, `H`, `Y`) preserving all OHLCV aggregation invariants.
- **Calculation Engine**: 5 analytical pillars (Bands, Candles, Impulse, Trend, Velocity) with centralized band envelope mathematics (YOGI-F03) and 0 numerical drift against golden regression fixtures.
- **Screening Engine**: Canonical screening pipeline (`QUALIFY → ORDER → SHOW → LIMIT → RESULTS`) and the 21 Verified Mentor Presets.
- **Results Engine**: Tabular projection and export formatters (XLSX, CSV, JSON byte streams).
- **Cockpit Presentation Prototype**: Interactive workbench featuring chart rendering, Stock Detail Drawer, on-demand single-symbol resolution (YOGI-F05), bounded chart data cache (YOGI-F04), and REST endpoints.
- **Architectural Audit**: All findings (YOGI-F01 through YOGI-F06) are fully resolved and covered by 557 passing tests (100% pass rate).

### Next Phase Objectives
1. **Mentor Review**: Engage with the trading mentor to review the existing calculations, metrics, filter conditions, ranking options, cutoffs, and preset recipes.
2. **UX & Presentation Definition**: Determine how existing analytical capabilities should ultimately be presented to users (controls, layout, interactive workflows, and mobile/desktop ergonomics).
3. **Backend Protection**: No new backend analytical features or Core redesigns will be conducted before mentor review. Future UX work will build on top of the frozen engine rather than altering Core contracts.

---

## 4. Planned Future Milestones & Deferred Capabilities

### Explicitly Deferred Capabilities
- **Bi-Weekly (`2W`) and Bi-Monthly (`2M`) Timeframes**: Deferred per ADR-007 due to non-uniform calendar trading days and excessive calculation overhead.
- **Automated Brokerage Order Execution**: Excluded from core scope; YOGI is strictly a systematic analytical screening platform.

### Step 12: Production Operations & Extensions (FUTURE — NOT STARTED)
- Real-time in-memory hot path tick stream processing.
- Persistent cold historical price database (TimescaleDB / PostgreSQL).
- Scheduled background batch rebuild cron runner (`/api/schedule`).
- Alerting, push notifications, and external webhook triggers.

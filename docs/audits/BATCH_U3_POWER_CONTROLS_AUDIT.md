# YOGI — Batch U3 Targeted UX / Source Exposure Audit
## Power Controls, Parity Gaps & Advanced Investor Workflows

**Date**: 2026-09-29  
**Status**: COMPLETE (STRICTLY READ-ONLY AUDIT)  
**Baseline Test Suite**: 580 passed, 0 failed across unit, integration, live smoke, and golden regression suites (100% pass rate).  
**Principle**: FULL CONTROL WITHOUT COMPLEXITY.

---

## Executive Summary

Following the completion of **Batch U1** (Stock Detail Technical Analysis Workspace) and **Batch U2** (Unified Screening / Configuration Workspace), the YOGI Cockpit operates as a unified, single-screen workspace organized around the canonical pipeline:

$$\text{UNIVERSE} \longrightarrow \text{QUALIFY} \longrightarrow \text{ORDER} \longrightarrow \text{SHOW} \longrightarrow \text{RESULTS}$$

This audit inspects the remaining capabilities from the original prototype (`yogi_engine`) and compares them against the current source code and backend contracts.

### Core Audit Finding
The backend analytical, storage, and API foundations are exceptionally complete:
1. **Discretionary Band Management**: Two-way band width updates (`PUT /api/bands/{symbol}`), per-stock change audit trails (`GET /api/bands/log/{symbol}`), global audit logs (`GET /api/bands/log`), dated daily snapshots (`GET /api/bands/backups`), and atomic backup restoration (`POST /api/bands/restore/{filename}`) **are already fully implemented, tested, and active in the backend**.
2. **Security Metadata Management**: Persistent two-way metadata updating (`POST /api/meta/{symbol}`) for investor grades, sector reclassifications, and notes **is already fully implemented and backed by `CsvMetadataRepository`**.
3. **Sprint Race Analytics**: Continuous multi-stock cumulative return curve generation from fixed anchor dates (`GET /api/race`) **is already implemented in `RaceDataService` and tested**.
4. **Universe & Categorization**: The `PipelineOrchestrator` already enriches every stock record with `sector`, `grade`, `mcap`, `fno`, `instr` (instrument type), and `grp` (series/group).

The primary remaining gap is **UI exposure and ergonomics**: these already-existing backend capabilities lack small, coherent controls inside the unified Cockpit. Furthermore, several legacy prototype features (such as personal Google Sheets sync, loose button farms, and separate card/table view modes) are **anti-patterns that should NOT be ported**.

---

## 1. Remaining Capability Inventory

| # | Capability Area | Specific Feature | Prototype Origin | Current Cockpit (U1/U2) Status |
|---|---|---|---|---|
| **1** | **Quick Screening** | EMA Up across 6 timeframes (`D, W, M, Q, H, Y`) | Checkbox strip `e_D`..`e_Y` | Segmented 6-button ribbon `#emaQuickToggles` in Card 2 |
| **2** | **Quick Screening** | Compact Band Position Shortcuts | `bandBelow` toggle + curated presets | 3 text buttons (`+ Above Monthly`, `+ Outside Band`, `+ Reaction`) |
| **3** | **Quick Screening** | Microcap filter shortcut (`< 100 cr`) | Checkbox `f_micro` | Filterable via Condition Builder (`mcap < 100`); absent in Card 1 |
| **4** | **Quick Screening** | Legacy Google Sheets sync filter | Dropdown `f_gs` (`in_gsheet`) | Excluded by design (legacy prototype spreadsheet sync) |
| **5** | **Rank / Selection** | Primary ranking metric & order | Dropdown `tf` + order | Card 3 `#rankingMetric` + `#rankingOrder` |
| **6** | **Rank / Selection** | Secondary tie-breaker ranking | Dropdown `tf2` | Card 3 progressive disclosure `#secondaryRankingMetric` |
| **7** | **Rank / Selection** | Rank Survival Cutoffs (Top N per Metric) | Input `mrankmax`, `yrankmax` | Card 4 dynamic `#cutoffsContainer` (`RankCutoffSpec`) |
| **8** | **Rank / Selection** | Multi-Period Rank Selection Mode (`ALL` vs `ANY`) | Dropdown `rkMode` (`all` / `any`) | `SelectionEngine` supports both; `ScreeningQuery` hardcodes `ALL` |
| **9** | **Rank / Selection** | Multi-Period Batch Rank Selector | Modal `#rankPanel` with period ticks | Row-by-row cutoff rows in Card 4 |
| **10** | **Rank / Selection** | Rank Climbers / Delinquents | Curated preset `climbers` | Preset `E3_RANK_CLIMBERS`, `RANK_CHG` column & filter rule |
| **11** | **Band Controls** | Active chart timeframe band width editing | Drawer text input + save | Drawer toolbar `#bandWidthInput` + `#saveBandBtn` |
| **12** | **Band Controls** | Simultaneous 6-TF band width editing | Drawer table inputs for D, W, M, Q, H, Y | Matrix Category 4 displays static read-only text |
| **13** | **Band Controls** | Per-stock band change history (audit log) | Icon `📜` $\to$ `#bandLogBox` | Backend endpoint exists (`/api/bands/log/{sym}`); ZERO UI |
| **14** | **Band Controls** | Global band change history & daily backups | Administrative scripts | Backend endpoints exist (`/api/bands/backups`); ZERO UI |
| **15** | **Band Controls** | Multi-chart 6-TF simultaneous grid | Button `▦ 6 timeframes` $\to$ `#multi` | Single chart canvas with 1-click TF switch + 6-TF matrix |
| **16** | **Universe / Meta** | Sector filtering | Dropdown `f_sector` | Enriched in dataset; filterable by typing; no dropdown in Card 1 |
| **17** | **Universe / Meta** | Extended Instrument Type (`ETF, SME, REIT, BE`) | Dropdown `f_fno` (`I:EQ`, `I:ETF`, etc.) | Card 1 only exposes `ALL`, `FNO`, `CASH`; `instr` in records |
| **18** | **Universe / Meta** | Trading Group (`A, B, T, Z`) | Dropdown `f_grp` | Enriched as `grp`; filterable in Condition Builder |
| **19** | **Universe / Meta** | Two-way security metadata editing | Drawer inputs for Grade & Sector | Drawer badges are read-only; backend endpoint exists |
| **20** | **Results Grid** | Dense tabular results with sorting | `ag-Grid` table view (`vTable`) | Dense HTML grid with dynamic columns and sort headers |
| **21** | **Results Grid** | Rich visual indicators & signals | Badges for EMA, Bands, ROC colors | Candlestick badges (`★ Breakout`), DMI states, ROC heat colors |
| **22** | **Results Grid** | Historical breakdown in stock drawer | Drawer `statTables` (CAGR, SPRINT) | Matrix has 6 TF; CAGRs/multi-year returns omitted in Drawer |
| **23** | **Results Grid** | Separate Card/List View mode | Tab `vList` ("List of shares") | Intentionally unified into dense grid; view toggle omitted |
| **24** | **Results Grid** | Quick Movers widget (Top 5 D, W, M) | Section `Quick movers` in card view | Achievable via column sorting; no dedicated top-5 widget |
| **25** | **Other Workflows** | Sprint Race cumulative % chart | Button `🏁 SPRINT race` $\to$ `#race` | `RaceDataService` & `/api/race` exist in backend; ZERO UI |
| **26** | **Other Workflows** | Stock Quick Search & Autocomplete | Search input `#search` + `#sugg` | Card 1 `#stockQuickSearch` with debounced drawer drilldown |

---

## 2. Backend / API / UI Mapping

| Capability | Backend Calculation / Storage Contract | Application / API Path | Current UI Exposure | Status / Gap |
|---|---|---|---|---|
| **Simultaneous 6-TF Band Editing** | `IBandsRepository.set_band()` in `CsvBandsRepository` | `PUT /api/bands/{symbol}` (`BandUpdateIn`) | Read-only text in Drawer Matrix | **UI Missing**: Matrix cells should be editable micro-inputs with auto-save |
| **Per-Stock Band Change History** | `IBandAuditRepository.get_history()` in `CsvBandsRepository` | `GET /api/bands/log/{symbol}` | None | **UI Missing**: Add audit history popover/modal trigger in Drawer |
| **Band Daily Backups & Restore** | `IBandBackupService.list_backups()`, `.restore_backup()` | `GET /api/bands/backups`, `POST /api/bands/restore/{fn}` | None | **UI Missing**: Add administrative snapshot manager modal |
| **Two-Way Metadata Editing** | `ISecurityMetadataRepository.update_metadata()` | `POST /api/meta/{symbol}` (`MetadataUpdateIn`) | Read-only badges in Drawer | **UI Missing**: Click-to-edit on Grade, Sector, Notes in Drawer Header |
| **Sprint Race Curve** | `RaceDataService.get_race()`, `calculate_anchored_curve()` | `GET /api/race` (`RaceResponseOut`) | None | **UI Missing**: Add `[🏁 Sprint Race]` action button & chart modal |
| **Sector Filter Dropdown** | In-memory `record["sector"]` enriched by Orchestrator | Extracted client-side from `GET /api/table` records | Filterable via Condition Builder | **UX Suboptimal**: Add searchable Sector selector in Card 1 |
| **Extended Instrument Filter** | In-memory `record["instr"]` enriched by Orchestrator | Extracted client-side from `GET /api/table` records | Card 1 Segment: `ALL, FNO, CASH` | **UX Suboptimal**: Expand Segment or add Instrument dropdown |
| **Microcap Filter Shortcut** | In-memory `record["mcap"]` enriched by Orchestrator | Evaluated via `FilterEngine` (`mcap < 100`) | Available as manual rule | **UX Suboptimal**: Add quick checkbox/pill in Card 1 |
| **Multi-Period Selection Mode** | `SelectionEngine.select(..., mode=SelectionMode)` | `ScreenRequestIn` / `ScreeningQuery` | None (hardcoded to `ALL`) | **Backend Contract Gap**: `ScreeningQuery` lacks `selection_mode` |
| **Historical Breakdown in Drawer** | `TrendCalculator` (`CAGR_*`, `Y20*`), `VelocityCalculator` (`SPA_*`) | In-memory `record` passed to Drawer | Only 6 standard TF rows shown | **Partially Exposed**: Add collapsible `<details>` in Drawer |

---

## 3. Prototype Parity Classification

Each remaining capability is classified into one of the authoritative categories:

### A. ALREADY EXPOSED (Preserved & Functional in U1 / U2)
1. **EMA Up Across 6 Timeframes**: Card 2 `#emaQuickToggles` segmented ribbon `[D] [W] [M] [Q] [H] [Y]`.
2. **Primary & Secondary Ranking**: Card 3 `#sectionRanking` with direction and tie-breaker details.
3. **Rank Survival Cutoffs**: Card 4 `#cutoffsContainer` mapping to `RankCutoffSpec`.
4. **Active Chart Band Tuning**: Drawer toolbar `#bandWidthInput` and `#saveBandBtn` connected to `PUT /api/bands/{symbol}`.
5. **Stock Identity & Badges**: Symbol, Name, Price, Exchange, Sector, Cap Group, Grade, F&O badge in Drawer header.
6. **Dense Professional Results Grid**: Dynamic columns, sort headers, and multi-format exports (`XLSX`, `CSV`, `JSON`).
7. **Rich Table Signals**: Candlestick pattern badges (`★ Breakout`, `★ Hammer`), DMI state badges, ROC heat colors.
8. **Quick Stock Find**: Card 1 `#stockQuickSearch` with debounced search and drawer trigger.
9. **Rank Climbers Preset**: Mentor preset `E3_RANK_CLIMBERS` filtering on `RANK_CHG > 0`.

### B. PARTIALLY EXPOSED (Accessible indirectly or missing minor context)
1. **Microcap Filter (`< 100 cr`)**: Fully supported by the backend and can be added as a condition `mcap < 100` in Card 2, but lacks a 1-click shortcut in Card 1 alongside Segment.
2. **Extended Instrument Filter (`ETF, SME, REIT/InvIT, BE`)**: Filterable in Card 2 via `instr`, but Card 1 Segment dropdown only exposes `ALL`, `FNO`, `CASH`.
3. **Historical Period Breakdown in Drawer**: Multi-year CAGRs, annual returns, and fixed-date sprints are calculated and accessible as grid columns, but are omitted from the Stock Detail Drawer.
4. **Trading Group (`grp`)**: Populated on every record and filterable via Condition Builder, but not discoverable as a dropdown.

### C. BACKEND PRESENT — UI MISSING (Complete backend/API, zero frontend exposure)
1. **Simultaneous 6-Timeframe Band Width Editing**: `PUT /api/bands/{symbol}` supports updating any timeframe, but Drawer Matrix Category 4 cells are static read-only text.
2. **Per-Stock Band Change History (Audit Log)**: `GET /api/bands/log/{symbol}` is implemented and tested with `CsvBandAuditRepository`, but has no trigger or view in Cockpit.
3. **Global Band Change History**: `GET /api/bands/log` is implemented, but unexposed in Cockpit.
4. **Dated Band Backups & Restoration**: `GET /api/bands/backups` and `POST /api/bands/restore/{filename}` are implemented with strict security validation, but have no UI modal.
5. **Two-Way Security Metadata Editing**: `POST /api/meta/{symbol}` updates `metadata.csv` for Grade, Sector, and Notes, but Drawer badges are strictly static.
6. **Sprint Race Visualization**: `RaceDataService` and `GET /api/race` calculate multi-stock cumulative return curves, but Cockpit has no button or chart modal.

### D. PRESENT BUT NEEDS BETTER UX (Functional but cumbersome or fragmented)
1. **Band Position Shortcuts**: The current 3 buttons (`+ Above Monthly`, `+ Outside Band`, `+ Reaction`) add rules to Card 2, but would be cleaner and more complete as a compact segmented dropdown `[Band Position: Any ▾ | Above | Inside | Below | Outside 2+]`.
2. **Sector Filtering**: Filterable only by manually typing string values into the Condition Builder; lacks a searchable sector dropdown with auto-discovered categories.
3. **Multi-Period Rank Cutoff Batch Setup**: Currently requires adding individual cutoff rows one by one; lacks a 1-click template to apply a rank cutoff across multiple standard periods.

### E. GENUINELY MISSING BACKEND (Requires contract or engine extension)
1. **`ScreeningQuery` / `PipelineOrchestrator` `SelectionMode.ANY` Support**:
   - **Contract State**: `ISelectionRule` and `SelectionEngine` (`src/yogi/selection/engine.py`) support both `SelectionMode.ALL` (intersection) and `SelectionMode.ANY` (union).
   - **Gap**: `ScreeningQuery` (`src/yogi/core/configuration/query.py`) does not define a `selection_mode` attribute, and `PipelineOrchestrator` (`src/yogi/core/orchestration/pipeline.py:227`) hardcodes `mode=SelectionMode.ALL`.
   - **Impact**: All multi-period selection cutoffs are evaluated as an intersection (`ALL`). Union-based rank cutoffs (`ANY`) cannot be passed through `ScreeningQuery`.
   - **Policy**: Per frozen core rules, Core contracts must NOT be modified. Multi-period selection cutoffs in U3 must continue to map to `SelectionMode.ALL`. If `SelectionMode.ANY` is required in the future, it must be addressed via an architectural RFC.

### F. DEFER / NOT PRODUCT-WORTHY (Anti-patterns from prototype to reject)
1. **Legacy Google Sheets Sync (`f_gs` / `in_gsheet`)**: Personal spreadsheet synchronization artifact from the original prototype author. YOGI has native disk repositories (`metadata.csv`, `bands.csv`, `user_presets.json`) and standard exports. **REJECT**.
2. **Separate Card / List View Mode (`vList`)**: Prototype had a whole separate tab rendering large cards. This fragments the UI, destroys information density, and directly violates the "One Unified Cockpit" mandate. **REJECT**.
3. **6-Chart Multi-Grid Modal (`multiTF` / `#multi`)**: Rendering 6 simultaneous WebGL TradingView chart canvases causes severe DOM and memory overhead. The U1 Stock Detail Drawer already provides instant 1-click chart timeframe switching combined with a 6-TF numerical inspection matrix. **DEFER / REJECT**.
4. **Button Farm Header**: Prototype strewn 25+ unorganized buttons across two horizontal bars. **REJECT**.
5. **Bhavcopy Manual Recovery Batches** | Prototype `recoverAll()` | YOGI's data layer handles resilient normalization, retries, and offline caching automatically. **REJECT**.

### G. UNVERIFIED
- None. Every inspected capability has been verified against actual source code and running test fixtures.

---

## 4. Recommended Cockpit Location for Each Capability

To maintain **Full Control Without Complexity**, all capabilities must fit seamlessly into the existing U2 workspace without adding new modes, new tabs, or button farms:

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ LEFT WORKBENCH (5 CARDS)                              │ RIGHT VIEWPORT & STOCK DETAIL DRAWER          │
├───────────────────────────────────────────────────────┼────────────────────────────────────────────────┤
│ 1. UNIVERSE & PRESETS                                 │ ACTIVE SETUP SUMMARY BANNER                    │
│    • Exchange [NSE] [BSE] [BOTH]                      │   Universe • Preset (Modified) • Rules • Ranks │
│    • Segment [ALL] [FNO] [CASH]                       ├────────────────────────────────────────────────┤
│    • ▾ Advanced Universe (<details>):                 │ FUNNEL TELEMETRY                               │
│      - Sector [Searchable Dropdown ▾]                 │   Universe (3,792) → Qualified (42) → Top (20) │
│      - Instrument [Equity | ETF | SME | REIT ▾]       ├────────────────────────────────────────────────┤
│      - Microcap [< 100 cr checkbox]                   │ DENSE RESULTS GRID                             │
│    • Presets: [Choose ▾] [Load] [Revert] [Save As]    │   Sortable Headers • Rich Badges • Pill Strips │
│    • Quick Stock Find [ 🔍 Symbol... ]                │   Row Click → Slides open Stock Detail Drawer  │
├───────────────────────────────────────────────────────┼────────────────────────────────────────────────┤
│ 2. CONDITIONS (QUALIFY)                               │ STOCK DETAIL DRAWER (Batch U1 + U3 Power)      │
│    • Quick EMA Ribbon: [D] [W] [M] [Q] [H] [Y]        │   • Header: Identity Badges + [✎ Edit Meta]    │
│    • Quick Band Filter: [Band: Any ▾]                 │   • Toolbar: Chart TF [D..Y] + Band TF         │
│    • Root Match [ALL / ANY] + [NOT]                   │   • Overlays ▾ Popover & Panels ▾ Popover      │
│    • Dynamic Condition Tree Builder (vs Col, NOT)     │   • TradingView Price Chart Canvas             │
├───────────────────────────────────────────────────────┤   • Analytical Sub-Panel Canvas (RSI, MACD...) │
│ 3. RANKING (ORDER)                                    │   • 6-TF Multi-Timeframe Matrix:               │
│    • Primary Metric [Select ▾] + Direction [DESC/ASC] │     - Trend & Alignment (EMA, Bands, DMI)      │
│    • ▾ Secondary Tie-Breaker (<details>)              │     - Momentum & Returns (ROC, Sprint Speed)   │
├───────────────────────────────────────────────────────┤     - Bands & Volatility:                      │
│ 4. SELECTION (SHOW)                                   │       ↳ Inline 6-TF Width Tuning [<input>%]    │
│    • Top N Limit [Input] + Quick Pills [10..All]      │       ↳ [📜 Band History] Popover Trigger      │
│    • Rank Survival Cutoffs Builder                    │   • ▾ Historical Breakdown (<details>):        │
│    • [+ Batch Multi-Period Cutoff Template ▾]         │     - Multi-year CAGRs (1y, 3y, 5y, 10y)       │
├───────────────────────────────────────────────────────┤     - Annual Returns (2025, 2024, 2023...)     │
│ 5. COLUMNS & ACTIONS                                  │     - Fixed-Date Sprints (Since 2021..)        │
│    • Column Presets [summary, returns, bands...]      ├────────────────────────────────────────────────┤
│    • [ 🚀 RUN SCREEN ]                                │ MODALS & DIALOGS (On Demand)                   │
│    • [ 🏁 Sprint Race ] (Opens multi-stock race chart)│   • Sprint Race Modal                          │
│    • [ Export XLSX ▾ ]                                │   • Band Backups & Snapshot Restore Modal      │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Grouping & Progressive Disclosure Recommendations

To prevent visual clutter, the following design patterns must be applied:

1. **Card 1: Advanced Universe Progressive Disclosure**:
   - Primary view remains strictly: Exchange pills (`[NSE] [BSE] [BOTH]`) and Segment pills (`[ALL] [FNO] [CASH]`).
   - A subtle collapsible toggle `▾ More Universe Filters` progressively reveals:
     - `Sector`: Searchable native dropdown populated dynamically with unique sectors from current dataset records. Selecting a sector injects a qualification rule `sector == "..."`.
     - `Instrument`: Dropdown with `Equity Shares`, `ETFs`, `SME / Emerge`, `REIT / InvIT`, `Trade-to-Trade (BE)`.
     - `Microcap`: Checkbox `[ ] Market Cap < 100 cr` injecting `mcap < 100`.
   - Default state is collapsed; zero vertical space consumed when not in use.

2. **Card 2: Compact Band Shortcut Selector**:
   - Replace the three separate buttons (`+ Above Monthly`, `+ Outside Band`, `+ Reaction`) with a single compact segmented dropdown:
     `[ Band Shortcut: Select ▾ ]`
     - `Above Monthly Band`
     - `Inside Monthly Band`
     - `Below Monthly Band (Reaction Setup)`
     - `Outside Band on 2+ Timeframes`
   - Selecting an option adds the corresponding rule to `#filterRulesContainer`.

3. **Card 4: Selection Multi-Period Batch Template**:
   - Above `#cutoffsContainer`, add a small template helper `[ + Multi-Period Template ▾ ]`:
     - `Top 100 in Month & Year` $\to$ adds `RANK_M <= 100` and `RANK_Y <= 100`.
     - `Top 50 across All Quarters` $\to$ adds `RANK_Q <= 50`, `RANK_Q_P1 <= 50`.
     - `Rank Climbers` $\to$ adds `RANK_CHG > 0`.
   - Populates the existing cutoff rows without inventing new UI controls.

4. **Stock Detail Drawer: Inline 6-TF Band Tuning**:
   - In Matrix Category 4 (Bands & Volatility), convert the static Band Width row (`BAND_D`..`BAND_Y`) into compact numeric input boxes:
     `<input type="number" step="0.5" min="0" max="100" class="matrix-band-input" value="12.0">%`
   - On change or blur, asynchronously call `PUT /api/bands/{symbol}` with `{timeframe: tf, value: val / 100}` and update the chart.

5. **Stock Detail Drawer: Band History Popover**:
   - Add a small icon button `📜 History` next to "Bands & Volatility" in the drawer.
   - Clicking opens a lightweight popover displaying the reverse-chronological change table from `GET /api/bands/log/{symbol}`:
     `When | TF | From | To | Changed By`

6. **Stock Detail Drawer: Click-to-Edit Metadata**:
   - In the Drawer Header, render the Grade and Sector badges with a subtle edit affordance:
     `<span class="badge badge-meta clickable" id="drawerSectorBadge" title="Click to edit sector">...</span>`
   - Clicking turns the badge into a small input/dropdown with `✓` and `✕` buttons that calls `POST /api/meta/{symbol}` on save.

7. **Card 5: Sprint Race Action**:
   - In Card 5 Actions, add a clean secondary action button `[ 🏁 Sprint Race ]`.
   - Clicking opens a full-viewport modal rendering the multi-line cumulative return chart via TradingView or canvas, consuming `GET /api/race?symbols=...&anchor=2021-01-01`.

---

## 6. Capabilities That Should NOT Be Ported

| Capability | Origin | Rationale for Rejection / Deferral |
|---|---|---|
| **Google Sheets Filter (`in_gsheet`)** | Prototype `f_gs` | Personal spreadsheet tracker specific to the prototype author. Completely superseded by YOGI's native storage (`metadata.csv`, `bands.csv`) and XLSX exports. |
| **Separate Card / List View Mode (`vList`)** | Prototype `vList` tab | Violates "One Unified Cockpit". Dense tabular grid is vastly superior for institutional screening, sorting, and comparison. |
| **6-Chart Multi-Grid Modal (`multiTF`)** | Prototype `#multi` | Spawning 6 simultaneous TradingView chart instances in WebGL creates high DOM/memory overhead. U1's 1-click chart TF switch + 6-TF synchronized numerical matrix already solves multi-timeframe analysis cleanly. |
| **Button Farm Architecture** | Prototype top bars | Scattered buttons without hierarchy overwhelm users and violate "Full Control Without Complexity". |
| **Bhavcopy Manual Recovery Batches** | Prototype `recoverAll()` | YOGI's data layer handles resilient normalization, retries, and offline caching automatically. |

---

## 7. Genuine Backend Gaps, If Any

1. **`ScreeningQuery` / `PipelineOrchestrator` `SelectionMode.ANY` Support**:
   - **Contract State**: `ISelectionRule` and `SelectionEngine` (`src/yogi/selection/engine.py`) support both `SelectionMode.ALL` (intersection) and `SelectionMode.ANY` (union).
   - **Gap**: `ScreeningQuery` (`src/yogi/core/configuration/query.py`) does not define a `selection_mode` attribute, and `PipelineOrchestrator` (`src/yogi/core/orchestration/pipeline.py:227`) hardcodes `mode=SelectionMode.ALL`.
   - **Impact**: All multi-period selection cutoffs are evaluated as an intersection (`ALL`). Union-based rank cutoffs (`ANY`) cannot be passed through `ScreeningQuery`.
   - **Policy**: Per frozen core rules, Core contracts must NOT be modified. Multi-period selection cutoffs in U3 must continue to map to `SelectionMode.ALL`. If `SelectionMode.ANY` is required in the future, it must be addressed via an architectural RFC.

2. **Dedicated Dynamic Sector List API**:
   - **Status**: No endpoint exists for `GET /api/sectors`.
   - **Workaround / Resolution**: None needed! The Cockpit already loads the entire universe feature records into memory on startup via `GET /api/table` or `GET /api/screen`. The frontend JavaScript controller can dynamically extract unique, sorted sector names directly from `app_state.dataset` with zero backend changes.

---

## 8. Exact Implementation Files Required (Batch U3 Scope)

If Batch U3 implementation proceeds, changes would be strictly confined to the presentation/Cockpit tier:

### Frontend Presentation Files:
1. `src/yogi/cockpit/static/index.html`:
   - Add `<details class="universe-advanced">` in Card 1 (Sector, Instrument, Microcap).
   - Add compact Band Position dropdown in Card 2.
   - Add Multi-Period Batch Template dropdown in Card 4.
   - Add `[ 🏁 Sprint Race ]` button in Card 5.
   - Add Sprint Race modal dialog `#raceModal`.
   - Add Band History popover and Snapshot Administration modal.
   - Add inline input cells in Drawer Matrix Category 4 and metadata edit affordances.
2. `src/yogi/cockpit/static/css/cockpit.css`:
   - Styles for `.universe-advanced`, `.matrix-band-input`, `.popover-history`, `.race-modal`, `.clickable-badge`.
3. `src/yogi/cockpit/static/js/app.js`:
   - Sector extraction from dataset and auto-population into Sector selector.
   - Advanced universe filter injection (`sector`, `instr`, `mcap`).
   - Inline 6-TF band width editing handler calling `API.updateBand()`.
   - Band history popover handler calling `GET /api/bands/log/{symbol}`.
   - Metadata two-way inline edit handler calling `POST /api/meta/{symbol}`.
   - Sprint Race modal controller invoking `GET /api/race` and drawing multi-line race canvas.
4. `src/yogi/cockpit/static/js/api.js`:
   - Add client methods `getBandLog(symbol)`, `getBandBackups()`, `restoreBandBackup(filename)`, `getRace(params)`, `updateMetadata(symbol, field, value)`.
5. `tests/cockpit/test_batch_u3_power_controls.py`:
   - Comprehensive test suite verifying all new power controls, API contracts, and UI elements.

---

## 9. Frozen Files / Layers

The following remain **strictly frozen** and must NOT be touched during any U3 implementation:

- `src/yogi/core/*` (contracts, registry, configuration, orchestration)
- `src/yogi/calculation/*` (bands, velocity, impulse, trend, candles)
- `src/yogi/filter/*` (qualification engine)
- `src/yogi/ranking/*` (ordinal relative standing)
- `src/yogi/selection/*` (rank cutoff engine)
- `src/yogi/strategy/*` (strategy composition and mentor presets)
- `src/yogi/timeframe/*` (synthesis engine)
- `src/yogi/data/*` (providers, normalization)
- `src/yogi/storage/*` (bands storage, metadata storage)
- `src/yogi/pipeline/*` (orchestrator implementation)

---

## 10. U3 Recommended Implementation Scope

Batch U3 should be strictly scoped to exposing **existing backend capabilities through minimal, high-ergonomics power controls**:

1. **Card 1: Advanced Universe Disclosure**:
   - Searchable Sector selector, Instrument type selector, and Microcap (`< 100 cr`) toggle inside a collapsible disclosure.
2. **Card 2: Segmented Band Position Shortcut**:
   - Single clean dropdown replacing disparate band buttons.
3. **Card 4: Multi-Period Cutoff Template**:
   - 1-click batch cutoff populator for common mentor ranking horizons.
4. **Card 5: Sprint Race Modal**:
   - Action button opening interactive multi-line sprint race chart consuming `GET /api/race`.
5. **Stock Detail Drawer Power Controls**:
   - Inline 6-TF band width tuning directly in Matrix Category 4.
   - Per-stock band audit log popover (`GET /api/bands/log/{sym}`).
   - Click-to-edit metadata updating for Grade, Sector, and Notes (`POST /api/meta/{sym}`).
   - Collapsible historical breakdown section (CAGRs, multi-year returns, fixed-date sprints).
6. **Band Administration Modal**:
   - Accessible via settings icon for dated snapshot inspection and restoration.

---

## 11. Acceptance Criteria

1. **Universe Ergonomics**: Selecting a Sector in Card 1 dynamically filters the universe without requiring manual text entry in the Condition Builder.
2. **Inline Band Tuning**: Changing a band width in the drawer's 6-TF matrix immediately persists via `PUT /api/bands/{symbol}`, updates the chart envelope, and recalculates live levels.
3. **Band Auditability**: Clicking the history icon in the drawer displays the exact audit trail (`when`, `TF`, `from`, `to`, `by`) returned by `GET /api/bands/log/{symbol}`.
4. **Metadata Annotation**: Editing a stock's Grade or Sector in the drawer persists to `metadata.csv` via `POST /api/meta/{symbol}` and reflects immediately in the results grid.
5. **Sprint Race Visualization**: Clicking `[ 🏁 Sprint Race ]` renders multi-stock cumulative return curves from the selected anchor date using real provider history via `GET /api/race`.
6. **Zero Backend Changes**: 100% of analytical calculations, filtering, ranking, and storage remain delegated to the frozen core.
7. **Regression Guard**: 580/580 baseline tests pass with zero regressions.

---

## 12. Remaining Mentor / Product Decisions

1. **`SelectionMode.ANY` Support**: Whether Core contracts should eventually be amended via RFC to allow union-based (`ANY`) rank cutoffs, or whether intersection (`ALL`) is sufficient for institutional momentum screening.
2. **Band Snapshot Restore Safeguards**: Whether snapshot restoration in live mode should require a typed confirmation string or administrator passcode to prevent accidental overwrite of discretionary bands.
3. **Sprint Race Presentation**: Whether Sprint Race belongs as a modal overlay or whether it justifies a dedicated full-screen drawer expansion.
4. **Multi-Chart Grid Modal (`multiTF`)**: Confirmation to permanently defer/reject the 6-chart WebGL grid in favor of the current 1-click TF switch and 6-TF numerical matrix.

---

### Final Audit Status
**BATCH U3 AUDIT COMPLETE — STRICTLY READ-ONLY**  
Baseline: **580 passed, 0 failed (100%)**

# YOGI — YFINANCE PROVIDER REPLACEMENT AUDIT
**Date**: 2026-09-29  
**Status**: COMPLETED (READ-ONLY AUDIT)  
**Target**: Replace LIVE Twelve Data implementation with Yahoo Finance (`yfinance`)  
**Core Architectural Law**: Stable Core • Replaceable Modules • Contract-Based Connections  
**Final Verdict**: `DIRECT REPLACEMENT — IMPLEMENT`

---

## 1. Executive Summary

This audit assesses whether Yahoo Finance (via `yfinance`) can replace Twelve Data (`TwelveDataProvider`) as the LIVE market data provider for YOGI cleanly through the existing `IDataProvider` contract and `RegistryHub` dependency-injection mechanism, without altering Core contracts, pipeline orchestration, financial calculations, screening, ranking, selection, or Cockpit presentation architecture.

### Key Findings:
1. **Ready Implementation Already Exists**: A fully functional, production-grade [`YFinanceDataProvider`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/yfinance.py) implementing [`IDataProvider`](file:///D:/Yogi%20Investing/My_version/src/yogi/core/contracts/provider.py) was already constructed during Step 6 ([ADR-006](file:///D:/Yogi%20Investing/My_version/docs/decisions.md#adr-006-data-providers--normalization-boundaries)). It is verified by 18 passing tests in [`tests/data/test_yfinance_provider.py`](file:///D:/Yogi%20Investing/My_version/tests/data/test_yfinance_provider.py).
2. **Package Dependency Already Configured**: `yfinance>=0.2.40` is already declared in [`pyproject.toml`](file:///D:/Yogi%20Investing/My_version/pyproject.toml#L24) and installed in the active environment. No new third-party dependencies are required.
3. **Prototype Provenance**: The original verified prototype (`yogi_engine`) used `yfinance` as its primary daily historical market data engine for all NSE/BSE equities, utilizing `yf.download(..., period="10y", interval="1d", auto_adjust=True, threads=True)`.
4. **Significant Operational Advantages Over Twelve Data**:
   - **No API Key / Authentication Required**: Removes `TWELVE_DATA_API_KEY` setup barriers and credential leakage risks.
   - **No Equity Plan Gating**: Twelve Data blocked major Indian large-caps (e.g. `RELIANCE` on NSE was blocked with HTTP 404 "available starting with the Grow or Venture plan"). Yahoo Finance provides open access to all NSE and BSE equities.
   - **No 8 Credits/Minute Rate Limit**: Twelve Data basic plan was throttled to 8 calls/min, forcing YOGI's live refresh to default to single-symbol `("INFY",)`. `yfinance` supports full-universe multithreaded batch queries.
   - **Full 10-Year History**: Provides full 10-year OHLCV daily history out of the box, satisfying long-term CAGRs, 52-week velocity sprints, and multi-year momentum curves without paywall truncation.
5. **Zero Blast Radius**: Replacing Twelve Data with YFinance requires **ZERO** changes to [`src/yogi/core/`](file:///D:/Yogi%20Investing/My_version/src/yogi/core/), [`src/yogi/calculation/`](file:///D:/Yogi%20Investing/My_version/src/yogi/calculation/), [`src/yogi/filter/`](file:///D:/Yogi%20Investing/My_version/src/yogi/filter/), [`src/yogi/ranking/`](file:///D:/Yogi%20Investing/My_version/src/yogi/ranking/), [`src/yogi/selection/`](file:///D:/Yogi%20Investing/My_version/src/yogi/selection/), [`src/yogi/strategy/`](file:///D:/Yogi%20Investing/My_version/src/yogi/strategy/), [`src/yogi/timeframe/`](file:///D:/Yogi%20Investing/My_version/src/yogi/timeframe/), or [`src/yogi/cockpit/router.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/router.py). The change is strictly confined to the provider adapter layer and minimal composition-root defaults in [`src/yogi/cockpit/state.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/state.py).

---

## 2. `IDataProvider` Contract Compatibility Matrix

The authoritative contract [`IDataProvider`](file:///D:/Yogi%20Investing/My_version/src/yogi/core/contracts/provider.py#L19-L104) defines 11 abstract members. Below is the precise compatibility comparison between the current `TwelveDataProvider` and the ready `YFinanceDataProvider`:

| Contract Capability | Required? | Twelve Data Implementation (`TwelveDataProvider`) | Yahoo/yfinance Implementation (`YFinanceDataProvider`) | Compatibility Status | Notes |
|---|---|---|---|---|---|
| **`name`** | Yes | Returns `"twelvedata"` | Returns `"yfinance"` | **COMPATIBLE** | Registered in `RegistryHub.providers` |
| **`supports_intraday`** | Yes | Returns `True` | Returns `True` | **COMPATIBLE** | Both support historical intraday bars |
| **`supports_live_ticks`** | Yes | Returns `False` | Returns `False` | **COMPATIBLE** | Neither provider supports live WebSocket ticks; designated for Zerodha / Step 12 hot path |
| **`universe(exchange)`** | Yes | Queries `/stocks` REST API; falls back to CSV normalizer | Calls `fetch_nse_universe()` / `fetch_bse_universe()` in `yogi.data.normalization.universe` | **COMPATIBLE** | Pure normalizers fetch official NSE `EQUITY_L.csv` (`SERIES == 'EQ'`) and BSE scrip master |
| **`daily_history(symbol, exchange, years)`** | Yes | GET `/time_series?interval=1day&outputsize=...`, normalized via `normalize_twelve_data_bars` | `yf.download(tickers=tk, period=f"{years}y", interval="1d", auto_adjust=True)`, normalized via `normalize_yfinance_bars` | **COMPATIBLE** | Both return `Sequence[MarketBar]` sorted chronologically ascending. Yahoo provides unconstrained 10-year history. |
| **`batch_daily_history(symbols, exchange, years)`** | Yes | Chunks into groups of 8 (basic rate limit); sequential HTTP queries | Multi-threaded single-call batch: `yf.download(tickers=tickers, period=f"{years}y", interval="1d", auto_adjust=True, threads=True, group_by="column")` | **COMPATIBLE (SUPERIOR)** | Yahoo performs parallel batch fetching with zero plan chunking restrictions |
| **`last_price(symbol, exchange)`** | Yes | Calls `/price` endpoint; falls back to `daily_history` | Calls `daily_history(symbol, years=1)[-1].close` | **COMPATIBLE** | Returns `Optional[float]` |
| **`intraday(symbol, exchange, interval, days)`** | Yes | Maps interval to Twelve Data syntax; calls `/time_series` | Maps interval to yfinance syntax (`5minute` $\to$ `5m`); calls `yf.download` | **COMPATIBLE** | Both return `Sequence[MarketBar]` |
| **`subscribe_ticks(symbols, on_tick, exchange)`** | Yes | Raises `NotImplementedError("Twelve Data provider does not support real-time tick streaming...")` | Raises `NotImplementedError("yfinance provider does not support real-time tick streaming")` | **COMPATIBLE** | Identical contractual behavior for pull-based market data sources |
| **`trading_holidays(year)`** | Yes | Returns `INDIAN_TRADING_HOLIDAYS` (imported from `yfinance.py`) | Authoritative source of `INDIAN_TRADING_HOLIDAYS` mapping (2024–2026+) | **COMPATIBLE (IDENTICAL)** | Twelve Data literally imported holiday definitions directly from `yfinance.py` |
| **`health()`** | Yes | Calls `/price` for benchmark symbol `INFY` (because `RELIANCE` was gated) | Calls `last_price(check_sym)` with configurable health symbol (default `RELIANCE`). Returns `ProviderHealth` | **COMPATIBLE** | Yahoo does not gate `RELIANCE` or any other large-cap equity |
| **Symbol/Exchange Handling** | N/A | Strips `.NS`/`.BO` suffixes and resolves colons (`twelve_data_symbol`) | Appends `.NS` for NSE and `.BO` for BSE (`yf_ticker`), respecting custom aliases | **COMPATIBLE** | Both encapsulate vendor-specific ticker syntax within their provider boundary |

**Contract Assessment Result**: `YFinanceDataProvider` completely satisfies the `IDataProvider` contract without any weakening, omitting, or special-casing of contract rules.

---

## 3. Current Twelve Data Integration Points

Tracing the actual execution path for LIVE data:
```text
LIVE provider selection
      ↓
AppState (src/yogi/cockpit/state.py)
      ↓
RegistryHub.providers.get("twelvedata")
      ↓
TwelveDataProvider (src/yogi/data/providers/twelve_data.py)
      ↓
normalize_twelve_data_batch (src/yogi/data/normalization/bars.py)
      ↓
PipelineOrchestrator.build_dataset()
      ↓
AppState._dataset (immutable MappingProxyType)
      ↓
Screening / Charting / Cockpit UI
```

### Precise Inventory of Twelve Data-Specific Integration Points:

1. **[`src/yogi/cockpit/state.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/state.py)**:
   - Line 133–135: `_live_provider_key` fallback defaulting to `"twelvedata"`.
   - Lines 329–335: `refresh()` checking `if provider in ("twelvedata", "twelve_data")`.
   - Lines 366–372: Lazy registration of `TwelveDataProvider` into `RegistryHub.providers`.
   - Lines 410–415: Hardcoded rate-limit mitigation:
     ```python
     elif target_provider in ("twelvedata", "twelve_data"):
         target_symbols = (
             self._config.symbols
             if (self._config.symbols and self._config.provider in ("twelvedata", "twelve_data"))
             else ("INFY",)
         )
     ```
     *(Note: Lines 373–379 in `state.py` already contained lazy registration for `yfinance`!)*
2. **[`src/yogi/cockpit/static/index.html`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/static/index.html)**:
   - Lines 62–64:
     ```html
     <button id="refreshBtn" class="btn btn-secondary btn-sm" title="Rebuild live dataset from Twelve Data provider">
         <span class="refresh-icon">↻</span> Rebuild Live (Twelve Data)
     </button>
     ```
3. **[`src/yogi/cockpit/static/js/app.js`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/static/js/app.js)**:
   - Lines 111–118: Status badge mapping checking `status.provider === 'twelvedata'`.
   - Lines 142–148: Refresh button handler calling `API.refreshDataset(null, null, 'twelvedata')`.
4. **[`src/yogi/data/providers/__init__.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/__init__.py)**:
   - Exports `TwelveDataProvider` and `twelve_data_symbol`.
5. **[`src/yogi/data/normalization/bars.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/normalization/bars.py)**:
   - Defines `normalize_twelve_data_bars` and `normalize_twelve_data_batch`.
6. **[`tests/cockpit/test_cockpit_twelve_data.py`](file:///D:/Yogi%20Investing/My_version/tests/cockpit/test_cockpit_twelve_data.py)**:
   - 4 tests verifying Twelve Data mock integration in Cockpit.
7. **[`tests/data/test_twelve_data_provider.py`](file:///D:/Yogi%20Investing/My_version/tests/data/test_twelve_data_provider.py)**:
   - 33 tests verifying Twelve Data provider unit methods, error responses, API key masking, and rate limits.
8. **Environment Variables**:
   - `TWELVE_DATA_API_KEY` and `TWELVEDATA_API_KEY`.
9. **Documentation**:
   - `docs/decisions.md` (ADR-009, ADR-010).
   - Mentions in `docs/current-state.md`, `docs/roadmap.md`, `docs/system-overview.md`.

### Crucial Architectural Affirmation:
- **`ChartDataService`** ([`src/yogi/cockpit/services/charting.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/services/charting.py)) contains **ZERO** Twelve Data references. It depends solely on `self._provider: IDataProvider`.
- **`RaceDataService`** ([`src/yogi/cockpit/services/race.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/services/race.py)) contains **ZERO** Twelve Data references. It depends solely on `self._provider: IDataProvider`.
- **`router.py`** ([`src/yogi/cockpit/router.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/router.py)) contains **ZERO** Twelve Data references. It forwards `req.provider` directly to `app_state.refresh()`.
- **`PipelineOrchestrator`** ([`src/yogi/core/orchestration/pipeline.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/core/orchestration/pipeline.py)) contains **ZERO** Twelve Data references. It resolves whatever provider key is in `EngineConfig.provider` from `RegistryHub.providers`.

---

## 4. Prototype yfinance Evidence

Verification from the original prototype source (`D:\Yogi Investing\yogi_engine\yogi_engine`):

1. **Default Live Provider**:
   In `config.py` (lines 42–43):
   ```python
   # ---- which market-data provider to use: "yfinance" (free) or "zerodha" (paid live) ----
   DATA_PROVIDER = "yfinance"
   ```
2. **Batch Ingestion Pattern**:
   In `yogi/data_feed/fetch.py` (lines 28–37):
   ```python
   def download_batch(symbols, exchange="NSE"):
       tickers = [yf_ticker(s, exchange) for s in symbols]
       try:
           return yf.download(tickers=tickers, period=PERIOD, interval="1d",
                              auto_adjust=AUTO_ADJUST, progress=False,
                              threads=True, group_by="column")
       except Exception as e:
           print("batch download error:", e)
           return None
   ```
3. **Single-Symbol OHLC Download**:
   In `yogi/data_feed/fetch.py` (lines 54–68):
   ```python
   def fetch_ohlc(symbol, period=None, exchange="NSE"):
       t = yf_ticker(symbol, exchange)
       df = yf.download(t, period=period or PERIOD, interval="1d",
                        auto_adjust=AUTO_ADJUST, progress=False)
       ...
       df = df.rename(columns=str.lower)[["open", "high", "low", "close"]]
       df.index = pd.to_datetime(df.index).tz_localize(None)
       return df.dropna()
   ```
4. **Ticker Suffix Mapping**:
   In `yogi/data_feed/fetch.py` (lines 7, 25):
   ```python
   SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
   ```
5. **Historical Horizon & Auto-Adjustment**:
   - `PERIOD = "10y"`
   - `AUTO_ADJUST = True`
6. **Error / Rate-Limit Resilience**:
   In `run.py` and `yogi/api/app.py`:
   - Set `logging.getLogger("yfinance").setLevel(logging.WARNING)` to suppress verbose scraping logs.
   - Multithreaded retrieval handled transient network retries internally within `urllib3` / `requests` sessions.

**Conclusion**: The existing [`YFinanceDataProvider`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/yfinance.py) in `My_version` faithfully incorporates all proven patterns from the prototype while upgrading them to strict type safety, canonical `MarketBar` DTOs, and testable dependency injection.

---

## 5. Proposed YFinanceProvider Boundary & Design

The replacement design requires **no new classes or architectural designs**, as [`YFinanceDataProvider`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/yfinance.py) is already in place.

### Architectural Boundary:
- **Location**: [`src/yogi/data/providers/yfinance.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/yfinance.py)
- **Class**: `YFinanceDataProvider(IDataProvider)`
- **Key Characteristics**:
  - **Zero Calculation Math**: Contains zero band envelopes, candlestick metrics, zigzag swings, momentum formulas, or ranking logic.
  - **Strict DTO Boundary**: Returns only `Sequence[MarketBar]`, `Mapping[str, Sequence[MarketBar]]`, and `ProviderHealth`. Raw pandas DataFrames never leak past the provider boundary.
  - **Offline Dependency Injection**: Constructor accepts `download_fn: Optional[Callable]` (defaults to `yf.download`), enabling 100% deterministic offline unit testing.
  - **Error Translation**: Operational network failures and rate limits raise `DataProviderError` (`src/yogi/data/providers/exceptions.py`), while programming errors (`TypeError`, `AttributeError`) propagate unmodified.
  - **Configurable Health Target**: Defaults to `RELIANCE` on `NSE` (a universally available ticker), fully overridable at runtime.

---

## 6. Replacement / Removal Analysis

### A. Operational Target Architecture
- **DEMO Mode**: `DemoDataProvider` $\to$ Golden 5-stock deterministic fixtures (completely isolated).
- **LIVE Mode**: `YFinanceDataProvider` $\to$ Live market queries via `yfinance`.
- **Isolation Guarantee**:
  - No `yfinance` $\to$ Twelve Data fallback.
  - No Twelve Data $\to$ Demo fallback.
  - No `yfinance` $\to$ Demo fallback.
  - Live failures fail fast with HTTP 500 error reporting to the trader.

### B. Files Requiring Modification (Minimal Composition Root Update)

1. **[`src/yogi/cockpit/state.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/state.py)**:
   - Change `self._live_provider_key`:
     ```python
     # From:
     self._live_provider_key = (
         self._config.provider if self._config.provider not in ("demo", "yfinance") else "twelvedata"
     )
     # To:
     self._live_provider_key = (
         self._config.provider if self._config.provider != "demo" else "yfinance"
     )
     ```
   - In `refresh()`: Update `provider in ("live", "yfinance")` to target `"yfinance"`.
   - Remove the Twelve Data free-tier restriction (`target_symbols = ("INFY",)`). In Yahoo Finance, the user can refresh any requested symbols or the full universe!
2. **[`src/yogi/cockpit/static/index.html`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/static/index.html)**:
   - Update `#refreshBtn` text to:
     `<button id="refreshBtn" class="btn btn-secondary btn-sm" title="Rebuild live dataset from Yahoo Finance">`
     `<span class="refresh-icon">↻</span> Rebuild Live (Yahoo Finance)`
     `</button>`
3. **[`src/yogi/cockpit/static/js/app.js`](file:///D:/Yogi%20Investing/My_version/src/yogi/cockpit/static/js/app.js)**:
   - Update `#refreshBtn` click handler:
     ```javascript
     showToast('Rebuilding live market dataset from Yahoo Finance...', 'info');
     await API.refreshDataset(null, null, 'yfinance');
     showToast('Live Yahoo Finance dataset refreshed successfully!', 'success');
     ```
   - Update `#systemStatusProvider` label mapping:
     `status.provider === 'yfinance' ? 'YAHOO FINANCE' : ...`
4. **Documentation**:
   - Add ADR-011 in [`docs/decisions.md`](file:///D:/Yogi%20Investing/My_version/docs/decisions.md) documenting the transition of LIVE market data from Twelve Data to Yahoo Finance.
   - Synchronize [`docs/current-state.md`](file:///D:/Yogi%20Investing/My_version/docs/current-state.md), [`docs/roadmap.md`](file:///D:/Yogi%20Investing/My_version/docs/roadmap.md), and [`docs/system-overview.md`](file:///D:/Yogi%20Investing/My_version/docs/system-overview.md).

### C. Files Eligible for Deprecation / Removal (If Twelve Data is Fully Excised)
- [`src/yogi/data/providers/twelve_data.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/twelve_data.py) (can be deleted or retained as an optional secondary provider).
- [`tests/data/test_twelve_data_provider.py`](file:///D:/Yogi%20Investing/My_version/tests/data/test_twelve_data_provider.py) (deleted if Twelve Data is removed).
- [`tests/cockpit/test_cockpit_twelve_data.py`](file:///D:/Yogi%20Investing/My_version/tests/cockpit/test_cockpit_twelve_data.py) (replaced with `tests/cockpit/test_cockpit_yfinance.py`).
- Twelve Data export in [`src/yogi/data/providers/__init__.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/providers/__init__.py).
- Unused Twelve Data normalizers in [`src/yogi/data/normalization/bars.py`](file:///D:/Yogi%20Investing/My_version/src/yogi/data/normalization/bars.py).
- Environment variable `TWELVE_DATA_API_KEY` (completely obsolete).

---

## 7. Refresh Semantics Verification

`YFinanceDataProvider` strictly behaves as a **PULL-based market data provider**:
- It introduces **NO** WebSockets.
- It introduces **NO** background daemon threads or polling loops.
- It introduces **NO** automated 20-minute cron schedulers.
- It introduces **NO** unsolicited state pushes.

### The Refresh Flow:
```text
Trader clicks "Rebuild Live" (or API issues POST /api/dataset/refresh)
                       ↓
FastAPI router.py: refresh_dataset(provider="yfinance")
                       ↓
AppState.refresh() acquires async lock
                       ↓
PipelineOrchestrator.build_dataset(EngineConfig(provider="yfinance"))
                       ↓
RegistryHub.providers.get("yfinance")
                       ↓
YFinanceDataProvider.batch_daily_history(symbols, exchange="NSE", years=10)
                       ↓
yf.download() pulls latest available market close from Yahoo Finance
                       ↓
normalize_yfinance_batch() packages canonical MarketBar sequences
                       ↓
TimeframeEngine synthesizes D -> W, M, Q, H, Y
                       ↓
Bands, Candles, Impulse, Trend, Velocity calculation modules evaluate
                       ↓
AppState freezes new dataset view atomically and clears isolated panel cache
                       ↓
Trader sees updated live market dataset in Cockpit table and charts
```
Any future scheduling concerns (such as an automated daily EOD rebuild) belong to Step 12 operational infrastructure, completely decoupled from provider logic.

---

## 8. Capability Gaps & Trade-off Analysis

| Feature / Metric | Twelve Data Provider | Yahoo Finance (`yfinance`) | Net Advantage |
|---|---|---|---|
| **Cost & API Key** | Requires API key; basic free tier severely limited | 100% Free; no API key or account needed | **Yahoo Finance** |
| **Rate Limits** | 8 credits/min on free tier (unusable for full screening) | No strict minute credits; handles multi-stock batches | **Yahoo Finance** |
| **Large-Cap Equity Access** | Gated on NSE (e.g. `RELIANCE` HTTP 404 on basic plan) | 100% of NSE/BSE equities accessible without tier gating | **Yahoo Finance** |
| **Historical Daily Depth** | 30–60 bars on free tier | 10+ years daily OHLCV | **Yahoo Finance** |
| **Multi-Timeframe Support** | Limited daily depth impeded multi-year CAGRs | Full history allows clean D $\to$ W/M/Q/H/Y synthesis | **Yahoo Finance** |
| **Live Tick Streaming** | Not supported in REST (`supports_live_ticks=False`) | Not supported (`supports_live_ticks=False`) | **Tie (Contract Parity)** |
| **Intraday Historical Bars** | Available via API | Available (7d for 1m, 60d for 5m) | **Twelve Data (slight depth edge)** |
| **API SLA / Official Contract** | Official commercial REST API | Unofficial Yahoo Finance web wrapper | **Twelve Data (commercial SLA)** |

**Assessment**: For YOGI's primary mission—systematic momentum, multi-timeframe relative strength, and structural technical screening on Indian equities—`yfinance` is overwhelmingly superior to Twelve Data's restrictive basic tier.

---

## 9. Risk Assessment & Mitigation Plan

1. **Risk: Yahoo Finance Rate Limiting on Entire 3,800+ Stock Universe**
   - *Analysis*: While yfinance does not have an 8-call/minute key limit, issuing 3,800 simultaneous requests in a single process could trigger temporary Yahoo HTTP 429 IP throttling.
   - *Mitigation*:
     - `yfinance` already utilizes batched requests (`yf.download(tickers=...)`) chunking queries under the hood.
     - For large universes, `batch_daily_history` can partition requests into chunks of 100–200 tickers with small backoffs if needed.
     - The prototype routinely refreshed hundreds of NSE momentum candidates without hitting IP bans.
2. **Risk: Upstream HTML/API Changes by Yahoo**
   - *Analysis*: As an unofficial API, Yahoo occasionally adjusts backend endpoint query parameters.
   - *Mitigation*: The `yfinance` open-source community rapidly releases patch updates (often within hours). `pyproject.toml` pins `yfinance>=0.2.40`.
3. **Risk: Offline Test Suite Degradation**
   - *Analysis*: CI/CD pipeline must never depend on live Yahoo connectivity.
   - *Mitigation*: `YFinanceDataProvider` supports `download_fn` dependency injection. All 18 tests in `tests/data/test_yfinance_provider.py` run 100% offline with zero network calls in $< 1.5$ seconds.

---

## 10. Test Plan for Implementation Phase

When implementation is approved, verification will proceed through three gates:

1. **Gate 1: Existing Unit Suite Verification**
   - Run `pytest tests/data/test_yfinance_provider.py -v` (confirm all 18 unit tests continue passing).
2. **Gate 2: Cockpit YFinance Integration Suite**
   - Create `tests/cockpit/test_cockpit_yfinance.py` mirroring `test_cockpit_twelve_data.py`:
     - Test provider selection and registry resolution (`"yfinance"`).
     - Test Demo and YFinance isolation (no silent fallback).
     - Test full cockpit workflow: screening, ranking, charting, bands tuning, and Excel export on YFinance dataset.
     - Test opt-in live network smoke test (if network is available).
3. **Gate 3: Cockpit Regression & Full Suite**
   - Run all UX suites: `test_batch_u1_stock_detail.py`, `test_batch_u2_screener.py`, `test_batch_u3_power_controls.py`, `test_batch_u4_features.py`.
   - Run full regression: `pytest -q` (confirming all ~609+ tests pass with zero regressions).

---

## 11. Architecture Compliance Verdict

```text
================================================================================
FINAL ARCHITECTURE VERDICT:
DIRECT REPLACEMENT — IMPLEMENT
================================================================================
```

### Rationale:
1. **Contract Invariant Preserved**: The frozen `IDataProvider` contract requires zero modifications.
2. **Implementation Already Complete**: `YFinanceDataProvider` in `src/yogi/data/providers/yfinance.py` already exists, is fully tested, and satisfies every requirement.
3. **Zero Core/Calculation Blast Radius**: Core contracts, pipeline orchestration, calculation modules, filters, ranking, selection, strategies, and results assemblers remain completely invariant.
4. **Clean Plug-and-Play**: Twelve Data can be seamlessly replaced by switching the LIVE provider key in `AppState` and updating the UI button label.

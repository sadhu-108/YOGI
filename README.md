# YOGI — Modular Stock Analysis Platform

> **Stable Core • Replaceable Modules • Contract-Based Connections**

YOGI is a modular, high-performance financial analysis and screening platform engineered for disciplined momentum, relative strength, and structural technical investing in Indian equities (NSE and BSE).

---

## 1. Architectural Principles

YOGI strictly enforces clean architectural separation governed by [`AGENTS.md`](AGENTS.md):

- **Stable Core**: The center (`src/yogi/core/`) coordinates the platform through contracts, registry, configuration, and orchestration without becoming a repository of domain implementations.
- **Contracts First**: Modules communicate exclusively through explicit interfaces (`IDataProvider`, `ICalcModule`, `IFilterRule`, `IStrategy`, `IRankingRule`, `IBandsRepository`, `ISecurityMetadataRepository`).
- **Replaceable Modules**: Concrete implementations (data feeds, calculation backends, storage layers) can be swapped or extended without impacting the core pipeline.
- **Math as Source of Truth**: Core mathematical definitions (Bands, Velocity, Impulse, Trend, Candlestick Theory) are immutable, verified, and protected by regression test suites.
- **Authoritative Screening Pipeline**:
  - **QUALIFY**: *Does it qualify?* (Boolean qualification checks via `FilterEngine`)
  - **ORDER**: *Where does it stand?* (Relative metric ordering across the universe via `RankingEngine`)
  - **SHOW**: *What should be displayed?* (Column projection & metadata enrichment via `ResultAssembler`)
  - **LIMIT**: *Does its rank qualify?* (Top N cutoffs & cohort survival via `SelectionEngine`)
  - **RESULTS**: *What is the execution payload?* (Immutable `QueryResult` output)
  - **Cockpit**: *Presentation & Interaction* (Zero authoritative math runs in the UI facade)

---

## 2. Directory Structure

```text
YOGI/
│
├── AGENTS.md                   # Architectural constitution for developers & agents
├── README.md                   # Project overview and quickstart
├── pyproject.toml              # Build system, dependencies, and tooling config
├── requirements.txt            # Locked runtime & development dependencies
│
├── docs/                       # Synchronized architectural documentation
│   ├── architecture.md         # System boundaries, dataflow, and contracts
│   ├── system-overview.md      # System map & developer onboarding baseline
│   ├── current-state.md        # Authoritative snapshot of implemented capabilities
│   ├── roadmap.md              # Phased milestones, roadmap status, and deferred items
│   ├── decisions.md            # Architectural Decision Records (ADRs 001–010)
│   └── audits/                 # Historical audit artifacts (Final re-audit baseline)
│
├── src/
│   └── yogi/
│       │
│       ├── core/               # Stable invariant foundation
│       │   ├── contracts/      # Public interfaces & protocols (10 contract modules)
│       │   ├── registry/       # Dynamic capability mapping (RegistryHub)
│       │   ├── configuration/  # ScreeningConfig, ScreeningQuery, StrategyCatalog
│       │   └── orchestration/  # PipelineOrchestrator coordination
│       │
│       ├── data/               # Ingestion & Market Context
│       │   ├── providers/      # Adapters (Demo, Yahoo Finance, Zerodha)
│       │   ├── normalization/  # Instrument classification, F&O universe, bar sanitization
│       │   └── sources/        # Resilient external data sources (NSE official bhavcopy)
│       │
│       ├── storage/            # Crash-resilient atomic persistence
│       │   ├── bands.py        # CsvBandsRepository, audit logging, daily backups, restore
│       │   └── metadata.py     # CsvMetadataRepository (Security master metadata)
│       │
│       ├── timeframe/          # Multi-timeframe synthesis (D -> W, M, Q, H, Y)
│       │
│       ├── calculation/        # Five Authoritative Mathematical Pillars
│       │   ├── bands/          # Envelope math, Bollinger, Donchian, ATR, band distance
│       │   ├── candles/        # Candlestick recognition theory (204 shapes/patterns)
│       │   ├── impulse/        # Zigzag reversal pivots & Ram's 50% recovery validation
│       │   ├── trend/          # Trailing ROC, 3/5 EMA, CAGRs, ATH, DMI/ADX, VWAP, RSI, MACD, OBV, MFI
│       │   └── velocity/       # Rolling speed (S4..S52), acceleration, sprint consistency, race curves
│       │
│       ├── filter/             # Qualification criteria & boolean composition (QUALIFY)
│       ├── ranking/            # Multi-key sorting & dynamic cohort ranking (ORDER)
│       ├── selection/          # Top N cutoffs & cohort survival limits (LIMIT)
│       ├── strategy/           # Declarative recipes & 21 Verified Mentor Presets
│       ├── results/            # Column projection, formatting & Excel exports (SHOW/RESULTS)
│       ├── pipeline/           # End-to-end screening orchestrator implementation
│       └── cockpit/            # Presentation workbench, REST API & TradingView charting
│           ├── app.py          # FastAPI application factory
│           ├── router.py       # REST API route handlers
│           ├── schemas.py      # Strongly typed Pydantic response models
│           ├── app_state.py    # In-memory coordination & bounded LRU caches
│           ├── services/       # ChartDataService (19+ series), RaceVisualizerService
│           └── static/         # HTML5 single-page workbench, JS, CSS
│
└── tests/                      # 578 automated unit, integration, and regression tests
    ├── calculation/            # Mathematical validation across all 5 pillars (116 tests)
    ├── cockpit/                # REST API, charting, drawer, and service tests (204 tests)
    ├── core/                   # Contracts, registry, configuration, orchestration (51 tests)
    ├── data/                   # Providers, classification, F&O normalization (72 tests)
    ├── filter/                 # FilterEngine qualification tests (13 tests)
    ├── pipeline/               # End-to-end pipeline execution tests (13 tests)
    ├── ranking/                # RankingEngine ordering tests (8 tests)
    ├── regression/             # Golden calculation invariant tests (6 tests)
    ├── results/                # Result formatting and export tests (14 tests)
    ├── selection/              # SelectionEngine limit tests (10 tests)
    ├── storage/                # Persistent bands, audit, backups, metadata (36 tests)
    ├── strategy/               # Strategy presets and engine tests (10 tests)
    └── timeframe/              # Synthesis and aggregation tests (25 tests)
```

---

## 3. Current Status: MVP Backend Complete & Frozen

- **MVP Backend Engine**: **COMPLETE & FROZEN**. Steps 1 through 11 plus Batches 1–5 and U1–U4 are completed, source-verified, and regression-tested (**577 tests passing**, 1 skipped, 100% pass rate).
- **Architectural Findings**: Findings **YOGI-F01 through YOGI-F06** are fully resolved.
- **Phase Boundary**: The system is entering a **Mentor Review & UX Definition** phase where the mentor will determine how existing analytical metrics, filters, rankings, options, and strategies will ultimately be presented to users.
- **Presentation Layer**: The current Cockpit UI in `src/yogi/cockpit/` serves as a functional, verified prototype workbench. Its presentation model is subject to mentor review and may be redesigned without requiring changes to the frozen Core engine.
- **Engineering Roadmap**: Step 12 (Production Operations, Real-Time Hot Path, Tick Streaming, Cold Database Storage) is deferred to subsequent operational phases.

---

## 4. Quick Start

### Prerequisites & Python Version
- **Supported Python**: `Python >= 3.11` (fully tested on Python 3.11 through 3.14).

### 1. Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Install all runtime and test dependencies from `requirements.txt`:
```bash
pip install -r requirements.txt
```

*(Alternatively, install in editable mode with optional developer packages via pip)*:
```bash
pip install -e ".[dev]"
```

### 3. Provider Configuration (Live Providers)

- **Demo Provider**: Zero configuration required. Operates 100% offline using verified golden datasets.
- **Yahoo Finance Provider (`yfinance`)**: Default live market-data provider for Indian equities (NSE & BSE). Free and operates without API keys or rate limits.
- **Zerodha Kite Connect (Optional)**: If using live Zerodha broker data, install `kiteconnect` and provide credentials:
  ```bash
  pip install kiteconnect>=4.2.0
  export KITE_API_KEY="your_api_key"
  export KITE_ACCESS_TOKEN="your_access_token"
  ```

### 4. Start YOGI Cockpit Application

Launch the local FastAPI ASGI web server using Uvicorn:
```bash
uvicorn --app-dir src "yogi.cockpit.app:create_app" --factory --host 127.0.0.1 --port 8000
```
Open your browser and navigate to:
```
http://127.0.0.1:8000
```

### 5. Running Tests

Execute the complete 578-item test suite across all subsystems:
```bash
# Run the full test suite
pytest

# Run mathematical validation tests
pytest tests/calculation/

# Run golden regression verification
pytest tests/regression/
```

---

## 5. Documentation

Refer to the documents in [`docs/`](docs/) for in-depth technical specifications:
- [`docs/system-overview.md`](docs/system-overview.md) — High-level system map & developer onboarding baseline
- [`docs/architecture.md`](docs/architecture.md) — Comprehensive technical architecture
- [`docs/decisions.md`](docs/decisions.md) — Architectural Decision Records (ADRs 001–010)
- [`docs/roadmap.md`](docs/roadmap.md) — Implementation roadmap and phase tracking
- [`docs/current-state.md`](docs/current-state.md) — Authoritative baseline project state

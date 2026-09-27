# YOGI — Agent Constitution

## 1. Purpose

YOGI is a modular stock-analysis platform built around:

> **Stable Core • Replaceable Modules • Contract-Based Connections**

This file is the architectural constitution for every coding agent working in this repository.

The agent must preserve these principles across all tasks, whether implementing, refactoring, debugging, testing, optimizing, or extending the system.

---

## 2. Non-Negotiable Architecture

### Stable Core

The stable center of YOGI is:

```text
core/
├── contracts/
├── registry/
├── configuration/
└── orchestration/
```

The Core coordinates the system but must not become a collection of domain implementations.

### Contracts First

Modules communicate through explicit YOGI contracts/interfaces.

Examples:

```text
IDataProvider
ICalcModule
IFilterRule
IStrategy
IRankingRule
```

Depend on **contracts, not concrete implementations**.

Do not create unnecessary dependencies between concrete modules.

### Registry

The Registry maps capabilities/contracts to available implementations.

```text
ICalcModule
├── bands    → BandsCalculator
├── velocity → VelocityCalculator
├── impulse  → ImpulseCalculator
└── trend    → TrendCalculator
```

The rest of Core should resolve capabilities through contracts/registry rather than hard-coding implementations.

### Configuration

Configuration answers:

> **What does YOGI want to do?**

It must not become a hidden dependency mechanism or contain domain implementations.

### Orchestration

Orchestration answers:

> **What needs to run, and in what dependency order?**

Execution order must come from actual dependencies/capabilities, not from accidental physical file order.

---

## 3. Modularity Rules

Every implementation should be replaceable where a contract exists.

Examples:

```text
IDataProvider
    → Zerodha
    → Yahoo
    → NSE/BSE
    → future provider

ICalcModule
    → Python implementation
    → Rust implementation
    → future implementation

IModel
    → external AI
    → local AI
    → future model
```

Changing an implementation should require the smallest practical change and must not force unrelated modules to change.

### Language Independence

Do not architect around Python-specific implementation details when they are not required by the contract.

Python is the initial implementation language.

Future implementations may be Python, Rust, Java, or another appropriate technology.

A performance-critical component may later be replaced by a faster implementation without rewriting the surrounding system.

### No Adapter Everywhere

Use adapters at genuine external boundaries where an external API/protocol differs from a YOGI contract.

Do not create pointless adapter layers between internal YOGI modules that already speak the same contract.

---

## 4. Module Boundaries

The MVP structure is:

```text
src/yogi/
├── core/
│   ├── contracts/
│   ├── registry/
│   ├── configuration/
│   └── orchestration/
├── data/
│   ├── providers/
│   └── normalization/
├── timeframe/
├── calculation/
│   ├── bands/
│   ├── velocity/
│   ├── impulse/
│   └── trend/
├── filter/
├── strategy/
├── ranking/
├── selection/
├── results/
└── cockpit/
```

Responsibilities must remain clear:

- **Data providers:** acquire external market data.
- **Normalization:** convert external data into YOGI-standard data/context.
- **Timeframe:** construct and manage trading timeframes/candles.
- **Calculation:** perform analytical calculations.
- **Filter:** answer **“Does it qualify?”**
- **Strategy:** answer **“How are conditions combined into a strategy/signal?”**
- **Ranking:** answer **“Where does it stand?”**
- **Selection:** answer **“Does its rank qualify?”**
- **Results:** answer **“What should be returned?”**
- **Cockpit:** present/interact with results; it is not the authoritative financial engine.

Do not collapse these responsibilities merely because they are convenient to implement together.



---

## Architectural Implementation Discipline

The following rules are mandatory for all future architectural implementation and migration work.

### 1. Modules Are Not Contracts

A module represents an implementation or capability.

A contract represents the stable interface through which other parts of YOGI interact with that capability.

Do not create a contract merely because a module exists.

Only create contracts for genuine architectural boundaries identified by the approved architecture, migration audit, or an explicitly approved design decision.

Each contract must have one authoritative definition. Do not duplicate the same interface in both `core/contracts/` and an implementation module.

### 2. Contracts Must Remain Contracts

Files under `src/yogi/core/contracts/` must contain only:

- interfaces or abstract contracts
- invariant data structures / DTOs
- enums
- specifications required to define the contract
- contract-level type definitions

Contracts must not contain:

- concrete business logic
- financial algorithms
- provider implementations
- database or storage behavior
- API behavior
- UI behavior
- implementation-specific workflows
- provider-specific convenience behavior

A contract may define what an implementation must provide, but must not perform the implementation's work.

### 3. Core Must Not Depend on Replaceable Implementations

Stable Core components must depend on contracts rather than concrete implementations.

Core contracts must remain independent of replaceable technologies such as:

- specific market-data providers
- Zerodha/Kite
- Yahoo Finance
- Excel/openpyxl
- FastAPI
- PostgreSQL
- Redis
- specific UI frameworks
- specific charting libraries
- specific AI providers

Provider-specific, storage-specific, presentation-specific, and technology-specific details belong behind the appropriate architectural boundary.

### 4. Preserve QUALIFY → ORDER → SHOW

The user-facing screening model is intentionally simple:

**QUALIFY → ORDER → SHOW**

Its internal responsibilities are:

- `IFilterRule` → qualification
- `IRankingRule` → relative ordering
- `ISelectionRule` → authoritative selection/show
- `IResultAssembler` → result assembly and presentation payload construction

Do not allow one layer to silently assume responsibility for another.

In particular:

- Filtering must not perform ranking.
- Ranking must not perform selection.
- Selection must remain authoritative for which ranked securities are returned.
- Results must not become a second filtering, ranking, or selection mechanism.

The internal separation may be more detailed than the user-facing interface. The Cockpit should continue to present the simpler screening model.

### 5. Strategy Is Configuration/Composition, Not a Replacement for the Screening Pipeline

`IStrategy` may define or compose reusable screening/strategy configurations, including mentor presets.

A strategy or mentor preset may populate or configure qualification, ranking, and selection behavior.

However:

- Strategy is not synonymous with Filter.
- Strategy is not synonymous with Ranking.
- Strategy is not synonymous with Selection.
- Strategy is not mandatory for every user-created screen.

The 21 Verified Mentor Presets are predefined configurations/recipes, not the complete set of individual filter rules.

### 6. Preserve Verified Prototype Behavior During Migration

When migrating the prototype:

1. Preserve verified financial mathematics and established semantics.
2. Refactor existing behavior behind the new architectural boundaries.
3. Do not silently change formulas or behavioral meaning.
4. Use regression/golden tests where existing verified behavior exists.
5. If prototype behavior conflicts with the target architecture, identify and report the conflict explicitly.

Do not invent a new implementation merely because the existing implementation is architecturally inconvenient.

The migration goal is:

**Preserve → Refactor → Extend**

not:

**Rewrite → Assume equivalent behavior**

### 7. Do Not Invent Hypothetical Architecture

Do not create contracts, modules, abstractions, services, configuration layers, adapters, or infrastructure merely because they might be useful in the future.

Every new architectural element must have a current requirement, an existing prototype responsibility, or an explicitly approved architectural purpose.

Prefer the smallest abstraction that establishes the required boundary.

### 8. Strong Typing Must Be Meaningful

Prefer explicit, strongly typed structures at architectural boundaries.

However, do not introduce elaborate abstractions merely to eliminate every occurrence of `Any`, generic mappings, or dynamic structures.

When dynamic typing is required because of an existing prototype boundary, treat it as an intentional migration boundary and document it when appropriate.

The objective is:

**meaningful typing and clear contracts**

not:

**maximum type complexity**

### 9. Verify the Actual Implementation

An implementation report is not sufficient evidence that an architectural step was implemented correctly.

Before declaring an architectural step complete:

1. Inspect the actual files created or modified.
2. Verify interfaces and dependency directions.
3. Confirm that prohibited implementation logic has not entered architectural layers.
4. Run the relevant tests.
5. Verify imports and basic contract adherence.
6. Report unresolved architectural concerns explicitly.

Passing tests verifies the behavior covered by those tests. It does not, by itself, prove architectural correctness.

### 10. Respect Architectural Step Boundaries

Architectural work must proceed one approved layer at a time.

When instructed to implement a specific step:

- complete only that step
- do not begin the next architectural layer
- do not implement dependent infrastructure prematurely
- stop at the requested boundary and await review

For example:

**Core Contracts → Review → Registry → Review → Orchestration → ...**

Do not implement Registry while performing Core Contracts work merely because Registry will eventually use those contracts.

### 11. Learn From Architectural Errors

When an implementation reveals a reusable architectural lesson, encode the lesson as a general rule rather than treating it only as a one-time correction.

Examples include:

- duplicated contract definitions
- concrete behavior inside contracts
- provider-specific dependencies inside Core
- overlapping responsibilities between modules
- Results performing selection
- Ranking performing filtering
- unnecessary abstractions
- undocumented assumptions
- architectural scope creep

The objective is not merely to correct the current implementation.

The objective is to prevent the same class of architectural error from recurring in future agent-driven development.

### 12. Minimalism Is an Architectural Requirement

When two designs satisfy the same architectural requirement, prefer the simpler one.

Do not add:

- unnecessary interfaces
- unnecessary adapters
- unnecessary files
- unnecessary layers
- unnecessary services
- unnecessary configuration systems
- unnecessary dependencies

Every abstraction must justify its existence through a real architectural boundary or current requirement.

YOGI should remain modular without becoming ceremonially complex.
---

### User Screening Model

The user-facing screener should remain simple and unified.

A screen should be understandable as three simple actions:

1. **Qualify** — define conditions that determine which securities qualify.
2. **Order** — define how qualifying securities are ranked.
3. **Show** — define how many or which ranked securities are returned.

The UI should not require users to understand the internal distinction
between Filter Engine, Ranking Engine, and Selection Engine.

Internally, these remain separate responsibilities:

- Filter Engine → evaluates qualification conditions.
- Ranking Engine → establishes relative ordering.
- Selection Engine → applies rank-based cutoffs or sustained-rank rules.
- Results Engine → assembles the final result.

A single user screen may therefore contain qualification conditions,
ranking criteria, and result limits without requiring separate
user-facing filter layers.

### Mentor Presets

The 21 Verified Mentor Presets are predefined, named screening/strategy
configurations derived from the mentor's methodology.

They are not the set of individual filters.

A mentor preset may internally combine multiple filter conditions,
ranking inputs, and/or selection rules according to its defined
methodology.

Users must also be able to construct custom screens without selecting
a mentor preset.

Mentor presets may be presented in the UI as convenient named
recipes/lists that populate the underlying screen configuration.

## 5. Financial-Math Preservation

**Existing verified YOGI mathematics is source-of-truth code.**

The prototype contains verified calculations, regression fixtures, hand-calculated vectors, and strategy assets.

During migration/refactoring:

> **Preserve → Refactor → Extend**

Do not silently alter a verified formula.

If a refactor changes an output:

1. Stop and identify the reason.
2. Compare against the existing regression/golden tests.
3. Preserve the original behavior unless an explicit change is requested.
4. Add/update tests only when the mathematical change is intentional and approved.

Never optimize mathematics merely for elegance if it changes verified behavior.

---

## 6. Data and Live-Processing Architecture

The intended data flow is:

```text
External Market Feed
        ↓
Data Provider
        ↓
Normalization
        ↓
In-Memory Hot State ───→ Persistent Storage
        ↓
Incremental Calculation
        ↓
Qualification
     ↓
Ranking
     ↓
Selection
     ↓
Results
        ↓
API/WebSocket
        ↓
Cockpit


```
Strategy/preset configuration may define or populate the qualification,
ranking, and selection configuration, but Strategy is not mandatory for
every user screen.

### Hot Path

Low-latency processing must not require a database round-trip for every live tick.

Use in-memory state for hot/live processing.

Persistent storage is for appropriate uses such as:

- historical data
- recovery
- backtesting
- snapshots
- audit/history
- rebuilding state

Storage must remain replaceable behind an appropriate boundary when needed.

---

## 7. Live and Scalability Readiness

Design for:

- historical data
- real-time data
- WebSocket streaming
- incremental calculations
- multiple exchanges
- expanding security universes
- future broker integration
- future notifications
- future AI capabilities
- future scaling

Do not prematurely over-engineer distributed infrastructure.

Build the simplest implementation that preserves the required contracts and future replacement points.

Optimize only when measurement shows a real bottleneck.

**Profile before rewriting for performance.**

If a bottleneck is found, prefer replacing the isolated implementation behind its contract over rewriting unrelated components.

---

## 8. External Boundaries

External systems must not leak their implementation details throughout YOGI.

Potential external boundaries include:

```text
Market APIs       → IDataProvider
Broker APIs       → broker contract/adapter
AI providers      → AI/model contract
Notifications     → notification contract
Storage engines   → storage contract where justified
```

An external API change should ideally be contained within its adapter/provider implementation.

---

## 9. UI / Cockpit Rules

The Cockpit is a consumer of the engine.

It must not become the source of truth for:

- calculations
- filters
- strategies
- rankings
- selection
- market state

UI code should request capabilities/results from the application/core layer.

Charts may display calculated data, but authoritative calculations belong in the engine.

The UI must not contain duplicated financial logic merely for convenience.

---

## 10. Extensibility

New functionality should normally be introduced by:

1. defining or reusing a contract,
2. implementing the capability,
3. registering it,
4. exposing configuration if required,
5. connecting it through orchestration,
6. testing it.

Avoid modifying stable Core logic when a new replaceable implementation can solve the problem.

Examples of future extensions:

```text
new calculation
new filter
new strategy
new ranking rule
new exchange
new broker
new AI model
new notification channel
new storage implementation
new UI/client
```

---

## 11. Dependencies

Prefer dependency direction toward stable abstractions.

Avoid:

```text
Calculation → Cockpit
Filter → Strategy implementation
Core → Zerodha
Core → specific AI provider
```

Prefer:

```text
Core → Contracts
Implementations → Contracts
External systems → Adapters/Providers → Contracts
Cockpit → Application/Core interfaces
```

Avoid circular dependencies.

Keep modules independently testable.

---

## 12. State and Global Variables

Do not introduce hidden module-level mutable state.

Avoid patterns such as:

```text
GLOBAL_DATA
GLOBAL_CONFIG
GLOBAL_PRICES
```

unless there is a deliberate, documented reason.

Prefer explicit state passed through contracts, context objects, services, or controlled state managers.

A module should not secretly depend on another module's mutable global state.

---

## 13. Testing

Tests are part of the architecture.

At minimum, maintain:

```text
tests/
├── core/
├── calculation/
├── pipeline/
└── regression/
```

Important categories:

- contract/interface behavior
- individual calculations
- end-to-end pipeline behavior
- golden/regression fixtures
- edge cases
- provider/normalization behavior
- strategy/filter behavior

A task is not complete merely because the code runs.

The agent must test the changed behavior and report what was verified.

---

## 14. Prototype Migration

The existing prototype is valuable source material, not an architecture to copy blindly.

Reuse:

- verified mathematical implementations
- strategy DSL
- mentor presets
- provider integrations
- normalization logic
- timeframe rules
- useful UI functionality
- regression fixtures
- tests
- proven utilities

But extract them into the new boundaries.

Do not preserve prototype shortcuts merely because they already exist.

In particular, watch for:

- global state
- tightly coupled pipeline functions
- mixed filtering/ranking/selection
- provider-specific assumptions
- UI-owned calculations
- hidden dependencies
- untyped structures where a real contract is required

Migration rule:

> **Reuse behavior and verified logic; redesign the boundaries.**

---

## 15. Minimalism

YOGI should be modular, not over-engineered.

Do not add:

- unnecessary abstractions
- unnecessary microservices
- unnecessary adapters
- unnecessary configuration layers
- unnecessary frameworks
- unnecessary classes
- unnecessary files

Every abstraction must have a reason.

The MVP should remain small while preserving the architectural boundaries needed for future growth.

---

## 16. Agent Workflow

For any non-trivial task:

### Before coding

1. Inspect the relevant architecture and existing code.
2. Identify dependencies and affected contracts.
3. Check whether the requested behavior already exists.
4. Preserve existing verified behavior.
5. State the implementation plan briefly when the task is substantial.

### While coding

- Make the smallest coherent change.
- Keep module boundaries intact.
- Reuse existing contracts where possible.
- Do not silently redesign unrelated areas.
- Do not duplicate existing logic.
- Do not modify verified mathematics without explicit intent.

### After coding

1. Run relevant tests.
2. Run regression tests when calculations are affected.
3. Check imports/dependencies and integration points.
4. Report what changed.
5. Report what was tested.
6. Report known limitations or unresolved decisions.

Never claim something is verified when it has not been tested.

---

## 17. Decision Rules

When uncertain:

### Prefer
- contracts over concrete dependencies
- composition over hard-coded coupling
- replacement over rewriting
- explicit state over hidden state
- measured optimization over premature optimization
- small modules over giant modules
- stable interfaces over implementation leakage
- existing verified behavior over speculative improvements

### Do not
- invent architecture without checking the existing design
- rewrite working mathematics for style
- couple UI to engine internals
- couple Core to a provider/vendor
- introduce language-specific assumptions into contracts
- create abstractions with no current or credible purpose
- make unrelated changes during a focused task

---

## 18. Change-Impact Principle

A good YOGI change should have a localized blast radius.

For example:

```text
Replace market provider
        ↓
provider + registration/configuration
        ↓
little/no change elsewhere
```

```text
Replace calculation implementation
        ↓
calculation module + registration
        ↓
tests
        ↓
little/no change elsewhere
```

```text
Add AI model
        ↓
AI implementation + registration/configuration
        ↓
little/no change elsewhere
```

If a supposedly replaceable component requires widespread changes, first investigate whether an implementation detail has leaked across a contract boundary.

---

## 19. Architectural Priority

When trade-offs occur, prioritize in this order:

1. **Correctness**
2. **Preservation of verified YOGI behavior**
3. **Clear contracts and module boundaries**
4. **Testability**
5. **Maintainability**
6. **Performance where measured**
7. **Convenience**

Do not sacrifice correctness or architectural integrity for short-term coding convenience.

---

## 20. Final Principle

The purpose of this architecture is not to predict every future feature.

It is to ensure that when YOGI evolves:

> **the stable core remains stable, implementations remain replaceable, and changes remain localized.**

Build today's simplest correct system while preserving tomorrow's ability to replace, extend, optimize, scale, and evolve it.

---

## 21. Architectural Discipline & Configuration Guardrails

Future architectural work must adhere to the following strict guardrails:

1. **Do Not Put Data Presentation in Screening Configuration**:
   A `ScreeningQuery` represents `QUALIFY → ORDER → SHOW`. Output column projection is an `IResultAssembler` / Results presentation responsibility. Do not add presentation fields to a configuration object simply because a prototype UI or route currently exposes that option. First determine which architectural layer owns that responsibility.

2. **Existing Contract Types Must Be Reused**:
   If a contract already defines a specification or data structure (e.g. `FilterGroupSpec`, `RankingOrder`, `RankCutoffSpec`, `StrategySpec`, `ColumnDefinition`), do not create duplicate configuration versions of those types. Configuration must compose existing stable contracts.

3. **Prototype Settings Must Not Be Migrated by Name Alone**:
   A setting existing in prototype `config.py` does not automatically become Core Configuration. For every setting, determine its true architectural owner:
   - User/system intent → Core Configuration
   - Domain mathematical invariant → Calculation module
   - Orchestration mechanics (batching, sleep, retry) → Orchestration / Adapter
   - Provider credentials and transport secrets → Concrete Provider Adapter
   - UI/hosting options (port, view-only, LAN) → Cockpit / Presentation
   - Scheduling / cron jobs → Operations
   - Storage cache paths → Caching / Storage adapters
   Only genuine user/system intent belongs in Core Configuration.

4. **Do Not Confuse "Configurable" with "Core Configuration"**:
   The fact that a value can technically be changed at runtime does not mean it belongs in `core/configuration`. Architectural ownership is determined by responsibility, not by whether a variable exists.

5. **Do Not Create Abstractions or Fields Without a Demonstrated Responsibility**:
   Every new configuration class, field, interface, or Registry category must have an active, demonstrated responsibility in YOGI's current architecture. Minimalism is mandatory.

6. **Preserve Pipeline Responsibility Boundaries**:
   - `QUALIFY` = filtering (`IFilterRule`)
   - `ORDER` = ranking (`IRankingRule`)
   - `SHOW` = selection (`ISelectionRule`)
   - `PRESENTATION` = result assembly and column projection (`IResultAssembler`)
   Do not allow one configuration object to absorb responsibilities belonging to another architectural stage.

7. **Semantic Fidelity in Configuration Translation**:
   Do not infer semantics from field names or prototype structure alone. Before mapping one configuration/specification type into another, trace each field to its authoritative contract and actual prototype behavior. Verify whether apparently similar fields represent distinct responsibilities or duplicate semantics. Do not hardcode defaults such as ordering direction unless they are explicitly established by the contract, verified prototype behavior, or an approved architectural decision.
   Configuration translation must preserve semantics, not merely copy fields. Every transformation between `StrategySpec`, `ScreeningQuery`, and other configuration types must be justified by the source and target contracts.

8. **Architecture Verification Over Passing Tests**:
   Passing tests are a necessary condition for correctness, but never a sufficient proof of architectural compliance. Tests can easily pass while violating boundary rules (such as hardcoded concrete fallbacks, hidden circular imports, or mutable state leaks). Before accepting an implementation or marking a milestone frozen, agents must independently verify boundaries and dependency direction against actual source files rather than generated reports. Specifically inspect:
   - actual source files (do not rely on summaries or pasted dumps)
   - dependency direction and contract boundaries
   - forbidden imports and framework/vendor leakages
   - concrete-provider instantiation (preventing hidden fallbacks)
   - state mutation paths (verifying deep immutability)
   - application and container initialization paths
   - API and frontend integration points

9. **No Concrete Provider Fallbacks in Consumer or Boundary Layers**:
   Presentation, API, and consumer layers (such as Cockpit, routers, or CLI scripts) must never instantiate or fall back to concrete external providers (e.g. `YFinanceDataProvider()`) directly. All external capabilities and data providers must be resolved strictly through dependency injection or the canonical `RegistryHub`. If a requested capability is absent from the registry, the component must handle the omission explicitly (e.g. returning HTTP 503 or raising an explicit configuration error), rather than creating an unauthorized secondary resolution path.

10. **Exception Handling & Fault Boundary Discipline**:
    Never swallow exceptions or use bare `except Exception: pass` within core orchestration, domain models, or capability resolution logic. Masking domain failures obscures contract violations and prevents proper error propagation. Application-boundary resilience (such as optional background startup dataset pre-warming in ASGI lifespan handlers) must be strictly isolated at the outermost presentation edge, clearly commented as a fault boundary, and scheduled for structured operational logging rather than silent omission.

11. **Minimal Change and Freeze Discipline**:
    Once a milestone or architectural step has passed through:
    **Audit → Implementation → Code Review → Correction → Tests → Freeze**,
    it must not be reopened, refactored, or redesigned unless a concrete defect in a subsequent layer proves that an existing contract is violated. When performing audits or corrections, verify the actual code on disk first before making edits, and correct only verified defects. Speculative improvements, stylistic rewrites, and unauthorized scope creep violate architectural stability.

12. **Frontend Presentation Security & Injection Defense**:
    When designing presentation templates or dynamic client-side tables that render model or external dataset attributes, never interpolate raw strings into `innerHTML` without entity escaping. All string columns (symbols, names, textual indicators) must be encoded through a dedicated escaping mechanism or assigned via safe DOM properties (`textContent`).

13. **Defensive Immutability of Published State**:
    In-memory datasets, caches, and shared application states must enforce true recursive immutability across all nesting levels (e.g. `MappingProxyType` for mappings, `tuple` for sequences). Do not assume nested child structures will remain unmutated; recursively freeze inner values so that external consumers can never mutate published snapshots in place.

---

## Documentation Synchronization

Project documentation must remain consistent with the actual state and design of the codebase, but documentation must not be updated for every routine implementation action. Avoid unnecessary documentation changes, duplication, and documentation noise.

The following documents are maintained under `docs/`:

```text
docs/
├── architecture.md
├── decisions.md
├── roadmap.md
└── current-state.md
```

### `docs/architecture.md`

Update when a change materially affects the system's architecture, including:

* module boundaries or responsibilities
* dependency direction
* contracts or interfaces
* data flow or execution flow
* major extension points
* architectural patterns
* significant infrastructure or integration boundaries

Do not update it for routine implementation changes that preserve the existing architecture.

### `docs/decisions.md`

Update when a significant architectural, technical, or design decision is made that is likely to matter to future development.

Record:

* the decision
* the reason for the decision
* important alternatives considered, when relevant
* significant consequences or trade-offs

Do not record trivial implementation choices or routine coding decisions.

### `docs/roadmap.md`

Update when project priorities, milestones, planned phases, scope, or sequencing materially change.

Do not update it for normal progress within an already-defined task or milestone.

### `docs/current-state.md`

Update when the implemented state of the project materially changes, such as:

* a major module or subsystem becoming implemented
* an architectural milestone being completed
* a significant capability being added or removed
* an important integration becoming operational
* a major project state or limitation changing

Do not update it for every individual file change, bug fix, or routine implementation step.

### General Rules

1. Update only the document(s) relevant to the change.
2. Documentation must describe the **actual implemented state**, not planned or proposed behavior, unless the document is explicitly describing plans or decisions.
3. When an approved architectural decision is made during a task, record it in `decisions.md` before considering the task complete.
4. When a task materially changes architecture, update `architecture.md` as part of the same task.
5. When project direction or milestones change, update `roadmap.md`.
6. When the project's implemented state materially changes, update `current-state.md`.
7. Do not duplicate the same information across multiple documents unless each document serves a distinct purpose.
8. Do not create additional documentation files unless there is a clear recurring need for them.
9. When no documented aspect is materially affected, do not modify the documentation.
10. Documentation updates are part of the task when the conditions above are met; they should not be deferred to a later cleanup task.

### System Overview Maintenance

`docs/system-overview.md` is the living high-level map of YOGI. After every significant change, the agent MUST determine whether the change materially affects the system-level understanding of the software. If it does, update `docs/system-overview.md` in the same task so that it remains consistent with the actual implementation, architecture, module responsibilities, major data flow, and current implementation status.

Significant changes include adding, removing, or restructuring major components; changing architectural boundaries or contracts; changing major data/execution flows; completing or freezing a major implementation step; changing responsibilities between layers; or making an architectural decision that materially changes the system.

Do NOT update it for ordinary bug fixes, internal refactoring that preserves the architecture, individual tests, minor implementation details, formatting, or other changes that do not affect the system-level map.

`system-overview.md` is not a changelog. It must describe the current verified state, while historical rationale belongs in `docs/decisions.md`, detailed architecture belongs in `docs/architecture.md`, implementation status belongs in `docs/current-state.md`, and planned work belongs in `docs/roadmap.md`.
# AGENTS.md

This file defines general agent design principles for this repository.

## Agent Design Principle

An agent is a model using tools in a loop.

Every agent must be defined by three core components:

1. Environment
   - The runtime context the agent can observe and operate in.
   - Examples: repository, terminal, filesystem, browser, VM, Kubernetes cluster, database, APIs.

2. Tools
   - The actions the agent is allowed to take in the environment.
   - Examples: bash, grep, read, write, edit, test, search, fetch, screenshot, kubectl, git.

3. System Prompt
   - The goals, constraints, behavior rules, and decision policy of the agent.
   - It defines what the agent is trying to do, how it should act, and what it must avoid.

The agent should operate as a loop:

```python
env = Environment()
tools = Tools(env)
system_prompt = "Goals, constraints, and how to act"

while True:
    action = llm.run(system_prompt + env.state)
    env.state = tools.run(action)
```

## Amazon Selector Agent

This repository implements the principle above as a local product sourcing agent.

### Environment

- Repository code and configuration.
- Terminal process running `docker compose up -d --build amazon-selector` for the official WebUI runtime.
- SQLite database at `data/amazon_selector.db`.
- Cookie files in `data/amazon_cookies.json` and `data/1688_cookies.json`.
- Exported result files in `data/exports/`.
- Amazon and 1688 browser sessions, including human-in-the-loop captcha or popup handling.

### Tools

- `agent.preflight.run_preflight()` checks whether the environment is ready.
- `pipeline.orchestrator.run_pipeline()` runs the 7-stage sourcing workflow.
- `agent.history` reads previous JSON/Excel exports and stores saved selections.
- `agent.server` exposes local JSON APIs and static WebUI assets.

### System Prompt

The runtime prompt is stored in `agent.runner.AGENT_SYSTEM_PROMPT`.

Policy summary:

- Prefer real Amazon and real 1688 data over mock data.
- In formal no-mock mode, do not allow mock suppliers into results.
- Run preflight before starting sourcing work.
- If 1688 is blocked by login, popup, or captcha, stop and ask for human action.
- Audit exports after each run before presenting candidates.

### Local WebUI

Run:

```bash
docker compose up -d --build amazon-selector
```

Open:

```text
http://127.0.0.1:8765
```

`python main.py agent-web` remains available only for local debugging fallback.

The UI can launch new sourcing runs, show preflight health, read previous product selection exports, search candidates, download Excel files, and save product selections to `data/agent_saved_items.json`.

## Commands

All commands run from the repository root.

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium        # only if Amazon / 1688 scraping is needed

# Initialize the database
python main.py init-db

# Run the full pipeline for a category
python main.py run --category "Home & Kitchen" --limit 50

# Start the local Agent WebUI (official runtime)
docker compose up -d --build amazon-selector

# Run all tests (pure unit tests, no network or API keys required)
pytest tests/

# Run a single test file
pytest tests/test_scoring.py -v

# Run tests with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

Tests use mock DTOs (`_MockProduct`, `_MockSupplier`, `_MockMarket`) — they do not call Amazon, 1688, or Sellersprite, so they run offline with no `.env` configured.

## Architecture

A **7-stage linear pipeline** that takes a category name and produces a ranked candidate product pool:

```
main.py (click CLI: init-db | run)
    └─ pipeline/orchestrator.py::run_pipeline(category, limit, marketplace, top_n)
           ├─ Stage 1  crawlers/amazon_bsr.py::crawl_best_sellers    → list[ProductDTO]
           │               backends: scrapling | playwright | keepa | rainforest (auto by .env keys)
           ├─ Stage 2  matchers/__init__.py::match_suppliers          → list[SupplierDTO]
           │               VisionAnalyzer → Alibaba1688PlaywrightMatcher → Verifier
           ├─ Stage 3  analyzers/profit_model.py::predict_profit      → ProfitBreakdown
           ├─ Stage 4  analyzers/maijiajingling.py::analyze_market    → MarketAnalysisDTO
           ├─ Stage 5  analyzers/scorer.py::score_product             → ScoreBreakdown
           ├─ Stage 6  pipeline/filters.py::rank_candidates           → list[PipelineRecord]
           └─ Stage 7  reports/exporter.py                            → Excel / Markdown / JSON
```

**Stage failure policy**: Stage 1 failure aborts the entire run. All other stages fail per-product and continue.

### Module boundaries

| Module | Responsibility |
|--------|----------------|
| `crawlers/` | Amazon BSR data acquisition (scrapling/playwright/keepa/rainforest) |
| `matchers/` | 1688 supplier matching (vision → text search → playwright → verify) |
| `analyzers/` | Profit model, market analysis, scoring |
| `pipeline/` | Orchestration, filtering, ranking |
| `db/` | SQLAlchemy ORM models, session, migrations |
| `execution/` | Run coordination, leases, policies |
| `agent/` | WebUI server, preflight, runner, history |
| `config/` | YAML params, pydantic-settings |
| `reports/` | Excel/Markdown/JSON export |

### DTO / ORM boundary

DTOs are dataclasses **separate from ORM models** — crawlers/matchers/analyzers never touch SQLAlchemy:

| Boundary | DTO (dataclass) | ORM model |
|----------|-----------------|----------|
| Stage 1 | `crawlers.ProductDTO` | `db.Product` |
| Stage 2 | `matchers.SupplierDTO` | `db.Supplier` |
| Stage 3 | `analyzers.ProfitBreakdown` | `db.ProfitSnapshot` |
| Stage 4 | `analyzers.MarketAnalysisDTO` | `db.MarketAnalysis` |
| Stage 5 | `analyzers.ScoreBreakdown` | `db.Score` |

The orchestrator carries per-product state in `pipeline.PipelineRecord` and inserts ORM rows at the end of each stage.

### Configuration system

Two YAML files drive all tunable parameters — **no code changes needed for tuning**:

- `config/profit_params.yaml` — cost rates (FBA fee tiers, ACOS, return rate, exchange rate, shipping)
- `config/scoring_weights.yaml` — dimension weights, scoring curves, hard-filter thresholds

Both use module-level cache with `reload_*()` for hot-reload. `config/settings.py` (pydantic-settings) reads `.env` and exposes a singleton `settings` object for all API keys and `DATABASE_URL`.

### Scoring hard constraints

- `scoring_weights.yaml` weights **must sum to exactly 1.0** — enforced at load time and by `tests/test_scoring.py::test_weights_sum_to_one`.
- **Always re-run `pytest tests/test_scoring.py` after editing `scoring_weights.yaml`.**
- Hard filters eliminate products before ranking; eliminated products are persisted with `passed_hard_filter=False`.

### Database patterns

- `ProfitSnapshot` and `Score` are **append-only** (snapshot pattern) — each run inserts new rows with `params_snapshot`/`weights_snapshot` JSON fields.
- Use `db/session.py::session_scope()` for all DB access (auto-commit on exit, rollback on exception).

## Docs

- `docs/PRD.md` — product requirements and module specs
- `docs/scoring_spec.md` — per-dimension scoring formulas
- `docs/database_schema.md` — schema design rationale
- `docs/DEPLOYMENT.md` — Docker deployment guide
- `docs/UI_DESIGN.md` — UI design tokens (Linear-style dark theme, webui/ only)

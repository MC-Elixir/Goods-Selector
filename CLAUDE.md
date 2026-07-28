# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Commands

All commands must be run from inside the `amazon_selector/` directory (the package root and git repo root).

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium        # only if Amazon / 1688 scraping is needed

# Initialize the database (creates SQLite tables via SQLAlchemy)
python main.py init-db
# equivalent:
python -m db.init_db

# Run the full pipeline for a category
python main.py run --category "Home & Kitchen" --limit 50
python main.py run --category "Home & Kitchen" --limit 50 --marketplace US   # default
python main.py run --category "Toys & Games" --limit 10 --marketplace UK

# Start the local Agent WebUI (official runtime)
docker compose up -d --build amazon-selector
# then open http://127.0.0.1:8765

# Local debugging fallback only
python main.py agent-web

# Run all tests (pure unit tests, no network or API keys required)
pytest tests/

# Run a single test file
pytest tests/test_scoring.py -v

# Run a single test
pytest tests/test_profit_model.py::test_profit_breakdown_math -v

# Run a class / all tests of a file
pytest tests/test_scoring.py::TestScoreProfit -v

# Run tests with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

The tests use mock DTOs (`_MockProduct`, `_MockSupplier`, `_MockMarket`) — they do not call Amazon, 1688, or Sellersprite, so they run offline with no `.env` configured.

## Architecture

A **7-stage linear pipeline** that takes a category name and produces a ranked candidate product pool. The orchestrator owns a `RunLog` row's lifecycle (started_at, status, stage counters, finished_at).

```
main.py (click CLI: init-db | run)
    └─ pipeline/orchestrator.py::run_pipeline(category, limit, marketplace, top_n)
           ├─ Stage 1  crawlers/amazon_bsr.py::crawl_best_sellers    → list[ProductDTO]
           │               backends: playwright | keepa | rainforest (auto by .env keys)
           ├─ Stage 2  matchers/__init__.py::match_suppliers          → list[SupplierDTO]
           │               0. VisionAnalyzer   (PPIO / Anthropic → 1688 中文关键词)
           │               1. Alibaba1688TextSearch        (1688 官方 API, 需 key — 默认未配/已弃用)
           │               2. Alibaba1688ScraplingMatcher  (HTTP 路径, 被 TMD 拦 — enable_scrapling_matcher 默认 False)
           │               3. Alibaba1688PlaywrightMatcher (浏览器兜底 ← 默认主路径, 注入 cookies)
           │               4. _mock_suppliers              (离线兜底)
           │               5. Alibaba1688Verifier          (启发式过滤)
           │               6. LLMVisualVerifier            (可选, settings.enable_llm_verification)
           ├─ Stage 3  analyzers/profit_model.py::predict_profit      → ProfitBreakdown
           │               calc_purchase_cost | calc_shipping_cost | calc_fba_fee
           │               calc_commission | calc_ad_cost | calc_return_loss
           ├─ Stage 4  analyzers/maijiajingling.py::analyze_market    → MarketAnalysisDTO
           │               asin_detail (API 3) + bsr_prediction (API 26) + competitor_lookup (API 1) + keyword_research (API 10)
           ├─ Stage 5  analyzers/scorer.py::score_product             → ScoreBreakdown
           │               score_profit | score_demand | score_competition
           │               score_supply  | score_logistics | score_risk
           │               + apply_hard_filters (6-dim → 0–100 total + passed/reasons)
           ├─ Stage 6  pipeline/filters.py::rank_candidates           → list[PipelineRecord]
           │               filter on passed_hard_filter, sort by total_score (+ net_profit)
           └─ Stage 7  reports/exporter.py                            → Excel / Markdown / JSON
                       export_excel | export_markdown | export_json
```

**Stage failure policy**: Stage 1 (crawl) failure aborts the entire run and marks `RunLog.status="failed"`. All other stages fail per-product, log a warning, and continue — a product that fails match/profit/score simply gets empty data and is dropped by the hard filter.

### Agent WebUI Architecture

The local agent layer wraps the pipeline instead of replacing it:

```
agent/server.py      ThreadingHTTPServer + static WebUI + JSON APIs
agent/runner.py      AgentRuntime: preflight -> run_pipeline -> export audit
agent/preflight.py   Environment checks: API keys, cookies, DB, exports, cooldown
agent/history.py     Reads data/exports/candidates_*.json and saved selections
webui/               Static HTML/CSS/JS operations console
```

Agent components under the design principle:

- **Environment**: local repository, terminal process, SQLite database, `data/` cookies/cache/exports, Amazon/1688 web sessions.
- **Tools**: preflight checks, `run_pipeline`, export readers, saved-selection writer, Excel/JSON download endpoints.
- **System Prompt**: `agent.runner.AGENT_SYSTEM_PROMPT`; it requires real data preference, no-mock formal mode, preflight before runs, human handoff for 1688 captcha/popup blockers, and post-run audit.

The WebUI is intentionally local-only by default (`127.0.0.1:8765`) and does not add external web framework dependencies. The official runtime is Docker on `127.0.0.1:8765`; `python main.py agent-web` is only a local debugging fallback.

### Data flow objects

DTOs are dataclasses that are **separate from the ORM models** — crawlers/matchers/analyzers never touch SQLAlchemy:

| Boundary | DTO (dataclass)         | ORM model        |
|----------|-------------------------|------------------|
| Stage 1  | `crawlers.ProductDTO`   | `db.Product`     |
| Stage 2  | `matchers.SupplierDTO`  | `db.Supplier`    |
| Stage 4  | `analyzers.MarketAnalysisDTO` | `db.MarketAnalysis` |
| Stage 3  | `analyzers.ProfitBreakdown`    | `db.ProfitSnapshot` |
| Stage 5  | `analyzers.ScoreBreakdown`     | `db.Score`           |

The orchestrator carries per-product state in `pipeline.PipelineRecord` (product + suppliers + profit + market + score) and inserts ORM rows at the end of each stage.

### Configuration system

Two YAML files drive all tunable parameters — **no code changes needed for tuning**:

- `config/profit_params.yaml` — every cost rate (FBA fee tiers, ACOS, return rate, exchange rate, shipping tiers, commission by category)
- `config/scoring_weights.yaml` — dimension weights, scoring curves, hard-filter thresholds

Both are loaded with a module-level cache (`_PARAMS_CACHE` / `_WEIGHTS_CACHE`) and a `reload_*()` function for hot-reload without restart. Read paths via `from config.settings import CONFIG_DIR`.

`config/settings.py` (pydantic-settings) reads `.env` and exposes a singleton `settings` object. All API keys (`KEEPA_API_KEY`, `RAINFOREST_API_KEY`, `ALIBABA_APP_KEY/SECRET`, `MJJL_API_KEY`, `PPIO_API_KEY`, `ANTHROPIC_API_KEY`) and `DATABASE_URL` come from here. `settings.vision_provider` auto-selects PPIO over Anthropic when both are configured.

### Database / ORM

`db/models.py` defines 6 SQLAlchemy ORM classes: `Product`, `Supplier`, `ProfitSnapshot`, `Score`, `MarketAnalysis`, `RunLog`. Schema is created by `Base.metadata.create_all(engine)` — no Alembic migrations in use today (the `db/migrations/` directory is reserved for future use).

**Snapshot pattern**: `ProfitSnapshot` and `Score` are **append-only** — each pipeline run inserts new rows rather than updating existing ones. Both carry a `params_snapshot` / `weights_snapshot` JSON field capturing the YAML state at run time, so historical decisions stay reproducible when YAML is retuned.

Use `db/session.py::session_scope()` for all DB access:

```python
from db.session import session_scope

with session_scope() as s:
    s.add(obj)   # auto-commit on exit, rollback on exception
```

The orchestrator's `_update_run(run_id, **kwargs)` helper is the pattern for partial field updates on `RunLog`.

### Scoring system

`analyzers/scorer.py::score_product()` returns a `ScoreBreakdown` with 6 dimension scores (0–1 each), a weighted `total_score` (0–100), and `passed_hard_filter` / `rejection_reasons`. Weights and curve parameters come from `scoring_weights.yaml`.

**Hard rule**: `weights` must sum to exactly 1.0 — enforced at YAML load time and by `tests/test_scoring.py::test_weights_sum_to_one`. **Always re-run tests after editing `scoring_weights.yaml`.**

Hard filters (`scoring_weights.yaml::hard_filters`) eliminate products before ranking; eliminated products are still persisted with `passed_hard_filter=False` for post-hoc analysis. See `docs/scoring_spec.md` for per-dimension formulas and threshold rationale.

### Caching & matching dedup

- `diskcache` is used for all external API calls (configured via `settings.enable_api_cache` and `settings.cache_ttl_seconds`, default TTL 24 h). Cache directory: `data/cache/`.
- 1688 image search dedup is done with `imagehash` (pHash) on the Amazon main image.
- Module-level singletons in `matchers/__init__.py` (`_vision`, `_text_search`, `_scrapling`, `_playwright`, `_verifier`, `_llm_verifier`) lazily initialize so the whole pipeline reuses one browser session.

### What's stubbed vs implemented

Most of the pipeline is real and runnable end-to-end. The genuinely-stubbed surface is narrow:

- `matchers/alibaba_pailitao.py::PailitaoClient.search_by_image` and `get_offer_detail` — raise `NotImplementedError`. Since 0.2.2 the 1688 production path is `alibaba_playwright` (Playwright + injected cookies) → mock fallback; the official `alibaba_text_search` REST API is deprecated (key cleared from `.env`) and `alibaba_scrapling` is disabled by default (`settings.enable_scrapling_matcher=False` — its HTTP header cookies are blocked by 1688 TMD). For true image-based 1688 search the working backend is `alibaba_playwright.search_by_image`.
- The default Amazon backend is `crawlers/amazon_scrapling.py::AmazonScraplingScraper` (Scrapling `StealthySession` — patchright-chromium + curl_cffi anti-bot, no API key required). `playwright` (`amazon_playwright.py`) is still available as a fallback by passing `backend="playwright"`. `keepa` / `rainforest` are used automatically when their keys are present and outrank scrapling.

### Docs

- `docs/PRD.md` — full product requirements including module specs, data-model rationale, and the development plan
- `docs/scoring_spec.md` — per-dimension scoring formulas with worked examples
- `docs/database_schema.md` — schema design rationale and common query patterns
- `docs/DEPLOYMENT.md` — Docker deployment guide
- `DESIGN.md` — UI design tokens (Linear-style dark theme)

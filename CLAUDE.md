# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands must be run from inside the `amazon_selector/` directory (the package root).

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database (creates SQLite tables via SQLAlchemy)
python -m db.init_db
# or
python main.py init-db

# Run the full pipeline for a category
python main.py run --category "Home & Kitchen" --limit 50

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_scoring.py -v

# Run a single test
pytest tests/test_profit_model.py::test_profit_breakdown_math -v

# Run tests with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

## Architecture

The system is a **7-stage linear pipeline** that takes a category name and produces a ranked candidate product pool.

```
main.py (CLI)
    └─ pipeline/orchestrator.py   # Orchestrates all 7 stages; owns RunLog lifecycle
           ├─ crawlers/amazon_bsr.py        # Stage 1: Keepa/Rainforest → ProductDTO list
           ├─ matchers/alibaba_pailitao.py  # Stage 2: Image search → SupplierDTO list
           ├─ analyzers/profit_model.py     # Stage 3: ProfitBreakdown per (product, supplier)
           ├─ analyzers/maijiajingling.py   # Stage 4: MarketAnalysisDTO per ASIN
           ├─ analyzers/scorer.py           # Stage 5: ScoreBreakdown per product
           ├─ pipeline/filters.py           # Stage 6: Hard filter + rank by total_score
           └─ reports/exporter.py           # Stage 7: Excel / Markdown / JSON output
```

**Stage failure policy**: Stage 1 (crawl) failure aborts the entire run. All other stages fail per-product and continue — the orchestrator catches exceptions and logs them.

### Configuration system

Two YAML files drive all tunable parameters — **no code changes needed for tuning**:

- `config/profit_params.yaml` — every cost rate (FBA fees, ACOS, return rate, exchange rate, shipping tiers)
- `config/scoring_weights.yaml` — dimension weights, curve parameters, hard-filter thresholds

Both are loaded with a module-level cache (`_PARAMS_CACHE` / `_WEIGHTS_CACHE`) and a corresponding `reload_*()` function for hot-reload without restart. Read via `from config.settings import CONFIG_DIR`.

`config/settings.py` (pydantic-settings) reads `.env` and exposes a singleton `settings` object. All API keys and `DATABASE_URL` come from here.

### Database / ORM

`db/models.py` defines 6 SQLAlchemy ORM classes: `Product`, `Supplier`, `ProfitSnapshot`, `Score`, `MarketAnalysis`, `RunLog`.

**Snapshot pattern**: `ProfitSnapshot` and `Score` are **append-only** — each pipeline run inserts new rows rather than updating existing ones. Both carry a `params_snapshot` / `weights_snapshot` JSON field capturing the YAML state at run time for reproducibility.

Use `db/session.py::session_scope()` for all DB access:
```python
with session_scope() as s:
    s.add(obj)   # auto-commit on exit, rollback on exception
```

### DTOs

Each external API boundary has a dedicated dataclass DTO that is separate from the ORM model:
- `ProductDTO` (crawlers) → `Product` ORM
- `SupplierDTO` (matchers) → `Supplier` ORM
- `MarketAnalysisDTO` (analyzers/maijiajingling) → `MarketAnalysis` ORM

### Implementation status

**All external API methods raise `NotImplementedError`** — the scaffold is complete but integrations are unbuilt:
- `crawlers/amazon_bsr.py::crawl_best_sellers` — needs Keepa SDK
- `matchers/alibaba_pailitao.py::PailitaoClient.search_by_image` — needs 1688 open platform credentials
- `analyzers/maijiajingling.py::MaijiajinglingClient.analyze_market` — needs Sellersprite API key
- `analyzers/profit_model.py` — 6 `calc_*` functions + `predict_profit` need implementation
- `analyzers/scorer.py` — 6 `score_*` functions + `apply_hard_filters` + `score_product` need implementation
- `reports/exporter.py` — 3 export functions need implementation

The orchestrator (`pipeline/orchestrator.py`) has the 7 stages stubbed out as commented code.

### Scoring system

`score_product()` produces a `ScoreBreakdown` with 6 dimension scores (0–1 each), a weighted `total_score` (0–100), and `passed_hard_filter`. Weights and curve parameters come from `scoring_weights.yaml`. The CI test `test_weights_sum_to_one` enforces that weights sum to exactly 1.0 — **always run tests after editing the YAML**.

Hard filters (from `scoring_weights.yaml::hard_filters`) eliminate products before ranking; eliminated products are still persisted with `passed_hard_filter=False` for post-hoc analysis.

### Caching

`diskcache` is used for all external API calls (configured via `settings.enable_api_cache` and `settings.cache_ttl_seconds`, default TTL 24 h). Cache directory: `data/cache/`. Image hashes (pHash via `imagehash`) deduplicate 1688 image searches.

### Docs

- `docs/PRD.md` — full product requirements including module specs and data model rationale
- `docs/scoring_spec.md` — scoring dimension formulas with examples
- `docs/database_schema.md` — schema design rationale and common query patterns
- `docs/选品参考/` — real sourcing reference Excel files used to calibrate scoring and profit parameters

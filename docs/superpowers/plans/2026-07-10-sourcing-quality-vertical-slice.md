# Sourcing Quality Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first no-mock, evidence-gated sourcing loop from Amazon product understanding through multi-query 1688 search, offer-detail enrichment, structured and dual-image verification, bounded retry, and an evidence-backed recommendation or rejection.

**Architecture:** Keep `pipeline.orchestrator.run_pipeline()` as the default deterministic path and add focused, typed services beside it. Pydantic v2 schemas define evidence and matching contracts; additive SQLite migrations persist provenance and query/match artifacts; a bounded vertical-slice coordinator composes existing search providers without introducing the Phase 3 agent state machine yet.

**Tech Stack:** Python 3.11, Pydantic 2, SQLAlchemy 2, SQLite, Alembic-compatible SQL migrations, pytest, httpx, tenacity, existing PPIO/Anthropic provider abstraction.

## Global Constraints

- Marketplace remains fixed to Amazon US.
- `python main.py run` and `pipeline.orchestrator.run_pipeline()` remain backward compatible and deterministic.
- Formal no-mock mode never admits a mock supplier to the candidate pool or exports.
- Missing, mock, stale, inferred, or conflicting critical evidence is never converted to zero, empty text, false, or a business-optimal default.
- New LLM responses are validated by Pydantic-generated JSON Schema before use.
- Every external call has a timeout, bounded retry, cache identity, sanitized logging, and an observable error code.
- Existing SQLite rows and export fields are preserved; schema changes are additive migrations.
- No matching-quality improvement is claimed until reviewed benchmark labels exist.
- Run all test commands with `TEMP=/tmp TMP=/tmp TMPDIR=/tmp` in this WSL workspace.

## Scope Boundary

This plan implements the Phase 1 data-safety foundation and Phase 2 matching-quality vertical slice from the approved design. It intentionally leaves the general Phase 3 finite-state Agent loop, `--mode agent` CLI routing, adjacent-opportunity expansion, checkpoint resume, and Phase 4 WebUI feedback controls for separate plans after this slice establishes reliable interfaces and benchmark evidence.

## File Map

- `schemas/sourcing.py`: canonical Pydantic evidence, understanding, query, match, and recommendation schemas.
- `agent/provenance.py`: evidence construction, freshness, completeness, and critical-gate helpers.
- `db/migrate.py`, `db/migrations/0001_evidence_foundation.sql`: additive migration runner and initial evidence tables.
- `matchers/query_planner.py`: twelve-type de-branded Chinese query generation.
- `matchers/match_evidence.py`: deterministic structured pair comparison and minimum-evidence decision.
- `matchers/vision_analyzer.py`: schema-validated Amazon understanding using text plus all available images.
- `matchers/verifier.py`: safe negative visual semantics and schema-validated pair verification.
- `matchers/alibaba_detail.py`: detail extraction with blocked-page detection and field provenance.
- `matchers/sourcing_slice.py`: bounded search, enrichment, verification, retry, and recommendation coordinator.
- `analyzers/profit_model.py`, `analyzers/scorer.py`: explicit insufficient-evidence behavior for critical costs and market inputs.
- `reports/exporter.py`: additive evidence fields without removing legacy columns.
- `benchmarks/evaluate.py`, `benchmarks/fixtures/sourcing_quality_seed.json`: reviewed-label evaluation harness and seed format.

---

### Task 1: Canonical Evidence and Decision Schemas

**Files:**
- Create: `schemas/__init__.py`
- Create: `schemas/sourcing.py`
- Create: `agent/provenance.py`
- Test: `tests/test_sourcing_schemas.py`

**Interfaces:**
- Consumes: Pydantic 2 from `requirements.txt`.
- Produces: `EvidenceStatus`, `FieldEvidence[T]`, `AmazonProductUnderstanding`, `QueryPlan`, `MatchEvidence`, `RecommendationEvidence`, `RecommendationStatus`, `critical_evidence_gaps()`.

- [ ] **Step 1: Write failing schema and provenance tests**

```python
# tests/test_sourcing_schemas.py
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent.provenance import critical_evidence_gaps, evidence
from schemas.sourcing import EvidenceStatus, MatchEvidence, RecommendationStatus


def test_missing_evidence_cannot_carry_a_value():
    with pytest.raises(ValidationError):
        evidence(value=12.5, status=EvidenceStatus.MISSING, source_provider="1688")


def test_extracted_evidence_requires_source_and_timestamp():
    item = evidence(
        value=12.5,
        status=EvidenceStatus.EXTRACTED,
        source_provider="1688_playwright",
        source_type="offer_detail",
        source_ref="https://detail.1688.com/offer/123.html",
        observed_at=datetime.now(timezone.utc),
        confidence=0.94,
    )
    assert item.value == 12.5
    assert item.status is EvidenceStatus.EXTRACTED


def test_stale_critical_evidence_is_a_gap():
    old = datetime.now(timezone.utc) - timedelta(days=31)
    fields = {
        "price": evidence(
            value=12.5,
            status=EvidenceStatus.EXTRACTED,
            source_provider="1688",
            source_type="offer_detail",
            source_ref="artifact:offer-123",
            observed_at=old,
            expires_at=old + timedelta(days=7),
            confidence=0.9,
        )
    }
    assert critical_evidence_gaps(fields, {"price"}) == ["price:stale"]


def test_negative_visual_classification_cannot_be_a_match():
    result = MatchEvidence(
        amazon_ref="asin:B000TEST",
        supplier_ref="offer:123",
        function_match=0.95,
        accessory_vs_full_product_match=1.0,
        package_quantity_match=1.0,
        visual_is_match=False,
        visual_confidence=0.99,
        mismatch_reasons=["visual_core_function_conflict"],
        decision="reject",
        overall_confidence=0.99,
    )
    assert result.decision == "reject"
    assert result.visual_is_match is False
    assert RecommendationStatus.RECOMMEND.value == "recommend"
```

- [ ] **Step 2: Run the tests and confirm the contract is absent**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_sourcing_schemas.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'schemas'`.

- [ ] **Step 3: Implement the canonical schemas**

```python
# schemas/sourcing.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    STALE = "stale"
    MISSING = "missing"
    MOCK = "mock"
    CONFLICTING = "conflicting"


class FieldEvidence(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")
    value: T | None = None
    status: EvidenceStatus
    source_provider: str
    source_type: str | None = None
    source_ref: str | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction_method: str | None = None
    schema_version: str = "1.0"
    conflict_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.status in {EvidenceStatus.MISSING, EvidenceStatus.MOCK} and self.value is not None:
            raise ValueError(f"{self.status.value} evidence cannot carry a value")
        if self.status in {EvidenceStatus.EXTRACTED, EvidenceStatus.VERIFIED}:
            if not self.source_type or not self.source_ref or self.observed_at is None:
                raise ValueError("extracted or verified evidence requires source metadata")
        return self

    def effective_status(self, now: datetime | None = None) -> EvidenceStatus:
        current = now or datetime.now(timezone.utc)
        if self.expires_at is not None and self.expires_at <= current:
            return EvidenceStatus.STALE
        return self.status


class AmazonProductUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asin: str
    original_title_en: str
    translated_title_cn: str | None = None
    generic_product_name: str
    supply_chain_name_cn: str
    category: str | None = None
    subcategory: str | None = None
    function: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    package_quantity: int | None = Field(default=None, ge=1)
    dimensions_visible: list[str] = Field(default_factory=list)
    target_user: list[str] = Field(default_factory=list)
    use_case: list[str] = Field(default_factory=list)
    replaceable_part_or_full_product: Literal["replacement", "consumable", "full_product", "unknown"]
    distinguishing_features: list[str] = Field(default_factory=list)
    likely_supplier_keywords_cn: list[str] = Field(default_factory=list)
    excluded_brand_tokens: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    model_provider: str
    model_name: str
    prompt_version: str


QueryType = Literal[
    "generic_name", "supply_chain_name", "function", "material", "structure",
    "use_case", "specification", "package_quantity", "replacement_consumable",
    "debranded_description", "factory_synonym", "alibaba_category",
]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    asin: str
    query_type: QueryType
    text: str = Field(min_length=2, max_length=120)
    reason: str
    excluded_brand_tokens: list[str] = Field(default_factory=list)
    source_evidence_refs: list[str] = Field(default_factory=list)
    retry_of: str | None = None


class MatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amazon_ref: str
    supplier_ref: str
    category_match: float | None = Field(default=None, ge=0, le=1)
    function_match: float | None = Field(default=None, ge=0, le=1)
    material_match: float | None = Field(default=None, ge=0, le=1)
    shape_match: float | None = Field(default=None, ge=0, le=1)
    dimension_match: float | None = Field(default=None, ge=0, le=1)
    weight_match: float | None = Field(default=None, ge=0, le=1)
    package_quantity_match: float | None = Field(default=None, ge=0, le=1)
    color_variant_match: float | None = Field(default=None, ge=0, le=1)
    accessory_vs_full_product_match: float | None = Field(default=None, ge=0, le=1)
    target_user_match: float | None = Field(default=None, ge=0, le=1)
    use_case_match: float | None = Field(default=None, ge=0, le=1)
    customization_feasibility: float | None = Field(default=None, ge=0, le=1)
    packaging_feasibility: float | None = Field(default=None, ge=0, le=1)
    image_similarity: float | None = Field(default=None, ge=0, le=1)
    title_semantic_similarity: float | None = Field(default=None, ge=0, le=1)
    specification_similarity: float | None = Field(default=None, ge=0, le=1)
    brand_dependency_risk: float | None = Field(default=None, ge=0, le=1)
    patent_risk: float | None = Field(default=None, ge=0, le=1)
    compliance_risk: float | None = Field(default=None, ge=0, le=1)
    visual_is_match: bool | None = None
    visual_confidence: float | None = Field(default=None, ge=0, le=1)
    overall_confidence: float = Field(ge=0, le=1)
    mismatch_reasons: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    passed_reasons: list[str] = Field(default_factory=list)
    decision: Literal["keep", "reject", "retry", "manual_review"]


class RecommendationStatus(str, Enum):
    RECOMMEND = "recommend"
    WATCHLIST = "watchlist"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    REJECT = "reject"
    INSUFFICIENT_DATA = "insufficient_data"


class RecommendationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asin: str
    supplier_offer_id: str | None = None
    status: RecommendationStatus
    discovery_reason: str
    amazon_completeness: float = Field(ge=0, le=1)
    demand_evidence_refs: list[str] = Field(default_factory=list)
    competition_evidence_refs: list[str] = Field(default_factory=list)
    supplier_match_ref: str | None = None
    confirmed_specs: list[str] = Field(default_factory=list)
    unconfirmed_specs: list[str] = Field(default_factory=list)
    purchase_cost_ref: str | None = None
    logistics_basis: list[str] = Field(default_factory=list)
    profit_basis: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommendation_reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    manual_verification_tasks: list[str] = Field(default_factory=list)
```

```python
# agent/provenance.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from schemas.sourcing import EvidenceStatus, FieldEvidence


def evidence(**kwargs: Any) -> FieldEvidence[Any]:
    return FieldEvidence[Any](**kwargs)


def critical_evidence_gaps(
    fields: dict[str, FieldEvidence[Any]], required: set[str]
) -> list[str]:
    gaps: list[str] = []
    disallowed = {
        EvidenceStatus.MISSING, EvidenceStatus.MOCK, EvidenceStatus.CONFLICTING,
        EvidenceStatus.INFERRED, EvidenceStatus.STALE,
    }
    for name in sorted(required):
        item = fields.get(name)
        if item is None:
            gaps.append(f"{name}:missing")
            continue
        status = item.effective_status()
        if item.value is None or status in disallowed:
            gaps.append(f"{name}:{status.value}")
    return gaps
```

- [ ] **Step 4: Run focused tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_sourcing_schemas.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit the schema contract**

```bash
git add schemas/__init__.py schemas/sourcing.py agent/provenance.py tests/test_sourcing_schemas.py
git commit -m "feat: add sourcing evidence contracts"
```

---

### Task 2: Additive SQLite Migration Foundation

**Files:**
- Create: `db/migrate.py`
- Create: `db/migrations/0001_evidence_foundation.sql`
- Modify: `db/init_db.py`
- Test: `tests/test_db_migrations.py`

**Interfaces:**
- Consumes: `db.session.engine`, SQLite connection URLs.
- Produces: `run_migrations(engine) -> list[str]`, tables `field_evidence`, `query_attempts`, `match_evidence`, `sourcing_recommendations`, and `schema_migrations`.

- [ ] **Step 1: Write migration idempotency and preservation tests**

```python
# tests/test_db_migrations.py
from sqlalchemy import create_engine, inspect, text

from db.migrate import run_migrations


def test_migration_is_additive_idempotent_and_enables_foreign_keys(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, asin TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO products(id, asin) VALUES (1, 'B000KEEP')"))
    assert run_migrations(engine) == ["0001_evidence_foundation"]
    assert run_migrations(engine) == []
    names = set(inspect(engine).get_table_names())
    assert {"field_evidence", "query_attempts", "match_evidence", "sourcing_recommendations"} <= names
    with engine.connect() as conn:
        assert conn.execute(text("SELECT asin FROM products WHERE id=1")).scalar_one() == "B000KEEP"
        assert conn.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
```

- [ ] **Step 2: Run the migration test and confirm failure**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_db_migrations.py -v`

Expected: collection fails because `db.migrate` does not exist.

- [ ] **Step 3: Add the migration SQL**

```sql
-- db/migrations/0001_evidence_foundation.sql
CREATE TABLE IF NOT EXISTS field_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type VARCHAR(40) NOT NULL,
    entity_ref VARCHAR(120) NOT NULL,
    field_name VARCHAR(120) NOT NULL,
    value_json TEXT,
    status VARCHAR(20) NOT NULL,
    source_provider VARCHAR(80) NOT NULL,
    source_type VARCHAR(80),
    source_ref TEXT,
    observed_at TIMESTAMP,
    expires_at TIMESTAMP,
    confidence REAL NOT NULL DEFAULT 0,
    extraction_method VARCHAR(80),
    schema_version VARCHAR(20) NOT NULL DEFAULT '1.0',
    conflict_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('verified','extracted','inferred','stale','missing','mock','conflicting')),
    CHECK (confidence >= 0 AND confidence <= 1)
);
CREATE INDEX IF NOT EXISTS ix_field_evidence_entity ON field_evidence(entity_type, entity_ref);

CREATE TABLE IF NOT EXISTS query_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    query_id VARCHAR(80) NOT NULL,
    query_type VARCHAR(40) NOT NULL,
    query_text VARCHAR(120) NOT NULL,
    reason TEXT NOT NULL,
    excluded_brand_tokens_json TEXT NOT NULL DEFAULT '[]',
    backend VARCHAR(60),
    result_count INTEGER NOT NULL DEFAULT 0,
    relevant_count INTEGER NOT NULL DEFAULT 0,
    retry_of VARCHAR(80),
    status VARCHAR(20) NOT NULL,
    artifact_ref TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, query_id)
);

CREATE TABLE IF NOT EXISTS match_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    offer_id VARCHAR(40) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    overall_confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, asin, offer_id)
);

CREATE TABLE IF NOT EXISTS sourcing_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref VARCHAR(80) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    offer_id VARCHAR(40),
    status VARCHAR(30) NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_ref, asin, offer_id)
);
```

- [ ] **Step 4: Implement the migration runner and wire initialization**

```python
# db/migrate.py
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, event, text

MIGRATIONS = Path(__file__).with_name("migrations")


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.dialect.name != "sqlite" or getattr(engine, "_fk_listener", False):
        return
    @event.listens_for(engine, "connect")
    def set_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    setattr(engine, "_fk_listener", True)


def run_migrations(engine: Engine) -> list[str]:
    _enable_sqlite_foreign_keys(engine)
    applied_now: list[str] = []
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            if conn.execute(text("PRAGMA integrity_check")).scalar_one() != "ok":
                raise RuntimeError("database integrity_check failed")
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(120) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = set(conn.execute(text("SELECT version FROM schema_migrations")).scalars())
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            raw = path.read_text(encoding="utf-8")
            for statement in (part.strip() for part in raw.split(";")):
                if statement:
                    conn.exec_driver_sql(statement)
            conn.execute(text("INSERT INTO schema_migrations(version) VALUES (:version)"), {"version": version})
            applied_now.append(version)
    return applied_now
```

Replace `db/init_db.py` with:

```python
"""Initialize legacy tables and apply additive migrations."""
from loguru import logger

from db.migrate import run_migrations
from db.models import Base
from db.session import engine


def init_db() -> None:
    logger.info(f"Creating tables at {engine.url}")
    Base.metadata.create_all(engine)
    applied = run_migrations(engine)
    logger.info(f"Database ready; migrations_applied={applied}")


if __name__ == "__main__":
    init_db()
```

- [ ] **Step 5: Run migration and legacy initialization tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_db_migrations.py tests/test_crawlers.py -v`

Expected: all selected tests pass, and the migration test reports one applied version on first run and none on second run.

- [ ] **Step 6: Commit the additive migration**

```bash
git add db/migrate.py db/migrations/0001_evidence_foundation.sql db/init_db.py tests/test_db_migrations.py
git commit -m "feat: add evidence database migration"
```

---

### Task 3: Fix Negative Visual Semantics and Remove Match Fallback Admission

**Files:**
- Modify: `matchers/verifier.py`
- Modify: `tests/test_vision_matcher.py`
- Modify: `tests/test_verifier_spec_match.py`

**Interfaces:**
- Consumes: existing `LLMVisualVerifier.verify()` and `Alibaba1688Verifier.verify()` callers.
- Produces: negative classifications with score `0`, explicit rejection metadata, and no automatic re-admission of rejected suppliers.

- [ ] **Step 1: Add regression tests for the audited false-positive path**

```python
# append to tests/test_vision_matcher.py
from types import SimpleNamespace


def test_high_confidence_negative_is_rejected(monkeypatch):
    product = SimpleNamespace(main_image_url="https://amazon/image.jpg")
    supplier = SupplierDTO(
        alibaba_offer_id="negative", supplier_name="整机供应商",
        offer_image_url="https://1688/image.jpg", match_quality_score=0.8,
    )
    verifier = LLMVisualVerifier(api_key="test", api_base="https://example.invalid", model="test")
    monkeypatch.setattr(
        verifier,
        "_compare_images",
        lambda *_: {"is_match": False, "confidence": 0.99, "reason": "整机与替换滤芯", "differences": ["功能不同"]},
    )
    result = verifier.verify([supplier], product, threshold=0.3)
    assert result == []
    assert supplier.match_quality_score == 0.0
    assert supplier.raw_data["visual_match"]["decision"] == "reject"


# append to tests/test_verifier_spec_match.py
def test_all_low_quality_suppliers_are_not_reintroduced():
    supplier = SupplierDTO(
        alibaba_offer_id="irrelevant", supplier_name="无关工厂",
        title_cn="完全无关的工业轴承", base_price_cny=10,
    )
    result = Alibaba1688Verifier(threshold_demote=0.4).verify(
        [supplier], _product(), analysis=_analysis(), search_keywords=["瑜伽垫"]
    )
    assert result == []
    assert supplier.match_verification_method == "heuristic_rejected"
```

- [ ] **Step 2: Run both regression tests and observe current failures**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_vision_matcher.py tests/test_verifier_spec_match.py -v`

Expected: the high-confidence negative remains admitted and the heuristic fallback returns a rejected supplier.

- [ ] **Step 3: Implement rejection semantics**

In `LLMVisualVerifier.verify()`, replace score blending with this classification-aware branch:

```python
if not is_match:
    sup.match_quality_score = 0.0
    sup.match_verification_method = "llm_rejected"
else:
    old_score = sup.match_quality_score if sup.match_quality_score is not None else 0.0
    sup.match_quality_score = round(0.6 * float(llm_score) + 0.4 * old_score, 4)
    sup.match_verification_method = "llm"
sup.raw_data["visual_match"] = {
    "score": float(llm_score) if is_match else 0.0,
    "classification_confidence": float(llm_score),
    "source": "llm",
    "is_match": bool(is_match),
    "decision": "keep" if is_match else "reject",
    "reason": result.get("reason"),
    "differences": result.get("differences") or [],
}
```

Delete both `ranked[:3]` fallback branches. Mark low-quality suppliers `heuristic_rejected` or `llm_rejected`, return only suppliers above threshold, and let callers surface manual-review evidence separately.

- [ ] **Step 4: Run all verifier tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_vision_matcher.py tests/test_verifier_spec_match.py tests/test_product_spec.py -v`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the safety fix**

```bash
git add matchers/verifier.py tests/test_vision_matcher.py tests/test_verifier_spec_match.py
git commit -m "fix: reject negative supplier matches"
```

---

### Task 4: Make Critical Profit and Scoring Inputs Explicitly Insufficient

**Files:**
- Modify: `analyzers/profit_model.py`
- Modify: `analyzers/scorer.py`
- Modify: `pipeline/orchestrator.py`
- Test: `tests/test_profit_model.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: product/supplier DTOs and existing scoring configuration.
- Produces: `InsufficientCostEvidence`, `ScoringEvidenceError`, rejection reasons `missing_purchase_price`, `missing_logistics_dimensions`, `missing_market_evidence`, `missing_moq`.

- [ ] **Step 1: Write tests that reject optimistic defaults**

```python
# append to tests/test_profit_model.py
import pytest
from analyzers.profit_model import InsufficientCostEvidence, calc_purchase_cost, calc_shipping_cost


def test_purchase_cost_requires_real_price():
    params = profit_model.load_profit_params()
    supplier = _MockSupplier(base_price_cny=None, price_tiers=[])
    with pytest.raises(InsufficientCostEvidence, match="purchase_price"):
        calc_purchase_cost(supplier, 200, params)


def test_shipping_requires_weight_and_dimensions():
    params = profit_model.load_profit_params()
    product = _MockProduct(weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
    with pytest.raises(InsufficientCostEvidence, match="weight_kg"):
        calc_shipping_cost(product, params)


# append to tests/test_scoring.py
def test_missing_competition_data_is_not_best_competition():
    curve = load_weights_config()["scoring_curves"]["competition"]
    with pytest.raises(ScoringEvidenceError, match="competition"):
        score_competition(None, None, curve)
```

- [ ] **Step 2: Run the focused tests and confirm current optimistic behavior**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py -v`

Expected: new tests fail because missing price becomes `0`, shipping uses `0.5kg`, and missing competition receives a high score.

- [ ] **Step 3: Implement explicit errors and orchestration handling**

```python
# analyzers/profit_model.py
class InsufficientCostEvidence(ValueError):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__("missing cost evidence: " + ",".join(fields))
```

Change `calc_purchase_cost()` to raise `InsufficientCostEvidence(["purchase_price"])` when neither an applicable normalized tier nor `base_price_cny` exists. Normalize tier keys through a helper that accepts legacy `{qty, price}` and extracted `{min_qty, price_cny}` but returns `None` for malformed tiers.

Change `calc_shipping_cost()` and `calc_fba_fee()` to require `weight_kg`, `length_cm`, `width_cm`, and `height_cm`; raise `InsufficientCostEvidence` listing the missing fields instead of substituting standard-size defaults.

```python
# analyzers/scorer.py
class ScoringEvidenceError(ValueError):
    def __init__(self, dimension: str, fields: list[str]):
        self.dimension = dimension
        self.fields = fields
        super().__init__(f"missing {dimension} evidence: {','.join(fields)}")
```

At the start of `score_competition()`, raise when both `competing_listings` and `top10_share` are `None`. In `score_supply()`, require at least one non-mock supplier with extracted price and MOQ. In `score_logistics()`, require all four physical fields.

In `pipeline/orchestrator.py`, catch these typed exceptions per product, append their field names to `PipelineRecord.rejection_reasons`, leave profit/score snapshots absent, and export the item only as review/insufficient evidence when `export_review_on_empty=True`.

- [ ] **Step 4: Run profit, scoring, pipeline, and exporter regression tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_profit_model.py tests/test_scoring.py tests/test_pipeline_review_fallback.py tests/test_exporter_spec_match.py -v`

Expected: all selected tests pass and no assertion expects missing inputs to create an optimistic score.

- [ ] **Step 5: Commit the critical evidence gates**

```bash
git add analyzers/profit_model.py analyzers/scorer.py pipeline/orchestrator.py tests/test_profit_model.py tests/test_scoring.py
git commit -m "fix: gate scoring on critical evidence"
```

---

### Task 5: Amazon Detail, Buy Box, and Market Evidence Enrichment

**Files:**
- Modify: `crawlers/_amazon_extractors.py`
- Modify: `crawlers/amazon_search.py`
- Modify: `analyzers/maijiajingling.py`
- Test: `tests/test_amazon_detail_evidence.py`
- Test: `tests/test_maijiajingling.py`

**Interfaces:**
- Consumes: Amazon US detail/search HTML and SellerSprite API responses.
- Produces: `extract_amazon_detail(page) -> dict[str, FieldEvidence]`, coupon/variation/buy-box/package/listing evidence, and market result states that distinguish success, partial, auth failure, and missing data.

- [ ] **Step 1: Write Amazon field-provenance and market-failure tests**

```python
# tests/test_amazon_detail_evidence.py
from crawlers._amazon_extractors import extract_amazon_detail


class FakePage:
    def __init__(self, texts=None, attrs=None, rows=None, text_lists=None):
        self.texts = texts or {}
        self.attrs = attrs or {}
        self.rows = rows or {}
        self.text_lists = text_lists or {}

    def text(self, selector):
        return self.texts.get(selector)

    def attr(self, selector, name):
        return self.attrs.get((selector, name))

    def table_row(self, label):
        return self.rows.get(label)

    def text_all(self, selector):
        return self.text_lists.get(selector, [])


def test_detail_keeps_buybox_coupon_package_and_secondary_images():
    page = FakePage(
        texts={
            "#productTitle": "Four Replacement Water Filters",
            "#corePrice_feature_div .a-offscreen": "$29.99",
            "#couponTextpctch": "Save 10% with coupon",
            "#merchant-info": "Ships from Amazon.com Sold by Filter Store",
            "#availability": "In Stock",
        },
        attrs={
            ("#landingImage", "src"): "https://img/main.jpg",
            ("#landingImage", "data-a-dynamic-image"): '{"https://img/main.jpg":[1000,1000]}',
            ("#altImages", "data-secondary-images"): '["https://img/2.jpg"]',
        },
        rows={
            "Brand Name": "Acme", "Item Weight": "1.2 pounds",
            "Product Dimensions": "10 x 8 x 4 inches", "Package Dimensions": "11 x 9 x 5 inches",
            "Best Sellers Rank": "#1,234 in Home & Kitchen", "Number of Items": "4",
            "Material": "Activated Carbon", "Date First Available": "January 2, 2025",
        },
    )
    detail = extract_amazon_detail(page, source_ref="artifact:amazon-B000TEST")
    assert detail["price"].value == 29.99
    assert detail["coupon"].value == "Save 10% with coupon"
    assert detail["package_quantity"].value == 4
    assert detail["package_dimensions"].value is not None
    assert detail["secondary_images"].value == ["https://img/2.jpg"]
    assert detail["price"].status.value == "extracted"
    assert detail["variation_price"].value is None
    assert detail["variation_price"].status.value == "missing"


def test_missing_buybox_fields_remain_missing():
    detail = extract_amazon_detail(FakePage(), source_ref="artifact:empty")
    assert detail["seller_count"].value is None
    assert detail["seller_count"].status.value == "missing"
    assert detail["fulfillment"].value is None
```

Append to `tests/test_maijiajingling.py`:

```python
def test_invalid_key_is_failed_evidence_not_empty_market(monkeypatch):
    client = MaijiajinglingClient(api_key="invalid")
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: (_ for _ in ()).throw(MarketDataError("AUTH_REQUIRED", "invalid key")))
    result = client.analyze_market_evidence("B000TEST", marketplace="US", keyword="water filter")
    assert result.status == "failed"
    assert result.error_code == "AUTH_REQUIRED"
    assert result.data is None


def test_partial_market_result_lists_missing_fields(monkeypatch):
    client = MaijiajinglingClient(api_key="test")
    monkeypatch.setattr(client, "analyze_market", lambda *args, **kwargs: MarketAnalysisDTO(asin="B000TEST", est_monthly_sales=500))
    result = client.analyze_market_evidence("B000TEST", marketplace="US", keyword="water filter")
    assert result.status == "partial"
    assert "competing_listings" in result.missing_fields
    assert "search_volume_monthly" in result.missing_fields
```

- [ ] **Step 2: Run tests and confirm missing extractors/status contracts**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_amazon_detail_evidence.py tests/test_maijiajingling.py -v`

Expected: tests fail because `extract_amazon_detail()`, `MarketDataError`, and `analyze_market_evidence()` do not exist.

- [ ] **Step 3: Implement field-level Amazon extraction**

Add small selector helpers for coupon, discount/list price, variation price range, availability, seller/buy-box text, fulfillment, package quantity, material, product and package dimensions, secondary images, bullets, description, A+ presence, and first-available date. Compose them without changing existing individual extractor signatures:

```python
# crawlers/_amazon_extractors.py
from datetime import datetime, timedelta, timezone

from agent.provenance import evidence
from schemas.sourcing import EvidenceStatus


def _field(value, name: str, source_ref: str, confidence: float = 0.9):
    if value is None or value == "" or value == []:
        return evidence(
            value=None, status=EvidenceStatus.MISSING, source_provider="amazon_us",
            source_type="product_detail", source_ref=source_ref,
            confidence=0.0, extraction_method=name,
        )
    now = datetime.now(timezone.utc)
    return evidence(
        value=value, status=EvidenceStatus.EXTRACTED, source_provider="amazon_us",
        source_type="product_detail", source_ref=source_ref, observed_at=now,
        expires_at=now + timedelta(days=1), confidence=confidence,
        extraction_method=name,
    )


def extract_amazon_detail(page: PageLike, source_ref: str) -> dict:
    weight_kg, length_cm, width_cm, height_cm = extract_dimensions(page)
    package_dimensions = _parse_dimensions_from_text(page.table_row("Package Dimensions") or "")
    return {
        "title": _field(extract_title(page), "title_selector", source_ref),
        "brand": _field(extract_brand(page), "brand_table_or_selector", source_ref),
        "price": _field(extract_price(page), "price_selector", source_ref),
        "coupon": _field(page.text("#couponTextpctch"), "coupon_selector", source_ref),
        "discount": _field(page.text(".savingsPercentage"), "discount_selector", source_ref),
        "variation_price": _field(_extract_variation_price(page), "variation_price", source_ref),
        "bsr": _field(extract_bsr(page), "bsr_table_or_selector", source_ref),
        "rating": _field(extract_rating(page), "rating_selector", source_ref),
        "review_count": _field(extract_reviews(page), "review_selector", source_ref),
        "weight_kg": _field(weight_kg, "weight_table", source_ref),
        "product_dimensions": _field((length_cm, width_cm, height_cm) if length_cm else None, "dimensions_table", source_ref),
        "package_dimensions": _field(package_dimensions, "package_dimensions_table", source_ref),
        "package_quantity": _field(_parse_int(page.table_row("Number of Items") or ""), "package_quantity_table", source_ref),
        "material": _field(page.table_row("Material"), "material_table", source_ref),
        "seller_count": _field(_extract_seller_count(page), "seller_count", source_ref),
        "fulfillment": _field(_extract_fulfillment(page), "buybox_fulfillment", source_ref),
        "availability": _field(page.text("#availability"), "availability_selector", source_ref),
        "main_image": _field(extract_image(page), "main_image_selector", source_ref),
        "secondary_images": _field(_extract_secondary_images(page), "secondary_images", source_ref),
        "bullet_points": _field(page.text_all("#feature-bullets li"), "bullet_selectors", source_ref),
        "description": _field(page.text("#productDescription"), "description_selector", source_ref),
        "a_plus": _field(bool(page.text("#aplus")) or None, "a_plus_selector", source_ref),
        "first_available_date": _field(page.table_row("Date First Available"), "available_date_table", source_ref),
    }
```

Implement the referenced private helpers beside existing parsing helpers. `extract_amazon_detail()` must always return all keys, even when missing. `amazon_search.py` copies values into legacy DTO fields only when status is extracted/verified and stores the full evidence objects under `raw_data["field_evidence"]`.

- [ ] **Step 4: Implement explicit SellerSprite result status**

```python
# analyzers/maijiajingling.py
@dataclass
class MarketEvidenceResult:
    status: str
    data: MarketAnalysisDTO | None
    missing_fields: list[str] = field(default_factory=list)
    error_code: str | None = None
    diagnostic: str | None = None


class MarketDataError(RuntimeError):
    def __init__(self, error_code: str, diagnostic: str):
        self.error_code = error_code
        self.diagnostic = diagnostic
        super().__init__(f"{error_code}: {diagnostic}")


    # Add this method inside MaijiajinglingClient.
    def analyze_market_evidence(self, asin: str, marketplace: str = "US", keyword: str | None = None) -> MarketEvidenceResult:
        try:
            data = self.analyze_market(asin, marketplace=marketplace, keyword=keyword)
        except MarketDataError as exc:
            return MarketEvidenceResult(status="failed", data=None, error_code=exc.error_code, diagnostic=exc.diagnostic)
        required = ("est_monthly_sales", "competing_listings", "search_volume_monthly", "top10_revenue_share")
        missing = [name for name in required if getattr(data, name, None) is None]
        return MarketEvidenceResult(status="partial" if missing else "success", data=data, missing_fields=missing)
```

Map HTTP 401/403 and invalid-key payloads to `AUTH_REQUIRED`, 429 to `RATE_LIMITED`, timeouts to `TIMEOUT`, and structurally invalid successful responses to `MISSING_REQUIRED_DATA`. Retain endpoint, response timestamp, and sanitized response hash in `raw_data`; never log the API key.

- [ ] **Step 5: Run Amazon, market, crawler, and scoring tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_amazon_detail_evidence.py tests/test_amazon_search.py tests/test_crawlers.py tests/test_maijiajingling.py tests/test_seller_sprite_diagnostics.py tests/test_scoring.py -v`

Expected: all selected tests pass; invalid credentials and partial market data cannot masquerade as complete evidence.

- [ ] **Step 6: Commit Amazon and market evidence enrichment**

```bash
git add crawlers/_amazon_extractors.py crawlers/amazon_search.py analyzers/maijiajingling.py tests/test_amazon_detail_evidence.py tests/test_maijiajingling.py
git commit -m "feat: enrich Amazon and market evidence"
```

---

### Task 6: Structured Amazon Product Understanding

**Files:**
- Modify: `matchers/vision_analyzer.py`
- Create: `matchers/product_understanding.py`
- Test: `tests/test_product_understanding.py`

**Interfaces:**
- Consumes: Amazon title, bullets, description, structured attributes, main image, secondary images, provider abstraction.
- Produces: `understand_amazon_product(product, analyzer) -> AmazonProductUnderstanding` and prompt/model/cache metadata.

- [ ] **Step 1: Write tests for all-image input, brand exclusion, and schema rejection**

```python
# tests/test_product_understanding.py
from types import SimpleNamespace

import pytest

from matchers.product_understanding import ProductUnderstandingError, understand_amazon_product


class FakeAnalyzer:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def analyze_product(self, payload):
        self.requests.append(payload)
        return self.response


def _product():
    return SimpleNamespace(
        asin="B000TEST", title="Acme replacement filter four pack", brand="Acme",
        main_image_url="https://img/1.jpg",
        raw_data={
            "bullet_points": ["Replacement filter, pack of 4"],
            "description": "Fits countertop water machine",
            "secondary_images": ["https://img/2.jpg", "https://img/3.jpg"],
        },
    )


def _response():
    return {
        "asin": "B000TEST", "original_title_en": "Acme replacement filter four pack",
        "generic_product_name": "water filter", "supply_chain_name_cn": "净水器替换滤芯",
        "function": ["过滤饮用水"], "material": ["活性炭"], "components": ["滤芯"],
        "package_quantity": 4, "replaceable_part_or_full_product": "replacement",
        "excluded_brand_tokens": ["Acme"], "model_provider": "fake",
        "model_name": "fake-v1", "prompt_version": "amazon-understanding-v1",
    }


def test_understanding_uses_text_main_and_secondary_images():
    product = _product()
    analyzer = FakeAnalyzer(_response())
    result = understand_amazon_product(product, analyzer)
    request = analyzer.requests[0]
    assert request["image_urls"] == [product.main_image_url, "https://img/2.jpg", "https://img/3.jpg"]
    assert "Acme" in result.excluded_brand_tokens
    assert result.replaceable_part_or_full_product == "replacement"
    assert result.package_quantity == 4


def test_invalid_model_json_is_not_silently_coerced():
    analyzer = FakeAnalyzer({"generic_product_name": "filter"})
    with pytest.raises(ProductUnderstandingError, match="schema_validation"):
        understand_amazon_product(_product(), analyzer)
```

- [ ] **Step 2: Run tests and confirm the current analyzer is main-image-only**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py -v`

Expected: collection fails because `matchers.product_understanding` does not exist.

- [ ] **Step 3: Add the understanding adapter and update the provider-neutral prompt**

Implement `understand_amazon_product()` to construct one request containing textual evidence and at most five deduplicated images. It must call a new `VisionAnalyzer.analyze_product(payload: dict)`, validate the response as `AmazonProductUnderstanding`, and set `model_provider`, `model_name`, and `prompt_version="amazon-understanding-v1"` from the actual provider.

The prompt must request every `AmazonProductUnderstanding` field, distinguish replacement/consumable/full product, infer no invisible dimension, state uncertainty, and retain brand solely in `excluded_brand_tokens`. The cache key must hash prompt version, provider, model, normalized text payload, and all image bytes; the old image-only cache key must not be reused.

```python
# matchers/product_understanding.py
class ProductUnderstandingError(RuntimeError):
    pass


def product_image_urls(product) -> list[str]:
    raw = product.raw_data if isinstance(product.raw_data, dict) else {}
    urls = [getattr(product, "main_image_url", None), *(raw.get("secondary_images") or [])]
    return list(dict.fromkeys(url for url in urls if isinstance(url, str) and url.startswith("http")))[:5]


def understand_amazon_product(product, analyzer) -> AmazonProductUnderstanding:
    raw = product.raw_data if isinstance(product.raw_data, dict) else {}
    payload = {
        "asin": product.asin,
        "title": product.title,
        "brand": getattr(product, "brand", None),
        "bullet_points": raw.get("bullet_points") or [],
        "description": raw.get("description"),
        "attributes": raw.get("attributes") or {},
        "image_urls": product_image_urls(product),
    }
    try:
        return AmazonProductUnderstanding.model_validate(analyzer.analyze_product(payload))
    except Exception as exc:
        raise ProductUnderstandingError(f"schema_validation: {exc}") from exc
```

- [ ] **Step 4: Run understanding and legacy vision tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_product_understanding.py tests/test_vision_matcher.py tests/test_matcher_keywords.py -v`

Expected: all selected tests pass; existing `VisionAnalyzer.analyze()` remains available for deterministic compatibility.

- [ ] **Step 5: Commit structured understanding**

```bash
git add matchers/vision_analyzer.py matchers/product_understanding.py tests/test_product_understanding.py
git commit -m "feat: add structured Amazon understanding"
```

---

### Task 7: Twelve-Type De-branded Query Planning

**Files:**
- Create: `matchers/query_planner.py`
- Test: `tests/test_query_planner.py`

**Interfaces:**
- Consumes: `AmazonProductUnderstanding`.
- Produces: `generate_query_plan(understanding: AmazonProductUnderstanding) -> list[QueryPlan]`, `rewrite_low_relevance_queries(understanding: AmazonProductUnderstanding, queries: list[QueryPlan], hit_rates: dict[str, float], iteration: int) -> list[QueryPlan]`.

- [ ] **Step 1: Write coverage and brand-safety tests**

```python
# tests/test_query_planner.py
from matchers.query_planner import QUERY_TYPES, generate_query_plan, rewrite_low_relevance_queries
from schemas.sourcing import AmazonProductUnderstanding


def _understanding():
    return AmazonProductUnderstanding(
        asin="B000TEST", original_title_en="Acme A-100 four pack filters",
        generic_product_name="净水滤芯", supply_chain_name_cn="净水器替换滤芯",
        category="净水设备配件", function=["过滤饮用水"], material=["活性炭"],
        components=["滤芯外壳"], package_quantity=4, use_case=["厨房净水"],
        replaceable_part_or_full_product="replacement",
        likely_supplier_keywords_cn=["滤芯厂家", "净水耗材"],
        excluded_brand_tokens=["Acme", "A-100"], model_provider="fake",
        model_name="fake-v1", prompt_version="amazon-understanding-v1",
    )


def test_query_plan_covers_all_twelve_types():
    understanding = _understanding()
    queries = generate_query_plan(understanding)
    assert {q.query_type for q in queries} == set(QUERY_TYPES)
    assert all(q.reason and q.source_evidence_refs for q in queries)


def test_queries_exclude_brand_tokens_case_insensitively():
    understanding = _understanding()
    queries = generate_query_plan(understanding)
    joined = " ".join(q.text.casefold() for q in queries)
    assert "acme" not in joined
    assert "a-100" not in joined


def test_low_relevance_rewrite_is_bounded_and_lineaged():
    understanding = _understanding()
    initial = generate_query_plan(understanding)
    rewritten = rewrite_low_relevance_queries(understanding, initial, {initial[0].query_id: 0.0}, iteration=1)
    assert rewritten
    assert all(q.retry_of for q in rewritten)
    assert rewrite_low_relevance_queries(understanding, initial, {}, iteration=3) == []
```

- [ ] **Step 2: Run tests and confirm planner absence**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_query_planner.py -v`

Expected: collection fails because `matchers.query_planner` does not exist.

- [ ] **Step 3: Implement deterministic query construction**

```python
# matchers/query_planner.py
from __future__ import annotations

import hashlib
import re

from schemas.sourcing import AmazonProductUnderstanding, QueryPlan

QUERY_TYPES = (
    "generic_name", "supply_chain_name", "function", "material", "structure",
    "use_case", "specification", "package_quantity", "replacement_consumable",
    "debranded_description", "factory_synonym", "alibaba_category",
)


def _clean(text: str, excluded: list[str]) -> str:
    value = text
    for token in sorted(excluded, key=len, reverse=True):
        value = re.sub(re.escape(token), " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" ,，-/")[:120]


def _query_id(asin: str, query_type: str, text: str, retry_of: str | None = None) -> str:
    raw = f"{asin}|{query_type}|{text}|{retry_of or ''}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def generate_query_plan(u: AmazonProductUnderstanding) -> list[QueryPlan]:
    material = " ".join(u.material[:2])
    function = " ".join(u.function[:2])
    structure = " ".join(u.components[:3])
    use_case = " ".join(u.use_case[:2])
    spec = " ".join(u.dimensions_visible[:2])
    pack = f"{u.package_quantity}件套" if u.package_quantity else u.generic_product_name
    relation = {
        "replacement": "替换件",
        "consumable": "耗材",
        "full_product": "整机",
        "unknown": "",
    }[u.replaceable_part_or_full_product]
    values = {
        "generic_name": u.generic_product_name,
        "supply_chain_name": u.supply_chain_name_cn,
        "function": f"{function} {u.generic_product_name}",
        "material": f"{material} {u.generic_product_name}",
        "structure": f"{structure} {u.generic_product_name}",
        "use_case": f"{use_case} {u.generic_product_name}",
        "specification": f"{spec} {u.generic_product_name}",
        "package_quantity": f"{pack} {u.generic_product_name}",
        "replacement_consumable": f"{relation} {u.supply_chain_name_cn}",
        "debranded_description": f"{material} {function} {structure} {u.generic_product_name}",
        "factory_synonym": " ".join(u.likely_supplier_keywords_cn[:3]) or u.supply_chain_name_cn,
        "alibaba_category": f"1688 {u.category or ''} {u.supply_chain_name_cn}",
    }
    result = []
    for query_type in QUERY_TYPES:
        text = _clean(values[query_type], u.excluded_brand_tokens)
        result.append(QueryPlan(
            query_id=_query_id(u.asin, query_type, text), asin=u.asin,
            query_type=query_type, text=text,
            reason=f"derive {query_type} query from structured Amazon evidence",
            excluded_brand_tokens=u.excluded_brand_tokens,
            source_evidence_refs=[f"understanding:{u.asin}:{u.prompt_version}"],
        ))
    return result


def rewrite_low_relevance_queries(u, queries, hit_rates, iteration):
    if iteration > 2:
        return []
    output = []
    for query in queries:
        if hit_rates.get(query.query_id, 1.0) >= 0.2:
            continue
        text = _clean(f"{u.supply_chain_name_cn} {u.generic_product_name}", u.excluded_brand_tokens)
        output.append(query.model_copy(update={
            "query_id": _query_id(u.asin, query.query_type, text, query.query_id),
            "text": text, "retry_of": query.query_id,
            "reason": f"rewrite low-relevance {query.query_type} query at iteration {iteration}",
        }))
    return output
```

- [ ] **Step 4: Run planner tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_query_planner.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit query planning**

```bash
git add matchers/query_planner.py tests/test_query_planner.py
git commit -m "feat: generate supply chain query plans"
```

---

### Task 8: Safe 1688 Offer Detail Extraction and Provenance

**Files:**
- Modify: `matchers/alibaba_detail.py`
- Modify: `matchers/_alibaba_playwright_search.py`
- Modify: `matchers/alibaba_result_cache.py`
- Test: `tests/test_alibaba_detail.py`
- Test: `tests/test_alibaba_playwright_detail.py`

**Interfaces:**
- Consumes: real offer page HTML/JSON and existing browser session.
- Produces: `OfferDetailResult`, `BlockedOfferPage`, source timestamps, cache freshness, tier/MOQ/SKU/material/size/weight/package/origin/lead-time/customization/supplier/certification evidence.

- [ ] **Step 1: Add blocked-page, tier, and non-default MOQ tests**

```python
# append to tests/test_alibaba_detail.py
import pytest
from matchers.alibaba_detail import BlockedOfferPage, parse_1688_offer_detail_html


def test_login_page_is_not_parsed_as_offer():
    html = '<html><title>登录</title><body>请登录后继续访问 验证码</body></html>'
    with pytest.raises(BlockedOfferPage, match="AUTH_REQUIRED"):
        parse_1688_offer_detail_html(html)


def test_detail_preserves_real_tiers_and_moq():
    html = '''<script>{"offerId":"123","priceRangeList":[
      {"startQuantity":20,"price":12.8},{"startQuantity":100,"price":10.5}],
      "beginAmount":20,"attributes":[{"name":"材质","value":"304不锈钢"}]}</script>'''
    result = parse_1688_offer_detail_html(html)
    assert result["moq"] == 20
    assert result["price_tiers"] == [
        {"min_qty": 20, "price_cny": 12.8},
        {"min_qty": 100, "price_cny": 10.5},
    ]
    assert result["material"] == "不锈钢"
    assert result["provenance"]["moq"]["status"] == "extracted"


def test_absent_moq_remains_missing():
    result = parse_1688_offer_detail_html('<html><body>普通商品详情</body></html>')
    assert result["moq"] is None
    assert result["provenance"]["moq"]["status"] == "missing"
```

- [ ] **Step 2: Run detail tests and confirm missing provenance/block detection**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py -v`

Expected: the new tests fail because blocked pages are parsed and absent keys are removed.

- [ ] **Step 3: Implement safe parsing and cache freshness**

Add the typed exception below and check status markers before parsing: login markers map to `AUTH_REQUIRED`, captcha/slider markers map to `CAPTCHA`, and rate-control markers map to `RATE_LIMITED`. Require either an offer-id marker or at least two product-detail markers before treating the page as an offer.

```python
class BlockedOfferPage(RuntimeError):
    def __init__(self, error_code: str, diagnostic: str):
        self.error_code = error_code
        self.diagnostic = diagnostic
        super().__init__(f"{error_code}: {diagnostic}")
```

Return every required field explicitly with `None` plus a `provenance` mapping. Extract SKU/specification images, detail images, packaging, origin, customization, supplier type/years/location, transactions, certifications, and return/dispute indicators from structured JSON before using text regex. Every extracted field records `status`, `source_type="offer_detail"`, `observed_at`, `confidence`, and artifact hash.

In `_alibaba_playwright_search.py`, reuse its browser context for details, apply one detail request at a time with configurable 1.5–3.0 second jitter, retry only timeout/rate-limit errors twice with exponential backoff, and propagate auth/captcha as a human-handoff result. Do not create a `SupplierDTO` from blocked HTML.

In `alibaba_result_cache.py`, include `observed_at`, `expires_at`, and `blocked=False` in cached detail entries. Refuse cached records whose `expires_at` has elapsed or whose schema version differs.

- [ ] **Step 4: Run all 1688 detail and cache tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py tests/test_alibaba_result_cache.py tests/test_alibaba_diagnostics.py -v`

Expected: all selected tests pass; blocked fixtures yield typed errors and absent MOQ remains `None`.

- [ ] **Step 5: Commit safe detail extraction**

```bash
git add matchers/alibaba_detail.py matchers/_alibaba_playwright_search.py matchers/alibaba_result_cache.py tests/test_alibaba_detail.py tests/test_alibaba_playwright_detail.py
git commit -m "feat: extract verified 1688 offer details"
```

---

### Task 9: Structured Match Evidence and Minimum Evidence Threshold

**Files:**
- Create: `matchers/match_evidence.py`
- Test: `tests/test_match_evidence.py`

**Interfaces:**
- Consumes: `AmazonProductUnderstanding`, enriched `SupplierDTO`, optional visual result.
- Produces: `build_match_evidence(understanding: AmazonProductUnderstanding, supplier: SupplierDTO, visual: dict | None = None) -> MatchEvidence`, deterministic hard mismatch rules, and explicit missing evidence.

- [ ] **Step 1: Write hard-negative and missing-evidence tests**

```python
# tests/test_match_evidence.py
from matchers.alibaba_pailitao import SupplierDTO
from matchers.match_evidence import build_match_evidence
from schemas.sourcing import AmazonProductUnderstanding


def _understanding():
    return AmazonProductUnderstanding(
        asin="B000TEST", original_title_en="four replacement filters",
        generic_product_name="净水滤芯", supply_chain_name_cn="净水器替换滤芯",
        category="净水设备配件", function=["过滤饮用水"], material=["活性炭"],
        components=["滤芯"], package_quantity=4,
        replaceable_part_or_full_product="replacement", model_provider="fake",
        model_name="fake-v1", prompt_version="amazon-understanding-v1",
    )


def _supplier(detail):
    return SupplierDTO(
        alibaba_offer_id="123", title_cn="活性炭净水器替换滤芯",
        base_price_cny=12.5, moq=20, raw_data={"detail": detail},
    )


def test_replacement_filter_does_not_match_full_machine():
    understanding = _understanding()
    supplier = _supplier({"product_type": "full_product", "package_quantity": 4, "function": "过滤饮用水", "base_price_cny": 12.5, "moq": 20})
    supplier.raw_data["detail"] = {"product_type": "full_product", "package_quantity": 1}
    result = build_match_evidence(understanding, supplier)
    assert result.decision == "reject"
    assert "accessory_full_product_conflict" in result.mismatch_reasons


def test_single_item_does_not_match_four_pack():
    understanding = _understanding()
    supplier = _supplier({"product_type": "replacement", "package_quantity": 1, "function": "过滤饮用水", "base_price_cny": 12.5, "moq": 20})
    result = build_match_evidence(understanding, supplier)
    assert result.decision == "reject"
    assert "package_quantity_conflict" in result.mismatch_reasons


def test_missing_function_and_pack_cannot_receive_high_confidence():
    understanding = _understanding()
    supplier = _supplier({})
    result = build_match_evidence(understanding, supplier)
    assert result.decision in {"retry", "manual_review"}
    assert result.overall_confidence <= 0.49
    assert {"function", "package_quantity"} <= set(result.missing_evidence)
```

- [ ] **Step 2: Run tests and confirm matcher absence**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_match_evidence.py -v`

Expected: collection fails because `matchers.match_evidence` does not exist.

- [ ] **Step 3: Implement structured comparison with hard mismatch precedence**

```python
# matchers/match_evidence.py
from __future__ import annotations

from statistics import mean

from matchers.product_spec import compare_specs, spec_from_supplier, spec_from_text
from schemas.sourcing import AmazonProductUnderstanding, MatchEvidence

CRITICAL = ("function", "package_quantity", "product_type", "price", "moq")


def _equal(a, b):
    if a is None or b is None:
        return None
    return 1.0 if str(a).casefold() == str(b).casefold() else 0.0


def build_match_evidence(u: AmazonProductUnderstanding, supplier, visual=None) -> MatchEvidence:
    detail = supplier.raw_data.get("detail", {}) if isinstance(supplier.raw_data, dict) else {}
    supplier_type = detail.get("product_type")
    target_type = u.replaceable_part_or_full_product
    type_match = None if target_type == "unknown" or supplier_type is None else _equal(target_type, supplier_type)
    pack_match = _equal(u.package_quantity, detail.get("package_quantity"))
    function_text = " ".join(u.function).casefold()
    supplier_text = " ".join(filter(None, [supplier.title_cn, detail.get("function")])).casefold()
    function_match = None if not function_text or not supplier_text else float(any(term.casefold() in supplier_text for term in u.function))
    target_spec = spec_from_text(" ".join([
        u.generic_product_name, u.category or "", *u.material, *u.components,
        *u.dimensions_visible,
    ]))
    target_spec.category = u.category or target_spec.category
    target_spec.material = u.material[0] if u.material else target_spec.material
    target_spec.pack_count = u.package_quantity or target_spec.pack_count
    target_spec.features = list(dict.fromkeys([*target_spec.features, *u.function, *u.distinguishing_features]))
    spec = compare_specs(target_spec, spec_from_supplier(supplier))
    mismatch = []
    missing = []
    if type_match == 0:
        mismatch.append("accessory_full_product_conflict")
    if pack_match == 0:
        mismatch.append("package_quantity_conflict")
    if function_match == 0:
        mismatch.append("core_function_conflict")
    for name, value in (("function", function_match), ("package_quantity", pack_match), ("product_type", type_match)):
        if value is None:
            missing.append(name)
    if detail.get("base_price_cny") is None and not detail.get("price_tiers"):
        missing.append("price")
    if detail.get("moq") is None:
        missing.append("moq")
    visual_is_match = None
    if visual:
        visual_is_match = bool(
            visual.get("same_product_type")
            and visual.get("same_core_function")
            and visual.get("same_package_quantity") is not False
        )
    if visual_is_match is False:
        mismatch.append("visual_core_function_conflict")
    scores = [v for v in (function_match, pack_match, type_match, spec.score) if v is not None]
    confidence = mean(scores) if scores else 0.0
    confidence *= max(0.25, 1 - 0.12 * len(missing))
    if mismatch:
        decision = "reject"
    elif any(name in missing for name in CRITICAL):
        decision = "retry"
        confidence = min(confidence, 0.49)
    else:
        decision = "keep" if confidence >= 0.70 else "manual_review"
    return MatchEvidence(
        amazon_ref=f"asin:{u.asin}", supplier_ref=f"offer:{supplier.alibaba_offer_id}",
        function_match=function_match, package_quantity_match=pack_match,
        accessory_vs_full_product_match=type_match,
        specification_similarity=spec.score,
        image_similarity=getattr(supplier, "image_similarity", None),
        visual_is_match=visual_is_match,
        visual_confidence=visual.get("confidence") if visual else None,
        overall_confidence=round(confidence, 4), mismatch_reasons=mismatch,
        missing_evidence=sorted(set(missing)),
        passed_reasons=[name for name, value in (("function", function_match), ("package_quantity", pack_match), ("product_type", type_match)) if value == 1],
        decision=decision,
    )
```

- [ ] **Step 4: Run structured matcher tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_match_evidence.py tests/test_product_spec.py tests/test_verifier_spec_match.py -v`

Expected: all selected tests pass; every hard mismatch returns `reject` before aggregate scoring.

- [ ] **Step 5: Commit structured match evidence**

```bash
git add matchers/match_evidence.py tests/test_match_evidence.py
git commit -m "feat: add structured supplier match evidence"
```

---

### Task 10: Schema-Validated Dual-Image Verification

**Files:**
- Modify: `schemas/sourcing.py`
- Modify: `matchers/verifier.py`
- Test: `tests/test_dual_image_verifier.py`

**Interfaces:**
- Consumes: Amazon main/secondary images, supplier offer/detail/SKU images, PPIO or Anthropic provider.
- Produces: `VisionMatchResult`, validated Task B response, provider/model/prompt version, evidence list.

- [ ] **Step 1: Write schema, multi-image, and invalid-response tests**

```python
# tests/test_dual_image_verifier.py
from types import SimpleNamespace

import pytest
from matchers.alibaba_pailitao import SupplierDTO
from matchers.verifier import LLMVisualVerifier
from matchers.verifier import VisionVerificationError


class FakeVisionClient:
    def __init__(self):
        self.requests = []
        self.response = {
            "same_product_type": True, "same_core_function": True,
            "same_structure": True, "same_material": True,
            "same_package_quantity": True, "confidence": 0.91,
            "evidence": ["两侧均为四只装替换滤芯"],
            "provider": "fake", "model": "fake-v1",
        }

    def verify(self, payload):
        self.requests.append(payload)
        return self.response


def _objects():
    product = SimpleNamespace(
        main_image_url="https://amazon/1.jpg",
        raw_data={"secondary_images": ["https://amazon/2.jpg"]},
    )
    supplier = SupplierDTO(
        alibaba_offer_id="123", offer_image_url="https://1688/1.jpg",
        raw_data={"detail": {"detail_images": ["https://1688/d1.jpg"], "sku_images": ["https://1688/s1.jpg"]}},
    )
    client = FakeVisionClient()
    verifier = LLMVisualVerifier(
        api_key="test", api_base="https://example.invalid", model="fake-v1",
        provider_client=client,
    )
    return verifier, client, product, supplier


def test_dual_image_request_contains_both_image_sets():
    verifier, client, product, supplier = _objects()
    verifier.verify_pair(product, supplier)
    request = client.requests[0]
    assert request["amazon_images"] == [product.main_image_url, "https://amazon/2.jpg"]
    assert request["supplier_images"] == [supplier.offer_image_url, "https://1688/d1.jpg", "https://1688/s1.jpg"]


def test_invalid_task_b_json_is_rejected():
    verifier, client, product, supplier = _objects()
    client.response = {"same_product_type": "probably"}
    with pytest.raises(VisionVerificationError, match="schema_validation"):
        verifier.verify_pair(product, supplier)
```

- [ ] **Step 2: Run tests and confirm Task B interface is absent**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_dual_image_verifier.py -v`

Expected: tests fail because `verify_pair()` and `VisionMatchResult` do not exist.

- [ ] **Step 3: Add `VisionMatchResult` and provider-neutral Task B call**

Add this schema to `schemas/sourcing.py`:

```python
class VisionMatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    same_product_type: bool
    same_core_function: bool
    same_structure: bool | None = None
    same_material: bool | None = None
    same_package_quantity: bool | None = None
    major_visual_differences: list[str] = Field(default_factory=list)
    potential_mismatch: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1)
    provider: str
    model: str
    prompt_version: str = "supplier-visual-match-v1"
```

Extend `LLMVisualVerifier.__init__()` with `provider_client=None`, stored as `self._provider_client`; production defaults to the configured PPIO/Anthropic adapter and tests inject `FakeVisionClient`. Implement `LLMVisualVerifier.verify_pair(product, supplier) -> VisionMatchResult` by calling `self._provider_client.verify(payload)`. Limit each side to five deduplicated images, include structured Amazon and supplier attributes in the prompt, require explicit package-quantity and replacement/full-product decisions, and validate the response with `VisionMatchResult.model_validate()`. Classification confidence remains separate from similarity; if any of product type/core function/package quantity is explicitly false, return negative evidence regardless of confidence.

Keep existing PPIO behavior and add Anthropic through the same internal `_vision_provider_call(payload)` boundary. Cache by prompt version, provider, model, normalized attributes, and all image content hashes.

- [ ] **Step 4: Run dual-image and legacy provider tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_dual_image_verifier.py tests/test_vision_matcher.py tests/test_product_understanding.py -v`

Expected: all selected tests pass; invalid JSON never reaches matching.

- [ ] **Step 5: Commit Task B verification**

```bash
git add schemas/sourcing.py matchers/verifier.py tests/test_dual_image_verifier.py
git commit -m "feat: validate dual image supplier matches"
```

---

### Task 11: Bounded Search, Enrichment, Retry, and Recommendation Coordinator

**Files:**
- Create: `matchers/sourcing_slice.py`
- Modify: `reports/exporter.py`
- Test: `tests/test_sourcing_slice.py`
- Test: `tests/test_exporter_evidence.py`

**Interfaces:**
- Consumes: understanding service, query planner, existing text-search backends, detail loader, structured matcher, visual verifier, profit/market evidence.
- Produces: `run_sourcing_slice(product, deps: SourcingSliceDependencies, run_ref: str, allow_mock: bool = False) -> SourcingSliceResult`, maximum two low-relevance rewrites, evidence-backed recommendation status.

- [ ] **Step 1: Write the end-to-end service test with deterministic fakes**

```python
# tests/test_sourcing_slice.py
from types import SimpleNamespace

from matchers.alibaba_detail import BlockedOfferPage
from matchers.alibaba_pailitao import SupplierDTO
from matchers.sourcing_slice import SourcingSliceDependencies, run_sourcing_slice
from schemas.sourcing import AmazonProductUnderstanding, VisionMatchResult


def _product():
    return SimpleNamespace(asin="B000TEST", title="four replacement filters")


def _understanding(_product):
    return AmazonProductUnderstanding(
        asin="B000TEST", original_title_en="four replacement filters",
        generic_product_name="净水滤芯", supply_chain_name_cn="净水器替换滤芯",
        category="净水设备配件", function=["过滤饮用水"], material=["活性炭"],
        components=["滤芯"], package_quantity=4,
        replaceable_part_or_full_product="replacement", model_provider="fake",
        model_name="fake-v1", prompt_version="amazon-understanding-v1",
    )


def _visual(_product, _supplier):
    return VisionMatchResult(
        same_product_type=True, same_core_function=True, same_structure=True,
        same_material=True, same_package_quantity=True, confidence=0.9,
        evidence=["四只装替换滤芯"], provider="fake", model="fake-v1",
    )


def test_slice_retries_low_relevance_and_recommends_only_complete_match():
    calls = {"search": 0}
    accepted = SupplierDTO(alibaba_offer_id="real-accepted", title_cn="活性炭净水器替换滤芯四只装")
    wrong = SupplierDTO(alibaba_offer_id="wrong-function", title_cn="空气滤芯")
    single = SupplierDTO(alibaba_offer_id="single-pack", title_cn="净水器替换滤芯单只")

    def search(_query):
        calls["search"] += 1
        return [] if calls["search"] <= 12 else [accepted, wrong, single]

    def detail(supplier):
        mapping = {
            "real-accepted": {"product_type": "replacement", "package_quantity": 4, "function": "过滤饮用水", "base_price_cny": 12.5, "moq": 20},
            "wrong-function": {"product_type": "replacement", "package_quantity": 4, "function": "过滤空气", "base_price_cny": 8, "moq": 20},
            "single-pack": {"product_type": "replacement", "package_quantity": 1, "function": "过滤饮用水", "base_price_cny": 5, "moq": 20},
        }
        supplier.raw_data["detail"] = mapping[supplier.alibaba_offer_id]
        return supplier

    deps = SourcingSliceDependencies(
        understand=_understanding, search=search, load_detail=detail,
        verify_visual=_visual,
        market_evidence=lambda _p: {
            "amazon_completeness": 1.0, "demand_refs": ["market:demand"],
            "competition_refs": ["market:competition"], "purchase_cost_ref": "offer:price",
            "logistics_basis": ["weight", "length", "width", "height"],
            "profit_basis": ["selling_price", "landed_cost"], "risks": [],
        },
    )
    result = run_sourcing_slice(_product(), deps, run_ref="test-run", allow_mock=False)
    assert result.iterations == 2
    assert result.query_attempts
    assert result.recommendation.status.value == "recommend"
    assert result.recommendation.supplier_offer_id == "real-accepted"
    assert {item.supplier_ref for item in result.rejected_matches} == {"offer:wrong-function", "offer:single-pack"}
    assert all(s.match_verification_method != "mock" for s in result.suppliers)


def test_slice_returns_insufficient_data_when_detail_is_blocked():
    supplier = SupplierDTO(alibaba_offer_id="blocked", title_cn="净水器滤芯")
    deps = SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [supplier],
        load_detail=lambda _s: (_ for _ in ()).throw(BlockedOfferPage("AUTH_REQUIRED", "login page")),
        verify_visual=_visual, market_evidence=lambda _p: {},
    )
    result = run_sourcing_slice(
        _product(), deps, run_ref="blocked-run", allow_mock=False
    )
    assert result.recommendation.status.value == "insufficient_data"
    assert "1688_detail_auth_required" in result.recommendation.rejection_reasons
    assert result.suppliers == []
```

- [ ] **Step 2: Run tests and confirm coordinator absence**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_sourcing_slice.py -v`

Expected: collection fails because `matchers.sourcing_slice` does not exist.

- [ ] **Step 3: Implement the bounded coordinator**

```python
# matchers/sourcing_slice.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from matchers.match_evidence import build_match_evidence
from matchers.query_planner import generate_query_plan, rewrite_low_relevance_queries
from matchers.alibaba_detail import BlockedOfferPage
from schemas.sourcing import MatchEvidence, RecommendationEvidence, RecommendationStatus


@dataclass
class SourcingSliceDependencies:
    understand: Callable
    search: Callable
    load_detail: Callable
    verify_visual: Callable
    market_evidence: Callable


@dataclass
class SourcingSliceResult:
    run_ref: str
    iterations: int
    understanding: object
    query_attempts: list[dict] = field(default_factory=list)
    suppliers: list = field(default_factory=list)
    accepted_matches: list[MatchEvidence] = field(default_factory=list)
    rejected_matches: list[MatchEvidence] = field(default_factory=list)
    recommendation: RecommendationEvidence | None = None


def _is_mock(supplier) -> bool:
    method = (getattr(supplier, "match_verification_method", "") or "").casefold()
    raw = supplier.raw_data if isinstance(supplier.raw_data, dict) else {}
    return method == "mock" or raw.get("data_status") == "mock"


def run_sourcing_slice(product, deps, run_ref: str, allow_mock: bool = False) -> SourcingSliceResult:
    understanding = deps.understand(product)
    queries = generate_query_plan(understanding)
    result = SourcingSliceResult(run_ref=run_ref, iterations=0, understanding=understanding)
    seen = set()
    for iteration in range(1, 3):
        result.iterations = iteration
        hit_rates = {}
        for query in queries:
            hits = deps.search(query)
            real_hits = [s for s in hits if allow_mock or not _is_mock(s)]
            relevant = [s for s in real_hits if s.alibaba_offer_id not in seen]
            hit_rates[query.query_id] = len(relevant) / max(1, len(real_hits))
            result.query_attempts.append({
                "query": query.model_dump(mode="json"), "result_count": len(real_hits),
                "relevant_count": len(relevant), "hit_rate": hit_rates[query.query_id],
            })
            for supplier in relevant:
                seen.add(supplier.alibaba_offer_id)
                try:
                    enriched = deps.load_detail(supplier)
                except BlockedOfferPage as exc:
                    result.recommendation = RecommendationEvidence(
                        asin=product.asin, status=RecommendationStatus.INSUFFICIENT_DATA,
                        discovery_reason="Amazon US source candidate passed initial discovery",
                        amazon_completeness=0.0, confidence=0.0,
                        rejection_reasons=[f"1688_detail_{exc.error_code.casefold()}"],
                        manual_verification_tasks=[exc.diagnostic],
                    )
                    return result
                visual = deps.verify_visual(product, enriched)
                match = build_match_evidence(understanding, enriched, visual.model_dump())
                if match.decision == "keep":
                    result.suppliers.append(enriched)
                    result.accepted_matches.append(match)
                elif match.decision == "reject":
                    result.rejected_matches.append(match)
        if result.accepted_matches:
            break
        queries = rewrite_low_relevance_queries(understanding, queries, hit_rates, iteration)
        if not queries:
            break
    market = deps.market_evidence(product)
    best = max(result.accepted_matches, key=lambda item: item.overall_confidence, default=None)
    critical_market = bool(market.get("demand_refs") and market.get("competition_refs"))
    critical_cost = bool(
        market.get("purchase_cost_ref")
        and len(market.get("logistics_basis", [])) >= 4
        and market.get("profit_basis")
    )
    if best and critical_market and critical_cost:
        status = RecommendationStatus.RECOMMEND
    elif best:
        status = RecommendationStatus.NEEDS_MANUAL_REVIEW
    elif result.rejected_matches:
        status = RecommendationStatus.REJECT
    else:
        status = RecommendationStatus.INSUFFICIENT_DATA
    result.recommendation = RecommendationEvidence(
        asin=product.asin,
        supplier_offer_id=best.supplier_ref.removeprefix("offer:") if best else None,
        status=status,
        discovery_reason="Amazon US source candidate passed initial discovery",
        amazon_completeness=market.get("amazon_completeness", 0.0),
        demand_evidence_refs=market.get("demand_refs", []),
        competition_evidence_refs=market.get("competition_refs", []),
        supplier_match_ref=best.supplier_ref if best else None,
        confirmed_specs=best.passed_reasons if best else [],
        unconfirmed_specs=best.missing_evidence if best else [],
        purchase_cost_ref=market.get("purchase_cost_ref") if best else None,
        logistics_basis=market.get("logistics_basis", []), profit_basis=market.get("profit_basis", []),
        risks=market.get("risks", []), confidence=best.overall_confidence if best else 0.0,
        recommendation_reasons=["minimum_supplier_evidence_passed"] if status is RecommendationStatus.RECOMMEND else [],
        rejection_reasons=[] if best else ["no_supplier_passed_minimum_evidence"],
        manual_verification_tasks=best.missing_evidence if best else [],
    )
    return result
```

Persist each query attempt and match/recommendation object using the Task 2 tables in one transaction per product. Use these stable search error codes: `AUTH_REQUIRED`, `CAPTCHA`, `RATE_LIMITED`, `TIMEOUT`, `NO_RESULTS`, and `LOW_RELEVANCE`. `AUTH_REQUIRED` or `CAPTCHA` ends the slice with `insufficient_data`; it never parses the response or substitutes mock data. Deduplicate offers by `alibaba_offer_id` across all queries.

- [ ] **Step 4: Add evidence fields to existing exports**

Extend JSON/Excel/Markdown output with `schema_version`, `run_ref`, `query_plan_and_hit_rates`, `match_evidence`, `recommendation_status`, `recommendation_reasons`, `rejection_reasons`, and `manual_verification_tasks`. Preserve all legacy keys and column order before the appended fields.

- [ ] **Step 5: Run coordinator and exporter tests**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_sourcing_slice.py tests/test_exporter_evidence.py tests/test_exporter_spec_match.py tests/test_history_review.py -v`

Expected: all selected tests pass; formal mode contains no mock supplier, and blocked detail produces `insufficient_data`.

- [ ] **Step 6: Commit the vertical slice coordinator**

```bash
git add matchers/sourcing_slice.py reports/exporter.py tests/test_sourcing_slice.py tests/test_exporter_evidence.py
git commit -m "feat: add evidence gated sourcing slice"
```

---

### Task 12: Benchmark Dataset Contract and Metric Evaluator

**Files:**
- Create: `benchmarks/__init__.py`
- Create: `benchmarks/evaluate.py`
- Create: `benchmarks/fixtures/sourcing_quality_seed.json`
- Create: `benchmarks/fixtures/empty_predictions.json`
- Create: `scripts/evaluate_sourcing_quality.py`
- Test: `tests/test_benchmark_evaluate.py`

**Interfaces:**
- Consumes: versioned reviewed labels plus run predictions.
- Produces: precision@1/@5, false-match rate, no-match accuracy, completeness, real/mock rates, recommendation precision, manual-review rate, retry/cost/success metrics.

- [ ] **Step 1: Write exact metric tests**

```python
# tests/test_benchmark_evaluate.py
from benchmarks.evaluate import evaluate


def test_metrics_use_only_reviewed_labels():
    labels = [
        {"case_id": "a", "reviewed": True, "correct_offer_ids": ["1"], "no_match": False, "recommendation_label": "recommend"},
        {"case_id": "b", "reviewed": True, "correct_offer_ids": [], "no_match": True, "recommendation_label": "reject"},
        {"case_id": "c", "reviewed": False, "correct_offer_ids": ["9"], "no_match": False, "recommendation_label": "recommend"},
    ]
    predictions = {
        "a": {"ranked_offer_ids": ["1", "2"], "recommendation_status": "recommend", "mock_count": 0, "supplier_count": 2, "field_completeness": 0.8, "retries": 1, "cost": 2.0, "pipeline_success": True},
        "b": {"ranked_offer_ids": [], "recommendation_status": "reject", "mock_count": 0, "supplier_count": 0, "field_completeness": 0.6, "retries": 0, "cost": 1.0, "pipeline_success": True},
    }
    result = evaluate(labels, predictions)
    assert result["reviewed_case_count"] == 2
    assert result["supplier_precision_at_1"] == 1.0
    assert result["no_match_accuracy"] == 1.0
    assert result["recommendation_precision"] == 1.0
    assert result["mock_contamination_rate"] == 0.0
```

- [ ] **Step 2: Run test and confirm evaluator absence**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_benchmark_evaluate.py -v`

Expected: collection fails because `benchmarks.evaluate` does not exist.

- [ ] **Step 3: Implement denominator-safe reviewed-label metrics**

```python
# benchmarks/evaluate.py
from __future__ import annotations


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate(labels: list[dict], predictions: dict[str, dict]) -> dict:
    reviewed = [item for item in labels if item.get("reviewed") is True and item["case_id"] in predictions]
    match_cases = [item for item in reviewed if not item.get("no_match")]
    no_match_cases = [item for item in reviewed if item.get("no_match")]
    p1 = sum(bool(set(predictions[item["case_id"]].get("ranked_offer_ids", [])[:1]) & set(item["correct_offer_ids"])) for item in match_cases)
    p5 = sum(bool(set(predictions[item["case_id"]].get("ranked_offer_ids", [])[:5]) & set(item["correct_offer_ids"])) for item in match_cases)
    false_matches = sum(bool(predictions[item["case_id"]].get("ranked_offer_ids")) for item in no_match_cases)
    recommendation_cases = [item for item in reviewed if item.get("recommendation_label") == "recommend"]
    correct_recommendations = sum(predictions[item["case_id"]].get("recommendation_status") == "recommend" for item in recommendation_cases)
    supplier_total = sum(predictions[item["case_id"]].get("supplier_count", 0) for item in reviewed)
    mock_total = sum(predictions[item["case_id"]].get("mock_count", 0) for item in reviewed)
    approved = sum(predictions[item["case_id"]].get("recommendation_status") == "recommend" for item in reviewed)
    return {
        "reviewed_case_count": len(reviewed),
        "supplier_precision_at_1": _ratio(p1, len(match_cases)),
        "supplier_precision_at_5": _ratio(p5, len(match_cases)),
        "false_match_rate": _ratio(false_matches, len(no_match_cases)),
        "no_match_accuracy": _ratio(len(no_match_cases) - false_matches, len(no_match_cases)),
        "field_completeness": _ratio(sum(predictions[item["case_id"]].get("field_completeness", 0) for item in reviewed), len(reviewed)),
        "real_supplier_rate": _ratio(supplier_total - mock_total, supplier_total),
        "mock_contamination_rate": _ratio(mock_total, supplier_total) or 0.0,
        "recommendation_precision": _ratio(correct_recommendations, len(recommendation_cases)),
        "manual_review_rate": _ratio(sum(predictions[item["case_id"]].get("recommendation_status") == "needs_manual_review" for item in reviewed), len(reviewed)),
        "cost_per_approved_candidate": _ratio(sum(predictions[item["case_id"]].get("cost", 0) for item in reviewed), approved),
        "average_retries": _ratio(sum(predictions[item["case_id"]].get("retries", 0) for item in reviewed), len(reviewed)),
        "quality_pipeline_success_rate": _ratio(sum(bool(predictions[item["case_id"]].get("pipeline_success")) for item in reviewed), len(reviewed)),
    }
```

The seed JSON must include the audited historical LLM top pairs as `reviewed: false`, artifact hashes, ASIN family, candidate offer ids, mismatch types, and blank reviewer metadata. Do not convert audit inference into ground truth. `scripts/evaluate_sourcing_quality.py` accepts label and prediction paths and writes deterministic JSON with sorted keys.

- [ ] **Step 4: Run evaluator tests and CLI fixture check**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_benchmark_evaluate.py -v`

Create `benchmarks/fixtures/empty_predictions.json` with the exact content `{}`.

Run: `python scripts/evaluate_sourcing_quality.py --labels benchmarks/fixtures/sourcing_quality_seed.json --predictions benchmarks/fixtures/empty_predictions.json --output /tmp/sourcing_metrics.json`

Expected: unit test passes; CLI reports `reviewed_case_count: 0` and null label-dependent precision values rather than claiming improvement.

- [ ] **Step 5: Commit benchmark infrastructure**

```bash
git add benchmarks scripts/evaluate_sourcing_quality.py tests/test_benchmark_evaluate.py
git commit -m "test: add sourcing quality benchmark metrics"
```

---

### Task 13: Compatibility, Full Verification, and No-Mock Real E2E

**Files:**
- Modify: `README.md`
- Modify: `STATUS.md`
- Modify: `docs/scoring_spec.md`
- Modify: `tests/test_smoke_run.py`
- Create: `docs/audits/2026-07-10-phase1-phase2-results.md`

**Interfaces:**
- Consumes: Tasks 1–11, Phase 0 completeness artifact, real Amazon/1688 sessions.
- Produces: compatibility proof, measured field-quality deltas, benchmark report, and unresolved-issue log.

- [ ] **Step 1: Add compatibility assertions before the real run**

```python
# append to tests/test_smoke_run.py
from click.testing import CliRunner
import main as main_module
from main import cli


def test_legacy_pipeline_command_remains_default(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "run_pipeline", lambda **kwargs: calls.append(kwargs) or 77)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--category", "Sports & Outdoors", "--limit", "1"])
    assert result.exit_code == 0
    assert calls == [{"category": "Sports & Outdoors", "limit": 1, "marketplace": "US"}]
```

- [ ] **Step 2: Run focused compatibility suites**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_smoke_run.py tests/test_pipeline_source_mode.py tests/test_pipeline_runtime_controls.py tests/test_agent_runtime.py tests/test_agent_server.py -v`

Expected: all selected tests pass and legacy mode remains the default.

- [ ] **Step 3: Run the complete test suite**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/`

Expected: zero failures. Record pass/skip/warning counts and wall time in `docs/audits/2026-07-10-phase1-phase2-results.md`.

- [ ] **Step 4: Verify migration against a copied production database**

```bash
cp data/amazon_selector.db /tmp/amazon_selector_migration_test.db
DATABASE_URL=sqlite:////tmp/amazon_selector_migration_test.db python -m db.init_db
sqlite3 /tmp/amazon_selector_migration_test.db 'PRAGMA integrity_check; PRAGMA foreign_key_check; SELECT version FROM schema_migrations ORDER BY version;'
```

Expected: `integrity_check` is `ok`, `foreign_key_check` prints no rows, migration `0001_evidence_foundation` is present, and legacy table row counts equal the pre-migration snapshot.

- [ ] **Step 5: Run a small real no-mock Docker E2E**

Run the official Docker WebUI runtime, then launch one Amazon US keyword or category sample with one product, formal no-mock mode, market evidence required, supplier detail required, and export enabled. Permit human login/captcha handoff but do not substitute mock data.

Expected terminal outcomes are `recommend`, `needs_manual_review`, `reject`, or `insufficient_data`; infrastructure failure is reported separately. A run with zero crawled products must not be marked quality-success. Capture query attempts, detail-field statuses, match decisions, retries, external-call errors, mock count, and export paths.

- [ ] **Step 6: Recompute completeness and benchmark metrics**

Compare the same field definitions and sample cohort against `data/audits/phase0_field_completeness_20260710.json`. Report Amazon completeness, 1688 completeness, market missing rate, real supplier rate, mock contamination, and reviewed benchmark metrics. If reviewed labels are still zero, write `not measurable: no reviewed labels` for accuracy metrics.

- [ ] **Step 7: Document verified results without overstating quality**

In `docs/audits/2026-07-10-phase1-phase2-results.md`, record:

```markdown
## Changes
## Focused test results
## Full test results
## SQLite migration and integrity
## Real no-mock E2E
## Field completeness before and after
## Match metrics from reviewed labels
## Mock contamination before and after
## Remaining blockers and human verification
```

Update README/STATUS/scoring spec only with behavior proven by the preceding commands. State that `run_pipeline()` is still deterministic and the Phase 3 `--mode agent` route is not yet implemented.

- [ ] **Step 8: Commit verification documentation**

```bash
git add README.md STATUS.md docs/scoring_spec.md docs/audits/2026-07-10-phase1-phase2-results.md tests/test_smoke_run.py
git commit -m "docs: report sourcing quality vertical slice"
```

## Completion Gate

This plan is complete only when all of the following are evidenced:

- Explicit negative visual classifications yield rejection and cannot improve match scores.
- Missing critical price, MOQ, dimensions, weight, market demand, or competition evidence cannot produce a strong recommendation.
- Twelve de-branded query types are generated and query outcomes are persisted.
- Blocked 1688 pages are never parsed as offers.
- Formal no-mock mode has zero mock contamination.
- Accessory/full-product, pack-count, and core-function hard negatives are rejected.
- New LLM outputs fail closed on schema validation errors.
- Existing deterministic CLI, SQLite history, and export fields remain compatible.
- Full tests and a real small-scale E2E are reported.
- Matching-accuracy deltas are reported only from reviewed benchmark labels.

## Follow-on Plans

After this completion gate passes, write two separate implementation plans:

1. Phase 3 finite-state Agentic Sourcing Loop: `AgentState`, typed tools, policy, checkpoints, resume, `--mode agent`, bounded expansion, re-score, and audit decisions.
2. Phase 4 feedback and replay: WebUI labels, versioned benchmark feedback, replay, and version comparison.

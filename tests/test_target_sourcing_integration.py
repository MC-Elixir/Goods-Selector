from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import matchers
from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.migrate import run_migrations
from db.models import Base
from domain.target_categories import (
    profile_from_product,
    profile_from_text,
    understanding_from_target_profile,
)
from matchers.alibaba_pailitao import SupplierDTO
from matchers.query_planner import generate_query_plan
from matchers.sourcing_slice import (
    evaluate_prefetched_suppliers,
    finalize_record_sourcing_evidence,
    persist_serialized_sourcing_evidence,
    serialize_sourcing_result,
)


def _target_product() -> ProductDTO:
    return ProductDTO(
        asin="B0TARGET01",
        marketplace="US",
        title="9 FT Market Patio Umbrella, 180 GSM Polyester Canopy",
        category="Patio Umbrellas & Shade",
    )


def _supplier(
    offer_id: str,
    title: str,
    *,
    supplier_type: str | None = "生产厂家",
) -> SupplierDTO:
    profile = profile_from_text(title)
    assert profile is not None
    detail = {
        "product_type": "full_product",
        "function": "户外遮阳",
        "category_profile": profile.to_dict(),
        "base_price_cny": 138.0,
        "moq": 20,
    }
    if supplier_type is not None:
        detail["factory_evidence"] = {"supplier_type": supplier_type}
    observed = datetime.now(timezone.utc).isoformat()
    detail["provenance"] = {
        key: {
            "status": "extracted",
            "source_type": "offer_detail",
            "source_ref": f"artifact:{offer_id}",
            "observed_at": observed,
            "confidence": 0.95,
        }
        for key, value in detail.items()
        if key != "provenance" and value is not None
    }
    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name="宁波户外用品生产厂家",
        title_cn=title,
        base_price_cny=138.0,
        moq=20,
        raw_data={"detail": detail},
    )


def _plan(product: ProductDTO):
    profile = profile_from_product(product)
    assert profile is not None
    understanding = understanding_from_target_profile(product, profile)
    product.raw_data["target_category_profile"] = profile.to_dict()
    return understanding, generate_query_plan(understanding)


def test_prefetched_gate_keeps_exact_manufacturer_and_rejects_spec_conflict():
    product = _target_product()
    understanding, queries = _plan(product)
    exact = _supplier("exact", "274cm 户外中柱遮阳伞 180gsm 涤纶")
    wrong = _supplier("wrong", "85cm 户外中柱遮阳伞 180gsm 涤纶")

    result = evaluate_prefetched_suppliers(
        product,
        [exact, wrong],
        understanding,
        queries,
        run_ref="run:target-test",
    )

    assert [item.alibaba_offer_id for item in result.suppliers] == ["exact"]
    assert result.accepted_matches[0].decision == "keep"
    assert "manufacturer" in result.accepted_matches[0].passed_reasons
    assert result.rejected_matches[0].supplier_ref == "offer:wrong"
    assert "target_category_conflict:canopy_diameter_cm" in result.rejected_matches[0].mismatch_reasons
    assert all(item["status"] == "not_started" for item in result.query_attempts)
    assert all(item["result_count"] is None for item in result.query_attempts)


def test_prefetched_gate_rejects_trader_and_reviews_unknown_manufacturer():
    product = _target_product()
    understanding, queries = _plan(product)
    trader = _supplier("trader", "274cm 户外中柱遮阳伞 180gsm 涤纶", supplier_type="贸易公司")
    unknown = _supplier("unknown", "274cm 户外中柱遮阳伞 180gsm 涤纶", supplier_type=None)

    result = evaluate_prefetched_suppliers(
        product,
        [trader, unknown],
        understanding,
        queries,
        run_ref="run:manufacturer-test",
    )

    assert result.suppliers == []
    assert "manufacturer_evidence_conflict" in result.rejected_matches[0].mismatch_reasons
    assert result.review_matches[0].decision in {"retry", "manual_review"}
    assert "manufacturer" in result.review_matches[0].missing_evidence


def test_serialized_target_evidence_persists_null_unknown_query_counts(tmp_path):
    product = _target_product()
    understanding, queries = _plan(product)
    result = evaluate_prefetched_suppliers(
        product,
        [_supplier("exact", "274cm 户外中柱遮阳伞 180gsm 涤纶")],
        understanding,
        queries,
        run_ref="run:persist-target",
    )
    payload = serialize_sourcing_result(result)
    engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    run_migrations(engine)

    persist_serialized_sourcing_evidence(payload, engine)

    with engine.connect() as connection:
        attempts = connection.execute(text(
            "select status,result_count,relevant_count from query_attempts order by id"
        )).mappings().all()
        matches = connection.execute(text(
            "select offer_id,decision from match_evidence order by id"
        )).mappings().all()
    assert len(attempts) == 12
    assert all(row["status"] == "not_started" for row in attempts)
    assert all(row["result_count"] is None and row["relevant_count"] is None for row in attempts)
    assert matches == [{"offer_id": "exact", "decision": "keep"}]


def test_query_trace_distinguishes_partial_results_and_auth_failure():
    product = _target_product()
    understanding, queries = _plan(product)
    result = evaluate_prefetched_suppliers(
        product,
        [],
        understanding,
        queries,
        run_ref="run:query-trace",
        query_execution=[
            {
                "query": queries[0].text,
                "status": "completed",
                "result_count": 5,
                "result_refs": ["offer:not-retained"],
                "backend": "fake_playwright",
            },
            {
                "query": queries[1].text,
                "status": "failed",
                "error": "1688 login required",
                "backend": "fake_playwright",
            },
        ],
    )

    partial, failed = result.query_attempts[:2]
    assert partial["status"] == "partial"
    assert partial["result_count"] is None
    assert partial["relevant_count"] is None
    assert partial["observed_result_count"] == 5
    assert failed["status"] == "failed"
    assert failed["result_count"] is None
    assert failed["error_code"] == "AUTH_REQUIRED"


def test_formal_matcher_executes_full_plan_and_returns_only_strict_keep(monkeypatch):
    product = _target_product()
    exact = _supplier("exact", "274cm 户外中柱遮阳伞 180gsm 涤纶")
    wrong = _supplier("wrong", "85cm 户外中柱遮阳伞 180gsm 涤纶")
    seen = {}

    class FakePlaywright:
        def __init__(self, *args, **kwargs):
            self.last_query_attempts = []

        def search_by_keyword(self, keywords, limit, *, exhaustive=False):
            seen["keywords"] = list(keywords)
            seen["exhaustive"] = exhaustive
            for supplier in (exact, wrong):
                supplier.raw_data["search_queries"] = list(keywords)
            self.last_query_attempts = [
                {
                    "query": keyword,
                    "status": "completed",
                    "result_count": 2,
                    "result_refs": ["offer:exact", "offer:wrong"],
                    "backend": "fake_playwright",
                    "error": None,
                }
                for keyword in keywords
            ]
            return [exact, wrong]

        def enrich_supplier_detail(self, supplier):
            return supplier

    monkeypatch.setattr(matchers, "_vision", None)
    monkeypatch.setattr(matchers, "_playwright", None)
    monkeypatch.setattr(matchers, "_verifier", None)
    monkeypatch.setattr(matchers, "_llm_verifier", None)
    monkeypatch.setattr(matchers, "load_cached_suppliers", lambda *args, **kwargs: [])
    monkeypatch.setattr(matchers, "find_imported_suppliers", lambda *args, **kwargs: [])
    monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
    monkeypatch.setattr(matchers, "save_cached_suppliers", lambda *args, **kwargs: None)
    monkeypatch.setattr(matchers, "save_cached_offer_detail", lambda *args, **kwargs: None)
    monkeypatch.setattr(matchers, "load_cached_offer_detail", lambda *args, **kwargs: {})
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", FakePlaywright)
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", False)
    monkeypatch.setattr(settings, "enable_scrapling_matcher", False)
    monkeypatch.setattr(settings, "enable_sellersprite_1688_sourcing", False)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)
    monkeypatch.setattr(settings, "enable_llm_verification", False)

    suppliers = matchers.match_suppliers(product, top_k=20, run_ref="run:formal-target")

    assert seen["exhaustive"] is True
    assert len(seen["keywords"]) == 12
    assert [supplier.alibaba_offer_id for supplier in suppliers] == ["exact"]
    evidence = product.raw_data["sourcing_evidence"]
    assert evidence["accepted_offer_ids"] == ["exact"]
    assert evidence["rejected_offer_ids"] == ["wrong"]
    assert len(evidence["query_attempts"]) == 12
    assert all(item["status"] == "completed" for item in evidence["query_attempts"])


def test_pipeline_supplier_writer_persists_target_query_match_and_recommendation(monkeypatch, tmp_path):
    import pipeline.orchestrator as orchestrator

    product = _target_product()
    understanding, queries = _plan(product)
    exact = _supplier("exact", "274cm 户外中柱遮阳伞 180gsm 涤纶")
    result = evaluate_prefetched_suppliers(
        product,
        [exact],
        understanding,
        queries,
        run_ref="run:pipeline-target",
    )
    product.raw_data["sourcing_evidence"] = serialize_sourcing_result(result)

    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline-target.db'}")
    Base.metadata.create_all(engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine, future=True)

    @contextmanager
    def session_scope():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(orchestrator, "session_scope", session_scope)

    orchestrator._persist_suppliers_for_product(product, result.suppliers)

    with engine.connect() as connection:
        assert connection.execute(text(
            "select count(*) from query_attempts where run_ref='run:pipeline-target'"
        )).scalar_one() == 12
        assert connection.execute(text(
            "select decision from match_evidence where offer_id='exact'"
        )).scalar_one() == "keep"
        assert connection.execute(text(
            "select status from sourcing_recommendations where asin='B0TARGET01'"
        )).scalar_one() == "watchlist"


def test_final_recommendation_clears_completed_tasks_and_rejected_alternative_reasons():
    product = _target_product()
    understanding, queries = _plan(product)
    result = evaluate_prefetched_suppliers(
        product,
        [
            _supplier("exact", "274cm 户外中柱遮阳伞 180gsm 涤纶"),
            _supplier("wrong", "85cm 户外中柱遮阳伞 180gsm 涤纶"),
        ],
        understanding,
        queries,
        run_ref="run:final-recommendation",
    )
    product.raw_data["sourcing_evidence"] = serialize_sourcing_result(result)
    record = SimpleNamespace(
        product=product,
        score=SimpleNamespace(passed_hard_filter=True, rejection_reasons=[]),
        profit=SimpleNamespace(selling_price=299.0, total_cost=180.0, profit_margin=0.30),
        market=SimpleNamespace(
            search_volume_monthly=12000,
            monthly_purchases=900,
            est_monthly_sales=400,
            competing_listings=350,
            top10_revenue_share=0.32,
            raw_data={"source_ref": "seller_sprite:historical:test"},
        ),
    )

    payload = finalize_record_sourcing_evidence(record)

    assert payload is not None
    recommendation = payload["recommendation"]
    assert recommendation["status"] == "recommend"
    assert recommendation["rejection_reasons"] == []
    assert recommendation["manual_verification_tasks"] == []
    assert recommendation["demand_evidence_refs"] == ["seller_sprite:historical:test"]
    assert recommendation["competition_evidence_refs"] == ["seller_sprite:historical:test"]
    assert payload["rejected_offer_ids"] == ["wrong"]

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from db.migrate import run_migrations
from matchers.alibaba_detail import BlockedOfferPage
from matchers.alibaba_pailitao import SupplierDTO
from matchers.sourcing_slice import SourcingSliceDependencies as _SourcingSliceDependencies
from matchers.sourcing_slice import _default_relevance, run_sourcing_slice
from matchers.verifier import VisionVerificationError
from schemas.sourcing import AmazonProductUnderstanding, VisionMatchResult


def SourcingSliceDependencies(**kwargs):
    kwargs.setdefault("assess_relevance", lambda _query, _supplier: True)
    return _SourcingSliceDependencies(**kwargs)


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
        same_product_type=True, same_core_function=True,
        same_accessory_full_product_relation=True, same_structure=True,
        same_material=True, same_package_quantity=True,
        major_visual_differences=[], potential_mismatch=[], confidence=0.9,
        evidence=["四只装替换滤芯"], provider="fake", model="fake-v1",
        prompt_version="vision-match-v1",
    )


def _complete_market():
    observed = datetime.now(timezone.utc).isoformat()
    def ev(value):
        return {"value": value, "status": "extracted", "source_type": "market_api",
                "source_ref": "artifact:market", "observed_at": observed, "confidence": 0.9}
    return {
        "amazon_completeness": ev(1.0), "demand_refs": ev(["market:demand"]),
        "competition_refs": ev(["market:competition"]), "purchase_cost_ref": ev("offer:price"),
        "logistics_basis": ev({
            "weight_kg": 1.2, "length_cm": 20, "width_cm": 10, "height_cm": 8,
            "refs": ["amazon:weight", "amazon:dimensions"],
        }),
        "profit_basis": ev({
            "selling_price": 29.99, "landed_cost": 12.0, "profit_margin": 0.3,
            "refs": ["profit:snapshot"],
        }), "risks": [],
    }


def _detail(supplier):
    details = {
        "good": {"product_type": "replacement", "package_quantity": 4, "function": "过滤饮用水", "base_price_cny": 12.5, "moq": 20},
        "wrong": {"product_type": "replacement", "package_quantity": 4, "function": "过滤空气", "base_price_cny": 8, "moq": 20},
        "single": {"product_type": "replacement", "package_quantity": 1, "function": "过滤饮用水", "base_price_cny": 5, "moq": 20},
    }
    detail = details[supplier.alibaba_offer_id]
    observed = datetime.now(timezone.utc).isoformat()
    detail["provenance"] = {
        key: {"status": "extracted", "source_type": "offer_detail", "source_ref": "artifact:offer",
              "observed_at": observed, "confidence": 0.95}
        for key in ("product_type", "package_quantity", "function", "base_price_cny", "moq")
    }
    supplier.raw_data["detail"] = detail
    return supplier


@pytest.mark.parametrize("status", ["missing", "stale", "inferred", "conflicting", "mock"])
def test_untrusted_critical_supplier_evidence_never_keeps_match(status):
    supplier = _detail(SupplierDTO("good"))
    supplier.raw_data["detail"]["provenance"]["function"]["status"] = status
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [supplier], load_detail=lambda s: s,
        verify_visual=_visual, market_evidence=lambda _p: _complete_market(),
    ), f"bad-function-{status}")
    assert result.accepted_matches == []
    assert result.recommendation.status.value != "recommend"
    assert "function" in result.review_matches[0].missing_evidence


def test_stale_market_reference_does_not_authorize_recommendation():
    market = _complete_market()
    market["demand_refs"]["observed_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: market,
    ), "stale-demand")
    assert result.recommendation.status.value == "needs_manual_review"
    assert "missing_demand_refs" in result.recommendation.rejection_reasons


def test_raw_amazon_completeness_does_not_authorize_recommendation():
    market = _complete_market()
    market["amazon_completeness"] = 1.0
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: market,
    ), "raw-completeness")
    assert result.recommendation.status.value == "needs_manual_review"
    assert "missing_amazon_completeness" in result.recommendation.rejection_reasons


def test_failed_query_attempt_has_unknown_counts_in_memory_and_persistence(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'failed-query.db'}")
    run_migrations(engine)
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: (_ for _ in ()).throw(TimeoutError("late")),
        load_detail=_detail, verify_visual=_visual, market_evidence=lambda _p: {}, engine=engine,
    ), "failed-query")
    first = result.query_attempts[0]
    assert first["status"] == "failed"
    assert first["result_count"] is None
    assert first["relevant_count"] is None
    assert first["hit_rate"] is None
    with engine.connect() as conn:
        row = conn.execute(text("select status,result_count,relevant_count,artifact_ref from query_attempts limit 1")).mappings().one()
    assert row["status"] == "failed"
    assert row["result_count"] is None and row["relevant_count"] is None
    assert json.loads(row["artifact_ref"])["hit_rate"] is None


def test_visual_failure_is_bounded_audited_and_persisted_as_review(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'visual-failure.db'}")
    run_migrations(engine)
    calls = 0
    def visual(*_args):
        nonlocal calls
        calls += 1
        raise VisionVerificationError("schema_validation")
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=visual, market_evidence=lambda _p: _complete_market(), engine=engine,
    ), "visual-failure")
    assert calls == 1
    assert result.accepted_matches == []
    assert result.recommendation.status.value == "needs_manual_review"
    assert result.visual_failures[0]["attempt_count"] == 1
    assert result.visual_failures[0]["error_code"] == "SCHEMA_VALIDATION"
    assert result.visual_failures[0]["reason"] == "supplier_visual_schema_validation"
    with engine.connect() as conn:
        match = conn.execute(text("select decision,evidence_json from match_evidence limit 1")).mappings().one()
        rec = conn.execute(text("select status,evidence_json from sourcing_recommendations limit 1")).mappings().one()
    assert match["decision"] == "manual_review"
    assert "visual" in json.loads(match["evidence_json"])["missing_evidence"]
    assert rec["status"] == "needs_manual_review"
    assert "supplier_visual_schema_validation" in json.loads(rec["evidence_json"])["rejection_reasons"]


def test_visual_provider_failure_retries_once_then_succeeds():
    calls = 0
    def visual(product, supplier):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise VisionVerificationError("provider_failure")
        return _visual(product, supplier)
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=visual, market_evidence=lambda _p: _complete_market(),
    ), "visual-provider-retry")
    assert calls == 2
    assert result.visual_failures == []
    assert result.recommendation.status.value == "recommend"


def test_visual_image_evidence_failure_is_not_retried():
    calls = 0
    def visual(*_args):
        nonlocal calls
        calls += 1
        raise VisionVerificationError("image_evidence_unavailable")
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=visual, market_evidence=lambda _p: _complete_market(),
    ), "visual-image-missing")
    assert calls == 1
    assert result.visual_failures[0]["error_code"] == "IMAGE_EVIDENCE_UNAVAILABLE"


def test_retries_low_relevance_deduplicates_and_recommends_complete_match():
    calls = 0
    good = SupplierDTO("good", title_cn="活性炭净水器替换滤芯四只装")
    wrong = SupplierDTO("wrong", title_cn="空气滤芯")
    single = SupplierDTO("single", title_cn="净水器替换滤芯单只")

    def search(_query):
        nonlocal calls
        calls += 1
        return [] if calls <= 12 else [good, good, wrong, single]

    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=search, load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: _complete_market(),
    ), run_ref="retry-run")

    assert result.iterations == 2
    assert result.recommendation.status.value == "recommend"
    assert result.recommendation.supplier_offer_id == "good"
    assert [s.alibaba_offer_id for s in result.suppliers] == ["good"]
    assert {m.supplier_ref for m in result.rejected_matches} == {"offer:wrong", "offer:single"}
    assert len([m for m in result.accepted_matches if m.supplier_ref == "offer:good"]) == 1
    assert all(a["error_code"] == "NO_RESULTS" for a in result.query_attempts[:12])


@pytest.mark.parametrize("code", ["AUTH_REQUIRED", "CAPTCHA"])
def test_blocked_search_or_detail_stops_without_parsing_or_mock(code):
    parsed = []
    mock = SupplierDTO("mock", match_verification_method="mock")
    deps = SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [mock],
        load_detail=lambda _s: parsed.append(True), verify_visual=_visual,
        market_evidence=lambda _p: {},
    )
    deps.search = lambda _q: (_ for _ in ()).throw(BlockedOfferPage(code, "blocked"))
    result = run_sourcing_slice(_product(), deps, run_ref=f"blocked-{code}")
    assert result.recommendation.status.value == "insufficient_data"
    assert result.recommendation.rejection_reasons == [f"1688_search_{code.casefold()}"]
    assert result.suppliers == []
    assert parsed == []


def test_formal_mode_mock_only_is_insufficient_and_never_enriched():
    mock = SupplierDTO("SECRET-MOCK", title_cn="SECRET TITLE", offer_url="https://mock/SECRET", match_verification_method="mock")
    enriched = []
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [mock],
        load_detail=lambda s: enriched.append(s), verify_visual=_visual,
        market_evidence=lambda _p: _complete_market(),
    ), run_ref="mock-only")
    assert result.suppliers == []
    assert enriched == []
    assert result.recommendation.status.value == "insufficient_data"
    assert "mock_supplier_excluded" in result.recommendation.rejection_reasons
    encoded = json.dumps(result.query_attempts, ensure_ascii=False)
    assert "SECRET" not in encoded
    assert all(a["result_count"] == 0 and a["result_refs"] == [] for a in result.query_attempts)


def test_blocked_detail_stops_before_visual_and_returns_handoff():
    visual_calls = []
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")],
        load_detail=lambda _s: (_ for _ in ()).throw(BlockedOfferPage("AUTH_REQUIRED", "login page")),
        verify_visual=lambda *args: visual_calls.append(args), market_evidence=lambda _p: {},
    ), run_ref="blocked-detail")
    assert result.recommendation.status.value == "insufficient_data"
    assert result.recommendation.rejection_reasons == ["1688_detail_auth_required"]
    assert result.recommendation.manual_verification_tasks == ["login page"]
    assert result.suppliers == []
    assert visual_calls == []


@pytest.mark.parametrize("missing", ["demand_refs", "competition_refs", "purchase_cost_ref", "logistics_basis", "profit_basis"])
def test_missing_decision_evidence_never_recommends(missing):
    market = _complete_market()
    market[missing] = [] if missing != "purchase_cost_ref" else None
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")],
        load_detail=_detail, verify_visual=_visual, market_evidence=lambda _p: market,
    ), run_ref=f"missing-{missing}")
    assert result.recommendation.status.value == "needs_manual_review"
    assert f"missing_{missing}" in result.recommendation.rejection_reasons
    assert f"verify_{missing}" in result.recommendation.manual_verification_tasks


@pytest.mark.parametrize("bad", [None, 0, float("nan"), float("inf"), "weight"])
def test_logistics_values_must_be_finite_positive_and_referenced(bad):
    market = _complete_market()
    market["logistics_basis"] = dict(market["logistics_basis"])
    market["logistics_basis"]["value"] = dict(market["logistics_basis"]["value"])
    market["logistics_basis"]["value"]["weight_kg"] = bad
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: market,
    ), run_ref="bad-logistics")
    assert result.recommendation.status.value != "recommend"


@pytest.mark.parametrize("bad", [None, 0, float("nan"), float("inf"), "selling_price"])
def test_profit_values_must_be_finite_positive_and_referenced(bad):
    market = _complete_market()
    market["profit_basis"] = dict(market["profit_basis"])
    market["profit_basis"]["value"] = dict(market["profit_basis"]["value"])
    market["profit_basis"]["value"]["selling_price"] = bad
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: market,
    ), run_ref="bad-profit")
    assert result.recommendation.status.value != "recommend"


def test_retry_match_preserves_missing_reasons_and_tasks():
    supplier = SupplierDTO("missing")
    supplier.raw_data["detail"] = {"product_type": "replacement"}
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [supplier], load_detail=lambda s: s,
        verify_visual=_visual, market_evidence=lambda _p: _complete_market(),
    ), run_ref="review")
    assert result.review_matches[0].decision == "retry"
    assert {"missing_price", "missing_moq", "missing_function", "missing_package_quantity"} <= set(result.recommendation.rejection_reasons)
    assert {"verify_price", "verify_moq", "verify_function", "verify_package_quantity"} <= set(result.recommendation.manual_verification_tasks)


@pytest.mark.parametrize("exc,code", [
    (TimeoutError("late"), "TIMEOUT"), (ValueError("bad"), "INVALID_INPUT"),
    (KeyError("missing"), "MISSING_REQUIRED_DATA"), (RuntimeError("bug"), "INTERNAL"),
])
def test_error_mapping_is_truthful_and_internal_is_not_retried(exc, code):
    calls = 0
    def search(_q):
        nonlocal calls
        calls += 1
        raise exc
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=search, load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: {},
    ), run_ref=f"error-{code}")
    assert result.query_attempts[0]["error_code"] == code
    if code in {"INTERNAL", "INVALID_INPUT", "MISSING_REQUIRED_DATA"}:
        assert calls == 1
        assert result.recommendation.status.value == "insufficient_data"


def test_persistence_is_atomic_scoped_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    run_migrations(engine)
    deps = SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")],
        load_detail=_detail, verify_visual=_visual,
        market_evidence=lambda _p: _complete_market(), engine=engine,
    )
    run_sourcing_slice(_product(), deps, run_ref="persist-run")
    run_sourcing_slice(_product(), deps, run_ref="persist-run")
    with engine.connect() as conn:
        attempts = conn.execute(text("select * from query_attempts where run_ref='persist-run'")).mappings().all()
        matches = conn.execute(text("select * from match_evidence where run_ref='persist-run'")).mappings().all()
        recs = conn.execute(text("select * from sourcing_recommendations where run_ref='persist-run'")).mappings().all()
    assert len(attempts) == 12
    assert len(matches) == 1
    assert len(recs) == 1
    assert json.loads(matches[0]["evidence_json"])["supplier_ref"] == "offer:good"
    assert all(a["artifact_ref"] for a in attempts)


def test_persistence_rolls_back_whole_product_on_failure(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    run_migrations(engine)
    engine.fail_persistence_after = "query_attempts"
    deps = SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")],
        load_detail=_detail, verify_visual=_visual,
        market_evidence=lambda _p: _complete_market(), engine=engine,
    )
    with pytest.raises(RuntimeError, match="injected persistence failure"):
        run_sourcing_slice(_product(), deps, run_ref="rollback-run")
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from query_attempts")).scalar_one() == 0
        assert conn.execute(text("select count(*) from match_evidence")).scalar_one() == 0
        assert conn.execute(text("select count(*) from sourcing_recommendations")).scalar_one() == 0


def test_persistence_replaces_scope_without_deleting_other_asin(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'replace.db'}")
    run_migrations(engine)
    deps = SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: _complete_market(), engine=engine,
    )
    run_sourcing_slice(_product(), deps, "same-run")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO query_attempts (run_ref,asin,query_id,query_type,query_text,reason,status) VALUES ('same-run','OTHER','other-q','generic_name','other','other','not_started')"))
    deps.search = lambda _q: []
    run_sourcing_slice(_product(), deps, "same-run")
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from match_evidence where run_ref='same-run' and asin='B000TEST'")).scalar_one() == 0
        assert conn.execute(text("select count(*) from query_attempts where run_ref='same-run' and asin='OTHER'")).scalar_one() == 1


def test_mock_identity_never_reaches_persisted_query_artifact(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mock.db'}")
    run_migrations(engine)
    mock = SupplierDTO("SECRET-MOCK", title_cn="SECRET TITLE", offer_url="https://mock/SECRET", match_verification_method="mock")
    run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [mock], load_detail=lambda s: s,
        verify_visual=_visual, market_evidence=lambda _p: {}, engine=engine,
    ), "mock-persist")
    with engine.connect() as conn:
        encoded = json.dumps([dict(row) for row in conn.execute(text("select * from query_attempts")).mappings()], ensure_ascii=False)
    assert "SECRET" not in encoded


def test_detail_timeout_retries_once_then_succeeds():
    calls = 0
    def detail(s):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BlockedOfferPage("TIMEOUT", "slow")
        return _detail(s)
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda q: [SupplierDTO("good")], load_detail=detail,
        verify_visual=_visual, market_evidence=lambda p: _complete_market(),
    ), "detail-retry")
    assert calls == 2
    assert result.recommendation.status.value == "recommend"


@pytest.mark.parametrize("code", ["TIMEOUT", "RATE_LIMITED"])
def test_detail_transient_exhaustion_is_audited_and_actionable(code):
    calls = 0
    def detail(_s):
        nonlocal calls
        calls += 1
        raise BlockedOfferPage(code, "blocked")
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda q: [SupplierDTO("good")], load_detail=detail,
        verify_visual=_visual, market_evidence=lambda p: {},
    ), f"detail-{code}")
    assert calls == 2
    assert result.detail_failures[0]["attempt_count"] == 2
    assert result.detail_failures[0]["offer_ref"] == "offer:good"
    reason = f"supplier_detail_{code.casefold()}"
    assert reason in result.recommendation.rejection_reasons
    assert f"retry_{reason}" in result.recommendation.manual_verification_tasks


def test_relevance_rate_uses_unique_real_hits_and_only_relevant_hits_are_enriched():
    hits = [SupplierDTO(str(i)) for i in range(5)]
    enriched = []
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda q: [*hits, hits[0]],
        load_detail=lambda s: enriched.append(s), verify_visual=_visual,
        market_evidence=lambda p: {}, assess_relevance=lambda q, s: s.alibaba_offer_id == "0",
    ), "relevance")
    first = result.query_attempts[0]
    assert first["result_count"] == 5
    assert first["relevant_count"] == 1
    assert first["hit_rate"] == pytest.approx(0.2)
    assert {s.alibaba_offer_id for s in enriched} == {"0"}


def test_all_irrelevant_real_hits_trigger_second_iteration():
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda q: [SupplierDTO("real")], load_detail=lambda s: s,
        verify_visual=_visual, market_evidence=lambda p: {}, assess_relevance=lambda q, s: False,
    ), "irrelevant")
    assert result.iterations == 2
    assert result.query_attempts[0]["hit_rate"] == 0
    assert result.query_attempts[0]["error_code"] == "LOW_RELEVANCE"


def test_default_relevance_without_signal_is_conservative_and_skips_detail():
    enriched = []
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda q: [SupplierDTO("real")],
        load_detail=lambda s: enriched.append(s), verify_visual=_visual,
        market_evidence=lambda p: {}, assess_relevance=_default_relevance,
    ), "default-no-signal")
    assert result.iterations == 2
    assert result.query_attempts[0]["hit_rate"] == 0
    assert result.query_attempts[0]["error_code"] == "LOW_RELEVANCE"
    assert enriched == []


@pytest.mark.parametrize("supplier", [
    SupplierDTO("text", text_similarity=0.8),
    SupplierDTO("bool", raw_data={"search_relevance": True}),
    SupplierDTO("score", raw_data={"search_relevance": 0.9}),
    SupplierDTO("image", image_similarity=0.9, raw_data={"source": "image_search"}),
])
def test_default_relevance_accepts_explicit_high_quality_signal(supplier):
    query = SimpleNamespace(text="净水器替换滤芯")
    assert _default_relevance(query, supplier) is True


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "bad", 0.1])
def test_default_relevance_rejects_malformed_or_low_scores(value):
    query = SimpleNamespace(text="净水器替换滤芯")
    supplier = SupplierDTO("bad", text_similarity=value)
    assert _default_relevance(query, supplier) is False


def test_default_relevance_title_requires_meaningful_phrase_not_short_substring():
    query = SimpleNamespace(text="净水器 替换滤芯")
    assert _default_relevance(query, SupplierDTO("yes", title_cn="家用净水器替换滤芯批发"))
    assert not _default_relevance(query, SupplierDTO("no", title_cn="空气滤芯"))
    assert not _default_relevance(SimpleNamespace(text="水"), SupplierDTO("short", title_cn="净水器"))


@pytest.mark.parametrize("query,title,expected", [
    ("净水器 替换滤芯", "净水器配件", False),
    ("净水器 替换滤芯", "净水器替换滤芯四只装", True),
    ("water filter", "water bottle", False),
    ("water filter", "water filter cartridge", True),
    ("replacement cartridge", "premium replacement cartridge", True),
])
def test_default_title_relevance_requires_core_term_coverage(query, title, expected):
    assert _default_relevance(SimpleNamespace(text=query), SupplierDTO("title", title_cn=title)) is expected


def test_default_relevance_recognizes_real_playwright_image_producer_shape_only_with_score():
    query = SimpleNamespace(text="unrelated query")
    image_hit = SupplierDTO(
        "img", image_similarity=0.85,
        raw_data={"title_cn": "unrelated", "full_text": "", "source": "alibaba_playwright"},
    )
    keyword_hit = SupplierDTO(
        "kw", image_similarity=None,
        raw_data={"title_cn": "unrelated", "full_text": "", "source": "alibaba_playwright"},
    )
    assert _default_relevance(query, image_hit)
    assert not _default_relevance(query, keyword_hit)


@pytest.mark.parametrize("query,title,expected", [
    ("净水器 替换滤芯", "净水器替换滤芯四只装", True),
    ("净水器 替换滤芯", "净水器配件", False),
    ("水器", "净水器配件", False),
    ("净水器", "净水器配件", True),
    ("滤芯", "净水器滤芯", True),
    ("水器", "净水器", True),
    ("净水器", "净水 器配件", False),
    ("净水器", "净水-器配件", False),
])
def test_default_cjk_relevance_preserves_runs_and_edges(query, title, expected):
    assert _default_relevance(SimpleNamespace(text=query), SupplierDTO("cjk", title_cn=title)) is expected

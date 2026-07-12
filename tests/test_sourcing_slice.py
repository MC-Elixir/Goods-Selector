import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from db.migrate import run_migrations
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
        same_product_type=True, same_core_function=True,
        same_accessory_full_product_relation=True, same_structure=True,
        same_material=True, same_package_quantity=True,
        major_visual_differences=[], potential_mismatch=[], confidence=0.9,
        evidence=["四只装替换滤芯"], provider="fake", model="fake-v1",
        prompt_version="vision-match-v1",
    )


def _complete_market():
    return {
        "amazon_completeness": 1.0, "demand_refs": ["market:demand"],
        "competition_refs": ["market:competition"], "purchase_cost_ref": "offer:price",
        "logistics_basis": {
            "weight_kg": 1.2, "length_cm": 20, "width_cm": 10, "height_cm": 8,
            "refs": ["amazon:weight", "amazon:dimensions"],
        },
        "profit_basis": {
            "selling_price": 29.99, "landed_cost": 12.0, "profit_margin": 0.3,
            "refs": ["profit:snapshot"],
        }, "risks": [],
    }


def _detail(supplier):
    details = {
        "good": {"product_type": "replacement", "package_quantity": 4, "function": "过滤饮用水", "base_price_cny": 12.5, "moq": 20},
        "wrong": {"product_type": "replacement", "package_quantity": 4, "function": "过滤空气", "base_price_cny": 8, "moq": 20},
        "single": {"product_type": "replacement", "package_quantity": 1, "function": "过滤饮用水", "base_price_cny": 5, "moq": 20},
    }
    supplier.raw_data["detail"] = details[supplier.alibaba_offer_id]
    return supplier


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
    market["logistics_basis"]["weight_kg"] = bad
    result = run_sourcing_slice(_product(), SourcingSliceDependencies(
        understand=_understanding, search=lambda _q: [SupplierDTO("good")], load_detail=_detail,
        verify_visual=_visual, market_evidence=lambda _p: market,
    ), run_ref="bad-logistics")
    assert result.recommendation.status.value != "recommend"


@pytest.mark.parametrize("bad", [None, 0, float("nan"), float("inf"), "selling_price"])
def test_profit_values_must_be_finite_positive_and_referenced(bad):
    market = _complete_market()
    market["profit_basis"] = dict(market["profit_basis"])
    market["profit_basis"]["selling_price"] = bad
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

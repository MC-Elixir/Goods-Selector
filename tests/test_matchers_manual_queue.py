import pytest

import matchers
from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from execution.models import HumanActionRequired
from matchers.alibaba_pailitao import SupplierDTO


def _product() -> ProductDTO:
    return ProductDTO(
        asin="BMANUAL123",
        marketplace="US",
        title="24 oz stainless steel water bottle",
        category="Sports",
        main_image_url=None,
    )


def _reset_matcher_globals(monkeypatch):
    monkeypatch.setattr(matchers, "_vision", None)
    monkeypatch.setattr(matchers, "_pifatuan_search", None)
    monkeypatch.setattr(matchers, "_text_search", None)
    monkeypatch.setattr(matchers, "_scrapling", None)
    monkeypatch.setattr(matchers, "_playwright", None)
    monkeypatch.setattr(matchers, "_verifier", None)
    monkeypatch.setattr(matchers, "_llm_verifier", None)


def _common_no_network(monkeypatch):
    _reset_matcher_globals(monkeypatch)
    monkeypatch.setattr(matchers, "load_cached_suppliers", lambda *args, **kwargs: [])
    monkeypatch.setattr(matchers, "find_imported_suppliers", lambda *args, **kwargs: [])
    monkeypatch.setattr(matchers, "make_cache_key", lambda *args, **kwargs: "cache")
    monkeypatch.setattr(matchers, "_SCRAPLING_AVAILABLE", False)
    monkeypatch.setattr(matchers, "save_cached_suppliers", lambda *args, **kwargs: None)
    monkeypatch.setattr(matchers, "reset_circuit", lambda: None)
    monkeypatch.setattr(matchers, "is_real_supplier", lambda supplier: False)
    monkeypatch.setattr(settings, "alibaba_app_key", "")
    monkeypatch.setattr(settings, "alibaba_app_secret", "")
    monkeypatch.setattr(settings, "alibaba_access_token", "")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", False)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", True)


def test_terro_query_plan_uses_supply_language_and_never_quantity_alone():
    product = ProductDTO(
        asin="B00E4GACB8",
        marketplace="US",
        title="TERRO Liquid Ant Killer Bait Stations, 12 Count",
        category="Home & Kitchen",
    )

    dimensions = matchers._extract_dimensional_keywords(product.title)
    seller_terms = matchers._supply_chain_keywords(["ant traps indoor"])
    queries = matchers._build_enriched_keywords(
        dimensions,
        [*seller_terms, *matchers._title_fallback_keywords(product.title)],
    )

    assert any("灭蚁" in query for query in queries)
    assert "12件套" not in queries
    assert "12条装" not in queries
    assert all(not matchers._is_spec_only_keyword(query) for query in queries)


def test_bedding_fallback_does_not_turn_solid_into_lid_or_kitchen_query():
    title = (
        "Amazon Basics Lightweight Super Soft, Wrinkle-Free, Breathable Luxury "
        "Microfiber 4 Piece Bed Sheet Set with 14-Inch Deep Pockets, Full, Dark Gray, Solid"
    )
    fallback = matchers._title_fallback_keywords(title)
    queries = matchers._build_enriched_keywords(
        matchers._extract_dimensional_keywords(title), fallback
    )

    assert "带盖" not in fallback
    assert "床品套件" in queries
    assert all("带盖" not in query for query in queries)


def test_match_suppliers_enqueues_when_circuit_is_open(monkeypatch):
    _common_no_network(monkeypatch)
    enqueued = []
    monkeypatch.setattr(matchers, "circuit_is_open", lambda: True)
    monkeypatch.setattr(
        matchers,
        "enqueue_sourcing_block",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )

    with pytest.raises(HumanActionRequired) as exc_info:
        matchers.match_suppliers(_product(), top_k=3)

    assert exc_info.value.error_code == "CAPTCHA_COOLDOWN"
    assert "当前 9222 页面可能没有验证码" in exc_info.value.instructions
    assert enqueued
    assert enqueued[0][1]["reason"] == "1688 search cooldown active"


def test_match_suppliers_enqueues_on_tmd_block(monkeypatch):
    _common_no_network(monkeypatch)
    enqueued = []
    opened = []

    class FakePlaywright:
        def __init__(self, *args, **kwargs):
            pass

        def search_by_keyword(self, keywords, limit):
            raise RuntimeError("1688 TMD 验证码拦截，请刷新 1688 登录态并手动解验证码")

    monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
    monkeypatch.setattr(matchers, "open_circuit", lambda *args, **kwargs: opened.append((args, kwargs)))
    monkeypatch.setattr(
        matchers,
        "enqueue_sourcing_block",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", FakePlaywright)

    with pytest.raises(HumanActionRequired) as exc_info:
        matchers.match_suppliers(_product(), top_k=3)

    assert exc_info.value.error_code == "CAPTCHA"
    assert opened
    assert enqueued
    assert "TMD" in enqueued[0][1]["reason"]


def test_match_suppliers_stops_when_no_usable_1688_keywords(monkeypatch):
    _common_no_network(monkeypatch)
    enqueued = []

    product = ProductDTO(
        asin="B07984JN3L",
        marketplace="US",
        title="B07984JN3L 3L",
        category="Home & Kitchen",
        main_image_url=None,
    )

    class FailPlaywright:
        def __init__(self, *args, **kwargs):
            raise AssertionError("playwright should not run without usable search keywords")

    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)
    monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", FailPlaywright)
    monkeypatch.setattr(
        matchers,
        "enqueue_sourcing_block",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )

    suppliers = matchers.match_suppliers(product, top_k=3)

    assert suppliers == []
    assert enqueued
    assert enqueued[0][1]["keywords"] == []
    assert "no usable 1688 search keywords" in enqueued[0][1]["reason"]


def test_cached_suppliers_still_run_verifier(monkeypatch):
    _common_no_network(monkeypatch)
    cached = SupplierDTO(
        alibaba_offer_id="123456789",
        supplier_name="Cached factory",
        title_cn="304不锈钢 700ml 水杯",
    )
    calls = []

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            calls.append((suppliers, search_keywords))
            suppliers[0].raw_data["spec_match"] = {"score": 0.8, "matched": ["material"]}
            return suppliers

    monkeypatch.setattr(matchers, "load_cached_suppliers", lambda *args, **kwargs: [cached])
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())

    suppliers = matchers.match_suppliers(_product(), top_k=3)

    assert suppliers == [cached]
    assert calls
    assert suppliers[0].raw_data["spec_match"]["score"] == 0.8


def test_imported_suppliers_run_before_live_1688_paths(monkeypatch):
    _common_no_network(monkeypatch)
    imported = SupplierDTO(
        alibaba_offer_id="import-1",
        supplier_name="Imported Factory",
        title_cn="304不锈钢 700ml 水杯",
        raw_data={"source": "alibaba_import"},
    )
    calls = []

    class FailPlaywright:
        def __init__(self, *args, **kwargs):
            raise AssertionError("playwright should not run when imported candidates exist")

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            calls.append((suppliers, search_keywords))
            return suppliers

    monkeypatch.setattr(matchers, "find_imported_suppliers", lambda keywords, top_k: [imported])
    monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", FailPlaywright)
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())

    suppliers = matchers.match_suppliers(_product(), top_k=3)

    assert suppliers == [imported]
    assert calls


def test_match_suppliers_prefers_pifatuan_when_open_platform_token_exists(monkeypatch):
    _common_no_network(monkeypatch)
    calls = []
    supplier = SupplierDTO(
        alibaba_offer_id="pft-1",
        supplier_name="Pifatuan Factory",
        title_cn="304不锈钢 700ml 水杯",
        raw_data={"source": "alibaba_pifatuan"},
    )

    class FakePifatuan:
        def search(self, keywords, top_k):
            calls.append((keywords, top_k))
            return [supplier]

    class FailTextSearch:
        def search(self, keywords, top_k):
            raise AssertionError("generic text API should not run after pifatuan returns suppliers")

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            return suppliers

    monkeypatch.setattr(settings, "alibaba_app_key", "app")
    monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "token")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FakePifatuan())
    monkeypatch.setattr(matchers, "Alibaba1688TextSearch", lambda: FailTextSearch())
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())

    suppliers = matchers.match_suppliers(_product(), top_k=3)

    assert suppliers == [supplier]
    assert calls


def test_unrelated_imported_suppliers_do_not_block_open_platform(monkeypatch):
    _common_no_network(monkeypatch)
    calls = []
    supplier = SupplierDTO(
        alibaba_offer_id="pft-2",
        supplier_name="Live Factory",
        title_cn="304不锈钢 700ml 水杯",
        raw_data={"source": "alibaba_pifatuan"},
    )

    class FakePifatuan:
        def search(self, keywords, top_k):
            calls.append((keywords, top_k))
            return [supplier]

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            return suppliers

    monkeypatch.setattr(matchers, "find_imported_suppliers", lambda keywords, top_k: [])
    monkeypatch.setattr(settings, "alibaba_app_key", "app")
    monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "token")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FakePifatuan())
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())

    suppliers = matchers.match_suppliers(_product(), top_k=3)

    assert suppliers == [supplier]
    assert calls


def test_match_suppliers_enriches_top_suppliers_with_cached_detail(monkeypatch):
    _common_no_network(monkeypatch)
    supplier = SupplierDTO(
        alibaba_offer_id="780485617589",
        supplier_name="Live Factory",
        title_cn="304不锈钢水杯",
        offer_url="https://detail.1688.com/offer/780485617589.html",
        raw_data={"source": "alibaba_pifatuan"},
    )

    class FakePifatuan:
        def search(self, keywords, top_k):
            return [supplier]

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            return suppliers

    class FailPlaywright:
        def enrich_supplier_detail(self, supplier):
            raise AssertionError("cached detail should avoid detail page")

    monkeypatch.setattr(settings, "alibaba_app_key", "app")
    monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "token")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(settings, "alibaba_detail_enrich_limit", 2, raising=False)
    monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FakePifatuan())
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *args, **kwargs: FailPlaywright())
    monkeypatch.setattr(matchers, "load_cached_offer_detail", lambda offer_id, ttl_seconds: {
        "moq": 25,
        "delivery_days": 7,
        "product_dimensions_cm": "8.0x8.0x26.0cm",
    })
    saved = []
    monkeypatch.setattr(matchers, "save_cached_offer_detail", lambda *args, **kwargs: saved.append((args, kwargs)))

    suppliers = matchers.match_suppliers(_product(), top_k=3)

    assert suppliers[0].moq == 25
    assert suppliers[0].delivery_days == 7
    assert suppliers[0].product_dimensions_cm == "8.0x8.0x26.0cm"
    assert suppliers[0].raw_data["detail_enrichment"]["source"] == "cache"
    assert saved == []


def test_match_suppliers_detail_enrichment_is_bounded(monkeypatch):
    _common_no_network(monkeypatch)
    suppliers = [
        SupplierDTO(
            alibaba_offer_id=f"78048561758{i}",
            supplier_name=f"Factory {i}",
            title_cn="水杯",
            offer_url=f"https://detail.1688.com/offer/78048561758{i}.html",
            raw_data={"source": "alibaba_pifatuan"},
        )
        for i in range(3)
    ]
    enriched = []

    class FakePifatuan:
        def search(self, keywords, top_k):
            return suppliers

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            return suppliers

    class FakePlaywright:
        def enrich_supplier_detail(self, supplier):
            enriched.append(supplier.alibaba_offer_id)
            supplier.moq = 10
            supplier.raw_data.setdefault("detail", {})["moq"] = 10
            return supplier

    monkeypatch.setattr(settings, "alibaba_app_key", "app")
    monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "token")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(settings, "alibaba_detail_enrich_limit", 2, raising=False)
    monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FakePifatuan())
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *args, **kwargs: FakePlaywright())
    monkeypatch.setattr(matchers, "load_cached_offer_detail", lambda offer_id, ttl_seconds: {})
    saved = []
    monkeypatch.setattr(matchers, "save_cached_offer_detail", lambda *args, **kwargs: saved.append(args))

    result = matchers.match_suppliers(_product(), top_k=3)

    assert enriched == ["780485617580", "780485617581"]
    assert result[0].raw_data["detail_enrichment"]["source"] == "playwright"
    assert len(saved) == 2


def test_invalid_detail_is_neither_applied_nor_cached(monkeypatch):
    _common_no_network(monkeypatch)
    supplier = SupplierDTO(
        alibaba_offer_id="780485617589",
        supplier_name="Live Factory",
        title_cn="304不锈钢水杯",
        offer_url="https://detail.1688.com/offer/780485617589.html",
        raw_data={"source": "alibaba_pifatuan"},
    )

    class FakePifatuan:
        def search(self, keywords, top_k):
            return [supplier]

    class FakeVerifier:
        def verify(self, suppliers, product, analysis=None, search_keywords=None):
            return suppliers

    class InvalidDetailPlaywright:
        def enrich_supplier_detail(self, candidate):
            candidate.raw_data["detail_error"] = "OFFER_ID_MISMATCH"
            return candidate

    monkeypatch.setattr(settings, "alibaba_app_key", "app")
    monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "token")
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(settings, "alibaba_detail_enrich_limit", 1, raising=False)
    monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FakePifatuan())
    monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: FakeVerifier())
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *args, **kwargs: InvalidDetailPlaywright())
    monkeypatch.setattr(matchers, "load_cached_offer_detail", lambda *args, **kwargs: {})
    saved = []
    monkeypatch.setattr(matchers, "save_cached_offer_detail", lambda *args, **kwargs: saved.append(args))

    result = matchers.match_suppliers(_product(), top_k=3)

    assert result[0].moq is None
    assert "detail" not in result[0].raw_data
    assert saved == []


def test_detail_captcha_stops_batch_and_enqueues_handoff(monkeypatch):
    _common_no_network(monkeypatch)
    supplier = SupplierDTO(
        alibaba_offer_id="780485617590",
        supplier_name="Blocked Factory",
        title_cn="304不锈钢水杯",
        offer_url="https://detail.1688.com/offer/780485617590.html",
        raw_data={"source": "alibaba_import"},
    )
    enqueued = []

    class CaptchaPlaywright:
        def enrich_supplier_detail(self, _candidate):
            raise HumanActionRequired("CAPTCHA", "detail slider required")

    monkeypatch.setattr(matchers, "find_imported_suppliers", lambda *args, **kwargs: [supplier])
    monkeypatch.setattr(settings, "alibaba_detail_enrich_limit", 1, raising=False)
    monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *args, **kwargs: CaptchaPlaywright())
    monkeypatch.setattr(matchers, "load_cached_offer_detail", lambda *args, **kwargs: {})
    monkeypatch.setattr(matchers, "open_circuit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        matchers,
        "enqueue_sourcing_block",
        lambda *args, **kwargs: enqueued.append((args, kwargs)),
    )

    with pytest.raises(HumanActionRequired) as exc_info:
        matchers.match_suppliers(_product(), top_k=3)

    assert exc_info.value.error_code == "CAPTCHA"
    assert enqueued

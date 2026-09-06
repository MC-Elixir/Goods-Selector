"""Tests for SellerSprite extension 1688 sourcing integration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent.cancellation import CancellationRequested
from agent.sellersprite_1688_sourcing import (
    _convert_to_supplier_dtos,
    _extract_offer_id,
    _parse_int,
    _parse_percentage,
    _parse_price,
    _parse_sales_volume,
    run_sellersprite_1688_sourcing,
)
from agent.sellersprite_models import SellerSpriteLocatorProfile
from agent.tools.sellersprite_browser import (
    PlaywrightSellerSpriteSession,
    SellerSpriteWorkflowError,
    _merge_raw_sourcing_cards,
)
from execution.models import HumanActionRequired


# ============================================================
# Fixtures
# ============================================================

def _base_locators(**overrides) -> dict[str, str]:
    """Minimal valid locator profile dict with optional overrides."""
    locators = {
        "panel_open": "css=#ext .logo",
        "ready": "css=#ext .main",
        "login_required": "css=#ext .login",
        "permission_required": "text=权限不足",
        "captcha": "css=#ext .captcha",
        "reverse_keywords": "css=#ext .nav-reverse",
        "asin_input": "css=#ext input",
        "submit": "css=#ext .submit",
        "results_ready": "css=#ext .results",
        "export_menu": "css=#ext .export-menu",
        "export": "css=#ext .export",
    }
    locators.update(overrides)
    return locators


def _sourcing_locators(**overrides) -> dict[str, str]:
    """Locator profile with 1688 sourcing locators configured."""
    return _base_locators(
        sourcing_1688_nav="css=#ext .nav-1688",
        sourcing_1688_results="css=#ext .results-1688",
        sourcing_1688_card="css=#ext .card-1688",
        sourcing_1688_login="css=#ext .login-1688",
        **overrides,
    )


def _profile(**overrides) -> SellerSpriteLocatorProfile:
    return SellerSpriteLocatorProfile(**_base_locators(**overrides))


def _sourcing_profile(**overrides) -> SellerSpriteLocatorProfile:
    return SellerSpriteLocatorProfile(**_sourcing_locators(**overrides))


# ============================================================
# Locator profile tests
# ============================================================

class TestLocatorProfile:
    def test_has_sourcing_1688_locators_true(self):
        profile = _sourcing_profile()
        assert profile.has_sourcing_1688_locators() is True

    def test_has_sourcing_1688_locators_false_when_missing(self):
        profile = _profile()
        assert profile.has_sourcing_1688_locators() is False

    def test_has_sourcing_1688_locators_false_when_partial(self):
        profile = _profile(sourcing_1688_nav="css=#ext .nav")
        assert profile.has_sourcing_1688_locators() is False

    def test_from_json_with_sourcing_locators(self, tmp_path):
        data = _sourcing_locators()
        path = tmp_path / "locators.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        profile = SellerSpriteLocatorProfile.from_json(path)
        assert profile.has_sourcing_1688_locators() is True
        assert profile.sourcing_1688_nav == "css=#ext .nav-1688"

    def test_from_json_without_sourcing_locators(self, tmp_path):
        data = _base_locators()
        path = tmp_path / "locators.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        profile = SellerSpriteLocatorProfile.from_json(path)
        assert profile.has_sourcing_1688_locators() is False
        assert profile.sourcing_1688_nav == ""


# ============================================================
# Data conversion tests
# ============================================================

class TestConvertToSupplierDTOs:
    def test_basic_conversion(self):
        raw = [
            {
                "title": "304不锈钢保温杯 700ml",
                "price": "¥25.50",
                "moq": "50件起订",
                "monthly_sales": "月销 1200+",
                "supplier_name": "宁波源头工厂",
                "offer_url": "https://detail.1688.com/offer/123456789.html",
                "image_url": "https://img.example/a.jpg",
                "is_factory": True,
            }
        ]
        dtos = _convert_to_supplier_dtos(raw, "B00Q7OAN50")
        assert len(dtos) == 1
        dto = dtos[0]
        assert dto.alibaba_offer_id == "123456789"
        assert dto.title_cn == "304不锈钢保温杯 700ml"
        assert dto.base_price_cny == 25.50
        assert dto.moq == 50
        assert dto.monthly_sales == 1200
        assert dto.supplier_name == "宁波源头工厂"
        assert dto.is_factory is True
        assert dto.raw_data["source"] == "sellersprite_1688"
        assert dto.match_verification_method == "sellersprite_extension_unverified"
        assert dto.match_quality_score is None

    def test_deduplication_by_offer_id(self):
        raw = [
            {
                "title": "产品A",
                "offer_url": "https://detail.1688.com/offer/111.html",
            },
            {
                "title": "产品A 重复",
                "offer_url": "https://detail.1688.com/offer/111.html",
            },
        ]
        dtos = _convert_to_supplier_dtos(raw, "B00Q7OAN50")
        assert len(dtos) == 1

    def test_skips_empty_title(self):
        raw = [{"title": "", "price": "10"}]
        dtos = _convert_to_supplier_dtos(raw, "B00Q7OAN50")
        assert len(dtos) == 0

    def test_skips_candidate_without_verifiable_offer_identity(self):
        raw = [{"title": "无链接产品"}]
        dtos = _convert_to_supplier_dtos(raw, "B00Q7OAN50")
        assert dtos == []

    def test_multiple_suppliers(self):
        raw = [
            {
                "title": f"产品{i}",
                "price": str(10 + i),
                "offer_url": f"https://detail.1688.com/offer/{1000 + i}.html",
            }
            for i in range(5)
        ]
        dtos = _convert_to_supplier_dtos(raw, "B00Q7OAN50")
        assert len(dtos) == 5

    def test_newton_card_with_real_offer_identity_is_retained(self):
        dtos = _convert_to_supplier_dtos(
            [{
                "title": "水果杯304不锈钢弹跳杯",
                "price": "16.00",
                "moq": "一件起订",
                "monthly_sales": "10+",
                "repeat_buyer_rate": "67%",
                "supplier_name": "永康市云迹工贸有限公司",
                "offer_url": "https://detail.1688.com/offer/1048948332973.html",
            }],
            "B00Q7OAN50",
        )

        assert len(dtos) == 1
        assert dtos[0].alibaba_offer_id == "1048948332973"
        assert dtos[0].repeat_buyer_rate == 0.67

    def test_newton_wan_sales_and_factory_type_are_preserved(self):
        dtos = _convert_to_supplier_dtos(
            [{
                "title": "1钓鱼伞折叠加大鱼伞",
                "price": "21.00",
                "moq": "一件起订",
                "monthly_sales": "1.4万+",
                "repeat_buyer_rate": "24%",
                "supplier_name": "泗阳至上户外用品有限公司",
                "offer_url": "https://detail.1688.com/offer/988881692944.html",
                "is_factory": True,
                "gm_type": "生产厂家",
                "merchant_identity": "超级工厂",
            }],
            "B0GGB2RMWK",
        )

        assert len(dtos) == 1
        assert dtos[0].monthly_sales == 14000
        assert dtos[0].is_factory is True
        assert dtos[0].repeat_buyer_rate == 0.24

    def test_factory_inferred_from_gm_type_when_flag_missing(self):
        dtos = _convert_to_supplier_dtos(
            [{
                "title": "庭院遮阳伞",
                "offer_url": "https://detail.1688.com/offer/650725223528.html",
                "gm_type": "生产厂家",
            }],
            "B0GGB2RMWK",
        )
        assert dtos[0].is_factory is True

    def test_dialog_card_parses_sales_repeat_and_moq_without_fake_company(self):
        dtos = _convert_to_supplier_dtos(
            [{
                "title": "户外钓鱼伞2.2米2.4米钓伞万向防雨折叠钓鱼专用大伞防紫外线",
                "price": "¥40.80",
                "moq": "1条起批",
                "monthly_sales": "月销量:1,240",
                "repeat_buyer_rate": "复购率:11%",
                "supplier_name": "",
                "offer_url": "https://detail.1688.com/offer/1018589675416.html",
            }],
            "B0GGB2RMWK",
        )
        assert len(dtos) == 1
        assert dtos[0].monthly_sales == 1240
        assert dtos[0].repeat_buyer_rate == 0.11
        assert dtos[0].moq == 1
        assert dtos[0].base_price_cny == 40.8
        assert dtos[0].supplier_name is None


class TestMergeRawSourcingCards:
    def test_dialog_keeps_exact_sales_and_fills_newton_company(self):
        merged = _merge_raw_sourcing_cards(
            [{
                "title": "户外钓鱼伞",
                "monthly_sales": "月销量:1,240",
                "repeat_buyer_rate": "11%",
                "supplier_name": "",
                "offer_url": "https://detail.1688.com/offer/1018589675416.html",
            }],
            [{
                "title": "户外钓鱼伞",
                "monthly_sales": "1.4万+",
                "supplier_name": "宿迁市林涧风户外用品有限公司",
                "gm_type": "生产厂家",
                "is_factory": True,
                "offer_url": "https://detail.1688.com/offer/1018589675416.html",
            }],
        )
        assert merged[0]["monthly_sales"] == "月销量:1,240"
        assert merged[0]["supplier_name"] == "宿迁市林涧风户外用品有限公司"
        assert merged[0]["is_factory"] is True
        assert merged[0]["gm_type"] == "生产厂家"


# ============================================================
# Parsing helper tests
# ============================================================

class TestParseHelpers:
    @pytest.mark.parametrize("value,expected", [
        ("¥25.50", 25.50),
        ("￥12.00-25.00", 12.00),
        ("$9.99", 9.99),
        ("15", 15.0),
        ("", None),
        (None, None),
        ("免费", None),
        ("￥", None),
        ("0", None),
    ])
    def test_parse_price(self, value, expected):
        assert _parse_price(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("月销 1200+", 1200),
        ("1条起批", 1),
        ("50件起订", 50),
        ("1,200", 1200),
        (100, 100),
        (0, None),
        ("", None),
        (None, None),
        ("无", None),
    ])
    def test_parse_int(self, value, expected):
        assert _parse_int(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("1.4万+", 14000),
        ("2.6万+", 26000),
        ("10万+", 100000),
        ("3100+", 3100),
        ("900+", 900),
        ("月销 1200+", 1200),
        (14000, 14000),
        ("月销量:1,240", 1240),
        ("月销量:20,267", 20267),
        ("1,240最近30天交易记录", 1240),
        ("", None),
        (None, None),
    ])
    def test_parse_sales_volume(self, value, expected):
        assert _parse_sales_volume(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("67%", 0.67),
        ("4.5%", 0.045),
        ("24.8%", 0.248),
        ("24", 0.24),
        (0.59, 0.59),
        ("-", None),
        (None, None),
        ("120%", None),
    ])
    def test_parse_percentage(self, value, expected):
        assert _parse_percentage(value) == expected

    @pytest.mark.parametrize("url,expected", [
        ("https://detail.1688.com/offer/123456789.html", "123456789"),
        ("https://m.1688.com/offer/987654321.html", "987654321"),
        ("https://detail.1688.com/offer.htm?offerId=24680", "24680"),
        ("https://example.com/no-offer", ""),
        ("https://example.com/offer/123.html", ""),
        ("", ""),
    ])
    def test_extract_offer_id(self, url, expected):
        assert _extract_offer_id(url) == expected


# ============================================================
# Service orchestration tests (mock session)
# ============================================================

class FakeSession:
    """Minimal fake session for testing the service layer."""

    def __init__(self, suppliers: list[dict] | None = None, error: str | None = None):
        self._suppliers = suppliers or []
        self._error = error
        self.opened_asin: str | None = None
        self.extension_checked = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def open_amazon_product(self, asin: str):
        self.opened_asin = asin

    def check_sellersprite_extension(self):
        self.extension_checked = True

    def source_1688_suppliers(self, asin: str) -> list[dict]:
        if self._error:
            raise SellerSpriteWorkflowError(self._error)
        return self._suppliers


class FakeDeps:
    """Minimal fake dependencies for testing without real Chrome."""

    def __init__(self, session, profile=None, enabled=True):
        self.browser_enabled = enabled
        self.profile = profile or _sourcing_profile()
        self.session_factory = lambda: session
        self.is_cancelled = lambda: False


class TestRunSellersprite1688Sourcing:
    def test_success_returns_suppliers(self):
        raw = [
            {
                "title": "保温杯",
                "price": "25.5",
                "offer_url": "https://detail.1688.com/offer/111.html",
            }
        ]
        session = FakeSession(suppliers=raw)
        deps = FakeDeps(session)
        result = run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert len(result) == 1
        assert result[0].alibaba_offer_id == "111"
        assert session.opened_asin == "B00Q7OAN50"
        assert session.extension_checked is True

    def test_extension_unavailable_requests_human_action_when_profile_is_configured(self):
        session = FakeSession(error="EXTENSION_UNAVAILABLE")
        deps = FakeDeps(session)
        with pytest.raises(HumanActionRequired) as exc_info:
            run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert exc_info.value.error_code == "EXTENSION_UNAVAILABLE"

    def test_login_required_requests_human_action(self):
        session = FakeSession(error="SELLERSPRITE_LOGIN_REQUIRED")
        deps = FakeDeps(session)
        with pytest.raises(HumanActionRequired) as exc_info:
            run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert exc_info.value.error_code == "SELLERSPRITE_LOGIN_REQUIRED"
        assert "9222" in exc_info.value.instructions

    def test_disabled_returns_empty(self):
        session = FakeSession(suppliers=[{"title": "test"}])
        deps = FakeDeps(session, enabled=False)
        result = run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert result == []

    def test_disabled_is_human_barrier_for_formal_pipeline(self):
        session = FakeSession(suppliers=[])
        deps = FakeDeps(session, enabled=False)
        with pytest.raises(HumanActionRequired) as exc_info:
            run_sellersprite_1688_sourcing(
                "B00Q7OAN50", dependencies=deps, required=True
            )
        assert exc_info.value.error_code == "EXTENSION_UNAVAILABLE"


    def test_no_sourcing_locators_returns_empty(self):
        session = FakeSession(suppliers=[{"title": "test"}])
        deps = FakeDeps(session, profile=_profile())  # No sourcing locators
        result = run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert result == []

    def test_empty_results_returns_empty(self):
        session = FakeSession(suppliers=[])
        deps = FakeDeps(session)
        result = run_sellersprite_1688_sourcing("B00Q7OAN50", dependencies=deps)
        assert result == []

    def test_cancel_check_respected(self):
        raw = [{"title": "保温杯", "price": "25.5"}]
        session = FakeSession(suppliers=raw)
        deps = FakeDeps(session)
        # Cancel after open_amazon_product
        call_count = [0]
        def cancel():
            call_count[0] += 1
            return call_count[0] > 1
        with pytest.raises(CancellationRequested):
            run_sellersprite_1688_sourcing(
                "B00Q7OAN50", cancel_check=cancel, dependencies=deps
            )


# ============================================================
# Browser session method tests (mock page)
# ============================================================

def test_formal_match_merges_market_keywords_into_verification_and_audit(monkeypatch):
    from types import SimpleNamespace
    from matchers.alibaba_pailitao import SupplierDTO
    from pipeline.recoverable import _formal_match_suppliers

    supplier = SupplierDTO(
        alibaba_offer_id="111",
        offer_url="https://detail.1688.com/offer/111.html",
        title_cn="户外遮阳伞",
        raw_data={"source": "sellersprite_1688"},
    )
    captured = {}
    monkeypatch.setattr(
        "agent.sellersprite_1688_sourcing.run_sellersprite_1688_sourcing",
        lambda *args, **kwargs: [supplier],
    )
    monkeypatch.setattr("matchers._enrich_supplier_details", lambda values, *args, **kwargs: values)
    monkeypatch.setattr("matchers._title_fallback_keywords", lambda title: ["遮阳伞"])

    class Verifier:
        def verify(self, *, suppliers, product, analysis, search_keywords):
            captured["keywords"] = search_keywords
            return suppliers

    monkeypatch.setattr("matchers.verifier.Alibaba1688Verifier", Verifier)
    result = _formal_match_suppliers(
        SimpleNamespace(asin="B00Q7OAN50", title="Patio Umbrella", raw_data={}),
        market_keywords=["patio umbrella", "outdoor shade"],
    )
    assert captured["keywords"] == ["patio umbrella", "outdoor shade", "遮阳伞"]
    assert result[0].raw_data["search_query_plan"]["market_keywords"] == [
        "patio umbrella", "outdoor shade"
    ]

class FakeLocator:
    def __init__(self, count=0, evaluate_results=None):
        self._count = count
        self._evaluate_results = evaluate_results or []
        self._clicked = False

    def count(self):
        return self._count

    def nth(self, i):
        return self

    def evaluate(self, js):
        if i < len(self._evaluate_results):
            return self._evaluate_results[i]
        return {}

    def is_visible(self):
        return True

    def wait_for(self, **kwargs):
        pass

    def click(self, **kwargs):
        self._clicked = True


class TestSource1688SuppliersMethod:
    def test_raises_without_locators(self):
        profile = _profile()  # No sourcing locators
        session = PlaywrightSellerSpriteSession(
            profile=profile,
            download_dir="/tmp",
            page=object(),
        )
        with pytest.raises(SellerSpriteWorkflowError, match="EXTENSION_UNAVAILABLE"):
            session.source_1688_suppliers("B00Q7OAN50")

    def test_waits_for_attached_card_when_result_is_below_fold(self, monkeypatch):
        session = PlaywrightSellerSpriteSession(
            profile=_sourcing_profile(),
            download_dir="/tmp",
            page=object(),
        )
        locator = FakeLocator(count=1)
        monkeypatch.setattr(session, "_locator", lambda _name: locator)

        assert session._wait_until_attached("sourcing_1688_results") is True

    def test_is_visible_uses_first_match_when_locator_is_strict(self, monkeypatch):
        session = PlaywrightSellerSpriteSession(
            profile=_sourcing_profile(),
            download_dir="/tmp",
            page=_FakeTab("https://www.amazon.com/dp/B0GGB2RMWK"),
        )

        class _First:
            def is_visible(self) -> bool:
                return True

        class _Strict:
            first = _First()

            def is_visible(self) -> bool:
                raise RuntimeError("strict mode violation: resolved to 2 elements")

        monkeypatch.setattr(session, "_locator", lambda _name: _Strict())
        assert session._is_visible("sourcing_1688_nav") is True

    def test_extracts_modal_cards_without_leaving_amazon(self, monkeypatch):
        amazon = _FakeTab("https://www.amazon.com/dp/B0GGB2RMWK")
        session = _session_with_tabs(amazon)
        switched: list[object] = []

        class _CardLocator:
            def count(self) -> int:
                return 1

            def nth(self, _index: int) -> "_CardLocator":
                return self

            def evaluate(self, _js: str) -> dict[str, str]:
                return {
                    "title": "户外遮阳伞",
                    "offer_url": "https://detail.1688.com/offer/988881692944.html",
                    "price": "21.00",
                    "supplier_name": "泗阳至上户外用品有限公司",
                }

        monkeypatch.setattr(session, "_raise_if_human_terminal", lambda: None)
        monkeypatch.setattr(session, "_is_visible", lambda _name: False)
        monkeypatch.setattr(session, "_reveal_sourcing_1688_nav", lambda: None)
        monkeypatch.setattr(session, "_click_required", lambda _name: None)
        monkeypatch.setattr(
            session,
            "_switch_to_sourcing_1688_page",
            lambda known: switched.append(known),
        )
        monkeypatch.setattr(
            session,
            "_wait_until_attached",
            lambda _name, timeout_seconds=None: True,
        )
        monkeypatch.setattr(session, "_locator", lambda _name: _CardLocator())

        result = session.source_1688_suppliers("B0GGB2RMWK")

        assert switched == []
        assert result[0]["title"] == "户外遮阳伞"
        assert "988881692944" in result[0]["offer_url"]


class _FakeTab:
    def __init__(self, url: str) -> None:
        self.url = url

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def wait_for_load_state(self, *_args, **_kwargs) -> None:
        return None


def _session_with_tabs(*tabs: _FakeTab) -> PlaywrightSellerSpriteSession:
    amazon = tabs[0]
    browser = type("Browser", (), {
        "contexts": [type("Context", (), {"pages": list(tabs)})()],
    })()
    session = PlaywrightSellerSpriteSession(
        profile=_sourcing_profile(),
        download_dir="/tmp",
        page=amazon,
        page_timeout_seconds=1,
        export_timeout_seconds=1,
    )
    session._browser = browser
    return session


class TestSwitchToSourcing1688Page:
    def test_reuses_existing_newton_tab_when_click_does_not_open_a_new_one(self):
        amazon = _FakeTab("https://www.amazon.com/dp/B0GGB2RMWK")
        newton = _FakeTab(
            "https://aibuy.1688.com/landingpage/new-home/find-products.html"
        )
        session = _session_with_tabs(amazon, newton)

        session._switch_to_sourcing_1688_page((amazon, newton))

        assert session.page is newton

    def test_prefers_a_newly_opened_newton_tab_over_an_existing_one(self):
        amazon = _FakeTab("https://www.amazon.com/dp/B0GGB2RMWK")
        stale = _FakeTab(
            "https://aibuy.1688.com/landingpage/new-home/find-products.html?old=1"
        )
        fresh = _FakeTab(
            "https://aibuy.1688.com/landingpage/new-home/find-products.html?new=1"
        )
        session = _session_with_tabs(amazon, stale, fresh)

        session._switch_to_sourcing_1688_page((amazon, stale))

        assert session.page is fresh

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
    _parse_price,
    run_sellersprite_1688_sourcing,
)
from agent.sellersprite_models import SellerSpriteLocatorProfile
from agent.tools.sellersprite_browser import (
    PlaywrightSellerSpriteSession,
    SellerSpriteWorkflowError,
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
        ("0", None),
    ])
    def test_parse_price(self, value, expected):
        assert _parse_price(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("月销 1200+", 1200),
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

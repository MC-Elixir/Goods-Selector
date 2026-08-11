"""match_suppliers 降级链聚焦测试。

覆盖场景：
  1. 首选路径成功时直接返回（不触发后续路径）
  2. 首选路径失败时降级到次选路径
  3. 所有路径失败时返回 mock fallback
  4. circuit breaker 开启时跳过对应路径
"""
from __future__ import annotations

import pytest

import matchers
from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from execution.models import HumanActionRequired
from matchers.alibaba_pailitao import SupplierDTO


# ============================================================
# Fixtures & helpers
# ============================================================


def _product() -> ProductDTO:
    return ProductDTO(
        asin="BDEGRADE01",
        marketplace="US",
        title="24 oz stainless steel insulated water bottle",
        category="Sports",
        main_image_url=None,
    )


def _supplier(offer_id: str, name: str, source: str = "test") -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=name,
        title_cn="304不锈钢保温杯",
        raw_data={"source": source},
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
    """Block all external I/O; leave degradation path controls to each test."""
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
    monkeypatch.setattr(settings, "enable_scrapling_matcher", False)
    monkeypatch.setattr(settings, "enable_image_search", False)


class _PassthroughVerifier:
    """Verifier that returns suppliers unchanged."""

    def verify(self, suppliers, product, analysis=None, search_keywords=None):
        return suppliers


# ============================================================
# 1. 首选路径成功时直接返回
# ============================================================


class TestPrimaryPathSuccess:
    """Playwright 成功时不应触发 mock fallback。"""

    def test_playwright_success_returns_real_suppliers(self, monkeypatch):
        _common_no_network(monkeypatch)
        expected = _supplier("100000001", "Playwright Factory", source="playwright")
        calls = []

        class FakePlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                calls.append(keywords)
                return [expected]

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FakePlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert len(result) == 1
        assert result[0].alibaba_offer_id == "100000001"
        assert result[0].supplier_name == "Playwright Factory"
        assert calls  # Playwright was actually invoked

    def test_playwright_success_does_not_generate_mock(self, monkeypatch):
        """正向验证：成功路径不产生 mock 货源。"""
        _common_no_network(monkeypatch)
        real = _supplier("200000002", "Real Factory", source="playwright")

        class FakePlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                return [real]

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FakePlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert all(s.raw_data.get("source") != "mock" for s in result)


# ============================================================
# 2. 首选路径失败时降级到次选路径
# ============================================================


class TestDegradationToSecondaryPath:
    """Playwright 失败后降级到 mock。Scrapling 失败后降级到 Playwright。"""

    def test_playwright_failure_falls_back_to_mock(self, monkeypatch):
        """Playwright 抛出非 TMD 异常 → 降级到 mock fallback。"""
        _common_no_network(monkeypatch)

        class FailingPlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                raise RuntimeError("connection timeout")

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FailingPlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        # mock fallback produces suppliers
        assert len(result) > 0
        assert all(s.match_verification_method == "mock" for s in result)

    def test_scrapling_failure_degrades_to_playwright(self, monkeypatch):
        """Scrapling 失败 → 降级到 Playwright 成功路径。"""
        _common_no_network(monkeypatch)
        monkeypatch.setattr(matchers, "_SCRAPLING_AVAILABLE", True)
        monkeypatch.setattr(settings, "enable_scrapling_matcher", True)

        pw_supplier = _supplier("300000003", "PW Factory", source="playwright")
        scrapling_calls = []
        playwright_calls = []

        class FailingScrapling:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit):
                scrapling_calls.append(keywords)
                raise RuntimeError("TMD blocked scrapling HTTP")

        class FakePlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                playwright_calls.append(keywords)
                return [pw_supplier]

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688ScraplingMatcher", lambda *a, **kw: FailingScrapling())
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FakePlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert scrapling_calls  # Scrapling was attempted
        assert playwright_calls  # Playwright was used as fallback
        assert result[0].alibaba_offer_id == "300000003"

    def test_open_api_failure_degrades_to_playwright(self, monkeypatch):
        """Open API (pifatuan + text) 失败 → 降级到 Playwright。"""
        _common_no_network(monkeypatch)
        monkeypatch.setattr(settings, "alibaba_app_key", "key")
        monkeypatch.setattr(settings, "alibaba_app_secret", "secret")
        monkeypatch.setattr(settings, "alibaba_access_token", "token")
        monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)

        pw_supplier = _supplier("400000004", "PW Fallback", source="playwright")

        class FailingPifatuan:
            def search(self, keywords, top_k):
                raise RuntimeError("API 403")

        class FailingTextSearch:
            def search(self, keywords, top_k):
                raise RuntimeError("API 500")

        class FakePlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                return [pw_supplier]

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "AlibabaPifatuanSearch", lambda: FailingPifatuan())
        monkeypatch.setattr(matchers, "Alibaba1688TextSearch", lambda: FailingTextSearch())
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FakePlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert result[0].alibaba_offer_id == "400000004"


# ============================================================
# 3. 所有路径失败时返回 mock fallback
# ============================================================


class TestAllPathsFailMockFallback:
    """所有真实路径失败 → mock 兜底。"""

    def test_all_paths_fail_returns_mock_suppliers(self, monkeypatch):
        _common_no_network(monkeypatch)

        class FailingPlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                raise RuntimeError("browser crashed")

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FailingPlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert len(result) > 0
        assert all(s.match_verification_method == "mock" for s in result)
        assert all(s.raw_data.get("source") == "mock" for s in result)

    def test_mock_disabled_returns_empty_when_all_fail(self, monkeypatch):
        """负向：mock 被禁用时，所有路径失败返回空列表。"""
        _common_no_network(monkeypatch)
        monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

        class FailingPlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                raise RuntimeError("browser crashed")

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FailingPlaywright())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert result == []

    def test_tmd_block_skips_mock_and_raises(self, monkeypatch):
        """TMD 拦截 → 开启 circuit、不走 mock、抛 HumanActionRequired。"""
        _common_no_network(monkeypatch)
        opened = []

        class TMDPlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                raise RuntimeError("1688 TMD 验证码拦截")

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "open_circuit", lambda *args, **kwargs: opened.append(args))
        monkeypatch.setattr(matchers, "enqueue_sourcing_block", lambda *args, **kwargs: None)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: TMDPlaywright())

        with pytest.raises(HumanActionRequired) as exc_info:
            matchers.match_suppliers(_product(), top_k=5)

        assert exc_info.value.error_code == "CAPTCHA"
        assert opened  # circuit was opened


# ============================================================
# 4. circuit breaker 开启时跳过对应路径
# ============================================================


class TestCircuitBreakerSkipsPath:
    """circuit breaker 开启 → 跳过 Playwright 搜索并抛出 HumanActionRequired。"""

    def test_circuit_open_raises_human_action_required(self, monkeypatch):
        _common_no_network(monkeypatch)
        enqueued = []

        class FailIfCalledPlaywright:
            def __init__(self, *args, **kwargs):
                raise AssertionError("Playwright must not be instantiated when circuit is open")

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: True)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", FailIfCalledPlaywright)
        monkeypatch.setattr(
            matchers,
            "enqueue_sourcing_block",
            lambda *args, **kwargs: enqueued.append((args, kwargs)),
        )

        with pytest.raises(HumanActionRequired) as exc_info:
            matchers.match_suppliers(_product(), top_k=5)

        assert exc_info.value.error_code == "CAPTCHA_COOLDOWN"
        assert enqueued
        assert enqueued[0][1]["reason"] == "1688 search cooldown active"

    def test_circuit_open_does_not_reach_mock_fallback(self, monkeypatch):
        """负向：circuit 开启时不应产生任何 mock 货源。"""
        _common_no_network(monkeypatch)

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: True)
        monkeypatch.setattr(matchers, "enqueue_sourcing_block", lambda *args, **kwargs: None)

        with pytest.raises(HumanActionRequired):
            matchers.match_suppliers(_product(), top_k=5)

        # If we reach here without exception, the test would fail —
        # the exception itself proves mock was never reached.

    def test_circuit_closed_allows_playwright_search(self, monkeypatch):
        """正向对照：circuit 关闭时 Playwright 正常执行。"""
        _common_no_network(monkeypatch)
        expected = _supplier("500000005", "Normal Factory", source="playwright")
        called = []

        class FakePlaywright:
            def __init__(self, *args, **kwargs):
                pass

            def search_by_keyword(self, keywords, limit, **kwargs):
                called.append(True)
                return [expected]

        monkeypatch.setattr(matchers, "circuit_is_open", lambda: False)
        monkeypatch.setattr(matchers, "Alibaba1688PlaywrightMatcher", lambda *a, **kw: FakePlaywright())
        monkeypatch.setattr(matchers, "Alibaba1688Verifier", lambda: _PassthroughVerifier())

        result = matchers.match_suppliers(_product(), top_k=5)

        assert called
        assert result[0].alibaba_offer_id == "500000005"

import pytest

from matchers._alibaba_playwright_search import enrich_offer_details
from matchers.alibaba_detail import BlockedOfferPage
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_playwright import _enrich_supplier_from_detail_html


def test_enrich_supplier_from_detail_html_updates_playwright_supplier():
    supplier = SupplierDTO(
        alibaba_offer_id="123",
        offer_url="https://detail.1688.com/offer/123.html",
        supplier_name="Bottle Factory",
        raw_data={"source": "alibaba_playwright"},
    )
    html = """
    <html><body>
      <div>起订量 40件</div>
      <div>40件 ¥18.8 120件 ¥15.2</div>
      <div>包装尺寸 8x8x26cm 重量 420g 发货期 6天 品牌授权</div>
    </body></html>
    """

    enriched = _enrich_supplier_from_detail_html(supplier, html)

    assert enriched is supplier
    assert enriched.moq == 40
    assert enriched.base_price_cny == 15.2
    assert enriched.delivery_days == 6
    assert enriched.product_dimensions_cm == "8.0x8.0x26.0cm"
    assert enriched.product_weight_g == 420.0
    assert "brand_authorization_required" in enriched.raw_data["risk_flags"]
    assert enriched.raw_data["detail"]["moq"] == 40


class _FakePage:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.urls = []

    def goto(self, url, **kwargs):
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome

    def content(self):
        return self.outcomes.pop(0)

    def close(self):
        pass


class _FakeContext:
    def __init__(self, page):
        self.page = page
        self.new_page_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        return self.page


def test_detail_fetch_reuses_context_and_enriches_serially_without_default_values():
    page = _FakePage([
        None, '<script>{"offerId":"1","beginAmount":20}</script>',
        None, '<script>{"offerId":"2","attributes":[{"name":"材质","value":"硅胶"}]}</script>',
    ])
    ctx = _FakeContext(page)
    offers = [
        {"offer_id": "1", "url": "https://detail.1688.com/offer/1.html"},
        {"offer_id": "2", "url": "https://detail.1688.com/offer/2.html"},
    ]

    enriched = enrich_offer_details(ctx, offers, jitter_range=(0, 0), sleep=lambda _: None)

    assert ctx.new_page_calls == 1
    assert enriched[0]["detail"]["moq"] == 20
    assert enriched[1]["detail"]["moq"] is None
    assert len(page.urls) == 2


def test_auth_page_is_returned_as_immediate_human_handoff_not_detail():
    ctx = _FakeContext(_FakePage([None, "<title>登录</title>请登录后继续访问"]))

    result = enrich_offer_details(
        ctx, [{"offer_id": "1", "url": "https://detail.1688.com/offer/1.html"}],
        jitter_range=(0, 0), sleep=lambda _: None,
    )[0]

    assert result["detail_status"] == "human_handoff"
    assert result["detail_error_code"] == "AUTH_REQUIRED"
    assert "detail" not in result


def test_transient_timeout_retries_twice_but_auth_does_not_retry():
    timeout_page = _FakePage([TimeoutError("slow"), TimeoutError("slow"), None,
                              '<script>{"offerId":"1","beginAmount":5}</script>'])
    result = enrich_offer_details(
        _FakeContext(timeout_page),
        [{"offer_id": "1", "url": "https://detail.1688.com/offer/1.html"}],
        jitter_range=(0, 0), sleep=lambda _: None,
    )[0]
    assert result["detail"]["moq"] == 5
    assert len(timeout_page.urls) == 3

    auth_page = _FakePage([None, "<body>滑块验证码</body>"])
    auth_result = enrich_offer_details(
        _FakeContext(auth_page),
        [{"offer_id": "1", "url": "https://detail.1688.com/offer/1.html"}],
        jitter_range=(0, 0), sleep=lambda _: None,
    )[0]
    assert auth_result["detail_error_code"] == "CAPTCHA"
    assert len(auth_page.urls) == 1


def test_detail_fetch_rejects_a_different_offer_identity():
    ctx = _FakeContext(_FakePage([
        None, '<script>{"offerId":"2","beginAmount":5}</script>',
    ]))
    result = enrich_offer_details(
        ctx, [{"offer_id": "1", "url": "https://detail.1688.com/offer/1.html"}],
        jitter_range=(0, 0), sleep=lambda _: None,
    )[0]
    assert result["detail_status"] == "human_handoff"
    assert result["detail_error_code"] == "OFFER_ID_MISMATCH"
    assert "detail" not in result

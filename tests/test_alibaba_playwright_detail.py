import pytest

from matchers._alibaba_playwright_search import enrich_offer_details, _parse_offer
from matchers.alibaba_detail import BlockedOfferPage
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_playwright import (
    _CdpContextProxy,
    _ContextManager,
    _enrich_supplier_from_detail_html,
    _visible_human_block,
)


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

    enriched = _enrich_supplier_from_detail_html(
        supplier, html, page_url="https://detail.1688.com/offer/123.html"
    )

    assert enriched is supplier
    assert enriched.moq == 40
    assert enriched.base_price_cny == 15.2
    assert enriched.delivery_days == 6
    assert enriched.product_dimensions_cm == "8.0x8.0x26.0cm"
    assert enriched.product_weight_g == 420.0
    assert "brand_authorization_required" in enriched.raw_data["risk_flags"]
    assert enriched.raw_data["detail"]["moq"] == 40


def test_production_detail_helper_rejects_wrong_offer_before_apply():
    supplier = SupplierDTO(
        alibaba_offer_id="123",
        offer_url="https://detail.1688.com/offer/123.html",
        supplier_name="Bottle Factory",
        moq=None,
        raw_data={"source": "alibaba_playwright"},
    )
    html = '<script>{"offerId":"999","beginAmount":10}</script>'
    with pytest.raises(BlockedOfferPage, match="OFFER_ID_MISMATCH"):
        _enrich_supplier_from_detail_html(
            supplier, html, page_url="https://detail.1688.com/offer/999.html"
        )
    assert supplier.moq is None
    assert "detail" not in supplier.raw_data


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
    assert result["detail_status"] == "blocked_invalid"
    assert result["detail_error_code"] == "OFFER_ID_MISMATCH"
    assert "detail" not in result


def test_detail_fetch_without_identity_is_invalid_not_human_handoff():
    ctx = _FakeContext(_FakePage([
        None, "<body>起订量 5件 价格 ￥10 材质 硅胶</body>",
    ]))
    result = enrich_offer_details(
        ctx, [{"offer_id": "1", "url": "https://example.invalid/product"}],
        jitter_range=(0, 0), sleep=lambda _: None,
    )[0]
    assert result["detail_status"] == "blocked_invalid"
    assert result["detail_error_code"] == "OFFER_ID_UNVERIFIED"


class _CardElement:
    def __init__(self, text="", href=None):
        self._text = text
        self._href = href

    def inner_text(self):
        return self._text

    def get_attribute(self, name):
        return self._href if name == "href" else None


class _SearchCard:
    def query_selector(self, selector):
        if selector == "a.sm-offer-title":
            return _CardElement("硅胶水杯", "https://detail.1688.com/offer/12345678.html")
        if selector == "span.sm-offer-priceNum":
            return _CardElement("¥12.5")
        return None


def test_search_card_missing_moq_remains_none():
    offer = _parse_offer(_SearchCard())
    assert offer is not None
    assert offer["offer_id"] == "12345678"
    assert offer["moq"] is None


class _VisibleBody:
    def __init__(self, text):
        self.text = text

    def inner_text(self, **kwargs):
        return self.text


class _VisiblePage:
    def __init__(self, url, text="", title="", frames=()):
        self.url = url
        self._text = text
        self._title = title
        self.frames = [type("Frame", (), {"url": frame_url}) for frame_url in frames]
        self.closed = False

    def title(self):
        return self._title

    def locator(self, selector):
        assert selector == "body"
        return _VisibleBody(self._text)

    def is_closed(self):
        return self.closed


def test_visible_captcha_blocks_even_when_offer_json_could_be_present():
    page = _VisiblePage(
        "https://detail.1688.com/offer/123.html",
        text='请拖动滑块完成验证码 {"offerId":"123","price":"130.0"}',
    )

    assert _visible_human_block(page) == (
        "CAPTCHA",
        "1688 页面显示验证码或人机验证",
    )


def test_captcha_iframe_is_a_visible_human_block():
    page = _VisiblePage(
        "https://detail.1688.com/offer/123.html",
        frames=("https://captcha.example/verify",),
    )

    assert _visible_human_block(page)[0] == "CAPTCHA"


def test_cdp_proxy_reuses_1688_tab_and_context_manager_never_closes_it():
    unrelated = _VisiblePage("https://example.com/")
    homepage = _VisiblePage("https://www.1688.com/")
    detail = _VisiblePage("https://detail.1688.com/offer/123.html")
    context = type(
        "Context",
        (),
        {
            "pages": [unrelated, homepage, detail],
            "new_page": lambda self: _VisiblePage("about:blank"),
        },
    )()
    proxy = _CdpContextProxy(context)
    playwright = type("Playwright", (), {"stop": lambda self: None})()

    assert proxy.pages == [detail]
    with _ContextManager(proxy, playwright, close_context=False):
        pass
    assert detail.closed is False

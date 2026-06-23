"""
Scrapling 后端 Amazon 爬虫 + 共享字段提取单测

驱动 crawlers/_amazon_extractors.py（共享模块）和 ScraplingPage 适配器。
所有"页面"用合成 HTML 构造，无网络请求。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from scrapling.parser import Adaptor

from crawlers._amazon_extractors import (
    _parse_float,
    _parse_int,
    _parse_price_text,
    extract_brand,
    extract_bsr,
    extract_dimensions,
    extract_image,
    extract_price,
    extract_rating,
    extract_reviews,
    extract_title,
    is_captcha,
    parse_bsr_page,
)
from crawlers._amazon_page import ScraplingPage


def _page(html: str) -> ScraplingPage:
    """用合成 HTML 构造一个 ScraplingPage（模拟 StealthySession.fetch() 的返回）。"""
    return ScraplingPage(Adaptor(html))


# ============================================================
# parse_bsr_page
# ============================================================
class TestParseBsrPage:
    def test_collects_unique_asins(self):
        html = """
        <a href="/dp/B08ABC1234">x</a>
        <a href="/dp/B08XYZ5678/ref=foo">x</a>
        <a href="/dp/B08ABC1234">dup</a>
        <a href="/gp/best-sellers">not-a-product</a>
        """
        asins = parse_bsr_page(_page(html))
        assert asins == ["B08ABC1234", "B08XYZ5678"]

    def test_returns_empty_when_no_links(self):
        assert parse_bsr_page(_page("<html></html>")) == []

    def test_skips_links_without_10char_asin(self):
        html = '<a href="/dp/short">x</a><a href="/dp/B08ABC1234">x</a>'
        assert parse_bsr_page(_page(html)) == ["B08ABC1234"]


# ============================================================
# extract_brand — 新版走 prodDetTable
# ============================================================
class TestExtractBrand:
    def test_from_prodDetTable_brand_name_row(self):
        # 2026 版主路径
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Brand Name </th><td> Terro </td></tr>
        </table>
        """
        assert extract_brand(_page(html)) == "Terro"

    def test_falls_back_to_bylineInfo_when_no_table(self):
        html = '<a id="bylineInfo" href="/b">Visit the Apple Store</a>'
        assert extract_brand(_page(html)) == "Apple Store"

    def test_strips_brand_prefix(self):
        html = '<span id="bylineInfo">Brand: Acme</span>'
        assert extract_brand(_page(html)) == "Acme"

    def test_falls_back_to_po_brand(self):
        html = '<div class="po-brand"><span class="a-span9">Acme Co</span></div>'
        assert extract_brand(_page(html)) == "Acme Co"

    def test_returns_none_when_missing(self):
        assert extract_brand(_page("<html></html>")) is None


# ============================================================
# _parse_price_text / extract_price
# ============================================================
class TestParsePriceText:
    def test_usd_simple(self):
        assert _parse_price_text("$29.99") == 29.99

    def test_usd_with_comma(self):
        assert _parse_price_text("$1,299.00") == 1299.00

    def test_jpy_with_symbol(self):
        v = _parse_price_text("¥6980")
        assert v is not None and 46 < v < 48

    def test_jpy_bare_number_high(self):
        v = _parse_price_text("6980")
        assert v is not None and v < 50

    def test_low_bare_number_treated_as_usd(self):
        assert _parse_price_text("29.99") == 29.99

    def test_garbage(self):
        assert _parse_price_text("Free!") is None
        assert _parse_price_text("") is None


class TestExtractPrice:
    def test_prefers_reinvent_price(self):
        html = """
        <div class="a-price reinventPricePriceToPayMargin">
          <span class="a-offscreen">$19.99</span>
        </div>
        <span id="priceblock_ourprice">$29.99</span>
        """
        assert extract_price(_page(html)) == 19.99

    def test_falls_back_to_a_offscreen(self):
        html = '<span class="a-offscreen">$15.00</span>'
        assert extract_price(_page(html)) == 15.00

    def test_returns_none_when_missing(self):
        assert extract_price(_page("<html></html>")) is None

    def test_falls_back_to_offscreen_scan(self):
        # 没有结构化选择器命中，但页面里有 a-offscreen 含主价
        html = '<span class="a-offscreen">$24.99</span>'
        assert extract_price(_page(html)) == 24.99


# ============================================================
# extract_rating
# ============================================================
class TestExtractRating:
    def test_from_acr_popover_title(self):
        html = '<span id="acrPopover" title="4.5 out of 5 stars">x</span>'
        assert extract_rating(_page(html)) == 4.5

    def test_from_icon_alt_text(self):
        # 真实 Amazon DOM: .a-icon-alt 嵌在 .a-icon-star 里
        html = '<i class="a-icon-star"><span class="a-icon-alt">4.3 out of 5 stars</span></i>'
        assert extract_rating(_page(html)) == 4.3

    def test_missing(self):
        assert extract_rating(_page("<html></html>")) is None


# ============================================================
# extract_reviews
# ============================================================
class TestExtractReviews:
    def test_parses_comma_number(self):
        html = '<span id="acrCustomerReviewText">1,234 ratings</span>'
        assert extract_reviews(_page(html)) == 1234

    def test_plain_number(self):
        html = '<span id="acrCustomerReviewText">87 ratings</span>'
        assert extract_reviews(_page(html)) == 87

    def test_missing(self):
        assert extract_reviews(_page("<html></html>")) is None


# ============================================================
# extract_bsr — 新版走 prodDetTable
# ============================================================
class TestExtractBsr:
    def test_from_prodDetTable(self):
        # 2026 版主路径
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Best Sellers Rank </th>
            <td> <span> <ul><li><span>#1,234 in Home &amp; Kitchen</span></li>
            <li><span>#42 in Pest Control</span></li></ul> </span>
          </td></tr>
        </table>
        """
        assert extract_bsr(_page(html)) == 1234

    def test_falls_back_to_old_detail_bullets(self):
        # 老版 layout
        html = """
        <div id="detailBullets_feature_div">
          Best Sellers Rank: #5,678 in Home & Kitchen
        </div>
        """
        assert extract_bsr(_page(html)) == 5678

    def test_missing(self):
        assert extract_bsr(_page("<html></html>")) is None


# ============================================================
# extract_image
# ============================================================
class TestExtractImage:
    def test_from_data_old_hires(self):
        html = '<img id="landingImage" data-old-hires="https://m.media-amazon.com/image1.jpg" src="x">'
        assert extract_image(_page(html)) == "https://m.media-amazon.com/image1.jpg"

    def test_from_dynamic_image_json(self):
        html = '<img id="landingImage" data-a-dynamic-image=\'{"https://m.media-amazon.com/A.jpg":[500,500]}\' src="x">'
        assert extract_image(_page(html)) == "https://m.media-amazon.com/A.jpg"

    def test_falls_back_to_src(self):
        html = '<img id="imgBlkFront" src="https://m.media-amazon.com/C.jpg">'
        assert extract_image(_page(html)) == "https://m.media-amazon.com/C.jpg"

    def test_missing(self):
        assert extract_image(_page("<html></html>")) is None


# ============================================================
# extract_dimensions — 新版走 prodDetTable
# ============================================================
class TestExtractDimensions:
    def test_prodDetTable_pounds_and_inches(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Item Weight </th><td> 1.5 pounds </td></tr>
          <tr><th> Package Dimensions </th><td> 10 x 5 x 3 inches </td></tr>
        </table>
        """
        w, l, wd, h = extract_dimensions(_page(html))
        assert w == pytest.approx(1.5 * 0.453592, rel=1e-3)
        assert l == pytest.approx(25.4, rel=1e-3)
        assert wd == pytest.approx(12.7, rel=1e-3)
        assert h == pytest.approx(7.62, rel=1e-3)

    def test_prodDetTable_grams_and_cm(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Item Weight </th><td> 800 grams </td></tr>
          <tr><th> Product Dimensions </th><td> 20 x 15 x 10 cm </td></tr>
        </table>
        """
        w, l, wd, h = extract_dimensions(_page(html))
        assert w == pytest.approx(0.8, rel=1e-3)
        assert (l, wd, h) == (20.0, 15.0, 10.0)

    def test_falls_back_to_ounces(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Item Weight </th><td> 16 ounces </td></tr>
        </table>
        """
        w, _, _, _ = extract_dimensions(_page(html))
        assert w == pytest.approx(16 * 0.0283495, rel=1e-3)

    def test_no_data_returns_none_tuple(self):
        w, l, wd, h = extract_dimensions(_page("<html></html>"))
        assert (w, l, wd, h) == (None, None, None, None)

    def test_only_weight_no_dimensions(self):
        html = '<table class="a-keyvalue prodDetTable"><tr><th>Item Weight</th><td>2 kg</td></tr></table>'
        w, l, wd, h = extract_dimensions(_page(html))
        assert w == 2.0
        assert (l, wd, h) == (None, None, None)


# ============================================================
# extract_title
# ============================================================
class TestExtractTitle:
    def test_returns_stripped_title(self):
        html = '<span id="productTitle">  Test Product  </span>'
        assert extract_title(_page(html)) == "Test Product"

    def test_fallback_when_missing(self):
        assert extract_title(_page("<html></html>"), fallback="B0XYZ") == "B0XYZ"

    def test_empty_when_both_missing(self):
        assert extract_title(_page("<html></html>")) == ""


# ============================================================
# is_captcha
# ============================================================
class TestIsCaptcha:
    def test_robot_check(self):
        assert is_captcha(_page("<title>Robot Check</title>")) is True

    def test_captcha_keyword(self):
        assert is_captcha(_page("<title>Please confirm the captcha below</title>")) is True

    def test_normal_page(self):
        assert is_captcha(_page("<title>Amazon.com Product Page</title>")) is False

    def test_missing_title_does_not_crash(self):
        assert is_captcha(_page("")) is False


# ============================================================
# 数值工具
# ============================================================
class TestParseUtils:
    def test_parse_float(self):
        assert _parse_float("$1,234.56") == 1234.56
        assert _parse_float("42") == 42.0
        assert _parse_float("") is None
        assert _parse_float("abc") is None

    def test_parse_int(self):
        assert _parse_int("1,234 ratings") == 1234
        assert _parse_int("87") == 87
        assert _parse_int("") is None
        assert _parse_int("nope") is None


# ============================================================
# 真实 Amazon HTML 集成测试（fixture 来自真实抓取）
# ============================================================
@pytest.mark.skipif(
    not Path("data/_probe_B00E4GACB8.html").exists(),
    reason="real Amazon HTML fixture not present",
)
class TestAgainstRealAmazonHtml:
    """用 _probe_selectors.py 保存的 B00E4GACB8 详情页验证共享提取器在真实页面上跑通。"""

    @pytest.fixture
    def real_page(self) -> ScraplingPage:
        html = Path("data/_probe_B00E4GACB8.html").read_text(encoding="utf-8")
        return ScraplingPage(Adaptor(html))

    def test_extract_brand(self, real_page):
        # TERRO T300B 详情页的 Brand Name 是 "Terro"
        assert extract_brand(real_page) == "Terro"

    def test_extract_bsr(self, real_page):
        # 该产品在 Home & Kitchen 是 #1
        assert extract_bsr(real_page) == 1

    def test_extract_dimensions(self, real_page):
        w, _l, _wd, _h = extract_dimensions(real_page)
        # Item Weight = 4.64 ounces
        assert w == pytest.approx(4.64 * 0.0283495, rel=1e-3)

    def test_extract_price(self, real_page):
        # 2026 Amazon: 第三方卖家主导的 product 经常没有内联 buybox 价格
        # (只在 "See All Buying Options" 后才显示)。extract_price 在这种页面上
        # 应正常返回 None，不应崩。
        result = extract_price(real_page)
        assert result is None or isinstance(result, float)
        if result is not None:
            assert result > 0

    def test_extract_title_present(self, real_page):
        t = extract_title(real_page)
        assert t and "TERRO" in t.upper()

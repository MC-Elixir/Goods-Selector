"""
爬虫层单测（mock 浏览器 / API，不需要真实网络）。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from scrapling.parser import Adaptor

from crawlers._amazon_extractors import (
    _parse_float,
    _parse_int,
    extract_dimensions,
    parse_bsr_page,
)
from crawlers._amazon_page import ScraplingPage
from crawlers.amazon_bsr import ProductDTO, _resolve_backend, crawl_best_sellers
from crawlers.amazon_rainforest import _rainforest_to_dto


def _page(html: str) -> ScraplingPage:
    return ScraplingPage(Adaptor(html))


# ============================================================
# _resolve_backend
# ============================================================
class TestResolveBackend:
    def test_explicit_playwright(self):
        assert _resolve_backend("playwright") == "playwright"

    def test_explicit_keepa(self):
        assert _resolve_backend("keepa") == "keepa"

    def test_auto_no_keys_uses_scrapling(self):
        # "auto" 默认走 Scrapling（无需 Key，抗检测）
        with patch("crawlers.amazon_bsr.settings") as m:
            m.keepa_api_key = ""
            m.rainforest_api_key = ""
            assert _resolve_backend("auto") == "scrapling"

    def test_explicit_scrapling(self):
        assert _resolve_backend("scrapling") == "scrapling"

    def test_auto_keepa_key_prefers_keepa(self):
        with patch("crawlers.amazon_bsr.settings") as m:
            m.keepa_api_key = "sk-test"
            m.rainforest_api_key = ""
            assert _resolve_backend("auto") == "keepa"

    def test_auto_rainforest_only(self):
        with patch("crawlers.amazon_bsr.settings") as m:
            m.keepa_api_key = ""
            m.rainforest_api_key = "rf-test"
            assert _resolve_backend("auto") == "rainforest"


# ============================================================
# crawl_best_sellers dispatch
# ============================================================
class TestCrawlBestSellers:
    def test_dispatches_to_playwright(self):
        mock_scraper = MagicMock()
        mock_scraper.scrape_best_sellers.return_value = []
        with patch("crawlers.amazon_bsr._resolve_backend", return_value="playwright"), \
             patch("crawlers.amazon_playwright.AmazonPlaywrightScraper", return_value=mock_scraper):
            crawl_best_sellers("Home & Kitchen", limit=10, backend="playwright")
            mock_scraper.scrape_best_sellers.assert_called_once_with("Home & Kitchen", 10, "US")

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="未知 backend"):
            crawl_best_sellers("Home & Kitchen", backend="nonexistent")  # type: ignore


# ============================================================
# Playwright 解析辅助函数
# ============================================================
class TestParseFloat:
    def test_plain_number(self):
        assert _parse_float("29.99") == pytest.approx(29.99)

    def test_price_with_dollar(self):
        assert _parse_float("$29.99") == pytest.approx(29.99)

    def test_comma_thousands(self):
        assert _parse_float("1,299.00") == pytest.approx(1299.00)

    def test_none_input(self):
        assert _parse_float(None) is None  # type: ignore

    def test_non_numeric_string(self):
        assert _parse_float("no number here") is None


class TestParseInt:
    def test_plain(self):
        assert _parse_int("1234") == 1234

    def test_comma(self):
        assert _parse_int("12,345") == 12345

    def test_with_suffix(self):
        assert _parse_int("1,234 ratings") == 1234

    def test_none(self):
        assert _parse_int(None) is None  # type: ignore


class TestParseBsrPage:
    def test_extracts_asins(self):
        html = """
        <a href="/dp/B0TEST0001/ref=zg_bs_1">x</a>
        <a href="/dp/B0TEST0002">x</a>
        <a href="/gp/something-else">x</a>
        """
        asins = parse_bsr_page(_page(html))
        assert "B0TEST0001" in asins
        assert "B0TEST0002" in asins
        assert len(asins) == 2

    def test_deduplicates(self):
        html = '<a href="/dp/B0TEST0001/ref=1">x</a><a href="/dp/B0TEST0001/ref=2">x</a>'
        asins = parse_bsr_page(_page(html))
        assert asins.count("B0TEST0001") == 1

    def test_non_dp_hrefs_ignored(self):
        assert parse_bsr_page(_page("<html></html>")) == []


class TestExtractDimensions:
    def test_inches_converted_to_cm(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Package Dimensions </th><td> 12 x 8 x 4 inches </td></tr>
        </table>
        """
        _, l, w, h = extract_dimensions(_page(html))
        assert l == pytest.approx(12 * 2.54, rel=0.01)
        assert w == pytest.approx(8 * 2.54, rel=0.01)
        assert h == pytest.approx(4 * 2.54, rel=0.01)

    def test_pounds_converted_to_kg(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Item Weight </th><td> 1.5 Pounds </td></tr>
        </table>
        """
        weight, _, _, _ = extract_dimensions(_page(html))
        assert weight == pytest.approx(1.5 * 0.453592, rel=0.01)

    def test_kg_direct(self):
        html = """
        <table class="a-keyvalue prodDetTable">
          <tr><th> Item Weight </th><td> 0.8 kilograms </td></tr>
        </table>
        """
        weight, _, _, _ = extract_dimensions(_page(html))
        assert weight == pytest.approx(0.8)

    def test_no_data_returns_none(self):
        w, l, wd, h = extract_dimensions(_page("<html></html>"))
        assert all(v is None for v in (w, l, wd, h))


# ============================================================
# Rainforest 解析
# ============================================================
class TestRainforestToDto:
    def _item(self, **kwargs) -> dict:
        base = {
            "asin": "B0RF001234",
            "title": "Test Product",
            "brand": "TestBrand",
            "price": {"value": 29.99},
            "rating": 4.3,
            "ratings_total": 1500,
            "link": "https://www.amazon.com/dp/B0RF001234",
            "bestseller_rank": 123,
            "images": [{"link": "https://img.example.com/img.jpg"}],
        }
        base.update(kwargs)
        return base

    def test_basic_parse(self):
        dto = _rainforest_to_dto(self._item(), "Home & Kitchen", "US")
        assert dto.asin == "B0RF001234"
        assert dto.price == pytest.approx(29.99)
        assert dto.rating == pytest.approx(4.3)
        assert dto.review_count == 1500
        assert dto.brand == "TestBrand"
        assert dto.bsr_rank == 123

    def test_image_extracted(self):
        dto = _rainforest_to_dto(self._item(), "Electronics", "US")
        assert dto.main_image_url == "https://img.example.com/img.jpg"

    def test_missing_price_returns_none(self):
        dto = _rainforest_to_dto(self._item(price=None), "Home & Kitchen", "US")
        assert dto.price is None

    def test_dto_is_product_dto(self):
        dto = _rainforest_to_dto(self._item(), "Home & Kitchen", "US")
        assert isinstance(dto, ProductDTO)

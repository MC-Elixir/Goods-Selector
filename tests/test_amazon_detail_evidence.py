from crawlers._amazon_extractors import extract_amazon_detail
from crawlers.amazon_bsr import ProductDTO
from crawlers.amazon_search import apply_detail_evidence
from crawlers.amazon_playwright import AmazonPlaywrightScraper
from crawlers.amazon_scrapling import AmazonScraplingScraper
from scrapling.parser import Adaptor


class FakePage:
    def __init__(self, texts=None, attrs=None, rows=None, text_lists=None):
        self.texts = texts or {}
        self.attrs = attrs or {}
        self.rows = rows or {}
        self.text_lists = text_lists or {}

    def text(self, selector):
        return self.texts.get(selector)

    def attr(self, selector, name):
        return self.attrs.get((selector, name))

    def table_row(self, label):
        return self.rows.get(label)

    def text_all(self, selector):
        return self.text_lists.get(selector, [])


def test_detail_keeps_buybox_coupon_package_and_secondary_images():
    page = FakePage(
        texts={
            "#productTitle": "Four Replacement Water Filters",
            "#corePrice_feature_div .a-offscreen": "$29.99",
            "#couponTextpctch": "Save 10% with coupon",
            "#merchant-info": "Ships from Amazon.com Sold by Filter Store",
            "#availability": "In Stock",
        },
        attrs={
            ("#landingImage", "src"): "https://img/main.jpg",
            ("#landingImage", "data-a-dynamic-image"): '{"https://img/main.jpg":[1000,1000]}',
            ("#altImages", "data-secondary-images"): '["https://img/2.jpg"]',
        },
        rows={
            "Brand Name": "Acme", "Item Weight": "1.2 pounds",
            "Product Dimensions": "10 x 8 x 4 inches", "Package Dimensions": "11 x 9 x 5 inches",
            "Best Sellers Rank": "#1,234 in Home & Kitchen", "Number of Items": "4",
            "Material": "Activated Carbon", "Date First Available": "January 2, 2025",
        },
    )
    detail = extract_amazon_detail(page, source_ref="artifact:amazon-B000TEST")
    assert detail["price"].value == 29.99
    assert detail["coupon"].value == "Save 10% with coupon"
    assert detail["package_quantity"].value == 4
    assert detail["package_dimensions"].value is not None
    assert detail["secondary_images"].value == ["https://img/2.jpg"]
    assert detail["fulfillment"].value == "Amazon.com"
    assert detail["price"].status.value == "extracted"
    assert detail["variation_price"].value is None
    assert detail["variation_price"].status.value == "missing"


def test_missing_buybox_fields_remain_missing_and_all_keys_exist():
    detail = extract_amazon_detail(FakePage(), source_ref="artifact:empty")
    expected = {
        "title", "brand", "price", "coupon", "discount", "list_price",
        "variation_price", "bsr", "rating", "review_count", "weight_kg",
        "product_dimensions", "package_dimensions", "package_quantity", "material",
        "seller_count", "seller", "fulfillment", "availability", "main_image",
        "secondary_images", "bullet_points", "description", "a_plus",
        "first_available_date",
    }
    assert set(detail) == expected
    assert detail["seller_count"].value is None
    assert detail["seller_count"].status.value == "missing"
    assert detail["fulfillment"].value is None
    assert all(item.status.value == "missing" for item in detail.values())


def test_detail_timestamps_are_timezone_aware():
    detail = extract_amazon_detail(
        FakePage(texts={"#productTitle": "Test"}), source_ref="artifact:test"
    )
    assert detail["title"].observed_at.utcoffset() is not None
    assert detail["title"].expires_at.utcoffset() is not None


def test_a_plus_empty_container_is_detected_by_adapter_presence():
    detail = extract_amazon_detail(
        FakePage(attrs={("#aplus", "id"): "aplus"}), source_ref="artifact:aplus"
    )
    assert detail["a_plus"].value is True


def test_legacy_dto_only_copies_extracted_values_and_retains_full_evidence():
    fields = extract_amazon_detail(
        FakePage(
            texts={"#productTitle": "Verified Title"},
            rows={"Product Dimensions": "10 x 8 x 4 inches"},
        ),
        source_ref="artifact:test",
    )
    product = ProductDTO(asin="B000TEST", marketplace="US", title="old", price=99.0)
    apply_detail_evidence(product, fields)

    assert product.title == "Verified Title"
    assert product.price == 99.0
    assert product.length_cm == 25.4
    assert product.raw_data["field_evidence"]["price"]["status"] == "missing"


DETAIL_HTML = """
<html><span id="productTitle">Adapter Product</span>
<div id="corePrice_feature_div"><span class="a-offscreen">$18.50</span></div>
<table class="prodDetTable"><tr><th>Brand Name</th><td>Acme</td></tr>
<tr><th>Product Dimensions</th><td>10 x 8 x 4 inches</td></tr></table></html>
"""


def test_scrapling_product_path_attaches_complete_evidence_without_refetch(monkeypatch):
    class Session:
        def __init__(self):
            self.calls = 0

        def fetch(self, *args, **kwargs):
            self.calls += 1
            return Adaptor(DETAIL_HTML)

    session = Session()
    scraper = AmazonScraplingScraper(use_cache=False)
    monkeypatch.setattr("crawlers.amazon_scrapling.set_html", lambda *args: None)
    product = scraper._scrape_product(
        session, "https://www.amazon.com", "B000TEST00", "US", "Home"
    )

    assert session.calls == 1
    assert product.price == 18.5
    assert product.raw_data["field_evidence"]["coupon"]["status"] == "missing"
    assert product.raw_data["field_evidence"]["title"]["source_ref"] == product.listing_url


def test_playwright_product_path_attaches_complete_evidence(monkeypatch):
    class Element:
        def __init__(self, text="", attrs=None):
            self._text = text
            self._attrs = attrs or {}

        def inner_text(self):
            return self._text

        def get_attribute(self, name):
            return self._attrs.get(name)

    class Page:
        def __init__(self):
            self.goto_calls = 0
            self.elements = {
                "#productTitle": Element("Adapter Product"),
                "#corePrice_feature_div .a-offscreen": Element("$18.50"),
            }

        def goto(self, *args, **kwargs):
            self.goto_calls += 1

        def wait_for_timeout(self, *args):
            return None

        def query_selector(self, selector):
            if "Brand Name" in selector:
                return Element("Acme")
            if "Product Dimensions" in selector:
                return Element("10 x 8 x 4 inches")
            return self.elements.get(selector)

        def query_selector_all(self, selector):
            return []

    page = Page()
    product = AmazonPlaywrightScraper()._scrape_product(
        page, "https://www.amazon.com", "B000TEST00", "US", "Home"
    )

    assert page.goto_calls == 1
    assert product.brand == "Acme"
    assert product.raw_data["field_evidence"]["availability"]["status"] == "missing"
    assert product.raw_data["field_evidence"]["title"]["source_ref"] == product.listing_url

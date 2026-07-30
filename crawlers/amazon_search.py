"""Amazon US keyword search source for the sourcing pipeline."""
from __future__ import annotations

import random
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote_plus

from loguru import logger
from scrapling.parser import Adaptor

from crawlers._amazon_cookies import load_cookies
from crawlers.amazon_bsr import ProductDTO
from domain.target_categories import profile_from_product, profile_from_text, target_query_matches_product
from schemas.sourcing import EvidenceStatus, FieldEvidence

_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_QUERY_STOPWORDS = {"and", "for", "the", "with", "of", "in", "a", "an"}
_KEYWORD_MAP = {
    "水杯": "water bottle",
    "保温杯": "insulated water bottle",
}
_AMAZON_US = "https://www.amazon.com"
_DEFAULT_COOKIES: list[dict] = [
    {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"},
    {"name": "lc-main", "value": "en_US", "domain": ".amazon.com", "path": "/"},
]


def apply_detail_evidence(
    product: ProductDTO,
    fields: dict[str, FieldEvidence],
) -> ProductDTO:
    """Persist the evidence envelope and safely hydrate legacy DTO fields."""
    raw = product.raw_data if isinstance(product.raw_data, dict) else {}
    product.raw_data = raw
    raw["field_evidence"] = {
        name: item.model_dump(mode="json") for name, item in fields.items()
    }

    allowed = {EvidenceStatus.EXTRACTED, EvidenceStatus.VERIFIED}
    simple_mapping = {
        "title": "title",
        "brand": "brand",
        "price": "price",
        "bsr": "bsr_rank",
        "rating": "rating",
        "review_count": "review_count",
        "weight_kg": "weight_kg",
        "main_image": "main_image_url",
    }
    for evidence_name, dto_name in simple_mapping.items():
        item = fields.get(evidence_name)
        if item is not None and item.status in allowed and item.value is not None:
            setattr(product, dto_name, item.value)
    dimensions = fields.get("product_dimensions")
    if dimensions is not None and dimensions.status in allowed and dimensions.value:
        product.length_cm, product.width_cm, product.height_cm = dimensions.value

    # Product understanding consumes the compact raw-data envelope, while the
    # full provenance remains under ``field_evidence``. Hydrate every rich field
    # from decision-grade evidence so bullets, secondary images, and structured
    # attributes are not silently lost between crawl and supplier matching.
    rich_fields = (
        "bullet_points",
        "description",
        "secondary_images",
        "package_dimensions",
        "package_quantity",
        "material",
        "a_plus",
        "availability",
        "seller",
        "fulfillment",
    )
    for name in rich_fields:
        item = fields.get(name)
        if item is not None and item.status in allowed and item.value is not None:
            raw[name] = item.value

    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    raw["attributes"] = attributes
    for name in ("material", "package_quantity", "product_dimensions", "package_dimensions"):
        item = fields.get(name)
        if item is not None and item.status in allowed and item.value is not None:
            attributes[name] = item.value
    return product


@dataclass(frozen=True)
class KeywordNormalization:
    original: str
    normalized: str
    warning: str | None = None
    requires_english_query: bool = False


@dataclass(frozen=True)
class SearchResult:
    asin: str
    source_rank: int
    sponsored: bool = False


@dataclass(frozen=True)
class SearchPageDiagnostic:
    """Safe, small summary of an Amazon search response."""

    kind: str
    action: str
    page_title: str
    result_cards: int
    product_links: int
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AmazonSearchFailure(RuntimeError):
    """An Amazon search failure with sanitized diagnostics for the run log."""

    def __init__(self, keyword: str, diagnostic: SearchPageDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(
            f"Amazon keyword search failed for {keyword!r}: {diagnostic.kind}. {diagnostic.action}"
        )


def normalize_keyword(keyword: str) -> KeywordNormalization:
    original = (keyword or "").strip()
    if not original:
        raise ValueError("keyword is required")
    mapped = _KEYWORD_MAP.get(original)
    if mapped:
        return KeywordNormalization(original=original, normalized=mapped)
    if _CHINESE_RE.search(original):
        return KeywordNormalization(
            original=original,
            normalized=original,
            warning=f"Amazon US 需要英文检索词；未配置中文映射：{original}",
            requires_english_query=True,
        )
    return KeywordNormalization(original=original, normalized=original)


def keyword_preview(keyword: str) -> dict[str, Any]:
    """Return the exact Amazon US query decision without starting a crawl."""
    return asdict(normalize_keyword(keyword))


def is_keyword_relevant_title(keyword: str, title: str) -> bool:
    """Require multi-word Amazon searches to retain at least two title anchors."""
    anchors = [
        token for token in re.findall(r"[a-z0-9]+", (keyword or "").lower())
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    ]
    if len(anchors) < 2:
        return True
    title_words = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
    return sum(token in title_words for token in anchors) >= 2


def classify_search_page(html: str, url: str) -> SearchPageDiagnostic:
    """Classify an Amazon search response without retaining raw page contents."""
    page = Adaptor(html or "")
    try:
        title = (page.css("title").first.text or "").strip()
    except Exception:
        title = ""
    try:
        result_cards = len(page.css('[data-component-type="s-search-result"]'))
    except Exception:
        result_cards = 0
    try:
        product_links = len(page.css('a[href*="/dp/"]'))
    except Exception:
        product_links = 0

    text = f"{title} {html or ''}".lower()
    if any(token in text for token in ("robot check", "captcha", "automated access", "type the characters")):
        return SearchPageDiagnostic(
            kind="captcha",
            action="Refresh Amazon cookies and retry after completing the robot check.",
            page_title=title,
            result_cards=result_cards,
            product_links=product_links,
            url=url,
        )
    if any(token in text for token in ("no results for", "did not match any products", "no results found")):
        return SearchPageDiagnostic(
            kind="no_results",
            action="Try a broader English Amazon US query and retry.",
            page_title=title,
            result_cards=result_cards,
            product_links=product_links,
            url=url,
        )
    if result_cards or product_links:
        return SearchPageDiagnostic(
            kind="results_detected",
            action="Search results were detected.",
            page_title=title,
            result_cards=result_cards,
            product_links=product_links,
            url=url,
        )
    return SearchPageDiagnostic(
        kind="unexpected_page",
        action="Refresh Amazon cookies and retry; if it repeats, inspect the Amazon page diagnostic.",
        page_title=title,
        result_cards=result_cards,
        product_links=product_links,
        url=url,
    )


def search_failure_details(error: BaseException) -> dict[str, Any]:
    """Return structured diagnostics for typed search errors only."""
    if isinstance(error, AmazonSearchFailure):
        return {"amazon_search": error.diagnostic.to_dict()}
    return {}


def parse_search_results_html(html: str) -> list[SearchResult]:
    """Extract deduped organic ASINs from an Amazon search result page."""
    page = Adaptor(html or "")
    seen: set[str] = set()
    results: list[SearchResult] = []

    cards = page.css('[data-component-type="s-search-result"]')
    if cards:
        for card in cards:
            asin = _card_asin(card)
            if not asin or asin in seen:
                continue
            if _is_sponsored_card(card):
                continue
            seen.add(asin)
            results.append(SearchResult(asin=asin, source_rank=len(results) + 1))
        return results

    for link in page.css('a[href*="/dp/"]'):
        href = link.attrib.get("href", "") or ""
        match = _ASIN_RE.search(href)
        if not match:
            continue
        asin = match.group(1)
        if asin in seen:
            continue
        seen.add(asin)
        results.append(SearchResult(asin=asin, source_rank=len(results) + 1))
    return results


def search_amazon_products(keyword: str, marketplace: str = "US", limit: int = 10) -> list[ProductDTO]:
    """Search Amazon US by keyword and hydrate organic ASINs into ProductDTOs."""
    site = (marketplace or "US").strip().upper()
    if site != "US":
        raise ValueError("Amazon keyword search currently supports Amazon US only")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    normalized = normalize_keyword(keyword)
    if normalized.requires_english_query:
        raise ValueError(
            f"Amazon US keyword sourcing requires an English query. "
            f"Please replace {normalized.original!r} with its English product phrase."
        )
    if normalized.warning:
        logger.warning(normalized.warning)
    target_query_profile = profile_from_text(normalized.normalized)

    from scrapling.fetchers import StealthySession

    from crawlers.amazon_scrapling import AmazonScraplingScraper

    cookies = load_cookies(None) or list(_DEFAULT_COOKIES)
    session = StealthySession(
        headless=True,
        cookies=cookies,
        extra_headers={"Accept-Language": "en-US,en;q=0.9"},
        locale="en-US",
        timezone_id="America/New_York",
        useragent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        solve_cloudflare=True,
        hide_canvas=True,
        block_webrtc=True,
        block_ads=True,
    )
    session.start()
    scraper = AmazonScraplingScraper(cookies=cookies)

    try:
        url = f"{_AMAZON_US}/s?k={quote_plus(normalized.normalized)}&language=en_US&currency=USD"
        page = session.fetch(
            url,
            timeout=25_000,
            wait=1.5,
            network_idle=False,
            disable_resources=True,
            wait_selector='[data-component-type="s-search-result"], a[href*="/dp/"]',
            wait_selector_state="attached",
        )
        diagnostic = classify_search_page(page.html_content, url)
        if diagnostic.kind in {"captcha", "no_results", "unexpected_page"}:
            raise AmazonSearchFailure(keyword, diagnostic)
        results = parse_search_results_html(page.html_content)
        if not results:
            raise AmazonSearchFailure(
                keyword,
                SearchPageDiagnostic(
                    kind="no_organic_results",
                    action="Try a broader English Amazon US query and retry.",
                    page_title=diagnostic.page_title,
                    result_cards=diagnostic.result_cards,
                    product_links=diagnostic.product_links,
                    url=url,
                ),
            )

        products: list[ProductDTO] = []
        for result in results[:limit]:
            try:
                product = scraper._scrape_product(session, _AMAZON_US, result.asin, "US", None)  # type: ignore[arg-type]
                raw = product.raw_data if isinstance(product.raw_data, dict) else {}
                product.raw_data = raw
                existing_evidence = raw.get("field_evidence")
                if isinstance(existing_evidence, dict):
                    parsed = {
                        name: value if isinstance(value, FieldEvidence) else FieldEvidence.model_validate(value)
                        for name, value in existing_evidence.items()
                    }
                    apply_detail_evidence(product, parsed)
                raw.update({
                    "source_mode": "keyword",
                    "source_keyword": normalized.original,
                    "keyword_normalized": normalized.normalized,
                    "keyword_warning": normalized.warning,
                    "source_rank": result.source_rank,
                    "source_sponsored": result.sponsored,
                })
                title_relevant = is_keyword_relevant_title(normalized.normalized, product.title)
                intent_relevant = (
                    target_query_profile is None
                    or target_query_matches_product(normalized.normalized, product)
                )
                product_profile = profile_from_product(product) if intent_relevant else None
                if product_profile is not None:
                    raw["target_category_profile"] = product_profile.to_dict()
                if title_relevant and intent_relevant:
                    products.append(product)
                else:
                    reason = "title anchors" if not title_relevant else "target category intent"
                    logger.info(
                        f"[amazon-search] skip off-query {reason} asin={result.asin} title={product.title[:80]!r}"
                    )
            except Exception as exc:
                logger.warning(f"[amazon-search] detail failed asin={result.asin}: {exc}")
            if len(products) < min(limit, len(results)):
                time.sleep(random.uniform(1.5, 3.0))

        if not products:
            raise RuntimeError(f"Amazon search found ASINs but no titles matched keyword anchors: {keyword}")
        return products
    except AmazonSearchFailure:
        raise
    except Exception as exc:
        raise RuntimeError(f"Amazon keyword search failed for {keyword!r}: {exc}") from exc
    finally:
        try:
            session.close()
        except Exception:
            pass


def _card_asin(card) -> str | None:
    asin = (card.attrib.get("data-asin", "") or "").strip().upper()
    if re.fullmatch(r"[A-Z0-9]{10}", asin):
        return asin
    for link in card.css('a[href*="/dp/"]'):
        match = _ASIN_RE.search(link.attrib.get("href", "") or "")
        if match:
            return match.group(1)
    return None


def _is_sponsored_card(card) -> bool:
    text = ""
    try:
        text = card.get_all_text(" ")
    except Exception:
        try:
            text = card.text or ""
        except Exception:
            text = ""
    attrs = " ".join(str(v) for v in getattr(card, "attrib", {}).values())
    haystack = f"{text} {attrs}".lower()
    return any(token in haystack for token in ("sponsored", "adholder", "广告", "赞助"))

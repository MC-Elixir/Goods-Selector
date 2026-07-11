"""Structured, fail-closed understanding of an Amazon product."""
from __future__ import annotations

from schemas.sourcing import AmazonProductUnderstanding


class ProductUnderstandingError(RuntimeError):
    """Raised when product understanding cannot satisfy the canonical schema."""


def product_image_urls(product) -> list[str]:
    """Return up to five unique HTTP product images, with the main image first."""
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    urls = [getattr(product, "main_image_url", None), *(raw.get("secondary_images") or [])]
    return list(
        dict.fromkeys(url for url in urls if isinstance(url, str) and url.startswith("http"))
    )[:5]


def understand_amazon_product(product, analyzer) -> AmazonProductUnderstanding:
    """Collect all available evidence and validate the analyzer response strictly."""
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    payload = {
        "asin": product.asin,
        "title": product.title,
        "brand": getattr(product, "brand", None),
        "bullet_points": raw.get("bullet_points") or [],
        "description": raw.get("description"),
        "attributes": raw.get("attributes") or {},
        "image_urls": product_image_urls(product),
    }
    try:
        result = AmazonProductUnderstanding.model_validate(analyzer.analyze_product(payload))
        brand = (getattr(product, "brand", None) or "").strip()
        if brand:
            excluded = list(dict.fromkeys([*result.excluded_brand_tokens, brand]))
            supplier_keywords = [
                keyword
                for keyword in result.likely_supplier_keywords_cn
                if brand.casefold() not in keyword.casefold()
            ]
            result = result.model_copy(update={
                "excluded_brand_tokens": excluded,
                "likely_supplier_keywords_cn": supplier_keywords,
            })
        return result
    except Exception as exc:
        raise ProductUnderstandingError(f"schema_validation: {exc}") from exc

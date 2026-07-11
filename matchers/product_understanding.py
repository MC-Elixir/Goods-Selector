"""Structured, fail-closed understanding of an Amazon product."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import ValidationError

from matchers.vision_analyzer import ProductAnalysisError
from schemas.sourcing import AmazonProductUnderstanding


class ProductUnderstandingError(RuntimeError):
    """Raised when product understanding cannot satisfy the canonical schema."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_RUNTIME_FIELDS = {
    "asin",
    "original_title_en",
    "model_provider",
    "model_name",
    "prompt_version",
}
_SEMANTIC_FIELDS = set(AmazonProductUnderstanding.model_fields) - _RUNTIME_FIELDS


def _is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def product_image_urls(product) -> list[str]:
    """Return up to five unique HTTP product images, with the main image first."""
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    urls = [getattr(product, "main_image_url", None), *(raw.get("secondary_images") or [])]
    return list(
        dict.fromkeys(url for url in urls if _is_http_url(url))
    )[:5]


def _brand_tokens(brand: str, excluded: list[str]) -> list[str]:
    values = [*excluded, brand]
    tokens: list[str] = []
    for value in values:
        clean = value.strip()
        if clean:
            tokens.append(clean)
            tokens.extend(part for part in re.split(r"[^\w]+", clean) if len(part) >= 2)
    return list(dict.fromkeys(token.casefold() for token in tokens))


def _contains_token(text: str, tokens: list[str]) -> bool:
    folded = text.casefold()
    return any(token in folded for token in tokens)


def _clean_supplier_name(text: str, tokens: list[str]) -> str:
    cleaned = text
    for token in sorted(tokens, key=len, reverse=True):
        cleaned = re.sub(re.escape(token), " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip(" -_,/|")


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
        response = analyzer.analyze_product(payload)
    except ProductAnalysisError as exc:
        raise ProductUnderstandingError(exc.code) from None
    except Exception:
        raise ProductUnderstandingError("provider_failure") from None

    try:
        if not isinstance(response, dict) or not _SEMANTIC_FIELDS.issubset(response):
            raise ValueError("missing explicit semantic fields")
        data = dict(response)
        data["asin"] = product.asin
        data["original_title_en"] = product.title
        result = AmazonProductUnderstanding.model_validate(data, strict=True)
    except (ValidationError, ValueError, TypeError):
        raise ProductUnderstandingError("schema_validation") from None

    brand = (getattr(product, "brand", None) or "").strip()
    excluded = list(dict.fromkeys([*result.excluded_brand_tokens, *([brand] if brand else [])]))
    tokens = _brand_tokens(brand, result.excluded_brand_tokens)
    return result.model_copy(update={
        "excluded_brand_tokens": excluded,
        "generic_product_name": _clean_supplier_name(result.generic_product_name, tokens),
        "supply_chain_name_cn": _clean_supplier_name(result.supply_chain_name_cn, tokens),
        "likely_supplier_keywords_cn": [
            keyword
            for keyword in result.likely_supplier_keywords_cn
            if not _contains_token(keyword, tokens)
        ],
    })

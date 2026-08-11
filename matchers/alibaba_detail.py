"""1688 offer detail parsing and supplier enrichment."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, TypedDict

from domain.target_categories import profile_from_text
from matchers.alibaba_pailitao import SupplierDTO
from matchers.product_spec import spec_from_text

_PRICE_TIER_RE = re.compile(r"(\d{1,6})\s*(?:件|个|只|pcs?|起)\s*(?:[¥￥]\s*)?(\d+(?:\.\d+)?)", re.I)
_MOQ_RE = re.compile(r"(?:起订量|起批量|最小起订|MOQ|min(?:imum)?\s*order)\D{0,12}(\d{1,6})", re.I)
_DELIVERY_RE = re.compile(r"(?:发货期|交期|供货周期|lead\s*time|delivery)\D{0,12}(\d{1,3})\s*(?:天|days?)?", re.I)
_WEIGHT_RE = re.compile(r"(?:毛重|净重|重量|weight)\D{0,12}(\d+(?:\.\d+)?)\s*(kg|千克|公斤|g|克)?", re.I)
_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:cm|厘米|公分)?\s*[x×*]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:cm|厘米|公分)?\s*[x×*]\s*"
    r"(\d+(?:\.\d+)?)\s*(?:cm|厘米|公分)?",
    re.I,
)

_PATENT_TERMS = ("专利", "外观专利", "patent", "patented")
_BRAND_TERMS = ("品牌授权", "授权", "迪士尼", "disney", "marvel", "apple", "nike", "lego", "pokemon")
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_PARSED_DETAIL_KEYS = {
    "moq",
    "base_price_cny",
    "price_tiers",
    "delivery_days",
    "product_dimensions_cm",
    "product_weight_g",
    "material",
    "color",
    "risk_flags",
    "raw_text",
    "function",
    "product_type",
    "package_quantity",
    "category_profile",
    "factory_evidence",
}

_REQUIRED_DETAIL_FIELDS = (
    "moq", "base_price_cny", "price_tiers", "sku_options", "material", "color",
    "specification", "product_dimensions_cm", "product_weight_g", "package_details",
    "origin", "delivery_days", "customization", "custom_logo", "custom_packaging",
    "sample_available", "supplier_type", "supplier_years", "supplier_location",
    "transaction_volume", "specification_images", "detail_images", "certifications",
    "return_dispute_terms", "risk_flags", "function", "product_type",
    "package_quantity", "category_profile", "factory_evidence",
)

_BLOCK_MARKERS = (
    ("AUTH_REQUIRED", ("请登录", "登录后", "passport.1688", "login.1688", "sign in")),
    ("CAPTCHA", ("验证码", "滑块", "人机验证", "captcha", "slider verification")),
    ("RATE_LIMITED", ("访问过于频繁", "请求过于频繁", "稍后再试", "流量控制", "rate limit", "too many requests")),
)


class ProvenanceRecord(TypedDict):
    status: str
    source_type: str
    observed_at: str
    confidence: float | None
    artifact_hash: str


class OfferDetailResult(TypedDict, total=False):
    provenance: dict[str, ProvenanceRecord]
    observed_at: str
    artifact_hash: str
    raw_text: str


class BlockedOfferPage(RuntimeError):
    """A typed signal that the fetched artifact is not an offer page."""

    def __init__(self, error_code: str, diagnostic: str):
        self.error_code = error_code
        self.diagnostic = diagnostic
        super().__init__(f"{error_code}: {diagnostic}")


def parse_1688_offer_detail(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Extract sourcing-critical details from a 1688 detail payload or text."""
    data = raw if isinstance(raw, dict) else {}
    text = _detail_text(raw)
    spec = spec_from_text(text)
    category_profile = profile_from_text(text)
    price_tiers = _price_tiers(data) or _price_tiers_from_text(text)
    dimensions = spec.dimensions_cm or _parse_dimensions(text)
    supplier_type = _deep_first_value(data, {"companyType", "supplierType", "businessType"})
    supplier_years = _first_int(data, "companyYears", "supplierYears", "yearsInBusiness")
    supplier_location = _deep_first_value(data, {"companyAddress", "supplierLocation", "location"})
    transaction_volume = _deep_first_value(data, {"transactionVolume", "tradeVolume", "transactions"})
    customization = _first_present(data, "supportCustom", "customization", "isCustomized")
    package_quantity = spec.pack_count
    if category_profile and category_profile.numeric.get("piece_count") is not None:
        package_quantity = int(category_profile.numeric["piece_count"])  # type: ignore[arg-type]
    product_type = None
    function = None
    if category_profile:
        product_type = "full_product" if category_profile.relation == "full_product" else category_profile.relation
        function = {
            "outdoor_storage": "户外储物",
            "patio_heater": "户外取暖",
            "patio_furniture_sets": "户外坐卧",
            "patio_umbrellas_shade": "户外遮阳",
        }[category_profile.category_id]
    factory_evidence = {
        key: value for key, value in {
            "supplier_type": supplier_type,
            "supplier_years": supplier_years,
            "supplier_location": supplier_location,
            "transaction_volume": transaction_volume,
            "customization": customization,
        }.items() if value not in (None, "", [], {})
    } or None
    detail: dict[str, Any] = {
        "moq": _coalesce(_first_int(data, "minOrderQuantity", "minOrder", "moq", "beginAmount"), _moq_from_text(text)),
        "base_price_cny": _coalesce(_first_price(price_tiers), _first_float(data, "price", "priceCny", "minPrice")),
        "price_tiers": price_tiers or None,
        "sku_options": _deep_first_value(data, {"skuMap", "skuOptions", "skuProps"}),
        "delivery_days": _coalesce(_first_int(data, "deliveryDays", "leadTime", "sendGoodsDays"), _delivery_from_text(text)),
        "product_dimensions_cm": _format_dimensions(dimensions),
        "product_weight_g": _coalesce(spec.weight_g, _weight_from_text(text)),
        "material": spec.material,
        "color": spec.color,
        "specification": _attribute_value(data, "规格", "型号", "specification", "spec"),
        "package_details": _attribute_value(data, "包装", "包装方式", "package", "packing"),
        "origin": _attribute_value(data, "产地", "原产地", "origin"),
        "customization": customization,
        "custom_logo": _first_present(data, "customLogo", "logoCustomization"),
        "custom_packaging": _first_present(data, "customPackaging", "packagingCustomization"),
        "sample_available": _first_present(data, "sampleAvailable", "supportSample"),
        "supplier_type": supplier_type,
        "supplier_years": supplier_years,
        "supplier_location": supplier_location,
        "transaction_volume": transaction_volume,
        "specification_images": _string_list(_deep_first_value(data, {"skuImages", "specificationImages"})),
        "detail_images": _string_list(_deep_first_value(data, {"detailImageUrls", "detailImages", "imageUrls"})),
        "certifications": _string_list(_deep_first_value(data, {"certifications", "certificateList", "certificates"})),
        "return_dispute_terms": _deep_first_value(data, {"returnPolicy", "disputeTerms", "afterSalePolicy"}),
        "risk_flags": _risk_flags(text, spec.risk_flags),
        "function": function,
        "product_type": product_type,
        "package_quantity": package_quantity,
        "category_profile": category_profile.to_dict() if category_profile else None,
        "factory_evidence": factory_evidence,
        "raw_text": text,
    }
    return _with_provenance(detail, raw)


def parse_1688_offer_detail_html(
    html: str,
    *,
    expected_offer_id: str | None = None,
    page_url: str | None = None,
) -> dict[str, Any]:
    """Extract detail evidence from a 1688 HTML detail page."""
    _raise_if_blocked(html)
    text = _html_text(html)
    best: dict[str, Any] = {}
    best_obj: dict[str, Any] = {}
    for obj in _embedded_json_objects(html):
        detail = parse_1688_offer_detail(obj)
        if not best_obj or _extracted_field_count(detail) > _extracted_field_count(best):
            best = detail
            best_obj = obj
    if not _looks_like_offer_page(html, page_url=page_url, primary=best_obj):
        raise BlockedOfferPage("INVALID_OFFER_PAGE", "missing offer id and product detail markers")
    if expected_offer_id:
        authoritative_ids = {
            *_offer_ids_from_urls(page_url or ""),
            *_canonical_offer_ids(html),
            *_primary_offer_ids(best_obj),
        }
        if not authoritative_ids:
            raise BlockedOfferPage("OFFER_ID_UNVERIFIED", f"no identity evidence for offer {expected_offer_id}")
        if authoritative_ids != {str(expected_offer_id)}:
            raise BlockedOfferPage(
                "OFFER_ID_MISMATCH",
                f"expected offer {expected_offer_id}, observed {sorted(authoritative_ids)}",
            )
    fallback = parse_1688_offer_detail(text)
    if not best:
        return _with_provenance(fallback, html)
    merged = _merge_detail_evidence(fallback, best)
    merged["risk_flags"] = _risk_flags(text, list(dict.fromkeys([
        *(fallback.get("risk_flags") or []),
        *(best.get("risk_flags") or []),
    ])))
    return _with_provenance(merged, html)


def _primary_offer_ids(value: dict[str, Any]) -> set[str]:
    return {
        str(child)
        for key, child in value.items()
        if key.lower().replace("_", "") == "offerid" and child is not None
    }


def _offer_ids_from_urls(value: str) -> set[str]:
    ids = set(re.findall(r"/offer/(\d+)\.html", value or "", re.I))
    ids.update(re.findall(r"[?&]offerId=(\d+)", value or "", re.I))
    return ids


def _canonical_offer_ids(html: str) -> set[str]:
    ids: set[str] = set()
    for tag in re.findall(r"<link\b[^>]*>", html or "", re.I):
        rel = re.search(r"\brel\s*=\s*(['\"])(.*?)\1", tag, re.I | re.S)
        href = re.search(r"\bhref\s*=\s*(['\"])(.*?)\1", tag, re.I | re.S)
        if rel and href and "canonical" in rel.group(2).lower().split():
            ids.update(_offer_ids_from_urls(href.group(2)))
    return ids


def _merge_detail_evidence(fallback: dict[str, Any], structured: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    fallback_provenance = fallback.get("provenance") or {}
    structured_provenance = structured.get("provenance") or {}
    provenance = dict(fallback_provenance)
    for key in _REQUIRED_DETAIL_FIELDS:
        if structured_provenance.get(key, {}).get("status") == "extracted":
            merged[key] = structured.get(key)
            provenance[key] = structured_provenance[key]
    merged["provenance"] = provenance
    return merged


def _extracted_field_count(detail: dict[str, Any]) -> int:
    provenance = detail.get("provenance") or {}
    return sum(record.get("status") == "extracted" for record in provenance.values())


def apply_1688_detail_to_supplier(supplier: SupplierDTO, raw: str | dict[str, Any]) -> SupplierDTO:
    """Fill missing SupplierDTO fields from parsed 1688 detail evidence."""
    if isinstance(raw, dict) and any(key in raw for key in _PARSED_DETAIL_KEYS):
        detail = dict(raw)
    else:
        detail = parse_1688_offer_detail(raw)
    if not isinstance(detail.get("category_profile"), dict):
        profile = profile_from_text(str(detail.get("raw_text") or ""))
        if profile:
            detail["category_profile"] = profile.to_dict()
            detail.setdefault("product_type", "full_product" if profile.relation == "full_product" else profile.relation)
            detail.setdefault("function", {
                "outdoor_storage": "户外储物",
                "patio_heater": "户外取暖",
                "patio_furniture_sets": "户外坐卧",
                "patio_umbrellas_shade": "户外遮阳",
            }[profile.category_id])
            if profile.numeric.get("piece_count") is not None:
                detail.setdefault("package_quantity", int(profile.numeric["piece_count"]))  # type: ignore[arg-type]
    if not isinstance(detail.get("factory_evidence"), dict):
        detail["factory_evidence"] = {
            key: detail.get(key)
            for key in ("supplier_type", "supplier_years", "supplier_location", "transaction_volume", "customization")
            if detail.get(key) not in (None, "", [], {})
        } or None
    if detail.get("moq") is not None:
        supplier.moq = supplier.moq or detail["moq"]
    if detail.get("base_price_cny") is not None:
        supplier.base_price_cny = supplier.base_price_cny or detail["base_price_cny"]
    if detail.get("price_tiers"):
        supplier.price_tiers = supplier.price_tiers or detail["price_tiers"]
    if detail.get("delivery_days") is not None:
        supplier.delivery_days = supplier.delivery_days or detail["delivery_days"]
    if detail.get("product_dimensions_cm"):
        supplier.product_dimensions_cm = supplier.product_dimensions_cm or detail["product_dimensions_cm"]
    if detail.get("product_weight_g") is not None:
        supplier.product_weight_g = supplier.product_weight_g or detail["product_weight_g"]
    if detail.get("material"):
        supplier.material = supplier.material or detail["material"]
    if detail.get("color"):
        supplier.color = supplier.color or detail["color"]
    factory_flag = _factory_flag(detail.get("supplier_type"))
    if supplier.is_factory is None and factory_flag is not None:
        supplier.is_factory = factory_flag
    supplier.raw_data.setdefault("detail", {}).update(detail)
    factory_evidence = detail.get("factory_evidence")
    if isinstance(factory_evidence, dict):
        supplier.raw_data["factory_evidence"] = dict(factory_evidence)
    factory_fields = ("supplier_type", "supplier_years", "supplier_location", "transaction_volume", "customization")
    known_factory_fields = sum(detail.get(name) not in (None, "", [], {}) for name in factory_fields)
    supplier.raw_data["supplier_evidence_completeness"] = round(known_factory_fields / len(factory_fields), 4)
    if detail.get("risk_flags"):
        supplier.raw_data["risk_flags"] = list(dict.fromkeys([
            *(supplier.raw_data.get("risk_flags") or []),
            *detail["risk_flags"],
        ]))
    return supplier


def _factory_flag(value: Any) -> bool | None:
    text = str(value or "").casefold()
    if any(term in text for term in ("生产厂家", "生产企业", "制造商", "manufacturer", "factory", "工厂")):
        return True
    if any(term in text for term in ("贸易", "经销", "批发商", "trading", "distributor")):
        return False
    return None


def _raise_if_blocked(html: str) -> None:
    # Normal offer pages can bundle anti-bot JavaScript containing words such
    # as "captcha" even when no verification UI is shown. Only visible page
    # text is authoritative for a human-action handoff.
    lowered = _html_text(html or "").lower()
    for error_code, markers in _BLOCK_MARKERS:
        matches = [marker for marker in markers if marker.lower() in lowered]
        if matches:
            raise BlockedOfferPage(error_code, f"blocked page marker: {matches[0]}")


def _looks_like_offer_page(
    html: str,
    *,
    page_url: str | None = None,
    primary: dict[str, Any] | None = None,
) -> bool:
    lowered = (html or "").lower()
    if (
        _primary_offer_ids(primary or {})
        or _canonical_offer_ids(html)
        or _offer_ids_from_urls(page_url or "")
    ):
        return True
    marker_groups = (
        ("起订", "起批", "beginamount", "minorder", "moq"),
        ("价格", "阶梯价", "pricerange", "¥", "￥"),
        ("材质", "material", "attributes"),
        ("规格", "尺寸", "重量", "spec", "dimensions", "weight"),
        ("包装", "package", "packing"),
        ("detailimage", "skuimage", "alicdn.com"),
    )
    return sum(any(marker.lower() in lowered for marker in group) for group in marker_groups) >= 2


def _with_provenance(detail: dict[str, Any], artifact: str | dict[str, Any]) -> dict[str, Any]:
    canonical = artifact if isinstance(artifact, str) else json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    artifact_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    observed_at = datetime.now(timezone.utc).isoformat()
    result = dict(detail)
    for key in _REQUIRED_DETAIL_FIELDS:
        value = result.get(key)
        if value in ("", [], {}):
            value = None
        result[key] = value
    result["observed_at"] = observed_at
    result["artifact_hash"] = artifact_hash
    result["provenance"] = {
        key: {
            "status": "extracted" if result[key] is not None else "missing",
            "source_type": "offer_detail",
            "observed_at": observed_at,
            "confidence": 0.95 if result[key] is not None else None,
            "artifact_hash": artifact_hash,
        }
        for key in _REQUIRED_DETAIL_FIELDS
    }
    return result


def _coalesce(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _first_present(parent: dict[str, Any], *keys: str) -> Any:
    return _deep_first_present(parent, set(keys))


def _deep_first_present(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] is not None:
                return value[key]
        for child in value.values():
            found = _deep_first_present(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_first_present(item, keys)
            if found is not None:
                return found
    return None


def _attribute_value(data: dict[str, Any], *labels: str) -> Any:
    wanted = {label.lower() for label in labels}
    for item in _all_dicts(data):
        name = _first_value(item, "attributeName", "attrName", "name", "key", "propertyName")
        if name is not None and str(name).lower() in wanted:
            return _first_value(item, "value", "attributeValue", "attrValue", "propertyValue", "text")
    return None


def _all_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _all_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _all_dicts(item)


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings = [str(item) for item in value if isinstance(item, (str, int, float))]
        return strings or None
    return None


def _detail_text(raw: str | dict[str, Any]) -> str:
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    _flatten(raw, parts)
    return " ".join(str(part) for part in parts if part not in (None, "", [], {}))


def _html_text(html: str) -> str:
    without_scripts = _SCRIPT_RE.sub(" ", html or "")
    return unescape(_TAG_RE.sub(" ", without_scripts))


def _embedded_json_objects(html: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in _SCRIPT_RE.findall(html or ""):
        for raw in _balanced_json_candidates(script):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                objects.append(obj)
                for nested in _interesting_dicts(obj):
                    objects.append(nested)
    return objects


def _balanced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for start, char in enumerate(text or ""):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            current = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:idx + 1])
                    break
    return candidates[:20]


def _interesting_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key in value for key in ("saleInfo", "detailInfo", "offerInfo", "productInfo", "priceRangeList")):
            found.append(value)
        for child in value.values():
            found.extend(_interesting_dicts(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(_interesting_dicts(item))
    return found


def _flatten(value: Any, parts: list[str], depth: int = 0) -> None:
    if depth > 6 or value in (None, "", [], {}):
        return
    if isinstance(value, (str, int, float)):
        parts.append(str(value))
        return
    if isinstance(value, list):
        for item in value:
            _flatten(item, parts, depth + 1)
        return
    if isinstance(value, dict):
        label = _first_value(value, "attributeName", "attrName", "name", "key", "propertyName", "specName")
        attr_value = _first_value(value, "value", "attributeValue", "attrValue", "propertyValue", "specValue", "text")
        if label or attr_value:
            parts.append(" ".join(str(v) for v in (label, attr_value) if v not in (None, "")))
        for child in value.values():
            _flatten(child, parts, depth + 1)


def _price_tiers(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    _collect_lists(data, candidates, {"priceRangeList", "priceRanges", "priceTiers", "skuPriceList"})
    tiers: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        qty = _first_int(item, "startQuantity", "beginAmount", "minQuantity", "quantity")
        price = _first_float(item, "price", "priceCny", "discountPrice")
        if qty is not None and price is not None:
            tiers.append({"min_qty": qty, "price_cny": price})
    return _dedupe_tiers(tiers)


def _price_tiers_from_text(text: str) -> list[dict[str, Any]]:
    tiers = [
        {"min_qty": int(qty), "price_cny": float(price)}
        for qty, price in _PRICE_TIER_RE.findall(text or "")
        if float(price) >= 0.1
    ]
    return _dedupe_tiers(tiers)


def _collect_lists(value: Any, output: list[Any], keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, list):
                output.extend(child)
            else:
                _collect_lists(child, output, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_lists(item, output, keys)


def _dedupe_tiers(tiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_qty: dict[int, dict[str, Any]] = {}
    for tier in tiers:
        by_qty[int(tier["min_qty"])] = tier
    return [by_qty[key] for key in sorted(by_qty)]


def _first_price(tiers: list[dict[str, Any]]) -> float | None:
    if not tiers:
        return None
    return min(float(tier["price_cny"]) for tier in tiers if tier.get("price_cny") is not None)


def _moq_from_text(text: str) -> int | None:
    match = _MOQ_RE.search(text or "")
    return int(match.group(1)) if match else None


def _delivery_from_text(text: str) -> int | None:
    match = _DELIVERY_RE.search(text or "")
    return int(match.group(1)) if match else None


def _parse_dimensions(text: str) -> tuple[float, float, float] | None:
    match = _DIM_RE.search(text or "")
    if not match:
        return None
    return tuple(round(float(v), 2) for v in match.groups())  # type: ignore[return-value]


def _format_dimensions(value: tuple[float, float, float] | None) -> str | None:
    if not value:
        return None
    return "x".join(f"{float(v):.1f}" for v in value) + "cm"


def _weight_from_text(text: str) -> float | None:
    match = _WEIGHT_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "g").lower()
    return round(value * 1000, 1) if unit in {"kg", "千克", "公斤"} else round(value, 1)


def _risk_flags(text: str, existing: list[str]) -> list[str]:
    lowered = (text or "").lower()
    flags = list(existing or [])
    if any(term in lowered if term.isascii() else term in text for term in _PATENT_TERMS):
        flags.append("patent_claim")
    if any(term in lowered if term.isascii() else term in text for term in _BRAND_TERMS):
        flags.append("brand_authorization_required")
    return list(dict.fromkeys(flags))


def _first_value(parent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = parent.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _first_int(parent: dict[str, Any], *keys: str) -> int | None:
    value = _deep_first_value(parent, set(keys))
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _first_float(parent: dict[str, Any], *keys: str) -> float | None:
    value = _deep_first_value(parent, set(keys))
    try:
        return float(str(value).replace("¥", "").replace("￥", ""))
    except (TypeError, ValueError):
        return None


def _deep_first_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            child = value.get(key)
            if child not in (None, "", [], {}):
                return child
        for child in value.values():
            found = _deep_first_value(child, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_first_value(item, keys)
            if found not in (None, "", [], {}):
                return found
    return None

"""1688 offer detail parsing and supplier enrichment."""
from __future__ import annotations

import json
import re
from typing import Any
from html import unescape

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
}


def parse_1688_offer_detail(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Extract sourcing-critical details from a 1688 detail payload or text."""
    data = raw if isinstance(raw, dict) else {}
    text = _detail_text(raw)
    spec = spec_from_text(text)
    price_tiers = _price_tiers(data) or _price_tiers_from_text(text)
    dimensions = spec.dimensions_cm or _parse_dimensions(text)
    detail = {
        "moq": _first_int(data, "minOrderQuantity", "minOrder", "moq", "beginAmount") or _moq_from_text(text),
        "base_price_cny": _first_price(price_tiers) or _first_float(data, "price", "priceCny", "minPrice"),
        "price_tiers": price_tiers,
        "delivery_days": _first_int(data, "deliveryDays", "leadTime", "sendGoodsDays") or _delivery_from_text(text),
        "product_dimensions_cm": _format_dimensions(dimensions),
        "product_weight_g": spec.weight_g or _weight_from_text(text),
        "material": spec.material,
        "color": spec.color,
        "risk_flags": _risk_flags(text, spec.risk_flags),
        "raw_text": text,
    }
    return {key: value for key, value in detail.items() if value not in (None, "", [], {})}


def parse_1688_offer_detail_html(html: str) -> dict[str, Any]:
    """Extract detail evidence from a 1688 HTML detail page."""
    text = _html_text(html)
    best: dict[str, Any] = {}
    for obj in _embedded_json_objects(html):
        detail = parse_1688_offer_detail(obj)
        if len(detail) > len(best):
            best = detail
    fallback = parse_1688_offer_detail(text)
    if not best:
        return fallback
    merged = {**fallback, **best}
    merged["risk_flags"] = _risk_flags(text, list(dict.fromkeys([
        *(fallback.get("risk_flags") or []),
        *(best.get("risk_flags") or []),
    ])))
    return {key: value for key, value in merged.items() if value not in (None, "", [], {})}


def apply_1688_detail_to_supplier(supplier: SupplierDTO, raw: str | dict[str, Any]) -> SupplierDTO:
    """Fill missing SupplierDTO fields from parsed 1688 detail evidence."""
    if isinstance(raw, dict) and any(key in raw for key in _PARSED_DETAIL_KEYS):
        detail = {key: value for key, value in raw.items() if value not in (None, "", [], {})}
    else:
        detail = parse_1688_offer_detail(raw)
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
    supplier.raw_data.setdefault("detail", {}).update(detail)
    if detail.get("risk_flags"):
        supplier.raw_data["risk_flags"] = list(dict.fromkeys([
            *(supplier.raw_data.get("risk_flags") or []),
            *detail["risk_flags"],
        ]))
    return supplier


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

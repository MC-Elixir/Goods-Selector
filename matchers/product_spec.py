"""Structured product specs and deterministic match scoring."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

MATERIAL_ALIASES = {
    "不锈钢": ("不锈钢", "304", "316", "stainless steel"),
    "硅胶": ("硅胶", "silicone"),
    "塑料": ("塑料", "plastic", "pp", "abs"),
    "铝合金": ("铝合金", "铝", "aluminum", "aluminium"),
    "棉": ("棉", "cotton"),
    "聚酯纤维": ("聚酯", "涤纶", "polyester", "化纤", "微纤维", "microfiber", "microfibre"),
    "记忆棉": ("记忆棉", "memory foam"),
    "树脂": ("树脂", "resin"),
    "钢": ("钢", "碳钢", "铁艺", "steel", "carbon steel", "powder coated steel"),
    "藤编": ("藤编", "藤条", "pe藤", "wicker", "rattan", "pe rattan"),
    "木": ("木", "实木", "柚木", "相思木", "wood", "teak", "acacia"),
    "腈纶": ("腈纶", "acrylic", "solution-dyed acrylic"),
    "烯烃布": ("烯烃布", "olefin"),
    "高密度聚乙烯": ("高密度聚乙烯", "hdpe", "high density polyethylene"),
}

CATEGORY_ALIASES = {
    "灭蚁用品": ("灭蚁", "蚂蚁药", "蚂蚁诱饵", "ant killer", "ant bait", "ant trap", "bait station"),
    "驱蚊用品": ("驱蚊", "灭蚊", "蚊香", "mosquito repellent", "mosquito killer", "mosquito trap"),
    "杀蟑用品": ("杀蟑", "蟑螂药", "蟑螂诱饵", "cockroach bait", "roach bait", "roach killer"),
    "餐厨用品": ("厨具", "锅铲", "烹饪工具", "硅胶铲", "厨房工具", "碗", "餐盒", "饭盒", "保鲜盒", "餐具", "锅", "cookware", "spatula", "cooking utensil"),
    "垃圾桶": ("垃圾桶", "垃圾箱", "trash can", "garbage bin", "waste bin"),
    "床品套件": ("床品套件", "四件套", "三件套", "床单", "被套", "sheet set", "bed sheet", "bedding set", "duvet cover"),
    "枕头": ("枕头", "枕", "pillow"),
    "保温杯": ("保温杯", "水杯", "water bottle", "tumbler"),
    "收纳盒": ("收纳盒", "收纳", "storage box", "organizer"),
    "瑜伽垫": ("瑜伽垫", "yoga mat"),
    "手机支架": ("手机支架", "phone stand"),
    "户外储物": ("户外储物", "庭院储物", "deck box", "outdoor storage", "storage shed", "outdoor cabinet", "storage bench"),
    "户外取暖器": ("户外取暖器", "露台取暖器", "patio heater", "outdoor heater", "propane heater"),
    "户外家具套装": ("户外家具", "庭院家具", "户外桌椅", "outdoor furniture set", "patio furniture", "conversation set", "outdoor dining set"),
    "户外遮阳": (
        "遮阳伞", "庭院伞", "中柱伞", "太阳伞", "沙滩伞", "遮阳帆",
        "patio umbrella", "market umbrella", "table umbrella", "cantilever umbrella",
        "beach umbrella", "shade sail",
    ),
}

COLOR_ALIASES = {
    "黑色": ("黑色", "black"),
    "白色": ("白色", "white"),
    "灰色": ("灰色", "gray", "grey"),
    "蓝色": ("蓝色", "blue"),
    "绿色": ("绿色", "green"),
    "红色": ("红色", "red"),
    "粉色": ("粉色", "pink"),
    "银色": ("银色", "silver"),
    "透明": ("透明", "clear", "transparent"),
}

RISK_TERMS = (
    "battery", "电池", "lithium", "锂电", "liquid", "液体", "磁", "magnet",
    "pesticide", "杀虫", "insecticide", "medical", "医疗", "婴儿", "baby",
)


@dataclass
class ProductSpec:
    category: Optional[str] = None
    material: Optional[str] = None
    color: Optional[str] = None
    dimensions_cm: tuple[float, float, float] | None = None
    weight_g: Optional[float] = None
    capacity_ml: Optional[float] = None
    pack_count: Optional[int] = None
    features: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class SpecMatchResult:
    score: float
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def spec_from_product(product, analysis=None) -> ProductSpec:
    raw = getattr(product, "raw_data", None)
    raw = raw if isinstance(raw, dict) else {}
    text = " ".join(
        str(v or "") for v in (
            getattr(product, "title", None),
            getattr(product, "category", None),
            getattr(product, "brand", None),
            " ".join(_flatten_attribute_values(raw.get("bullet_points"))),
            raw.get("description"),
            " ".join(_flatten_attribute_values(raw.get("attributes"))),
        )
    )
    spec = spec_from_text(text)
    analysis_category = getattr(analysis, "category_zh", None)
    spec.category = (
        _canonical_category(analysis_category)
        or spec.category
        or _canonical_category(getattr(product, "category", None))
    )
    if analysis is not None:
        spec.material = getattr(analysis, "material", None) or spec.material
        spec.color = getattr(analysis, "color", None) or spec.color
        spec.features = _dedupe([*spec.features, *(getattr(analysis, "key_features", None) or [])])
        if getattr(analysis, "has_dangerous_attr", False):
            spec.risk_flags = _dedupe([*spec.risk_flags, "vision_dangerous_attr"])
    weight_kg = getattr(product, "weight_kg", None)
    if weight_kg and spec.weight_g is None:
        spec.weight_g = round(float(weight_kg) * 1000, 1)
    dims = [
        getattr(product, "length_cm", None),
        getattr(product, "width_cm", None),
        getattr(product, "height_cm", None),
    ]
    if all(dims) and spec.dimensions_cm is None:
        spec.dimensions_cm = tuple(round(float(d), 2) for d in dims)  # type: ignore[assignment]
    return spec


def spec_from_supplier(supplier) -> ProductSpec:
    raw = getattr(supplier, "raw_data", None) or {}
    raw_spec_text = _supplier_raw_spec_text(raw)
    text = " ".join(
        str(v or "") for v in (
            getattr(supplier, "title_cn", None),
            getattr(supplier, "supplier_name", None),
            raw.get("title_cn"),
            raw.get("full_text"),
            raw_spec_text,
            getattr(supplier, "material", None),
            getattr(supplier, "color", None),
            getattr(supplier, "product_dimensions_cm", None),
        )
    )
    spec = spec_from_text(text)
    spec.material = getattr(supplier, "material", None) or spec.material
    spec.color = getattr(supplier, "color", None) or spec.color
    spec.dimensions_cm = _parse_dimensions(getattr(supplier, "product_dimensions_cm", None)) or spec.dimensions_cm
    spec.weight_g = getattr(supplier, "product_weight_g", None) or spec.weight_g
    return spec


def _supplier_raw_spec_text(raw: dict[str, Any]) -> str:
    """Flatten common 1688/OpenAPI attribute shapes into text for spec parsing."""
    if not isinstance(raw, dict):
        return ""
    parts: list[str] = []
    for key in (
        "productAttributeList", "productAttributes", "attributes", "attributeList",
        "properties", "propertyList", "specs", "skuAttributes", "skuProps",
        "saleProperties", "productProps", "offerAttributes",
    ):
        parts.extend(_flatten_attribute_values(raw.get(key)))
    for parent_key in ("productInfo", "saleInfo", "skuInfo", "detailInfo", "result", "data"):
        child = raw.get(parent_key)
        if isinstance(child, dict):
            parts.extend(_flatten_attribute_values(child))
    detail = raw.get("detail")
    if isinstance(detail, dict):
        parts.extend(_flatten_attribute_values(detail))
    return " ".join(_dedupe([p for p in parts if p]))


def _flatten_attribute_values(value: Any, depth: int = 0) -> list[str]:
    if value in (None, "", [], {}) or depth > 5:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_attribute_values(item, depth + 1))
        return parts
    if not isinstance(value, dict):
        return []

    label = _first_attr_value(
        value,
        "attributeName", "attrName", "name", "key", "propertyName",
        "propName", "specName", "title", "label",
    )
    attr_value = _first_attr_value(
        value,
        "value", "attributeValue", "attrValue", "propertyValue",
        "propValue", "specValue", "text", "displayValue",
    )
    parts = []
    if label or attr_value:
        parts.append(" ".join(str(v) for v in (label, attr_value) if v not in (None, "")))

    for key, child in value.items():
        if key in {
            "attributeName", "attrName", "name", "key", "propertyName", "propName",
            "specName", "title", "label", "value", "attributeValue", "attrValue",
            "propertyValue", "propValue", "specValue", "text", "displayValue",
        }:
            continue
        if _looks_like_spec_key(str(key)):
            parts.append(f"{key} {child}")
        elif isinstance(child, (dict, list)):
            parts.extend(_flatten_attribute_values(child, depth + 1))
    return parts


def _first_attr_value(parent: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = parent.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _looks_like_spec_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in (
        "material", "color", "colour", "capacity", "volume", "size",
        "dimension", "length", "width", "height", "weight", "pack",
        "材质", "颜色", "容量", "尺寸", "规格", "长", "宽", "高", "重量", "净重", "件数",
    ))


def spec_from_text(text: str) -> ProductSpec:
    raw = text or ""
    normalized = raw.lower()
    return ProductSpec(
        category=_infer_category(raw),
        material=_find_alias(raw, normalized, MATERIAL_ALIASES),
        color=_find_alias(raw, normalized, COLOR_ALIASES),
        dimensions_cm=_parse_dimensions(raw),
        weight_g=_parse_weight_g(raw, normalized),
        capacity_ml=_parse_capacity_ml(raw, normalized),
        pack_count=_parse_pack_count(raw, normalized),
        features=_extract_features(raw, normalized),
        risk_flags=_extract_risks(raw, normalized),
        raw_text=raw,
    )


def compare_specs(target: ProductSpec, candidate: ProductSpec) -> SpecMatchResult:
    matched: list[str] = []
    missing: list[str] = []
    conflicts: list[str] = []
    weighted_score = 0.0
    total_weight = 0.0

    def add(name: str, weight: float, result: Optional[bool], required: bool = True) -> None:
        nonlocal weighted_score, total_weight
        if result is None and not required:
            return
        total_weight += weight
        if result is True:
            matched.append(name)
            weighted_score += weight
        elif result is False:
            conflicts.append(name)
        else:
            missing.append(name)
            weighted_score += weight * 0.35

    add("category", 2.0, _same_category(target.category, candidate.category), target.category is not None)
    add("material", 1.2, _same_alias(target.material, candidate.material, MATERIAL_ALIASES), target.material is not None)
    add("capacity", 1.0, _close_number(target.capacity_ml, candidate.capacity_ml, 0.12), target.capacity_ml is not None)
    add("pack_count", 1.0, _same_number(target.pack_count, candidate.pack_count), target.pack_count is not None)
    add("dimensions", 1.0, _close_dimensions(target.dimensions_cm, candidate.dimensions_cm), target.dimensions_cm is not None)
    add("color", 0.4, _same_alias(target.color, candidate.color, COLOR_ALIASES), target.color is not None)

    if target.features:
        total_weight += 0.8
        hits = _feature_hits(target.features, candidate.raw_text)
        if hits:
            matched.append("features")
            weighted_score += 0.8 * min(hits / len(target.features), 1.0)
        else:
            missing.append("features")
            weighted_score += 0.8 * 0.25

    return SpecMatchResult(
        score=round(weighted_score / total_weight if total_weight else 0.0, 4),
        matched=matched,
        missing=missing,
        conflicts=conflicts,
    )


def _find_alias(raw: str, normalized: str, aliases: dict[str, tuple[str, ...]]) -> Optional[str]:
    for canonical, values in aliases.items():
        for value in values:
            haystack = normalized if _is_ascii(value) else raw
            needle = value.lower() if _is_ascii(value) else value
            if _alias_present(needle, haystack):
                return canonical
    return None


def _infer_category(text: str) -> Optional[str]:
    lowered = text.lower()
    if "umbrella" in lowered and any(
        context in lowered for context in ("patio", "outdoor", "garden", "table", "market")
    ):
        return "户外遮阳"
    rules = (
        ("户外取暖器", ("patio heater", "outdoor heater", "propane heater", "露台取暖器", "户外取暖器", "燃气取暖器")),
        ("户外家具套装", ("patio furniture", "outdoor furniture set", "outdoor conversation set", "outdoor dining set", "户外家具", "庭院家具", "户外桌椅")),
        ("户外遮阳", ("patio umbrella", "market umbrella", "table umbrella", "cantilever umbrella", "offset umbrella", "beach umbrella", "shade sail", "遮阳伞", "庭院伞", "中柱伞", "太阳伞", "沙滩伞", "遮阳帆")),
        ("户外储物", ("outdoor storage", "deck box", "storage shed", "outdoor cabinet", "storage bench", "户外储物", "庭院储物", "储物棚")),
        ("灭蚁用品", ("ant killer", "ant bait", "ant trap", "bait station", "灭蚁", "蚂蚁药", "蚂蚁诱饵")),
        ("驱蚊用品", ("mosquito repellent", "mosquito killer", "mosquito trap", "驱蚊", "灭蚊", "蚊香")),
        ("杀蟑用品", ("cockroach bait", "roach bait", "roach killer", "杀蟑", "蟑螂药", "蟑螂诱饵")),
        ("餐厨用品", ("cookware", "spatula", "cooking utensil", "锅铲", "硅胶铲", "厨房工具", "厨具", "碗", "餐盒", "饭盒", "保鲜盒", "餐具", "锅")),
        ("垃圾桶", ("垃圾桶", "垃圾箱", "trash can", "garbage bin", "waste bin")),
        ("枕头", ("pillow", "枕")),
        ("床品套件", ("sheet set", "bed sheet", "bed sheets", "bedding set", "duvet cover", "床单", "床品", "四件套", "三件套", "被套")),
        ("保温杯", ("water bottle", "tumbler", "保温杯", "水杯")),
        ("收纳盒", ("storage box", "organizer", "收纳")),
        ("瑜伽垫", ("yoga mat", "瑜伽垫")),
        ("手机支架", ("phone stand", "手机支架")),
    )
    for category, needles in rules:
        if any((n in lowered if _is_ascii(n) else n in text) for n in needles):
            return category
    return None


def _canonical_category(value: Any) -> Optional[str]:
    if not value:
        return None
    raw = str(value)
    lowered = raw.lower()
    return _find_alias(raw, lowered, CATEGORY_ALIASES)


def _parse_dimensions(text: Any) -> tuple[float, float, float] | None:
    if not text:
        return None
    s = str(text).lower().replace("×", "x").replace("*", "x")
    m = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(cm|厘米|m|米|in|inch|inches|英寸|ft|feet|foot|英尺)?", s)
    if not m:
        return None
    values = [float(m.group(i)) for i in (1, 2, 3)]
    unit = m.group(4) or "cm"
    if unit in {"in", "inch", "英寸"}:
        values = [v * 2.54 for v in values]
    elif unit in {"ft", "feet", "foot", "英尺"}:
        values = [v * 30.48 for v in values]
    elif unit in {"m", "米"}:
        values = [v * 100 for v in values]
    return tuple(round(v, 2) for v in values)  # type: ignore[return-value]


def _parse_weight_g(raw: str, normalized: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg\b|公斤|千克)", normalized)
    if m:
        return round(float(m.group(1)) * 1000, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(lb\b|lbs\b|pound\b|pounds\b)", normalized)
    if m:
        return round(float(m.group(1)) * 453.59237, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(oz\b|ounce\b|ounces\b)", normalized)
    if m:
        return round(float(m.group(1)) * 28.3495, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g\b|克)", normalized)
    if m:
        return round(float(m.group(1)), 1)
    return None


def _parse_capacity_ml(raw: str, normalized: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|毫升)", normalized)
    if m:
        return round(float(m.group(1)), 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(l|升)", normalized)
    if m:
        return round(float(m.group(1)) * 1000, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(oz|盎司)", normalized)
    if m:
        return round(float(m.group(1)) * 29.5735, 1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:us\s*)?(gallon|gallons|加仑)", normalized)
    if m:
        return round(float(m.group(1)) * 3785.411784, 1)
    return None


def _parse_pack_count(raw: str, normalized: str) -> Optional[int]:
    patterns = (
        r"(\d+)\s*[- ]?(?:pack|pcs|pieces|piece|count|ct)",
        r"(\d+)\s*[- ]?piece\s+set",
        r"(\d+)\s*[- ]?pc\s+set",
        r"(\d+)\s*(?:件套|条装|盒装|只装|个装|支装|片装|套装)",
        r"(?:pack of|set of)\s*(\d+)",
    )
    for pattern in patterns:
        m = re.search(pattern, normalized)
        if m:
            return int(m.group(1))
    m = re.search(r"([一二两三四五六七八九十])\s*(?:件套|条装|盒装|只装|个装|支装|片装|套装)", raw)
    if m:
        return _chinese_digit(m.group(1))
    return None


def _extract_features(raw: str, normalized: str) -> list[str]:
    features = []
    for label, values in {
        "折叠": ("foldable", "folding", "折叠"),
        "防水": ("waterproof", "防水"),
        "保温": ("insulated", "保温"),
        "可机洗": ("machine washable", "可机洗"),
        "带盖": ("with lid", "带盖"),
        "吸管": ("straw", "吸管"),
        "床单式": ("sheet set", "flat sheet", "fitted sheet", "床单式", "床单"),
        "深口袋": ("deep pocket", "deep pockets", "深口袋"),
        "透气": ("breathable", "透气"),
        "凉感": ("cooling", "凉感"),
        "柔软": ("soft", "柔软"),
        "防皱": ("wrinkle free", "wrinkle-free", "防皱"),
        "磨毛": ("磨毛", "brushed"),
        "纯色": ("solid color", "solid", "纯色"),
        "耐候": ("weather resistant", "weather-resistant", "耐候"),
        "防紫外线": ("uv resistant", "uv-resistant", "防紫外线", "抗uv"),
        "可上锁": ("lockable", "可上锁"),
        "倾斜": ("tilt", "倾斜"),
        "手摇": ("crank", "手摇", "摇把"),
        "倾倒保护": ("tip-over", "tip over", "倾倒保护"),
    }.items():
        if any((v in normalized if _is_ascii(v) else v in raw) for v in values):
            features.append(label)
    return features


def _chinese_digit(value: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return digits.get(value)


def _extract_risks(raw: str, normalized: str) -> list[str]:
    return [term for term in RISK_TERMS if (term in normalized if _is_ascii(term) else term in raw)]


def _same_text(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    if not a:
        return None
    if not b:
        return None
    return a == b or a in b or b in a


def _same_category(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    return _same_alias(a, b, CATEGORY_ALIASES)


def _same_alias(a: Optional[str], b: Optional[str], aliases: dict[str, tuple[str, ...]]) -> Optional[bool]:
    if not a:
        return None
    if not b:
        return None
    return bool(_canonical_set(a, aliases) & _canonical_set(b, aliases))


def _canonical(value: str, aliases: dict[str, tuple[str, ...]]) -> str:
    normalized = value.lower()
    for canonical, values in aliases.items():
        if value == canonical or normalized in values:
            return canonical
    return value


def _canonical_set(value: str, aliases: dict[str, tuple[str, ...]]) -> set[str]:
    normalized = value.lower()
    out: set[str] = set()
    for canonical, values in aliases.items():
        if value == canonical or normalized == canonical.lower():
            out.add(canonical)
            continue
        for alias in values:
            needle = alias.lower() if _is_ascii(alias) else alias
            haystack = normalized if _is_ascii(alias) else value
            if needle and _alias_present(needle, haystack):
                out.add(canonical)
                break
    if not out:
        out.add(_canonical(value, aliases))
    return out


def _alias_present(needle: str, haystack: str) -> bool:
    """Match short ASCII aliases as tokens, not inside dimensions or words."""
    if not needle:
        return False
    if not _is_ascii(needle):
        return needle in haystack
    escaped = re.escape(needle.casefold())
    value = haystack.casefold()
    if re.fullmatch(r"\d+", needle):
        return re.search(rf"(?<![\d.]){escaped}(?![\d.])", value) is not None
    if re.fullmatch(r"[a-z0-9]+", needle, re.I):
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", value) is not None
    return needle.casefold() in value


def _same_number(a: Optional[int], b: Optional[int]) -> Optional[bool]:
    if a is None:
        return None
    if b is None:
        return None
    return a == b


def _close_number(a: Optional[float], b: Optional[float], tolerance: float) -> Optional[bool]:
    if a is None:
        return None
    if b is None:
        return None
    if a == 0:
        return b == 0
    return abs(a - b) / a <= tolerance


def _close_dimensions(a: tuple[float, float, float] | None, b: tuple[float, float, float] | None) -> Optional[bool]:
    if a is None:
        return None
    if b is None:
        return None
    aa = sorted(a)
    bb = sorted(b)
    return all(abs(x - y) / max(x, 1) <= 0.15 for x, y in zip(aa, bb))


def _feature_hits(features: list[str], text: str) -> int:
    return sum(1 for f in features if f and f in text)


def _is_ascii(value: str) -> bool:
    return all(ord(ch) < 128 for ch in value)


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out

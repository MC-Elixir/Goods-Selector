"""Deterministic contracts for the four client outdoor sourcing categories.

The goal of this module is intentionally narrower than generic product NLP:
identify the product family, preserve decision-grade numeric attributes in
canonical units, and reject explicit full-product/accessory or specification
conflicts before semantic or business ranking can rescue a bad match.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from schemas.sourcing import AmazonProductUnderstanding

TARGET_CATEGORY_IDS = {
    "outdoor_storage",
    "patio_heater",
    "patio_furniture_sets",
    "patio_umbrellas_shade",
}

CATEGORY_NAMES = {
    "outdoor_storage": "Outdoor Storage",
    "patio_heater": "Patio Heater",
    "patio_furniture_sets": "Patio Furniture Sets",
    "patio_umbrellas_shade": "Patio Umbrellas & Shade",
}

_GENERIC_SUBTYPES = {
    "outdoor_storage",
    "patio_heater",
    "patio_furniture_set",
    "umbrella_shade",
    "patio_umbrella",
}

_MATERIAL_ALIASES = {
    "resin": ("resin", "树脂"),
    "hdpe": ("hdpe", "high density polyethylene", "高密度聚乙烯"),
    "plastic": ("plastic", "polypropylene", "polyethylene", "pp塑料", "塑料"),
    "steel": ("stainless steel", "powder coated steel", "carbon steel", "steel", "不锈钢", "碳钢", "铁艺", "钢"),
    "aluminum": ("aluminum", "aluminium", "铝合金", "铝"),
    "wood": ("solid wood", "acacia", "teak", "wood", "实木", "柚木", "相思木", "木"),
    "rattan": ("pe rattan", "wicker", "rattan", "藤编", "藤条", "藤"),
    "polyester": ("polyester", "涤纶", "聚酯"),
    "olefin": ("olefin", "烯烃布"),
    "acrylic": ("acrylic", "solution-dyed acrylic", "腈纶", "亚克力布"),
}

_FUNCTIONS = {
    "outdoor_storage": ["户外储物", "防雨收纳"],
    "patio_heater": ["户外取暖", "露台加热"],
    "patio_furniture_sets": ["户外坐卧", "庭院家具组合"],
    "patio_umbrellas_shade": ["户外遮阳", "庭院防晒"],
}

_SUPPLY_NAMES = {
    "outdoor_storage": "户外储物产品",
    "patio_heater": "户外取暖器",
    "patio_furniture_sets": "户外家具套装",
    "patio_umbrellas_shade": "户外遮阳产品",
}

_MATERIAL_SEARCH_CN = {
    "resin": "树脂",
    "hdpe": "高密度聚乙烯",
    "plastic": "塑料",
    "steel": "钢制",
    "aluminum": "铝合金",
    "wood": "实木",
    "rattan": "藤编",
    "polyester": "涤纶",
    "olefin": "烯烃布",
    "acrylic": "腈纶",
}

_COMPONENT_SEARCH_CN = {
    "door": "门板",
    "lid": "箱盖",
    "shelf": "层板",
    "burner": "燃烧器",
    "reflector": "反射罩",
    "table": "桌子",
    "chair": "椅子",
    "sofa": "沙发",
    "cushion": "坐垫",
    "canopy": "伞面",
    "rib": "伞骨",
    "pole": "伞杆",
    "base": "底座",
}

_SUBTYPE_TERMS_CN = {
    "deck_box": ["户外储物箱", "庭院甲板箱", "防水收纳箱"],
    "storage_shed": ["户外储物棚", "庭院工具房"],
    "storage_cabinet": ["户外储物柜", "庭院工具柜"],
    "storage_bench": ["户外储物凳", "庭院收纳长椅"],
    "storage_bin": ["户外收纳桶", "户外储物箱"],
    "pyramid_heater": ["金字塔燃气取暖器", "户外塔式取暖器"],
    "mushroom_heater": ["蘑菇头燃气取暖器", "户外立式取暖器"],
    "tabletop_heater": ["桌面户外取暖器", "小型露台取暖器"],
    "wall_mounted_heater": ["壁挂户外取暖器", "户外红外取暖器"],
    "hanging_heater": ["吊顶户外取暖器", "悬挂式取暖器"],
    "freestanding_heater": ["户外立式取暖器", "露台取暖器"],
    "sectional_set": ["户外组合沙发套装", "庭院转角沙发"],
    "conversation_set": ["户外休闲桌椅套装", "庭院会客家具"],
    "dining_set": ["户外餐桌椅套装", "庭院餐桌组合"],
    "bistro_set": ["户外三件套桌椅", "庭院小桌椅"],
    "sofa_set": ["户外沙发套装", "庭院藤编沙发"],
    "market_umbrella": ["户外中柱遮阳伞", "庭院市场伞"],
    "cantilever_umbrella": ["户外侧立伞", "庭院香蕉伞", "悬臂遮阳伞"],
    "beach_umbrella": ["沙滩伞", "户外沙滩遮阳伞"],
    "clamp_umbrella": ["夹式遮阳伞", "椅夹伞"],
    "shade_sail": ["户外遮阳帆", "庭院遮阳布"],
    "gazebo_canopy": ["户外凉亭", "庭院遮阳棚"],
    "replacement_canopy": ["替换伞布", "遮阳伞替换篷布"],
}


@dataclass
class TargetCategoryProfile:
    category_id: str
    category_name: str
    subtype: str
    relation: str
    numeric: dict[str, float | int | list[float]] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    materials: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)
    search_terms_cn: list[str] = field(default_factory=list)
    evidence_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TargetCategoryProfile":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})


@dataclass
class TargetCategoryMatch:
    score: float
    decision: str
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str:
    text = str(value or "").casefold()
    text = text.replace("×", "x").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _contains(text: str, values: tuple[str, ...] | list[str]) -> bool:
    return any(value in text for value in values)


def classify_target_category(text: str) -> str | None:
    value = _norm(text)
    if (
        ("户外" in value or "庭院" in value) and _contains(value, ("家具", "桌椅", "沙发"))
    ) or _contains(value, (
        "patio furniture", "outdoor furniture set", "outdoor conversation set",
        "conversation patio furniture",
        "outdoor dining set", "outdoor bistro set", "outdoor sectional",
        "庭院家具", "户外家具", "户外桌椅", "户外沙发", "藤编沙发",
    )):
        return "patio_furniture_sets"
    if (
        ("户外" in value or "露台" in value) and "取暖器" in value
    ) or _contains(value, (
        "patio heater", "outdoor heater", "terrace heater", "propane heater",
        "electric patio heater", "露台取暖", "户外取暖", "燃气取暖器",
        "伞形取暖器", "蘑菇头取暖器",
    )):
        return "patio_heater"
    umbrella_context = "umbrella" in value and _contains(
        value, ("patio", "outdoor", "garden", "table", "market")
    )
    if umbrella_context or _contains(value, (
        "patio umbrella", "market umbrella", "cantilever umbrella", "offset umbrella",
        "beach umbrella", "clamp umbrella", "umbrella canopy", "shade sail",
        "gazebo canopy", "sun shade", "遮阳伞", "沙滩伞", "香蕉伞", "侧立伞",
        "罗马伞", "遮阳帆", "遮阳棚", "伞布",
    )):
        return "patio_umbrellas_shade"
    if _contains(value, (
        "outdoor storage", "deck box", "patio storage", "garden storage",
        "storage shed", "outdoor cabinet", "storage bench", "户外储物",
        "庭院储物", "户外收纳", "储物棚", "工具房", "户外储物柜",
    )):
        return "outdoor_storage"
    return None


def _relation(text: str, category_id: str) -> str:
    value = _norm(text)
    replacement_patterns = (
        r"\breplacement\b", r"\bspare\s+part\b", r"\bcanopy\s+only\b",
        r"\bfabric\s+only\b", r"替换(?:件|布|篷|顶|坐垫|伞布|篷布)", r"仅伞布", r"配件替换",
    )
    if any(re.search(pattern, value) for pattern in replacement_patterns):
        return "replacement"
    accessory_patterns = {
        "outdoor_storage": (
            r"(?:protective\s+)?cover\s+for\s+(?:deck|storage)", r"储物箱防护罩",
        ),
        "patio_heater": (
            r"patio\s+heater\s+cover", r"heater\s+(?:reflector|burner|regulator|thermocouple|wheel\s+kit)",
            r"取暖器(?:罩|反射罩|燃烧器|减压阀|热电偶|配件)",
        ),
        "patio_furniture_sets": (
            r"patio\s+furniture\s+(?:set\s+)?cover", r"replacement\s+cushion", r"furniture\s+clips?",
            r"家具(?:防护罩|罩|替换坐垫|固定夹|配件)",
        ),
        "patio_umbrellas_shade": (
            r"umbrella\s+(?:base|stand|cover|light)", r"base\s+for\s+(?:patio\s+)?umbrella",
            r"遮阳伞(?:底座|伞座|防护罩|灯|配件)",
        ),
    }
    if any(re.search(pattern, value) for pattern in accessory_patterns.get(category_id, ())):
        return "accessory"
    return "full_product"


def _subtype(text: str, category_id: str, relation: str) -> str:
    value = _norm(text)
    if category_id == "outdoor_storage":
        if _contains(value, ("storage shed", "garden shed", "储物棚", "工具房")):
            return "storage_shed"
        if _contains(value, ("storage cabinet", "outdoor cabinet", "储物柜", "工具柜")):
            return "storage_cabinet"
        if _contains(value, ("storage bench", "deck bench", "储物凳", "收纳长椅")):
            return "storage_bench"
        if _contains(value, ("deck box", "patio box", "甲板箱", "户外储物箱")):
            return "deck_box"
        if _contains(value, ("storage bin", "收纳桶")):
            return "storage_bin"
        return "outdoor_storage"
    if category_id == "patio_heater":
        if _contains(value, ("pyramid", "金字塔", "塔式")):
            return "pyramid_heater"
        if _contains(value, ("mushroom", "蘑菇", "伞形")):
            return "mushroom_heater"
        if _contains(value, ("tabletop", "table top", "桌面")):
            return "tabletop_heater"
        if _contains(value, ("wall mounted", "wall-mounted", "壁挂")):
            return "wall_mounted_heater"
        if _contains(value, ("hanging", "ceiling", "悬挂", "吊顶")):
            return "hanging_heater"
        if _contains(value, ("freestanding", "standing", "立式")):
            return "freestanding_heater"
        return "patio_heater"
    if category_id == "patio_furniture_sets":
        if relation != "full_product":
            return "furniture_accessory"
        if _contains(value, ("sectional", "corner sofa", "组合沙发", "转角沙发")):
            return "sectional_set"
        if _contains(value, ("dining set", "dining table", "餐桌椅", "餐桌套装")):
            return "dining_set"
        if _contains(value, ("bistro", "小桌椅")):
            return "bistro_set"
        if _contains(value, ("conversation set", "outdoor conversation", "会客", "休闲桌椅")):
            return "conversation_set"
        if _contains(value, ("sofa set", "沙发套装")):
            return "sofa_set"
        return "patio_furniture_set"
    if relation == "replacement":
        return "replacement_canopy"
    if relation == "accessory":
        return "umbrella_accessory"
    broad_umbrella_category = _contains(
        value,
        ("patio umbrellas & shade", "patio umbrellas and shade", "umbrella shade category"),
    )
    explicit_subtype = _contains(value, (
        "market umbrella", "market patio umbrella", "cantilever", "offset umbrella", "banana umbrella",
        "beach umbrella", "clamp umbrella", "chair umbrella", "shade sail",
        "gazebo", "pergola", "庭院伞", "中柱伞", "市场伞", "香蕉伞",
        "侧立伞", "罗马伞", "沙滩伞", "夹式伞", "椅夹伞", "遮阳帆", "凉亭",
    ))
    if broad_umbrella_category and not explicit_subtype:
        return "umbrella_shade"
    if _contains(value, ("shade sail", "遮阳帆")):
        return "shade_sail"
    if _contains(value, ("gazebo", "pergola", "凉亭", "遮阳棚")):
        return "gazebo_canopy"
    if _contains(value, ("cantilever", "offset umbrella", "banana umbrella", "香蕉伞", "侧立伞", "罗马伞")):
        return "cantilever_umbrella"
    if _contains(value, ("beach umbrella", "沙滩伞")):
        return "beach_umbrella"
    if _contains(value, ("clamp umbrella", "chair umbrella", "夹式伞", "椅夹伞")):
        return "clamp_umbrella"
    if _contains(value, (
        "patio umbrella", "market umbrella", "table umbrella", "umbrella outdoor patio",
        "庭院伞", "中柱伞", "中柱遮阳伞", "市场伞",
    )):
        return "market_umbrella"
    return "patio_umbrella"


def _to_cm(value: float, unit: str) -> float:
    unit = unit.casefold()
    factor = {
        "mm": 0.1, "毫米": 0.1,
        "cm": 1.0, "厘米": 1.0, "公分": 1.0,
        "m": 100.0, "米": 100.0,
        "in": 2.54, "inch": 2.54, "inches": 2.54, '"': 2.54, "英寸": 2.54,
        "ft": 30.48, "foot": 30.48, "feet": 30.48, "英尺": 30.48,
    }[unit]
    return round(value * factor, 2)


_UNIT = r"(?:mm|cm|m|inches|inch|in|ft|feet|foot|毫米|厘米|公分|米|英寸|英尺|\")"


def _measurement(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        try:
            return _to_cm(float(match.group("value")), match.group("unit"))
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _dimensions_cm(text: str) -> list[float] | None:
    pattern = re.compile(
        rf"(?P<a>\d+(?:\.\d+)?)\s*[x*]\s*(?P<b>\d+(?:\.\d+)?)"
        rf"(?:\s*[x*]\s*(?P<c>\d+(?:\.\d+)?))?\s*(?P<unit>{_UNIT})",
        re.I,
    )
    match = pattern.search(text)
    if not match:
        return None
    values = [float(match.group("a")), float(match.group("b"))]
    if match.group("c") is not None:
        values.append(float(match.group("c")))
    return [_to_cm(value, match.group("unit")) for value in values]


def _first_number(text: str, patterns: list[str], *, integer: bool = False) -> float | int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = float(match.group(1).replace(",", ""))
            return int(value) if integer else value
    return None


def _materials(text: str) -> list[str]:
    value = _norm(text)
    return [
        canonical
        for canonical, aliases in _MATERIAL_ALIASES.items()
        if any(alias in value for alias in aliases)
    ]


def _components(text: str, category_id: str) -> list[str]:
    value = _norm(text)
    terms = {
        "patio_furniture_sets": {
            "sofa": ("sofa", "沙发"),
            "chair": ("chair", "chairs", "椅"),
            "table": ("table", "茶几", "桌"),
            "ottoman": ("ottoman", "脚凳"),
            "loveseat": ("loveseat", "双人椅"),
            "cushion": ("cushion", "坐垫", "靠垫"),
        },
        "outdoor_storage": {
            "lid": ("lid", "上盖", "箱盖"),
            "door": ("door", "柜门"),
            "floor": ("floor", "地板"),
            "lock": ("lock", "锁"),
        },
        "patio_heater": {
            "burner": ("burner", "燃烧器"),
            "reflector": ("reflector", "反射罩"),
            "tank_compartment": ("tank compartment", "气瓶仓"),
        },
        "patio_umbrellas_shade": {
            "canopy": ("canopy", "伞布", "伞面"),
            "pole": ("pole", "伞杆"),
            "rib": ("rib", "伞骨"),
            "base": ("base included", "with base", "含底座", "带底座"),
        },
    }
    return [name for name, aliases in terms.get(category_id, {}).items() if any(alias in value for alias in aliases)]


def _features(text: str) -> list[str]:
    value = _norm(text)
    aliases = {
        "weather_resistant": ("weather resistant", "weather-resistant", "耐候"),
        "waterproof": ("waterproof", "防水"),
        "uv_resistant": ("uv resistant", "uv-resistant", "防紫外线", "抗uv"),
        "lockable": ("lockable", "可上锁"),
        "tilt": ("tilt", "倾斜"),
        "crank": ("crank", "摇把", "手摇"),
        "vented": ("air vent", "vented", "通风顶"),
        "ignition": ("ignition", "点火"),
        "tip_over_protection": ("tip-over", "tip over", "倾倒保护"),
    }
    return [name for name, terms in aliases.items() if any(term in value for term in terms)]


def _fuel_type(text: str) -> str | None:
    value = _norm(text)
    if _contains(value, ("natural gas", "天然气")):
        return "natural_gas"
    if _contains(value, ("propane", "lpg", "liquid propane", "丙烷", "液化气")):
        return "propane"
    if _contains(value, ("electric", "infrared", "电热", "红外")):
        return "electric"
    return None


def _numeric(text: str, category_id: str, subtype: str) -> dict[str, float | int | list[float]]:
    value = _norm(text)
    result: dict[str, float | int | list[float]] = {}
    dims = _dimensions_cm(value)
    if dims:
        result["dimensions_cm"] = dims
    if category_id == "outdoor_storage":
        gallons = _first_number(value, [r"(\d+(?:\.\d+)?)\s*(?:us\s*)?gallons?\b", r"(\d+(?:\.\d+)?)\s*加仑"])
        cubic_feet = _first_number(value, [r"(\d+(?:\.\d+)?)\s*(?:cu\.?\s*ft|cubic\s+feet|ft³)", r"(\d+(?:\.\d+)?)\s*立方英尺"])
        liters = _first_number(value, [r"(\d+(?:\.\d+)?)\s*(?:liters?|litres?|l)\b", r"(\d+(?:\.\d+)?)\s*升"])
        if gallons is not None:
            result["capacity_l"] = round(float(gallons) * 3.785411784, 2)
        elif cubic_feet is not None:
            result["capacity_l"] = round(float(cubic_feet) * 28.316846592, 2)
        elif liters is not None:
            result["capacity_l"] = round(float(liters), 2)
    elif category_id == "patio_heater":
        btu = _first_number(value, [r"([\d,]+(?:\.\d+)?)\s*btu\b"])
        watts = _first_number(value, [r"(\d+(?:\.\d+)?)\s*(?:watts?|w)\b", r"(\d+(?:\.\d+)?)\s*瓦"])
        area = _first_number(value, [r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*ft|square\s+feet|ft²)"])
        if btu is not None:
            result["heat_output_btu"] = float(btu)
        if watts is not None:
            result["power_w"] = float(watts)
        if area is not None:
            result["heating_area_sqft"] = float(area)
    elif category_id == "patio_furniture_sets":
        pieces = _first_number(value, [
            r"(\d+)\s*[- ]?pieces?\b", r"set\s+of\s+(\d+)\b", r"(\d+)\s*件套",
        ], integer=True)
        seats = _first_number(value, [
            r"(?:seats?|seating\s+for)\s*(\d+)", r"(\d+)\s*[- ]?(?:person|seater)\b", r"(\d+)\s*人位",
        ], integer=True)
        if pieces is not None:
            result["piece_count"] = pieces
        if seats is not None:
            result["seating_count"] = seats
    else:
        diameter = _measurement(value, [
            rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})\s*(?:wide\s+)?(?:(?:patio|market|beach|cantilever|offset)\s+){{0,2}}umbrella\b",
            rf"(?:canopy\s+)?diameter\D{{0,12}}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})",
            rf"伞面(?:直径|宽度)?\D{{0,8}}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})",
            rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})\D{{0,10}}(?:遮阳伞|沙滩伞|香蕉伞|罗马伞)",
        ])
        pole = _measurement(value, [
            rf"(?:pole\s+diameter|diameter\s+pole)\D{{0,8}}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})",
            rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})\s*(?:diameter\s+)?pole\b",
            rf"伞杆直径\D{{0,8}}(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT})",
        ])
        ribs = _first_number(value, [r"(\d+)\s*(?:ribs?|伞骨|骨架)", r"(\d+)\s*骨"], integer=True)
        gsm = _first_number(value, [r"(\d+(?:\.\d+)?)\s*gsm\b", r"(\d+(?:\.\d+)?)\s*克(?:重)?布"])
        if diameter is not None and subtype not in {"shade_sail", "gazebo_canopy"}:
            result["canopy_diameter_cm"] = diameter
        if pole is not None:
            result["pole_diameter_cm"] = pole
        if ribs is not None:
            result["rib_count"] = ribs
        if gsm is not None:
            result["fabric_gsm"] = float(gsm)
    weight_kg = _first_number(value, [
        r"(?:item\s+weight|net\s+weight|weight|净重|重量)\D{0,10}(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)",
    ])
    if weight_kg is not None:
        result["weight_kg"] = float(weight_kg)
    return result


def _missing_critical(profile: TargetCategoryProfile) -> list[str]:
    missing: list[str] = []
    if profile.subtype in _GENERIC_SUBTYPES:
        missing.append("subtype")
    if profile.category_id == "outdoor_storage":
        if "capacity_l" not in profile.numeric and "dimensions_cm" not in profile.numeric:
            missing.append("capacity_or_dimensions")
    elif profile.category_id == "patio_heater":
        if not profile.attributes.get("fuel_type"):
            missing.append("fuel_type")
        if "heat_output_btu" not in profile.numeric and "power_w" not in profile.numeric:
            missing.append("heat_output")
    elif profile.category_id == "patio_furniture_sets":
        if "piece_count" not in profile.numeric:
            missing.append("piece_count")
        if not profile.components:
            missing.append("components")
    elif profile.subtype in {"market_umbrella", "cantilever_umbrella", "beach_umbrella", "clamp_umbrella"}:
        if "canopy_diameter_cm" not in profile.numeric:
            missing.append("canopy_diameter_cm")
    elif profile.subtype == "shade_sail" and "dimensions_cm" not in profile.numeric:
        missing.append("dimensions_cm")
    return missing


def profile_from_text(text: str) -> TargetCategoryProfile | None:
    value = _norm(text)
    category_id = classify_target_category(value)
    if category_id is None:
        return None
    relation = _relation(value, category_id)
    subtype = _subtype(value, category_id, relation)
    numeric = _numeric(value, category_id, subtype)
    attributes: dict[str, Any] = {}
    if category_id == "patio_heater":
        attributes["fuel_type"] = _fuel_type(value)
    shape = next((name for name, terms in {
        "round": ("round", "圆形"), "square": ("square", "方形"),
        "rectangular": ("rectangular", "rectangle", "长方形"),
        "triangular": ("triangular", "triangle", "三角形"),
    }.items() if any(term in value for term in terms)), None)
    if shape:
        attributes["shape"] = shape
    profile = TargetCategoryProfile(
        category_id=category_id,
        category_name=CATEGORY_NAMES[category_id],
        subtype=subtype,
        relation=relation,
        numeric=numeric,
        attributes=attributes,
        materials=_materials(value),
        components=_components(value, category_id),
        features=_features(value),
        search_terms_cn=list(_SUBTYPE_TERMS_CN.get(subtype, [_SUPPLY_NAMES[category_id]])),
        evidence_excerpt=str(text or "")[:600],
    )
    profile.missing_critical = _missing_critical(profile)
    return profile


def _field_value(raw: dict[str, Any], name: str) -> Any:
    evidence = raw.get("field_evidence")
    if not isinstance(evidence, dict):
        return None
    item = evidence.get(name)
    if not isinstance(item, dict) or item.get("status") not in {"extracted", "verified"}:
        return None
    return item.get("value")


def _flatten_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [item for child in value for item in _flatten_values(child)]
    if isinstance(value, dict):
        return [f"{key} {item}" for key, child in value.items() for item in _flatten_values(child)]
    return []


def product_evidence_text(product: Any) -> str:
    raw = product.raw_data if isinstance(getattr(product, "raw_data", None), dict) else {}
    values: list[Any] = [
        getattr(product, "title", None), getattr(product, "category", None),
        getattr(product, "subcategory", None), raw.get("bullet_points"), raw.get("description"),
        raw.get("attributes"), _field_value(raw, "material"), _field_value(raw, "package_quantity"),
        _field_value(raw, "product_dimensions"), _field_value(raw, "package_dimensions"),
    ]
    return " ".join(item for value in values for item in _flatten_values(value))


def supplier_evidence_text(supplier: Any) -> str:
    raw = supplier.raw_data if isinstance(getattr(supplier, "raw_data", None), dict) else {}
    detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else {}
    values: list[Any] = [
        getattr(supplier, "title_cn", None), getattr(supplier, "supplier_name", None),
        getattr(supplier, "material", None), getattr(supplier, "color", None),
        getattr(supplier, "product_dimensions_cm", None), raw.get("full_text"),
        detail.get("raw_text"), detail.get("specification"), detail.get("package_details"),
        detail.get("sku_options"),
    ]
    return " ".join(item for value in values for item in _flatten_values(value))


def profile_from_product(product: Any) -> TargetCategoryProfile | None:
    profile = profile_from_text(product_evidence_text(product))
    if profile is None:
        return None
    dims = [
        getattr(product, "length_cm", None), getattr(product, "width_cm", None),
        getattr(product, "height_cm", None),
    ]
    if all(value is not None and float(value) > 0 for value in dims):
        profile.numeric.setdefault("dimensions_cm", [round(float(value), 2) for value in dims])
    weight = getattr(product, "weight_kg", None)
    if weight is not None and float(weight) > 0:
        profile.numeric.setdefault("weight_kg", round(float(weight), 3))
    profile.missing_critical = _missing_critical(profile)
    return profile


def profile_from_supplier(supplier: Any) -> TargetCategoryProfile | None:
    return profile_from_text(supplier_evidence_text(supplier))


def _close(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) / max(abs(left), 1.0) <= tolerance


def _dimensions_close(left: list[float], right: list[float], tolerance: float = 0.15) -> bool:
    if len(left) != len(right):
        return False
    return all(_close(a, b, tolerance) for a, b in zip(sorted(left), sorted(right), strict=True))


def compare_target_profiles(
    target: TargetCategoryProfile,
    candidate: TargetCategoryProfile | None,
) -> TargetCategoryMatch:
    matched: list[str] = []
    missing: list[str] = [f"target.{name}" for name in target.missing_critical]
    conflicts: list[str] = []
    earned = 0.0
    possible = 0.0

    def exact(name: str, left: Any, right: Any, weight: float, *, hard: bool = True) -> None:
        nonlocal earned, possible
        possible += weight
        if right in (None, "", [], {}):
            missing.append(f"candidate.{name}")
        elif left == right:
            matched.append(name)
            earned += weight
        elif hard:
            conflicts.append(name)
        else:
            missing.append(f"candidate.{name}_mismatch")

    if candidate is None:
        return TargetCategoryMatch(
            score=0.0,
            decision="manual_review",
            missing=list(dict.fromkeys([*missing, "candidate.category_profile"])),
        )

    exact("category", target.category_id, candidate.category_id, 3.0)
    exact("relation", target.relation, candidate.relation, 3.0)
    if target.subtype not in _GENERIC_SUBTYPES:
        exact("subtype", target.subtype, candidate.subtype, 2.5)

    target_fuel = target.attributes.get("fuel_type")
    if target_fuel:
        exact("fuel_type", target_fuel, candidate.attributes.get("fuel_type"), 3.0)
    target_shape = target.attributes.get("shape")
    if target_shape:
        exact("shape", target_shape, candidate.attributes.get("shape"), 0.8, hard=False)

    tolerances = {
        "capacity_l": 0.12,
        "heat_output_btu": 0.10,
        "power_w": 0.10,
        "heating_area_sqft": 0.20,
        "canopy_diameter_cm": 0.10,
        "pole_diameter_cm": 0.10,
        "fabric_gsm": 0.15,
        "weight_kg": 0.15,
    }
    exact_integer = {"piece_count", "seating_count", "rib_count"}
    for name, left in target.numeric.items():
        if name == "dimensions_cm":
            possible += 2.0
            right = candidate.numeric.get(name)
            if not isinstance(right, list):
                missing.append(f"candidate.{name}")
            elif _dimensions_close(list(left), right):  # type: ignore[arg-type]
                matched.append(name)
                earned += 2.0
            else:
                conflicts.append(name)
            continue
        right = candidate.numeric.get(name)
        weight = 2.5 if name in {"piece_count", "heat_output_btu", "canopy_diameter_cm"} else 1.2
        possible += weight
        if right is None:
            missing.append(f"candidate.{name}")
            continue
        if name in exact_integer:
            same = int(left) == int(right)  # type: ignore[arg-type]
        else:
            same = _close(float(left), float(right), tolerances.get(name, 0.15))  # type: ignore[arg-type]
        if same:
            matched.append(name)
            earned += weight
        else:
            conflicts.append(name)

    if target.materials:
        possible += 1.0
        if not candidate.materials:
            missing.append("candidate.materials")
        elif set(target.materials) & set(candidate.materials):
            matched.append("materials")
            earned += 1.0
        else:
            conflicts.append("materials")

    critical_missing = {
        "candidate.category_profile", "candidate.subtype", "candidate.fuel_type",
        "candidate.capacity_l", "candidate.dimensions_cm", "candidate.heat_output_btu",
        "candidate.power_w", "candidate.piece_count", "candidate.canopy_diameter_cm",
        "target.subtype", "target.capacity_or_dimensions", "target.fuel_type",
        "target.heat_output", "target.piece_count", "target.components",
        "target.canopy_diameter_cm", "target.dimensions_cm",
    }
    score = round(earned / possible if possible else 0.0, 4)
    if conflicts:
        decision = "reject"
    elif critical_missing & set(missing):
        decision = "manual_review"
    else:
        decision = "keep" if score >= 0.80 else "manual_review"
    return TargetCategoryMatch(
        score=score,
        decision=decision,
        matched=list(dict.fromkeys(matched)),
        missing=list(dict.fromkeys(missing)),
        conflicts=list(dict.fromkeys(conflicts)),
    )


def target_query_matches_product(query: str, product_or_title: Any) -> bool:
    """Return whether an Amazon result preserves target-category intent."""
    target = profile_from_text(query)
    if target is None:
        return True
    candidate = (
        profile_from_product(product_or_title)
        if not isinstance(product_or_title, str)
        else profile_from_text(product_or_title)
    )
    if candidate is None or candidate.category_id != target.category_id:
        return False
    if target.relation == "full_product" and candidate.relation != "full_product":
        return False
    if target.subtype not in _GENERIC_SUBTYPES and candidate.subtype != target.subtype:
        return False
    return True


def understanding_from_target_profile(
    product: Any,
    profile: TargetCategoryProfile,
) -> AmazonProductUnderstanding:
    relation = "full_product" if profile.relation == "full_product" else "replacement"
    package_quantity = profile.numeric.get("piece_count")
    if package_quantity is not None:
        package_quantity = int(package_quantity)  # type: ignore[arg-type]
    dimensions: list[str] = []
    if profile.numeric.get("dimensions_cm"):
        dimensions.append(
            "x".join(str(value) for value in profile.numeric["dimensions_cm"]) + "厘米"  # type: ignore[index]
        )
    numeric_labels = {
        "capacity_l": ("容量", "升"),
        "heat_output_btu": ("热功率", "BTU"),
        "power_w": ("功率", "瓦"),
        "canopy_diameter_cm": ("伞面直径", "厘米"),
        "pole_diameter_cm": ("伞杆直径", "厘米"),
        "rib_count": ("伞骨", "根"),
        "fabric_gsm": ("面料克重", "GSM"),
        "seating_count": ("座位", "座"),
    }
    for key, (label, unit) in numeric_labels.items():
        if key in profile.numeric:
            dimensions.append(f"{label}{profile.numeric[key]}{unit}")
    terms = list(dict.fromkeys([
        *profile.search_terms_cn,
        _SUPPLY_NAMES[profile.category_id],
    ]))
    materials_cn = [
        _MATERIAL_SEARCH_CN.get(value, value) for value in profile.materials
    ]
    components_cn = [
        _COMPONENT_SEARCH_CN.get(value, value) for value in profile.components
    ]
    supplier_terms = list(dict.fromkeys([
        *terms,
        *(f"{term}生产厂家" for term in terms[:1]),
        *(f"{term}源头工厂" for term in terms[:1]),
    ]))
    return AmazonProductUnderstanding(
        asin=str(getattr(product, "asin", "") or ""),
        original_title_en=str(getattr(product, "title", "") or ""),
        translated_title_cn=terms[0] if terms else None,
        generic_product_name=terms[0] if terms else _SUPPLY_NAMES[profile.category_id],
        supply_chain_name_cn=_SUPPLY_NAMES[profile.category_id],
        category=profile.category_id,
        subcategory=profile.subtype,
        function=list(_FUNCTIONS[profile.category_id]),
        material=materials_cn,
        components=components_cn,
        package_quantity=package_quantity,
        dimensions_visible=dimensions,
        target_user=["户外庭院用户"],
        use_case=list(_FUNCTIONS[profile.category_id]),
        replaceable_part_or_full_product=relation,
        distinguishing_features=list(profile.features),
        likely_supplier_keywords_cn=supplier_terms,
        excluded_brand_tokens=[str(getattr(product, "brand", "") or "")] if getattr(product, "brand", None) else [],
        uncertainty=[f"missing:{name}" for name in profile.missing_critical],
        model_provider="deterministic",
        model_name="target-category-contract-v1",
        prompt_version="target-category-contract-v1",
    )

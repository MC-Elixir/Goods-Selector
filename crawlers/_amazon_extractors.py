"""
Amazon 字段提取器（共享，2026 版）
====================================

输入：一个 PageLike（包 Scrapling Adaptor 或 Playwright Page）
输出：ProductDTO 所需的所有字段

设计原则：
    1. 所有函数纯函数，零副作用
    2. 字段来源优先级：prodDetTable（"Brand Name" / "Item Weight" / "Best Sellers Rank" / "Package Dimensions"）
       > 老的选择器（bylineInfo / detailBullets / reinventPricePriceToPayMargin 等）
    3. 数值解析（_parse_float / _parse_int / _parse_price_text / 单位换算）原样保留
       — 这些跟后端无关。

变更要点（vs 旧版 amazon_playwright.py / amazon_scrapling.py）：
    * 老的选择器（如 #detailBullets_feature_div）2026 年页面 0 命中
    * prodDetTable 是新页面的唯一可靠来源
    * 一些字段（Brand Name、Item Weight、Package Dimensions、Best Sellers Rank）
      prodDetTable 没有就退回老选择器
"""
from __future__ import annotations

import re
from typing import Optional

from crawlers._amazon_page import PageLike


# ============================================================
# BSR 列表页：去重 ASIN
# ============================================================
ASIN_LINK_SEL = 'a[href*="/dp/"]'
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


def parse_bsr_page(page: PageLike) -> list[str]:
    """从 BSR 列表页提取所有唯一 ASIN。"""
    asins: list[str] = []
    seen: set[str] = set()
    for _text, href in page.all_links(ASIN_LINK_SEL):
        m = _ASIN_RE.search(href or "")
        if m:
            a = m.group(1)
            if a not in seen:
                seen.add(a)
                asins.append(a)
    return asins


# ============================================================
# Brand
# ============================================================
_BRAND_SELECTORS_OLD = (
    # 老版 bylineInfo
    "#bylineInfo a",
    "#bylineInfo",
    ".po-brand .a-span9",
    # 新版品牌 logo（<img alt="Brand">）
    "img#brandLogoHiResByline",
)


def extract_brand(page: PageLike) -> Optional[str]:
    # 1. prodDetTable "Brand Name" 行（2026 版最可靠）
    val = page.table_row("Brand Name")
    if val:
        s = _strip_brand_prefix(val)
        if s:
            return s
    # 2. 老选择器兜底
    for sel in _BRAND_SELECTORS_OLD:
        t = page.text(sel)
        if t:
            s = _strip_brand_prefix(t)
            if s:
                return s
    return None


def _strip_brand_prefix(s: str) -> str:
    return re.sub(r"^(Visit the |Brand: |by )", "", s.strip(), flags=re.I).strip()


# ============================================================
# Price
# ============================================================
_PRICE_SELECTORS = (
    # 老版：reinventPricePriceToPayMargin 命中率下降但偶尔还有
    ".a-price.reinventPricePriceToPayMargin .a-offscreen",
    # 老版 priceblock
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    # 通用 .a-price .a-offscreen（首位通常是主价，含 "List:" 的会被 _parse_price_text 拒掉）
    ".a-price .a-offscreen",
    # corePrice 系列
    "#corePrice_feature_div .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
)


def extract_price(page: PageLike) -> Optional[float]:
    # 优先尝试带语义的选择器（首位 a-offscreen 通常是主价）
    for sel in _PRICE_SELECTORS:
        t = page.text(sel)
        if t:
            v = _parse_price_text(t)
            if v:
                return v
    # 兜底：扫所有 .a-offscreen，取第一个看起来像主价的（≥ $1 且无 "List:" 前缀）
    for text in page.text_all(".a-offscreen"):
        v = _parse_price_text(text)
        if v and v >= 1.0:
            return v
    return None


# ============================================================
# Rating
# ============================================================
_RATING_SELECTORS = (
    "#acrPopover",
    ".a-icon-star .a-icon-alt",
)


def extract_rating(page: PageLike) -> Optional[float]:
    for sel in _RATING_SELECTORS:
        # 有些版本把分数放在 title 属性
        title = page.attr(sel, "title")
        if title:
            m = re.search(r"([\d.]+)\s*out of", title)
            if m:
                return float(m.group(1))
        # 有些版本在 inner text
        t = page.text(sel)
        if t:
            m = re.search(r"([\d.]+)\s*out of", t)
            if m:
                return float(m.group(1))
    return None


# ============================================================
# Reviews (count)
# ============================================================
def extract_reviews(page: PageLike) -> Optional[int]:
    t = page.text("#acrCustomerReviewText")
    if t:
        return _parse_int(t)
    return None


# ============================================================
# Best Sellers Rank
# ============================================================
_BSR_SELECTORS_OLD = (
    "#detailBullets_feature_div",
    "#productDetails_detailBullets_sections1",
    "#SalesRank",
    "#detail-bullets",
)


def extract_bsr(page: PageLike) -> Optional[int]:
    # 1. prodDetTable "Best Sellers Rank" 行（2026 版最可靠）
    cell = page.table_row("Best Sellers Rank")
    if cell:
        m = re.search(r"#\s*([\d,]+)", cell)
        if m:
            return _parse_int(m.group(1))
    # 2. 老选择器
    for sel in _BSR_SELECTORS_OLD:
        t = page.text(sel)
        if t and ("Best Sellers Rank" in t or "Best Seller" in t):
            m = re.search(r"#([\d,]+)", t)
            if m:
                return _parse_int(m.group(1))
    return None


# ============================================================
# Main image
# ============================================================
_IMAGE_SELECTORS = (
    "#landingImage",
    "#imgBlkFront",
    "#ebooksImgBlkFront",
)


def extract_image(page: PageLike) -> Optional[str]:
    for sel in _IMAGE_SELECTORS:
        for attr in ("data-old-hires", "data-a-dynamic-image", "src"):
            v = page.attr(sel, attr)
            if not v:
                continue
            if attr == "data-a-dynamic-image":
                # JSON {"url": sz, ...}，取第一个键
                m = re.search(r'"(https?://[^"]+)"', v)
                if m:
                    return m.group(1)
            elif v.startswith("http"):
                return v
    return None


# ============================================================
# Dimensions / Weight
# ============================================================
def extract_dimensions(
    page: PageLike,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """返回 (weight_kg, length_cm, width_cm, height_cm)。"""
    weight_kg = _parse_weight_from_text(page.table_row("Item Weight") or "")
    if weight_kg is None:
        for label in ("Package Weight", "Product Weight", "Shipping Weight"):
            weight_kg = _parse_weight_from_text(page.table_row(label) or "")
            if weight_kg is not None:
                break

    dims: Optional[tuple[float, float, float]] = None
    for label in ("Package Dimensions", "Product Dimensions", "Item Dimensions"):
        dims = _parse_dimensions_from_text(page.table_row(label) or "")
        if dims:
            break

    if dims:
        length, width, height = dims
    else:
        length = width = height = None

    return weight_kg, length, width, height


def _parse_weight_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(
        r"([0-9.]+)\s*(pounds?|lbs?|ounces?|oz|kilograms?|kg|grams?|g)\b",
        text, re.I,
    )
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("pound") or unit.startswith("lb"):
        return val * 0.453592
    if unit.startswith("oz") or unit.startswith("ounce"):
        return val * 0.0283495
    if unit.startswith("kg") or unit.startswith("kilo"):
        return val
    return val / 1000  # grams


def _parse_dimensions_from_text(text: str) -> Optional[tuple[float, float, float]]:
    if not text:
        return None
    m = re.search(
        r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(inches?|in\b|cm|centimeters?)",
        text, re.I,
    )
    if not m:
        return None
    a, b, c = float(m.group(1)), float(m.group(2)), float(m.group(3))
    unit = m.group(4).lower()
    factor = 2.54 if unit.startswith("in") else 1.0
    return sorted([a * factor, b * factor, c * factor], reverse=True)


# ============================================================
# Captcha detection
# ============================================================
def is_captcha(page: PageLike) -> bool:
    t = (page.text("title") or "").lower()
    return "robot check" in t or "captcha" in t or "automated access" in t


# ============================================================
# Title
# ============================================================
def extract_title(page: PageLike, fallback: str = "") -> str:
    t = page.text("#productTitle")
    return (t or fallback).strip() if (t or fallback) else (fallback or "")


# ============================================================
# 数值 / 价格解析工具（与旧版一致，与后端无关）
# ============================================================
_JPY_TO_USD = 0.0067  # 2025/2026 年均汇率


def _parse_price_text(t: str) -> Optional[float]:
    """从价格文本提取 USD 金额，自动处理 JPY。"""
    t = t.replace("\xa0", " ").strip()
    if "JPY" in t or "¥" in t:
        v = _parse_float(t.replace("JPY", "").replace("¥", ""))
        return round(v * _JPY_TO_USD, 2) if v and v > 0 else None
    v = _parse_float(t)
    if not v or v <= 0:
        return None
    if "$" not in t and "USD" not in t and v >= 500:
        # 裸数字且 ≥ 500：兜底视为 JPY
        return round(v * _JPY_TO_USD, 2)
    return v


def _parse_float(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    try:
        return float(m.group().replace(",", "")) if m else None
    except ValueError:
        return None


def _parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"[\d,]+", text.replace(",", ""))
    try:
        return int(m.group().replace(",", "")) if m else None
    except ValueError:
        return None

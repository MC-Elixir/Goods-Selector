"""
Amazon Best Seller Playwright 爬虫
====================================
无需 API Key，用 Playwright 浏览器直接爬取 Amazon BSR 页面。

依赖：
    pip install playwright
    playwright install chromium

限速：产品详情页间隔 2–5 秒随机延时，避免触发反爬。
验证码检测：遇到 Robot Check 自动停止并返回已收集数据。

用法：
    scraper = AmazonPlaywrightScraper()
    products = scraper.scrape_best_sellers("Home & Kitchen", limit=50)
"""
from __future__ import annotations

import math
import random
import re
import time
from typing import Optional

from loguru import logger

from crawlers.amazon_bsr import ProductDTO

# ============================================================
# 类目 → BSR URL slug 映射（US 站）
# ============================================================
_CATEGORY_SLUGS: dict[str, str] = {
    "Home & Kitchen":           "home-garden",
    "Kitchen & Dining":         "kitchen",
    "Electronics":              "electronics",
    "Toys & Games":             "toys-and-games",
    "Beauty & Personal Care":   "beauty",
    "Clothing":                 "clothing-shoes-jewelry",
    "Shoes":                    "clothing-shoes-jewelry",
    "Sports & Outdoors":        "sporting-goods",
    "Books":                    "books",
    "Garden & Outdoor":         "lawn-garden",
    "Office Products":          "office-products",
    "Pet Supplies":             "pet-supplies",
    "Baby":                     "baby-products",
    "Health & Household":       "hpc",
    "Tools & Home Improvement": "hi",
    "Automotive":               "automotive",
    "Musical Instruments":      "musical-instruments",
    "Industrial & Scientific":  "industrial",
    "Arts, Crafts & Sewing":    "arts-crafts",
    "Cell Phones & Accessories":"mobile",
    "Video Games":              "videogames",
    "Grocery & Gourmet Food":   "grocery",
}

_MARKETPLACE_DOMAINS: dict[str, str] = {
    "US": "https://www.amazon.com",
    "UK": "https://www.amazon.co.uk",
    "DE": "https://www.amazon.de",
    "JP": "https://www.amazon.co.jp",
}

_BSR_PER_PAGE = 50


# ============================================================
# 主爬虫类
# ============================================================
class AmazonPlaywrightScraper:
    """Playwright-based Amazon Best Sellers 爬虫。"""

    def __init__(
        self,
        headless: bool = True,
        rate_min: float = 2.0,
        rate_max: float = 5.0,
    ):
        self.headless = headless
        self.rate_min = rate_min
        self.rate_max = rate_max

    # --------------------------------------------------------
    def scrape_best_sellers(
        self,
        category: str,
        limit: int = 100,
        marketplace: str = "US",
    ) -> list[ProductDTO]:
        """抓取指定类目 BSR 前 limit 名产品。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "请安装 playwright：\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )

        base_url = _MARKETPLACE_DOMAINS.get(marketplace, _MARKETPLACE_DOMAINS["US"])
        slug = _CATEGORY_SLUGS.get(category)
        if not slug:
            logger.warning(
                f"未找到类目 {category!r} 的 URL slug，"
                f"可用类目：{list(_CATEGORY_SLUGS.keys())}"
            )
            slug = category.lower().replace(" & ", "-").replace(" ", "-")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "CloudFront-Viewer-Country": "US",
                },
            )
            # 强制 Amazon 以美元显示价格（无论 IP 地区）
            ctx.add_cookies([
                {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"},
                {"name": "lc-main",    "value": "en_US", "domain": ".amazon.com", "path": "/"},
            ])
            page = ctx.new_page()
            # 隐藏 webdriver 特征
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                asins = self._collect_asins(page, base_url, slug, limit)
                logger.info(f"[playwright] 收集到 {len(asins)} 个 ASIN，开始抓详情...")

                products: list[ProductDTO] = []
                for i, asin in enumerate(asins[:limit], 1):
                    try:
                        dto = self._scrape_product(page, base_url, asin, marketplace, category)
                        products.append(dto)
                        logger.debug(f"[playwright] [{i}/{len(asins)}] {asin} OK")
                    except Exception as e:
                        logger.warning(f"[playwright] {asin} 详情失败，跳过: {e}")

                    if i < len(asins[:limit]):
                        time.sleep(random.uniform(self.rate_min, self.rate_max))

                logger.info(f"[playwright] 完成，共抓取 {len(products)} 个产品")
                return products

            finally:
                browser.close()

    # --------------------------------------------------------
    def _collect_asins(
        self, page, base_url: str, slug: str, limit: int
    ) -> list[str]:
        """从 BSR 分页列表中收集 ASIN，不重复。"""
        asins: list[str] = []
        seen: set[str] = set()
        pages_needed = math.ceil(limit / _BSR_PER_PAGE)

        for pg in range(1, pages_needed + 1):
            if len(asins) >= limit:
                break
            url = f"{base_url}/Best-Sellers/zgbs/{slug}/ref=zg_bs_pg_{pg}?ie=UTF8&pg={pg}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if self._is_captcha(page):
                    logger.warning(f"[playwright] 遇到验证码，已停止（已收集 {len(asins)} 个）")
                    break
                page.wait_for_timeout(1500)
                new = self._parse_bsr_page(page)
                for a in new:
                    if a not in seen:
                        seen.add(a)
                        asins.append(a)
                logger.debug(f"[playwright] BSR 第 {pg} 页，新增 {len(new)} 个 ASIN")
            except Exception as e:
                logger.warning(f"[playwright] BSR 第 {pg} 页失败: {e}")
                break
            time.sleep(random.uniform(1.5, 3.0))

        return asins

    @staticmethod
    def _parse_bsr_page(page) -> list[str]:
        """从当前 BSR 页面提取所有 ASIN。"""
        asins: list[str] = []
        seen: set[str] = set()
        hrefs = page.eval_on_selector_all(
            'a[href*="/dp/"]', "els => els.map(e => e.getAttribute('href'))"
        )
        for href in hrefs:
            if not href:
                continue
            m = re.search(r"/dp/([A-Z0-9]{10})", href)
            if m:
                a = m.group(1)
                if a not in seen:
                    seen.add(a)
                    asins.append(a)
        return asins

    # --------------------------------------------------------
    def _scrape_product(
        self, page, base_url: str, asin: str, marketplace: str, category: str
    ) -> ProductDTO:
        """爬取单个产品详情页，返回 ProductDTO。"""
        url = f"{base_url}/dp/{asin}?language=en_US&currency=USD"
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if self._is_captcha(page):
            raise RuntimeError("验证码页面")
        page.wait_for_timeout(random.randint(800, 1500))

        title    = _sel_text(page, "#productTitle")
        brand    = _extract_brand(page)
        price    = _extract_price(page)
        rating   = _extract_rating(page)
        reviews  = _extract_reviews(page)
        bsr_rank = _extract_bsr(page)
        img_url  = _extract_image(page)
        listing  = url
        weight_kg, length_cm, width_cm, height_cm = _extract_dimensions(page)

        return ProductDTO(
            asin=asin,
            marketplace=marketplace,
            title=title or asin,
            category=category,
            brand=brand,
            price=price,
            bsr_rank=bsr_rank,
            rating=rating,
            review_count=reviews,
            weight_kg=weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            main_image_url=img_url,
            listing_url=listing,
        )

    @staticmethod
    def _is_captcha(page) -> bool:
        t = (page.title() or "").lower()
        return "robot check" in t or "captcha" in t or "automated access" in t


# ============================================================
# 字段提取辅助函数
# ============================================================

def _sel_text(page, selector: str) -> Optional[str]:
    """安全取元素文本，找不到返回 None。"""
    try:
        el = page.query_selector(selector)
        return el.inner_text().strip() if el else None
    except Exception:
        return None


def _extract_brand(page) -> Optional[str]:
    for sel in ("#bylineInfo a", "#bylineInfo", ".po-brand .a-span9"):
        t = _sel_text(page, sel)
        if t:
            return re.sub(r"^(Visit the |Brand: |by )", "", t.strip(), flags=re.I).strip()
    return None


_JPY_TO_USD = 0.0067  # ≈ 2025/2026 年均汇率，仅作兜底用


def _parse_price_text(t: str) -> Optional[float]:
    """从价格文本中提取 USD 金额，自动处理 JPY。"""
    t = t.replace("\xa0", " ").strip()
    # 明确的日元标记
    if "JPY" in t or "¥" in t:
        v = _parse_float(t.replace("JPY", "").replace("¥", ""))
        return round(v * _JPY_TO_USD, 2) if v and v > 0 else None
    v = _parse_float(t)
    if not v or v <= 0:
        return None
    # 没有 $ 符号且金额 ≥ 500，很可能是日元裸数字（如 "6980"）
    if "$" not in t and "USD" not in t and v >= 500:
        return round(v * _JPY_TO_USD, 2)
    return v


def _extract_price(page) -> Optional[float]:
    candidates = [
        ".a-price.reinventPricePriceToPayMargin .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
        "#corePrice_feature_div .a-offscreen",
    ]
    for sel in candidates:
        t = _sel_text(page, sel)
        if t:
            v = _parse_price_text(t)
            if v:
                return v

    # 兜底：所有 a-offscreen，跳过明显非价格文本
    all_offscreen = page.query_selector_all(".a-offscreen")
    for el in (all_offscreen or []):
        try:
            t = el.inner_text().strip()
            if not t:
                continue
            v = _parse_price_text(t)
            if v:
                return v
        except Exception:
            pass
    return None


def _extract_rating(page) -> Optional[float]:
    for sel in ("#acrPopover", ".a-icon-star .a-icon-alt"):
        el = page.query_selector(sel)
        if not el:
            continue
        title = el.get_attribute("title") or el.inner_text()
        m = re.search(r"([\d.]+)\s*out of", title or "")
        if m:
            return float(m.group(1))
    return None


def _extract_reviews(page) -> Optional[int]:
    t = _sel_text(page, "#acrCustomerReviewText")
    if t:
        return _parse_int(t)
    return None


def _extract_bsr(page) -> Optional[int]:
    """从产品详情页提取 Best Sellers Rank（主类目排名）。"""
    # 尝试多处位置
    selectors = [
        "#detailBullets_feature_div",
        "#productDetails_detailBullets_sections1",
        "#SalesRank",
        "#detail-bullets",
    ]
    for sel in selectors:
        el = page.query_selector(sel)
        if not el:
            continue
        text = el.inner_text()
        if "Best Sellers Rank" in text or "Best Seller" in text:
            # 提取第一个 #数字
            m = re.search(r"#([\d,]+)", text)
            if m:
                return _parse_int(m.group(1))
    return None


def _extract_image(page) -> Optional[str]:
    for sel in ("#landingImage", "#imgBlkFront", "#ebooksImgBlkFront"):
        el = page.query_selector(sel)
        if not el:
            continue
        for attr in ("data-old-hires", "data-a-dynamic-image", "src"):
            v = el.get_attribute(attr)
            if not v:
                continue
            if attr == "data-a-dynamic-image":
                # 是 JSON {"url": sz, ...}，取第一个键
                m = re.search(r'"(https?://[^"]+)"', v)
                if m:
                    return m.group(1)
            elif v.startswith("http"):
                return v
    return None


def _extract_dimensions(
    page,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """返回 (weight_kg, length_cm, width_cm, height_cm)。"""
    weight = length = width = height = None

    # 合并所有可能包含规格的文本区域
    text = ""
    for sel in (
        "#productDetails_techSpec_section_1",
        "#productDetails_detailBullets_sections1",
        "#detail-bullets",
        "#detailBullets_feature_div",
        ".a-expander-content",
    ):
        el = page.query_selector(sel)
        if el:
            text += "\n" + el.inner_text()

    if not text:
        return weight, length, width, height

    # 重量
    m = re.search(
        r"(?:Item|Package|Product)\s+Weight[:\s]+([0-9.]+)\s*(pounds?|lbs?|ounces?|oz|kilograms?|kg|grams?|g)\b",
        text, re.I,
    )
    if m:
        val, unit = float(m.group(1)), m.group(2).lower()
        if unit.startswith("pound") or unit.startswith("lb"):
            weight = val * 0.453592
        elif unit.startswith("oz") or unit.startswith("ounce"):
            weight = val * 0.0283495
        elif unit.startswith("kg") or unit.startswith("kilo"):
            weight = val
        else:  # grams
            weight = val / 1000

    # 尺寸（优先 Package，其次 Product）
    for pattern in (
        r"(?:Package|Product|Item)\s+Dimensions[:\s]+([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(inches?|in|cm|centimeters?)",
        r"([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*(inches?|in\b|cm|centimeters?)",
    ):
        m = re.search(pattern, text, re.I)
        if m:
            a, b, c = float(m.group(1)), float(m.group(2)), float(m.group(3))
            unit = m.group(4).lower()
            factor = 2.54 if unit.startswith("in") else 1.0
            dims = sorted([a * factor, b * factor, c * factor], reverse=True)
            length, width, height = dims[0], dims[1], dims[2]
            break

    return weight, length, width, height


# ============================================================
# 数值解析工具
# ============================================================

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

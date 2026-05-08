"""
1688 Playwright 货源匹配器
===========================
无需 API Key，Playwright 直接爬 1688 搜索结果页。

支持两种搜索方式（自动按优先级尝试）：
  1. 图搜（以图搜货）  → 需已登录的持久化浏览器 Profile
                         Profile 路径：data/browser_profiles/1688/
  2. 关键词搜索        → 无需登录，公开页面直接抓

返回标准 SupplierDTO 列表，可直接接入 predict_profit()。

用法：
    matcher = Alibaba1688PlaywrightMatcher()
    # 方式 1：图搜（有登录 Profile 时优先）
    suppliers = matcher.search_by_image(image_url="https://...", keywords=["折叠桌"])
    # 方式 2：纯关键词
    suppliers = matcher.search_by_keyword(["折叠桌", "户外折叠桌"])
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from loguru import logger

from matchers.alibaba_pailitao import SupplierDTO

# ============================================================
# 常量
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_DIR = _PROJECT_ROOT / "data" / "browser_profiles" / "1688"
_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_SEARCH_BASE = "https://s.1688.com/selloffer/offer_search.htm"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# 1688 搜索结果容器选择器（按优先级依次尝试）
_CARD_SELECTORS = [
    "div[data-offer-id]",
    "div.sm-offer-item",
    "div.offer-item",
    "div[class*='offerItem']",
    "div[class*='offer_item']",
    "div[class*='list-item']",
]

# 标题/链接选择器
_TITLE_SELS = [
    "a.sm-offer-title",
    "a.offer-title",
    "a[class*='title']",
    "div[class*='title'] a",
    "h3 a",
    "a[href*='detail.1688.com/offer/']",
]

# 价格选择器
_PRICE_SELS = [
    "span.sm-offer-priceNum",
    "span[class*='priceNum']",
    "span.price-num",
    "em.price",
    "span.price",
    "span[class*='price']",
    "strong.price",
]

# 图片选择器
_IMAGE_SELS = [
    "img.sm-offer-image",
    "img[class*='offer-image']",
    "img[class*='offerImage']",
    "div[class*='pic'] img",
    "img[src*='alicdn']",
    "img[data-src*='alicdn']",
    "img",
]

# 月成交量选择器
_SALES_SELS = [
    "span[class*='monthSold']",
    "span[class*='month-sold']",
    "span[class*='trade']",
    "div[class*='saleNum']",
    "span[class*='saleNum']",
]

# 工厂标签选择器
_FACTORY_SELS = [
    "span[class*='factory']",
    "span[class*='Factory']",
    "span.tag-factory",
    "div[class*='tag'] span",
    "span[class*='label']",
]

# 供应商名称
_SUPPLIER_SELS = [
    "a[class*='company']",
    "span[class*='company']",
    "div[class*='company'] a",
    "a[class*='factory']",
    "div[class*='supplier'] a",
    "span[class*='name']",
]

# MOQ 选择器
_MOQ_SELS = [
    "span[class*='moq']",
    "span[class*='Moq']",
    "span[class*='minimum']",
    "div[class*='moq']",
]


# ============================================================
# 主类
# ============================================================
class Alibaba1688PlaywrightMatcher:
    """Playwright 1688 货源匹配器（无 API Key 版）。"""

    def __init__(
        self,
        headless: bool = True,
        page_wait_ms: int = 4000,
    ):
        self.headless = headless
        self.page_wait_ms = page_wait_ms

    # ─────────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────────

    def search_by_image(
        self,
        image_url: str,
        keywords: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[SupplierDTO]:
        """以图搜货（需已登录 Profile）；失败则自动降级关键词搜索。

        Args:
            image_url   Amazon 主图 URL
            keywords    关键词列表（图搜失败时作为兜底）
            limit       返回数量上限
        """
        if not _profile_has_cookies():
            logger.info("[1688-img] 无登录 Profile，直接使用关键词搜索")
            return self.search_by_keyword(keywords or [], limit=limit)

        try:
            results = self._image_search(image_url, limit)
            if results:
                logger.info(f"[1688-img] 图搜返回 {len(results)} 条")
                return results
            logger.info("[1688-img] 图搜无结果，降级关键词搜索")
        except Exception as e:
            logger.warning(f"[1688-img] 图搜失败: {e}，降级关键词搜索")

        return self.search_by_keyword(keywords or [], limit=limit)

    def search_by_keyword(
        self,
        keywords: list[str],
        limit: int = 10,
    ) -> list[SupplierDTO]:
        """按关键词搜索 1688，无需登录。

        多关键词逐一搜索，去重合并，按月销量排序。
        """
        if not keywords:
            return []

        seen_ids: set[str] = set()
        results: list[SupplierDTO] = []

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                ctx = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=_UA,
                    locale="zh-CN",
                )
                page = ctx.new_page()

                for kw in keywords:
                    if len(results) >= limit:
                        break
                    try:
                        url = f"{_SEARCH_BASE}?keywords={quote(kw)}&n=y&netType=1%2C11"
                        batch = self._scrape_search_page(page, url, limit - len(results))
                        for dto in batch:
                            if dto.alibaba_offer_id not in seen_ids:
                                seen_ids.add(dto.alibaba_offer_id)
                                results.append(dto)
                        logger.info(f"[1688-kw] '{kw}' → {len(batch)} 条")
                    except Exception as e:
                        logger.warning(f"[1688-kw] '{kw}' 搜索失败: {e}")

                browser.close()

        except ImportError:
            logger.error("Playwright 未安装：pip install playwright && playwright install chromium")
            return []

        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[1688-kw] 共 {len(results)} 条（关键词={len(keywords)} 个）")
        return results[:limit]

    # ─────────────────────────────────────────────────────────
    # 内部：图搜（持久化浏览器）
    # ─────────────────────────────────────────────────────────

    def _image_search(self, image_url: str, limit: int) -> list[SupplierDTO]:
        from playwright.sync_api import sync_playwright

        results: list[SupplierDTO] = []
        pw = sync_playwright().start()
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR),
                headless=self.headless,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                viewport={"width": 1920, "height": 1080},
                user_agent=_UA,
                locale="zh-CN",
            )
            page = ctx.new_page()

            url = f"{_SEARCH_BASE}?imageAddress={quote(image_url, safe=':/')}&n=y"
            logger.info(f"[1688-img] 图搜 URL: {url[:80]}...")
            page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(self.page_wait_ms / 1000)

            # 检查是否跳转登录
            if "login" in page.url.lower() or "passport" in page.url.lower():
                logger.warning("[1688-img] 已跳转登录页，Session 过期")
                return []

            results = self._scrape_search_page(page, page.url, limit)
            # 标记图搜相似度（列表页无具体分值，给一个默认值区分来源）
            for dto in results:
                dto.image_similarity = 0.85

        finally:
            try:
                for pg in ctx.pages:
                    pg.close()
                ctx.close()
            except Exception:
                pass
            pw.stop()

        return results

    # ─────────────────────────────────────────────────────────
    # 内部：解析搜索结果页
    # ─────────────────────────────────────────────────────────

    def _scrape_search_page(self, page, url: str, limit: int) -> list[SupplierDTO]:
        """跳转到 url 并解析当前页结果（复用已有 page 对象）。"""
        if page.url != url:
            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_timeout(self.page_wait_ms)

        if "login" in page.url.lower() or "passport" in page.url.lower():
            logger.warning("[1688] 页面跳转到登录，放弃")
            return []

        cards = self._find_cards(page)
        if not cards:
            # 兜底：解析所有 detail.1688.com 链接
            cards = page.query_selector_all("a[href*='detail.1688.com/offer/']")
            logger.debug(f"[1688] 兜底模式，找到链接 {len(cards)} 条")

        results: list[SupplierDTO] = []
        for card in cards[: limit * 2]:
            if len(results) >= limit:
                break
            try:
                dto = _parse_card(card)
                if dto:
                    results.append(dto)
            except Exception as e:
                logger.debug(f"[1688] 解析卡片失败: {e}")

        return results

    def _find_cards(self, page) -> list:
        for sel in _CARD_SELECTORS:
            cards = page.query_selector_all(sel)
            if len(cards) >= 3:
                logger.debug(f"[1688] 使用选择器 {sel!r}，找到 {len(cards)} 张卡片")
                return cards
        return []


# ============================================================
# 卡片解析（纯函数）
# ============================================================

def _parse_card(card) -> Optional[SupplierDTO]:
    """从单张搜索结果卡片提取 SupplierDTO。"""
    # ── 标题 & offer URL ──
    title = ""
    offer_url = ""
    offer_id = ""
    for sel in _TITLE_SELS:
        el = card.query_selector(sel)
        if not el:
            continue
        t = el.inner_text().strip()
        href = el.get_attribute("href") or ""
        if t and len(t) >= 3:
            title = t
            offer_url = _normalize_url(href)
            offer_id = _extract_offer_id(offer_url or href)
            break

    if not title:
        return None

    if not offer_id:
        offer_id = hashlib.md5(title.encode()).hexdigest()[:12]

    # ── 价格（取最低价） ──
    price_cny: Optional[float] = None
    price_tiers: list[dict] = []
    for sel in _PRICE_SELS:
        el = card.query_selector(sel)
        if not el:
            continue
        raw = el.inner_text().strip()
        v = _parse_price(raw)
        if v:
            price_cny = v
            price_tiers = [{"qty": 1, "price": v}]
            break
    # 尝试解析阶梯价（有些卡片显示"1-99件 ¥12 / 100件+ ¥9.5"）
    price_tiers = _extract_price_tiers(card) or price_tiers

    # ── 图片 ──
    img_url: Optional[str] = None
    for sel in _IMAGE_SELS:
        el = card.query_selector(sel)
        if not el:
            continue
        src = el.get_attribute("src") or el.get_attribute("data-src") or ""
        if src and ("alicdn" in src or "1688" in src):
            img_url = _normalize_url(src)
            break

    # ── MOQ ──
    moq: Optional[int] = None
    for sel in _MOQ_SELS:
        el = card.query_selector(sel)
        if el:
            moq = _parse_int(el.inner_text())
            if moq:
                break
    if not moq:
        # 正则兜底：在卡片文本里找 "起订量 N" 或 "≥N件"
        full_text = card.inner_text()
        moq = _parse_moq_from_text(full_text)

    # ── 月成交量 ──
    monthly_sales: Optional[int] = None
    for sel in _SALES_SELS:
        el = card.query_selector(sel)
        if el:
            monthly_sales = _parse_int(el.inner_text())
            if monthly_sales is not None:
                break
    if monthly_sales is None:
        full_text = card.inner_text()
        monthly_sales = _parse_monthly_sales(full_text)

    # ── 供应商名称 ──
    supplier_name: Optional[str] = None
    for sel in _SUPPLIER_SELS:
        el = card.query_selector(sel)
        if el:
            t = el.inner_text().strip()
            if t and len(t) >= 2:
                supplier_name = t
                break

    # ── 工厂标签 ──
    is_factory = False
    full_text = card.inner_text()
    if any(kw in full_text for kw in ("工厂", "生产厂", "manufacturer", "factory", "Factory")):
        is_factory = True
    else:
        for sel in _FACTORY_SELS:
            el = card.query_selector(sel)
            if el and "工厂" in (el.inner_text() or ""):
                is_factory = True
                break

    # ── 复购率（列表页通常没有，留 None） ──
    repeat_buyer_rate: Optional[float] = _parse_repeat_rate(full_text)

    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=supplier_name,
        offer_url=offer_url or f"https://detail.1688.com/offer/{offer_id}.html",
        offer_image_url=img_url,
        image_similarity=None,
        text_similarity=None,
        moq=moq,
        base_price_cny=price_cny,
        price_tiers=price_tiers,
        monthly_sales=monthly_sales,
        repeat_buyer_rate=repeat_buyer_rate,
        is_factory=is_factory,
        delivery_days=None,
        fba_ready=None,
        raw_data={"title_cn": title},
    )


# ============================================================
# 工具函数
# ============================================================

def _extract_offer_id(url: str) -> str:
    m = re.search(r"/offer/(\d+)", url or "")
    return m.group(1) if m else ""


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if not url.startswith("http"):
        return f"https://detail.1688.com{url}"
    return url


def _parse_price(text: str) -> Optional[float]:
    """从价格文本提取浮点数（人民币）。"""
    clean = re.sub(r"[¥￥,，\s]", "", text or "")
    m = re.search(r"(\d+\.?\d*)", clean)
    if m:
        try:
            v = float(m.group(1))
            return v if v > 0 else None
        except ValueError:
            return None
    return None


def _parse_int(text: str) -> Optional[int]:
    if not text:
        return None
    clean = re.sub(r"[,，\s]", "", text)
    m = re.search(r"\d+", clean)
    try:
        return int(m.group()) if m else None
    except (ValueError, AttributeError):
        return None


def _parse_moq_from_text(text: str) -> Optional[int]:
    """从卡片全文正则提取最小起订量。"""
    for pattern in (
        r"起订量[：:\s]*(\d+)",
        r"最小起订[：:\s]*(\d+)",
        r"≥\s*(\d+)\s*件",
        r"最少(\d+)件",
    ):
        m = re.search(pattern, text or "")
        if m:
            return int(m.group(1))
    return None


def _parse_monthly_sales(text: str) -> Optional[int]:
    """从卡片全文提取月成交量。"""
    for pattern in (
        r"月销[售量]*[：:\s]*(\d+[\d,万]*)",
        r"月成交[：:\s]*(\d+[\d,万]*)",
        r"(\d+[\d,万]+)\s*笔",
        r"月销(\d+)",
    ):
        m = re.search(pattern, text or "")
        if m:
            raw = m.group(1).replace(",", "")
            if "万" in raw:
                num = re.search(r"[\d.]+", raw)
                if num:
                    return int(float(num.group()) * 10000)
            try:
                return int(raw)
            except ValueError:
                pass
    return None


def _parse_repeat_rate(text: str) -> Optional[float]:
    """从卡片全文提取复购率（如 "回头率 72%"）。"""
    m = re.search(r"(?:回头率|复购率)[：:\s]*([\d.]+)\s*%", text or "")
    if m:
        try:
            return float(m.group(1)) / 100
        except ValueError:
            pass
    return None


def _extract_price_tiers(card) -> list[dict]:
    """尝试提取价格阶梯（格式：1-99件 ¥12 / 100+件 ¥9.5）。"""
    tiers: list[dict] = []
    # 找所有包含数量+价格的配对元素
    price_els = card.query_selector_all("[class*='price']")
    qty_els = card.query_selector_all("[class*='qty'], [class*='quantity'], [class*='range']")

    if len(price_els) == len(qty_els) and 1 < len(price_els) <= 5:
        for qty_el, price_el in zip(qty_els, price_els):
            qty = _parse_int(qty_el.inner_text())
            price = _parse_price(price_el.inner_text())
            if qty and price:
                tiers.append({"qty": qty, "price": price})

    return tiers


def _profile_has_cookies() -> bool:
    """检查持久化 Profile 目录是否存在登录态文件。"""
    cookies_file = _PROFILE_DIR / "Default" / "Cookies"
    return cookies_file.exists() and cookies_file.stat().st_size > 10_000

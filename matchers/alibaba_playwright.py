"""
1688 Playwright 货源匹配器
===========================
无需 API Key，Playwright 直接爬 1688 搜索结果页。

关键实现细节：
  - URL 关键词必须用 GBK 编码（1688 老系统）
  - Playwright 需显式传入系统代理（HTTP_PROXY），不自动继承
  - 产品卡片选择器：a.search-offer-item.major-offer
  - Offer ID 从 href 的 offerId= 参数提取

支持两种搜索方式：
  1. 图搜（以图搜货）  → 需已登录的持久化浏览器 Profile
  2. 关键词搜索        → 无需登录，公开页面直接抓

用法：
    matcher = Alibaba1688PlaywrightMatcher()
    suppliers = matcher.search_by_image(image_url="https://...", keywords=["折叠桌"])
    suppliers = matcher.search_by_keyword(["折叠桌", "户外折叠桌"])
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse, parse_qs

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

# 产品卡片选择器（经过实测验证）
_CARD_SEL = "a.search-offer-item.major-offer"

# 页面等待时间（秒）
_PAGE_WAIT = 10


def _system_proxy() -> Optional[str]:
    """从环境变量读取系统代理，Playwright 不自动继承。"""
    return (
        os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    ) or None


def _gbk_url(keyword: str) -> str:
    """1688 搜索 URL 使用 GBK 编码（非 UTF-8）。"""
    return f"{_SEARCH_BASE}?keywords={quote(keyword, encoding='gbk')}"


def _offer_id_from_href(href: str) -> str:
    """从 detail.m.1688.com 链接提取 offerId。"""
    try:
        qs = parse_qs(urlparse(href).query)
        ids = qs.get("offerId", [])
        if ids:
            return ids[0]
    except Exception:
        pass
    m = re.search(r"offerId=(\d+)", href or "")
    return m.group(1) if m else ""


def _offer_url(offer_id: str) -> str:
    return f"https://detail.1688.com/offer/{offer_id}.html"


# ============================================================
# 主类
# ============================================================
class Alibaba1688PlaywrightMatcher:
    """Playwright 1688 货源匹配器（无 API Key 版）。"""

    def __init__(
        self,
        headless: bool = True,
        page_wait: float = _PAGE_WAIT,
    ):
        self.headless = headless
        self.page_wait = page_wait
        self._proxy = _system_proxy()

    # ─────────────────────────────────────────────────────────
    # 公开接口
    # ─────────────────────────────────────────────────────────

    def search_by_image(
        self,
        image_url: str,
        keywords: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[SupplierDTO]:
        """以图搜货（需已登录 Profile）；失败则自动降级关键词搜索。"""
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
        """按关键词搜索 1688，无需登录。多关键词逐一搜索，去重合并。"""
        if not keywords:
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright 未安装：pip install playwright && playwright install chromium")
            return []

        seen_ids: set[str] = set()
        results: list[SupplierDTO] = []

        with sync_playwright() as pw:
            # 关键词搜索也用持久化 Profile（1688 需要登录态才返回产品列表）
            ctx = self._new_context(pw, persistent=True)
            page = self._new_page(ctx)

            for kw in keywords:
                if len(results) >= limit:
                    break
                try:
                    batch = self._scrape_page(page, _gbk_url(kw), limit - len(results))
                    for dto in batch:
                        if dto.alibaba_offer_id not in seen_ids:
                            seen_ids.add(dto.alibaba_offer_id)
                            results.append(dto)
                    logger.info(f"[1688-kw] '{kw}' → {len(batch)} 条")
                except Exception as e:
                    logger.warning(f"[1688-kw] '{kw}' 失败: {e}")

            ctx.close()

        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[1688-kw] 共 {len(results)} 条（关键词 {len(keywords)} 个）")
        return results[:limit]

    # ─────────────────────────────────────────────────────────
    # 内部：图搜
    # ─────────────────────────────────────────────────────────

    def _image_search(self, image_url: str, limit: int) -> list[SupplierDTO]:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            ctx = self._new_context(pw, persistent=True)
            page = self._new_page(ctx)

            url = f"{_SEARCH_BASE}?imageAddress={quote(image_url, safe=':/')}"
            logger.info(f"[1688-img] {url[:80]}...")
            page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            time.sleep(self.page_wait)

            if "login" in page.url.lower() or "passport" in page.url.lower():
                logger.warning("[1688-img] 跳转登录页，Session 过期")
                return []

            results = self._parse_cards(page, limit)
            for dto in results:
                dto.image_similarity = 0.85
            return results

        finally:
            try:
                ctx.close()
            except Exception:
                pass
            pw.stop()

    # ─────────────────────────────────────────────────────────
    # 内部：浏览器管理
    # ─────────────────────────────────────────────────────────

    def _new_context(self, pw, persistent: bool):
        proxy_arg = {"server": self._proxy} if self._proxy else None
        common = dict(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            proxy=proxy_arg,
            viewport={"width": 1920, "height": 1080},
            user_agent=_UA,
            locale="zh-CN",
        )
        if persistent:
            return pw.chromium.launch_persistent_context(
                user_data_dir=str(_PROFILE_DIR), **common
            )
        launch_args = {k: v for k, v in common.items() if k in ("headless", "args", "proxy")}
        browser = pw.chromium.launch(**launch_args)
        ctx_args: dict = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": _UA,
            "locale": "zh-CN",
        }
        if proxy_arg:
            ctx_args["proxy"] = proxy_arg
        return browser.new_context(**ctx_args)

    def _new_page(self, ctx):
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(page)
        except Exception:
            pass
        return page

    # ─────────────────────────────────────────────────────────
    # 内部：页面解析
    # ─────────────────────────────────────────────────────────

    def _scrape_page(self, page, url: str, limit: int) -> list[SupplierDTO]:
        page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        time.sleep(self.page_wait)

        if "login" in page.url.lower() or "passport" in page.url.lower():
            logger.warning("[1688] 页面跳转到登录，放弃")
            return []

        return self._parse_cards(page, limit)

    def _parse_cards(self, page, limit: int) -> list[SupplierDTO]:
        cards = page.query_selector_all(_CARD_SEL)
        logger.debug(f"[1688] 找到 {len(cards)} 张卡片")

        results: list[SupplierDTO] = []
        for card in cards[: limit * 2]:
            if len(results) >= limit:
                break
            try:
                dto = _parse_card(card)
                if dto:
                    results.append(dto)
            except Exception as e:
                logger.debug(f"[1688] 卡片解析失败: {e}")
        return results


# ============================================================
# 卡片解析（纯函数）
# ============================================================

def _parse_card(card) -> Optional[SupplierDTO]:
    """从 a.search-offer-item.major-offer 卡片提取 SupplierDTO。"""
    href = card.get_attribute("href") or ""
    offer_id = _offer_id_from_href(href)
    if not offer_id:
        return None

    full_text = card.inner_text() or ""

    # ── 标题 ──────────────────────────────────────────────
    title_el = card.query_selector(".offer-title-row, [class*='title']")
    title = title_el.inner_text().strip() if title_el else full_text.split("\n")[0][:60]

    # ── 价格（格式：¥\n10\n.99 → 10.99） ─────────────────
    price_cny: Optional[float] = None
    price_tiers: list[dict] = []
    price_el = card.query_selector(".offer-price-row, [class*='price']")
    if price_el:
        raw_price = price_el.inner_text().replace("\n", "").replace(" ", "")
        price_cny = _parse_price(raw_price)
        if price_cny:
            price_tiers = [{"qty": 1, "price": price_cny}]

    # ── 图片 ──────────────────────────────────────────────
    img_url: Optional[str] = None
    img_el = card.query_selector("img")
    if img_el:
        src = img_el.get_attribute("src") or img_el.get_attribute("data-src") or ""
        if src.startswith("//"):
            src = f"https:{src}"
        img_url = src or None

    # ── 供应商名称（全文末行中找公司名） ─────────────────
    supplier_name = _extract_supplier(full_text)

    # ── 月销量 ──────────────────────────────────────────
    monthly_sales = _parse_monthly_sales(full_text)

    # ── 复购率 ──────────────────────────────────────────
    repeat_buyer_rate = _parse_repeat_rate(full_text)

    # ── 工厂标签 ─────────────────────────────────────────
    is_factory = "工厂" in full_text or "源头厂家" in full_text

    # ── MOQ ─────────────────────────────────────────────
    moq = _parse_moq(full_text)

    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=supplier_name,
        offer_url=_offer_url(offer_id),
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
        raw_data={"title_cn": title, "full_text": full_text[:200]},
    )


# ============================================================
# 字段解析工具
# ============================================================

def _parse_price(text: str) -> Optional[float]:
    """从价格文本提取 CNY 价格。

    1688 价格格式：'¥\\n10\\n.99\\n新人价\\n全网1.5万+件'
    策略：找第一个 ¥/￥ 后的数字序列，最多两段（整数+小数）。
    上限 ¥9999，超出视为解析错误（可能把销量数据误读为价格）。
    """
    t = (text or "").replace("\n", "").replace(" ", "")
    # 找 ¥ 后的数字（可能含小数点）
    m = re.search(r"[¥￥]([\d,]+\.?\d*)", t)
    if not m:
        # 无货币符号时，取第一个合理数字
        m = re.search(r"^([\d,]+\.?\d*)", re.sub(r"[^\d.,]", "", t))
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            if 0 < v <= 9999:
                return v
        except ValueError:
            pass
    return None


def _parse_monthly_sales(text: str) -> Optional[int]:
    """解析月销量 / 全网销量：'全网1.5万+件' → 15000，'月销200' → 200。"""
    for pattern in (
        r"全网([\d.]+)万\+?件",
        r"月销[量售]*([\d.]+)万\+?件",
        r"月成交([\d.]+)万\+?",
        r"月销[量售]*([\d,]+)",
        r"([\d,]+)\s*笔",
    ):
        m = re.search(pattern, text or "")
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                if "万" in pattern:
                    return int(val * 10000)
                return int(val)
            except ValueError:
                pass
    return None


def _parse_repeat_rate(text: str) -> Optional[float]:
    m = re.search(r"回头率(\d+)%", text or "")
    if m:
        try:
            return float(m.group(1)) / 100
        except ValueError:
            pass
    return None


def _parse_moq(text: str) -> Optional[int]:
    for pattern in (
        r"起订量[：:\s]*(\d+)",
        r"最小起订[：:\s]*(\d+)",
        r"≥\s*(\d+)\s*件",
        r"最少(\d+)件",
        r"(\d+)件起",
    ):
        m = re.search(pattern, text or "")
        if m:
            return int(m.group(1))
    return 1  # 默认最小起订 1


def _extract_supplier(text: str) -> Optional[str]:
    """从卡片全文末尾提取供应商名（通常是最后一行非空文本）。"""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    # 找包含"公司"、"工厂"、"厂家"的行
    for line in reversed(lines):
        if any(k in line for k in ("公司", "工厂", "厂家", "有限", "店")):
            return line[:40]
    # 没找到则取最后一行
    return lines[-1][:40] if lines else None


def _profile_has_cookies() -> bool:
    cookies_file = _PROFILE_DIR / "Default" / "Cookies"
    return cookies_file.exists() and cookies_file.stat().st_size > 10_000

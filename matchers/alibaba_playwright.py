"""
1688 Scrapling 货源匹配器
===========================
基于 Scrapling DynamicFetcher（Playwright 底层）爬 1688 搜索结果。
相比原生 Playwright，Scrapling 提供：
  - 内置反检测（指纹伪装、webdriver 隐藏）
  - Scrapy 风格 CSS 选择器（::text, ::attr）
  - 自适应元素定位（auto_save/adaptive）
  - 内置代理支持和 network_idle 等待

关键实现细节：
  - URL 关键词必须用 GBK 编码（1688 老系统）
  - Scrapling DynamicFetcher 基于 Chromium
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

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

from loguru import logger

from matchers.alibaba_detail import (
    BlockedOfferPage,
    apply_1688_detail_to_supplier,
    parse_1688_offer_detail_html,
)
from execution.models import HumanActionRequired
from matchers.alibaba_pailitao import SupplierDTO

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_DIR = _PROJECT_ROOT / "data" / "browser_profiles" / "1688"
_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_ARTIFACTS_DIR = _PROJECT_ROOT / "data" / "logs" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

_COOKIES_FILE = _PROJECT_ROOT / "data" / "1688_cookies.json"

_SEARCH_BASE = "https://s.1688.com/selloffer/offer_search.htm"

_CARD_SEL = "a.search-offer-item.major-offer"

_PAGE_WAIT = 10


def _save_failure_screenshot(page, context_label: str) -> str | None:
    """在浏览器失败时自动保存截图到 data/logs/artifacts/，返回截图路径。"""
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^\w\-]", "_", context_label)[:60]
        filename = f"{ts}_{safe_label}.png"
        filepath = _ARTIFACTS_DIR / filename
        page.screenshot(path=str(filepath), full_page=False)
        logger.info(f"[1688-diag] 失败截图已保存: {filepath}")
        return str(filepath)
    except Exception as exc:
        logger.debug(f"[1688-diag] 截图保存失败: {exc}")
        return None


def _system_proxy() -> Optional[str]:
    return (
        os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    ) or None


def _playwright_proxy(proxy_url: Optional[str]) -> Optional[dict]:
    """把 env 读出的 proxy 字符串 (或 None) 转成 Playwright 接受的 dict / None。

    之前的实现传 `proxy=self._proxy or ""`，但：
      - 空字符串 ""  → Playwright 抛 "expected object, got string"
      - 字符串 URL   → 同样不被接受
    正确：None 表示无代理；非空 URL 包装成 {"server": url}。
    """
    if not proxy_url:
        return None
    return {"server": proxy_url}


def _playwright_context(headless: bool, proxy_url: Optional[str]):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    configured_cdp = bool(
        (os.environ.get("BU_CDP_HTTP") or "").strip()
        or (os.environ.get("BU_CDP_WS") or "").strip()
    )
    try:
        from agent.browser_agent import _resolve_cdp_ws

        endpoint = _resolve_cdp_ws(timeout_seconds=2)
    except Exception:
        endpoint = ""
    if endpoint:
        try:
            browser = pw.chromium.connect_over_cdp(endpoint)
            contexts = list(browser.contexts)
            if contexts:
                logger.info("[1688] 使用 9222 专用 Chrome 会话")
                proxy = _CdpContextProxy(contexts[0])
                return _ContextManager(
                    proxy,
                    pw,
                    close_context=False,
                )
        except Exception as exc:
            logger.warning(f"[1688] 连接 9222 Chrome 失败: {exc}")
            if configured_cdp:
                pw.stop()
                raise HumanActionRequired(
                    "BROWSER_UNAVAILABLE",
                    "1688 专用 Chrome 9222 当前不可连接",
                    instructions=(
                        "请保持 9222 专用 Chrome 打开，然后在 WebUI 继续任务。"
                    ),
                ) from exc
    elif_configured = configured_cdp and not endpoint
    if elif_configured:
        pw.stop()
        raise HumanActionRequired(
            "BROWSER_UNAVAILABLE",
            "1688 专用 Chrome 9222 当前不可连接",
            instructions="请保持 9222 专用 Chrome 打开，然后在 WebUI 继续任务。",
        )

    kwargs = {
        "user_data_dir": str(_PROFILE_DIR),
        "headless": headless,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1920, "height": 1080},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    }
    proxy = _playwright_proxy(proxy_url)  # type: ignore[assignment]
    if proxy:
        kwargs["proxy"] = proxy
    ctx = pw.chromium.launch_persistent_context(**kwargs)  # type: ignore[arg-type]
    return _ContextManager(ctx, pw, close_context=True)


class _ContextManager:
    def __init__(self, ctx, playwright, *, close_context: bool):
        self.ctx = ctx
        self.playwright = playwright
        self.close_context = close_context

    def __enter__(self):
        return self.ctx

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.close_context:
                self.ctx.close()
        finally:
            self.playwright.stop()


class _CdpContextProxy:
    """Reuse and preserve a 1688 tab in the user's 9222 Chrome context."""

    is_cdp = True

    def __init__(self, context):
        self._context = context
        self._created_pages = []

    @property
    def pages(self):
        pages = [
            page for page in self._context.pages
            if not getattr(page, "is_closed", lambda: False)()
        ]
        candidates = [page for page in pages if _is_1688_url(page.url or "")]
        if not candidates:
            return []

        def priority(page):
            url = (page.url or "").lower()
            if _is_tmd_block(url):
                return 0
            if "detail.1688.com" in url:
                return 1
            if "s.1688.com" in url:
                return 2
            return 3

        return [sorted(candidates, key=priority)[0]]

    def new_page(self):
        page = self._context.new_page()
        self._created_pages.append(page)
        return page

    def __getattr__(self, name):
        return getattr(self._context, name)


def _load_cookies_into(ctx) -> int:
    if getattr(ctx, "is_cdp", False):
        try:
            return len(ctx.cookies([
                "https://login.1688.com/",
                "https://login.taobao.com/",
                "https://work.1688.com/",
                "https://www.1688.com/",
            ]))
        except Exception:
            return 0
    if not _COOKIES_FILE.exists():
        logger.warning(f"[1688] cookies 文件不存在：{_COOKIES_FILE}")
        return 0
    try:
        with open(_COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception as e:
        logger.warning(f"[1688] 读取 cookies 失败: {e}")
        return 0

    cleaned: list[dict] = []
    for c in cookies:
        if not isinstance(c, dict) or not c.get("name") or c.get("value") is None:
            continue
        item = {
            "name": c["name"],
            "value": str(c["value"]),
            "domain": c.get("domain") or ".1688.com",
            "path": c.get("path") or "/",
            "expires": c.get("expires", c.get("expirationDate", -1)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
        }
        same_site = c.get("sameSite")
        if same_site in {"Strict", "Lax", "None"}:
            item["sameSite"] = same_site
        cleaned.append(item)

    if not cleaned:
        return 0
    try:
        ctx.add_cookies(cleaned)
        return len(cleaned)
    except Exception as e:
        logger.warning(f"[1688] 注入 cookies 失败: {e}")
        return 0


def _gbk_url(keyword: str) -> str:
    return f"{_SEARCH_BASE}?keywords={quote(keyword, encoding='gbk')}"


def _offer_id_from_href(href: str) -> str:
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


class Alibaba1688PlaywrightMatcher:
    """Scrapling 1688 货源匹配器（基于 DynamicFetcher）。"""

    def __init__(
        self,
        headless: bool = True,
        page_wait: float = _PAGE_WAIT,
    ):
        self.headless = headless
        self.page_wait = page_wait
        self._proxy = _system_proxy()
        self.last_query_attempts: list[dict] = []

    def search_by_image(
        self,
        image_url: str,
        keywords: Optional[list[str]] = None,
        limit: int = 10,
        *,
        exhaustive: bool = False,
    ) -> list[SupplierDTO]:
        if keywords:
            logger.info("[1688-img] imageAddress 图搜不稳定，使用视觉关键词搜索")
            return self.search_by_keyword(keywords, limit=limit, exhaustive=exhaustive)

        if not _profile_has_cookies():
            logger.info("[1688-img] 无登录 Profile，直接使用关键词搜索")
            return self.search_by_keyword(keywords or [], limit=limit, exhaustive=exhaustive)

        try:
            results = self._image_search(image_url, limit)
            if results:
                logger.info(f"[1688-img] 图搜返回 {len(results)} 条")
                return results
            logger.info("[1688-img] 图搜无结果，降级关键词搜索")
        except HumanActionRequired:
            raise
        except Exception as e:
            logger.warning(f"[1688-img] 图搜失败: {e}，降级关键词搜索")

        return self.search_by_keyword(keywords or [], limit=limit, exhaustive=exhaustive)

    def search_by_keyword(
        self,
        keywords: list[str],
        limit: int = 10,
        *,
        exhaustive: bool = False,
    ) -> list[SupplierDTO]:
        if not keywords:
            self.last_query_attempts = []
            return []

        seen_ids: set[str] = set()
        results: list[SupplierDTO] = []
        self.last_query_attempts = []

        per_query_limit = max(1, min(limit, 5)) if exhaustive else limit
        for kw in keywords:
            if not exhaustive and len(results) >= limit:
                break
            try:
                with _playwright_context(self.headless, self._proxy) as ctx:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    try:
                        loaded = _load_cookies_into(ctx)
                        if loaded:
                            logger.info(f"[1688] 已加载 {loaded} 个 cookies")
                        page.goto(_gbk_url(kw), wait_until="domcontentloaded", timeout=60_000)
                        page.wait_for_timeout(int(self.page_wait * 1000))
                        dismissed = _dismiss_popups(page)
                        if dismissed:
                            logger.info(f"[1688] 已关闭 {dismissed} 个弹窗/遮罩")
                            page.wait_for_timeout(1500)
                        page_url = page.url or ""
                        _raise_if_visible_human_block(page)
                        remaining = per_query_limit if exhaustive else limit - len(results)
                        batch = self._parse_playwright_page(page, remaining)
                        for dto in batch:
                            raw = dto.raw_data if isinstance(dto.raw_data, dict) else {}
                            dto.raw_data = raw
                            queries = raw.setdefault("search_queries", [])
                            if kw not in queries:
                                queries.append(kw)
                            raw["search_backend"] = "alibaba_playwright_keyword"
                            if dto.alibaba_offer_id not in seen_ids:
                                seen_ids.add(dto.alibaba_offer_id)
                                results.append(dto)
                            else:
                                existing = next(
                                    item for item in results
                                    if item.alibaba_offer_id == dto.alibaba_offer_id
                                )
                                existing_raw = existing.raw_data if isinstance(existing.raw_data, dict) else {}
                                existing.raw_data = existing_raw
                                existing_queries = existing_raw.setdefault("search_queries", [])
                                if kw not in existing_queries:
                                    existing_queries.append(kw)
                        logger.info(f"[1688-kw] '{kw}' → {len(batch)} 条")
                        # Anti-TMD: random delay between keyword searches
                        time.sleep(random.uniform(3, 7))
                        self.last_query_attempts.append({
                            "query": kw,
                            "status": "completed",
                            "result_count": len(batch),
                            "result_refs": [
                                f"offer:{dto.alibaba_offer_id}" for dto in batch
                                if dto.alibaba_offer_id
                            ],
                            "error": None,
                            "backend": "alibaba_playwright_keyword",
                        })
                    except Exception:
                        _save_failure_screenshot(page, f"kw_{kw}")
                        raise
            except HumanActionRequired as e:
                self.last_query_attempts.append({
                    "query": kw,
                    "status": "failed",
                    "result_count": None,
                    "error": str(e)[:200],
                    "backend": "alibaba_playwright_keyword",
                })
                logger.warning(f"[1688-kw] '{kw}' 失败: {e}")
                # If we already have partial results, use them instead of aborting.
                if results:
                    logger.info(f"[1688-kw] 已有 {len(results)} 条部分结果，跳过剩余关键词继续")
                else:
                    logger.warning("[1688-kw] 无部分结果，跳过剩余关键词（pipeline 将继续无供应商匹配）")
                break
            except Exception as e:
                self.last_query_attempts.append({
                    "query": kw,
                    "status": "failed",
                    "result_count": None,
                    "error": str(e)[:200],
                    "backend": "alibaba_playwright_keyword",
                })
                logger.warning(f"[1688-kw] '{kw}' 失败: {e}")

        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[1688-kw] 共 {len(results)} 条（关键词 {len(keywords)} 个）")
        return results[:limit]

    def _image_search(self, image_url: str, limit: int) -> list[SupplierDTO]:
        url = f"{_SEARCH_BASE}?imageAddress={quote(image_url, safe=':/')}"
        logger.info(f"[1688-img] {url[:80]}...")

        with _playwright_context(self.headless, self._proxy) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                loaded = _load_cookies_into(ctx)
                if loaded:
                    logger.info(f"[1688] 已加载 {loaded} 个 cookies")
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(int(self.page_wait * 1000))
                dismissed = _dismiss_popups(page)
                if dismissed:
                    logger.info(f"[1688] 已关闭 {dismissed} 个弹窗/遮罩")
                    page.wait_for_timeout(1500)
                page_url = page.url or ""
                _raise_if_visible_human_block(page)
                results = self._parse_playwright_page(page, limit)
            except Exception:
                _save_failure_screenshot(page, "image_search")
                raise
        for rank, dto in enumerate(results, 1):
            raw = dto.raw_data if isinstance(dto.raw_data, dict) else {}
            dto.raw_data = raw
            raw["search_backend"] = "alibaba_playwright_image"
            raw["image_search_rank"] = rank
        return results

    def _parse_scrapling_page(self, page, limit: int) -> list[SupplierDTO]:
        cards = page.css(_CARD_SEL) or []
        logger.debug(f"[1688] 找到 {len(cards)} 张卡片")

        results: list[SupplierDTO] = []
        for card in cards[:limit * 2]:
            if len(results) >= limit:
                break
            try:
                dto = _parse_card(card)
                if dto:
                    results.append(dto)
            except Exception as e:
                logger.debug(f"[1688] 卡片解析失败: {e}")
        return results

    def _parse_playwright_page(self, page, limit: int) -> list[SupplierDTO]:
        selectors = (
            _CARD_SEL,
            "a[data-aplus-report]",
            "a[href*='offerId=']",
            "a[href*='detail.1688.com']",
            ".sm-offer-item",
        )
        cards = None
        for sel in selectors:
            loc = page.locator(sel)
            try:
                if loc.count() > 0:
                    cards = loc
                    logger.debug(f"[1688] selector={sel!r} cards={loc.count()}")
                    break
            except Exception:
                continue
        if cards is None:
            return []

        results: list[SupplierDTO] = []
        count = min(cards.count(), limit * 2)
        for i in range(count):
            if len(results) >= limit:
                break
            try:
                dto = _parse_playwright_card(cards.nth(i))
                if dto:
                    results.append(dto)
            except Exception as e:
                logger.debug(f"[1688] Playwright 卡片解析失败: {e}")
        return results

    def enrich_supplier_detail(self, supplier: SupplierDTO) -> SupplierDTO:
        """Open a 1688 detail page and fill MOQ/spec/logistics/risk fields."""
        if not supplier.offer_url:
            return supplier
        try:
            with _playwright_context(self.headless, self._proxy) as ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    loaded = _load_cookies_into(ctx)
                    if loaded:
                        logger.info(f"[1688-detail] 已加载 {loaded} 个 cookies")
                    page.goto(supplier.offer_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(int(min(self.page_wait, 5) * 1000))
                    _raise_if_visible_human_block(page)
                    html = page.content()
                    final_url = page.url or ""
                    # Parse while the browser context is still attached. A visible
                    # verification page must remain open and must never yield a
                    # supplier price merely because embedded JSON was present.
                    return _enrich_supplier_from_detail_html(
                        supplier, html, page_url=final_url
                    )
                except Exception:
                    _save_failure_screenshot(page, f"detail_{supplier.alibaba_offer_id or 'unknown'}")
                    raise
        except HumanActionRequired:
            raise
        except BlockedOfferPage as exc:
            if exc.error_code in {"AUTH_REQUIRED", "CAPTCHA"}:
                raise HumanActionRequired(
                    exc.error_code,
                    exc.diagnostic,
                    instructions=(
                        "请在专用 Chrome 中打开 1688，完成登录或滑块验证，"
                        "然后在 WebUI 保存 1688 cookies 并继续任务。"
                    ),
                ) from exc
            logger.warning(f"[1688-detail] 详情页补采失败 offer={supplier.alibaba_offer_id}: {exc}")
            supplier.raw_data.setdefault("detail_error", str(exc))
            return supplier
        except Exception as exc:
            logger.warning(f"[1688-detail] 详情页补采失败 offer={supplier.alibaba_offer_id}: {exc}")
            supplier.raw_data.setdefault("detail_error", str(exc))
            return supplier


def _card_full_text(card) -> str:
    text_nodes = card.css("::text").getall() if hasattr(card, 'css') else []
    return "\n".join(t.strip() for t in text_nodes if t.strip()) if text_nodes else ""


def _enrich_supplier_from_detail_html(
    supplier: SupplierDTO, html: str, *, page_url: str | None = None
) -> SupplierDTO:
    detail = parse_1688_offer_detail_html(
        html,
        expected_offer_id=supplier.alibaba_offer_id or None,
        page_url=page_url,
    )
    return apply_1688_detail_to_supplier(supplier, detail)


def _parse_card(card) -> Optional[SupplierDTO]:
    href = card.attrib.get("href") or ""
    if not href:
        href_links = card.css("::attr(href)").getall() if hasattr(card, 'css') else []
        href = href_links[0] if href_links else ""

    offer_id = _offer_id_from_href(href)
    if not offer_id:
        return None

    full_text = _card_full_text(card)

    title_els = card.css(".offer-title-row")
    if not title_els:
        title_els = card.css("[class*='title']")
    if title_els:
        title = (title_els[0].css("::text").getall())
        title = "".join(t.strip() for t in title).strip()
        if not title:
            title = full_text.split("\n")[0][:60] if full_text else ""
    else:
        title = full_text.split("\n")[0][:60] if full_text else ""

    price_cny: Optional[float] = None
    price_tiers: list[dict] = []
    price_els = card.css(".offer-price-row")
    if not price_els:
        price_els = card.css("[class*='price']")
    if price_els:
        price_texts = price_els[0].css("::text").getall()
        raw_price = "".join(price_texts).replace("\n", "").replace(" ", "")
        price_cny = _parse_price(raw_price)
        if price_cny:
            price_tiers = [{"qty": 1, "price": price_cny}]

    img_url: Optional[str] = None
    img_els = card.css("img")
    if img_els:
        src = img_els[0].attrib.get("src") or img_els[0].attrib.get("data-src") or ""
        if src.startswith("//"):
            src = f"https:{src}"
        img_url = src or None

    supplier_name = _extract_supplier(full_text)

    monthly_sales = _parse_monthly_sales(full_text)

    repeat_buyer_rate = _parse_repeat_rate(full_text)

    is_factory = "工厂" in full_text or "源头厂家" in full_text

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
        title_cn=title,
        raw_data={"title_cn": title, "full_text": full_text[:200], "source": "alibaba_playwright"},
    )


def _parse_playwright_card(card) -> Optional[SupplierDTO]:
    href = card.get_attribute("href") or ""
    if not href:
        links = card.locator("a[href*='detail.1688.com'], a[href*='offerId=']")
        if links.count() > 0:
            href = links.first.get_attribute("href") or ""

    offer_id = _offer_id_from_href(href)
    if not offer_id:
        return None

    full_text = _safe_inner_text(card)
    title = ""
    for sel in (".offer-title-row", "[class*='title']", "a[href*='detail.1688.com']"):
        loc = card.locator(sel)
        if loc.count() > 0:
            title = _safe_inner_text(loc.first).replace("\n", "").strip()
            if title:
                break
    if not title:
        title = full_text.split("\n")[0][:60] if full_text else ""

    price_cny: Optional[float] = None
    price_tiers: list[dict] = []
    for sel in (".offer-price-row", "[class*='price']"):
        loc = card.locator(sel)
        if loc.count() > 0:
            price_cny = _parse_price(_safe_inner_text(loc.first))
            if price_cny:
                price_tiers = [{"qty": 1, "price": price_cny}]
                break
    if price_cny is None:
        price_cny = _parse_price(full_text)
        if price_cny:
            price_tiers = [{"qty": 1, "price": price_cny}]

    img_url: Optional[str] = None
    imgs = card.locator("img")
    if imgs.count() > 0:
        src = (
            imgs.first.get_attribute("src")
            or imgs.first.get_attribute("data-src")
            or imgs.first.get_attribute("data-lazyload-src")
            or ""
        )
        if src.startswith("//"):
            src = f"https:{src}"
        img_url = src or None

    supplier_name = _extract_supplier(full_text)
    monthly_sales = _parse_monthly_sales(full_text)
    repeat_buyer_rate = _parse_repeat_rate(full_text)
    is_factory = "工厂" in full_text or "源头厂家" in full_text
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
        title_cn=title,
        raw_data={"title_cn": title, "full_text": full_text[:200], "source": "alibaba_playwright"},
    )


def _safe_inner_text(locator) -> str:
    try:
        return locator.inner_text(timeout=1500).strip()
    except Exception:
        return ""


def _parse_price(text: str) -> Optional[float]:
    raw = text or ""
    if "¥" in raw or "￥" in raw:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if "¥" not in line and "￥" not in line:
                continue
            after = re.sub(r".*[¥￥]\s*", "", line).strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", after):
                return float(after)
            if not after and i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.fullmatch(r"\d+(?:\.\d+)?", next_line):
                    if i + 2 < len(lines) and re.fullmatch(r"\.\d+", lines[i + 2]):
                        return float(next_line + lines[i + 2])
                    return float(next_line)

    t = raw.replace("\n", "").replace(" ", "")
    m = re.search(r"[¥￥]([\d,]+\.?\d*)", t)
    if not m:
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
    for pattern in (
        r"全网([\d.]+)万\+?件",
        r"([\d.]+)万\+?件",
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
    return 1


def _extract_supplier(text: str) -> Optional[str]:
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    for line in reversed(lines):
        if any(k in line for k in ("公司", "工厂", "厂家", "有限", "店")):
            return line[:40]
    return lines[-1][:40] if lines else None


def _profile_has_cookies() -> bool:
    cookies_file = _PROFILE_DIR / "Default" / "Cookies"
    return (
        (_COOKIES_FILE.exists() and _COOKIES_FILE.stat().st_size > 1000)
        or (cookies_file.exists() and cookies_file.stat().st_size > 10_000)
    )


def _wait_for_slider_render(page, timeout_ms: int = 8000) -> bool:
    """Wait for the NoCaptcha slider to be rendered by punishpage.min.js.

    The TMD punish page loads slider JS asynchronously. This polls for the
    presence of known slider DOM elements until they appear or timeout.
    """
    poll_interval = 500
    elapsed = 0
    check_js = """
        () => {
            // Check for any known slider element
            const selectors = [
                '#nc_1_n1z', '.btn_slide', '.nc_iconfont.btn_slide',
                '#nocaptcha .nc_wrapper', '.slidetounlock',
                '.nc_scale', '#nocaptcha .nc-lang-cnt',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.getBoundingClientRect().width > 0) return true;
            }
            // Also check for >> text element (the slider arrow button)
            const allEls = document.querySelectorAll('span, div, a, i');
            for (const el of allEls) {
                const text = (el.textContent || '').trim();
                if (text === '>>' || text === '\\u00bb\\u00bb') {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 15 && rect.width < 80 && rect.height > 15 && rect.height < 60) {
                        return true;
                    }
                }
            }
            return false;
        }
    """
    while elapsed < timeout_ms:
        try:
            if page.evaluate(check_js):
                logger.debug(f"[1688-tmd-slider] 滑块已渲染 (等待 {elapsed}ms)")
                return True
        except Exception:
            pass
        page.wait_for_timeout(poll_interval)
        elapsed += poll_interval
    logger.debug(f"[1688-tmd-slider] 等待滑块渲染超时 ({timeout_ms}ms)")
    return False


def _try_solve_tmd_slider(page, max_attempts: int = 3) -> bool:
    """Attempt to solve the TMD full-page slider CAPTCHA by simulating a human-like drag.

    The TMD punish page (s.1688.com/.../___tmd___/punish) shows a simple
    left-to-right slider with text "请按住滑块，拖动到最右边".
    The slider is rendered asynchronously by punishpage.min.js into #nocaptcha.
    This function waits for the slider to render, locates the button, drags it
    across the track with human-like motion, and checks whether the page
    navigated away from the TMD block.

    Returns True if the slider was solved and the page is no longer blocked.
    """
    import math

    # Wait for the slider JS to render (punishpage.min.js is async)
    _wait_for_slider_render(page, timeout_ms=8000)

    # Selector strategies for the slider button (ordered by specificity)
    slider_selectors = (
        "#nc_1_n1z",                          # Classic Alibaba NoCaptcha slider
        ".nc_iconfont.btn_slide",              # NoCaptcha icon button
        ".btn_slide",                          # Generic slide button
        "[data-nc-lang='SLIDE']",              # NoCaptcha data attribute
        ".nc-lang-cnt .nc_iconfont",           # NoCaptcha container icon
        "span.nc_iconfont",                    # Icon span inside slider
        "#nocaptcha .nc_wrapper .btn_slide",   # Full path
        ".slidetounlock .btn_slide",           # Slide-to-unlock variant
        "#nocaptcha span.btn_slide",           # Inside nocaptcha container
        ".nc_wrapper .btn_slide",             # Wrapper variant
        "span.btn_slide",                      # Any span with btn_slide
    )
    # Track selectors for width calculation
    track_selectors = (
        "#nc_1__scale_text",
        ".nc-lang-cnt",
        ".scale_text",
        ".slidetounlock",
        "[data-nc-lang='SLIDE']",
        "#nocaptcha .nc_scale",               # NoCaptcha scale/track
        ".nc_scale",                          # Generic track
        "#nocaptcha",                          # The container itself
    )

    for attempt in range(1, max_attempts + 1):
        logger.info(f"[1688-tmd-slider] 尝试第 {attempt}/{max_attempts} 次自动滑动")
        slider_btn = None
        track_el = None

        # Try to locate slider button via CSS selectors
        for sel in slider_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=800):
                    slider_btn = loc
                    break
            except Exception:
                continue

        # Fallback 1: XPath for nc_wrapper descendants
        if slider_btn is None:
            try:
                slider_btn = page.locator(
                    "xpath=//div[contains(@class,'nc_wrapper')]//span[contains(@class,'btn')]"
                ).first
                if slider_btn.count() == 0 or not slider_btn.is_visible(timeout=500):
                    slider_btn = None
            except Exception:
                slider_btn = None

        # Fallback 2: Find by JS - look for small clickable element with >> or slider icon
        if slider_btn is None:
            try:
                btn_handle = page.evaluate_handle("""
                    () => {
                        // Strategy A: element with >> text content (the arrow icon)
                        const allEls = document.querySelectorAll('span, div, a, i');
                        for (const el of allEls) {
                            const text = (el.textContent || '').trim();
                            if (text === '>>' || text === '\\u00bb\\u00bb' || text === '\\xbb\\xbb') {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 15 && rect.width < 80 && rect.height > 15 && rect.height < 60) {
                                    return el;
                                }
                            }
                        }
                        // Strategy B: element with cursor:move or cursor:grab near slider text
                        const sliderText = document.querySelector(
                            '[data-nc-lang], .nc-lang-cnt, .scale_text'
                        );
                        if (sliderText) {
                            const parent = sliderText.closest('.nc_wrapper, .slidetounlock, #nocaptcha') || sliderText.parentElement;
                            if (parent) {
                                const candidates = parent.querySelectorAll('span, div, a');
                                for (const el of candidates) {
                                    const style = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    if ((style.cursor === 'move' || style.cursor === 'grab' || style.cursor === 'pointer')
                                        && rect.width > 15 && rect.width < 80
                                        && rect.height > 15 && rect.height < 60) {
                                        return el;
                                    }
                                }
                            }
                        }
                        // Strategy C: first child of nc_scale or track-like element
                        const track = document.querySelector('.nc_scale, .slidetounlock, [class*="scale"]');
                        if (track) {
                            const firstChild = track.firstElementChild;
                            if (firstChild) {
                                const rect = firstChild.getBoundingClientRect();
                                if (rect.width > 15 && rect.width < 80 && rect.height > 15) {
                                    return firstChild;
                                }
                            }
                        }
                        return null;
                    }
                """)
                el = btn_handle.as_element()
                if el and el.is_visible():
                    slider_btn = el
            except Exception:
                pass

        # Try to locate the track (for width calculation)
        for sel in track_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=500):
                    track_el = loc
                    break
            except Exception:
                continue

        if slider_btn is None:
            logger.warning("[1688-tmd-slider] 未找到滑块按钮元素")
            # On retry, wait more for JS to render
            if attempt < max_attempts:
                page.wait_for_timeout(3000)
                _wait_for_slider_render(page, timeout_ms=5000)
            continue

        try:
            btn_box = slider_btn.bounding_box()
        except Exception:
            btn_box = None
        if not btn_box:
            logger.warning("[1688-tmd-slider] 无法获取滑块按钮坐标")
            return False

        # Determine drag distance
        if track_el:
            try:
                track_box = track_el.bounding_box()
                drag_distance = track_box["width"] - btn_box["width"] - 4
            except Exception:
                drag_distance = 300
        else:
            # Fallback: use viewport width heuristic
            try:
                vp = page.viewport_size or {"width": 1280}
                drag_distance = min(vp["width"] * 0.35, 340)
            except Exception:
                drag_distance = 300

        # Ensure minimum drag distance
        drag_distance = max(drag_distance, 200)

        # Starting position: center of slider button
        start_x = btn_box["x"] + btn_box["width"] / 2
        start_y = btn_box["y"] + btn_box["height"] / 2

        # Generate human-like trajectory points
        steps = random.randint(25, 40)
        points: list[tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # Ease-in-out cubic with slight overshoot
            if t < 0.5:
                ease = 4 * t * t * t
            else:
                ease = 1 - (-2 * t + 2) ** 3 / 2
            # Add slight overshoot at the end (humans often overshoot)
            if t > 0.85:
                overshoot = math.sin((t - 0.85) / 0.15 * math.pi) * random.uniform(3, 8)
            else:
                overshoot = 0
            dx = ease * (drag_distance + overshoot)
            # Y-axis jitter: small random vertical movement
            dy = random.gauss(0, 1.5) if 0.1 < t < 0.9 else 0
            points.append((start_x + dx, start_y + dy))

        # Final position: exact end of track (correct overshoot)
        points.append((start_x + drag_distance, start_y + random.uniform(-1, 1)))

        # Perform the drag
        try:
            page.mouse.move(start_x, start_y)
            page.wait_for_timeout(random.randint(100, 300))
            page.mouse.down()
            page.wait_for_timeout(random.randint(50, 150))

            for idx, (px, py) in enumerate(points[1:], 1):
                page.mouse.move(px, py)
                # Variable delay: faster in middle, slower at start/end
                progress = idx / len(points)
                if progress < 0.2 or progress > 0.8:
                    delay = random.randint(15, 35)
                else:
                    delay = random.randint(5, 18)
                # Occasional micro-pause (human hesitation)
                if random.random() < 0.05:
                    delay += random.randint(50, 120)
                page.wait_for_timeout(delay)

            page.wait_for_timeout(random.randint(80, 200))
            page.mouse.up()
        except Exception as exc:
            logger.warning(f"[1688-tmd-slider] 鼠标拖动异常: {exc}")
            continue

        # Wait for page navigation / verification result
        page.wait_for_timeout(random.randint(2000, 3500))

        # Check if TMD block is gone
        new_url = page.url or ""
        try:
            new_title = page.title() or ""
        except Exception:
            new_title = ""
        if not _is_tmd_block(new_url, new_title):
            logger.info("[1688-tmd-slider] 滑块验证通过，页面已跳转")
            return True

        # Check for success indicators on the same page
        try:
            body = page.locator("body").inner_text(timeout=2000)
            if "验证通过" in body or "验证成功" in body:
                logger.info("[1688-tmd-slider] 页面显示验证通过")
                page.wait_for_timeout(1500)
                return True
        except Exception:
            pass

        logger.info(f"[1688-tmd-slider] 第 {attempt} 次滑动未通过，页面仍在 TMD")
        # Wait before retry (the slider may reset)
        page.wait_for_timeout(random.randint(1500, 3000))

    logger.warning("[1688-tmd-slider] 所有自动滑动尝试均失败")
    return False


def _dismiss_popups(page) -> int:
    selectors = (
        ".next-dialog-close",
        ".next-overlay-close",
        ".next-dialog-close-icon",
        ".rax-dialog-close",
        ".dialog-close",
        ".modal-close",
        ".close",
        "[aria-label='close']",
        "[aria-label='Close']",
        "[title='关闭']",
        "[title='close']",
        "button:has-text('关闭')",
        "button:has-text('我知道了')",
        "button:has-text('知道了')",
        "button:has-text('稍后再说')",
        "text=关闭",
        "text=我知道了",
        "text=知道了",
        "text=稍后再说",
        "text=×",
        # 1688 baxia verification overlay close button
        ".baxia-dialog-close",
        ".baxia-dialog .close",
        "#baxia-dialog-content .close",
        ".J_MIDDLEWARE_FRAME_WIDGET .close",
        "a.nc-close",
        ".nc_iconfont.btn_close",
    )
    clicked = 0
    for _ in range(3):
        did_click = False
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() == 0 or not loc.is_visible(timeout=300):
                    continue
                loc.click(timeout=1000)
                clicked += 1
                did_click = True
                page.wait_for_timeout(500)
                break
            except Exception:
                continue
        if not did_click:
            break

    # Some 1688 overlays close on Escape even when the close button is hard to select.
    if clicked == 0:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
    # JS fallback: click baxia/verification overlay close buttons that CSS selectors miss.
    if clicked == 0:
        try:
            js_clicked = page.evaluate("""
                () => {
                    // Strategy 1: class-based close buttons
                    const candidates = document.querySelectorAll(
                        '[class*="close"], [class*="Close"], [aria-label*="close"], [aria-label*="Close"]'
                    );
                    for (const el of candidates) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0 && rect.width < 60) {
                            el.click();
                            return 1;
                        }
                    }
                    // Strategy 2: elements containing × or ✕ character (baxia overlay)
                    const allEls = document.querySelectorAll('span, a, div, button, i');
                    for (const el of allEls) {
                        const text = (el.textContent || '').trim();
                        if (text === '×' || text === '✕' || text === 'X' || text === 'x') {
                            const rect = el.getBoundingClientRect();
                            // Must be small (icon-sized) and visible in viewport
                            if (rect.width > 0 && rect.width < 50 && rect.height < 50
                                && rect.top > 100 && rect.top < 600) {
                                el.click();
                                return 2;
                            }
                        }
                    }
                    return 0;
                }
            """)
            if js_clicked:
                clicked += 1
                page.wait_for_timeout(500)
        except Exception:
            pass
    # Also try dismissing in iframes (baxia may render in a frame)
    if clicked == 0:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                js_clicked = frame.evaluate("""
                    () => {
                        const candidates = document.querySelectorAll(
                            '[class*="close"], [class*="Close"]'
                        );
                        for (const el of candidates) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0 && rect.width < 60) {
                                el.click();
                                return 1;
                            }
                        }
                        const allEls = document.querySelectorAll('span, a, div, button, i');
                        for (const el of allEls) {
                            const text = (el.textContent || '').trim();
                            if (text === '×' || text === '✕') {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 0 && rect.width < 50 && rect.height < 50) {
                                    el.click();
                                    return 2;
                                }
                            }
                        }
                        return 0;
                    }
                """)
                if js_clicked:
                    clicked += 1
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue
    return clicked


def _is_tmd_block(url: str, title: str = "") -> bool:
    text = f"{url} {title}".lower()
    return "_____tmd_____" in text or "punish" in text or "验证码拦截" in title


def _is_1688_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "1688.com" or host.endswith(".1688.com")


def _visible_human_block(page) -> tuple[str, str] | None:
    """Classify verification/login UI using only visible browser state."""
    url = page.url or ""
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    if _is_tmd_block(url, title):
        return "CAPTCHA", "1688 TMD 验证码拦截"

    frame_urls: list[str] = []
    try:
        frame_urls = [frame.url or "" for frame in page.frames]
    except Exception:
        pass
    frame_text = " ".join(frame_urls).lower()
    if any(marker in frame_text for marker in ("captcha", "punish", "verify")):
        return "CAPTCHA", "1688 页面显示验证码或人机验证"

    try:
        body_text = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        body_text = ""
    visible_text = f"{title}\n{body_text}".lower()
    captcha_markers = (
        "验证码",
        "滑动滑块",
        "拖动滑块",
        "人机验证",
        "访问过于频繁",
        "安全验证",
    )
    if any(marker in visible_text for marker in captcha_markers):
        return "CAPTCHA", "1688 页面显示验证码或人机验证"

    lowered_url = url.lower()
    if (
        "login" in lowered_url
        or "passport" in lowered_url
        or "请登录后继续访问" in visible_text
    ):
        return "AUTH_REQUIRED", "1688 登录态已过期"
    return None


def _raise_if_visible_human_block(page) -> None:
    blocked = _visible_human_block(page)
    if not blocked:
        return
    error_code, diagnostic = blocked
    # Dismissable overlay popups (e.g. detail-page slider captcha) can be closed
    # by clicking the X button or pressing Escape.  Try that before raising.
    if error_code == "CAPTCHA" and not _is_tmd_block(page.url or "", ""):
        dismissed = _dismiss_popups(page)
        if dismissed:
            page.wait_for_timeout(1000)
            blocked = _visible_human_block(page)
            if not blocked:
                logger.info("[1688] 验证弹窗已自动关闭，继续操作")
                return
    # TMD full-page slider: attempt automatic solve before requiring human action
    if error_code == "CAPTCHA" and _is_tmd_block(page.url or "", ""):
        if _try_solve_tmd_slider(page):
            page.wait_for_timeout(1500)
            blocked = _visible_human_block(page)
            if not blocked:
                logger.info("[1688] TMD 滑块已自动通过，继续操作")
                return
    action = "重新登录" if error_code == "AUTH_REQUIRED" else "完成登录或滑块验证"
    raise HumanActionRequired(
        error_code,
        diagnostic,
        instructions=(
            f"请在专用 Chrome 中打开 1688，{action}，"
            "然后在 WebUI 保存 1688 cookies 并继续任务。"
        ),
    )

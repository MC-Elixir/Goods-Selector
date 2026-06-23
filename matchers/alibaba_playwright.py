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

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse, parse_qs

from loguru import logger

from matchers.alibaba_pailitao import SupplierDTO

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_DIR = _PROJECT_ROOT / "data" / "browser_profiles" / "1688"
_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

_COOKIES_FILE = _PROJECT_ROOT / "data" / "1688_cookies.json"

_SEARCH_BASE = "https://s.1688.com/selloffer/offer_search.htm"

_CARD_SEL = "a.search-offer-item.major-offer"

_PAGE_WAIT = 10


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

    def search_by_image(
        self,
        image_url: str,
        keywords: Optional[list[str]] = None,
        limit: int = 10,
    ) -> list[SupplierDTO]:
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
        if not keywords:
            return []

        try:
            from scrapling.fetchers import DynamicFetcher
        except ImportError:
            logger.error("Scrapling 未安装：pip install 'scrapling[fetchers]' && scrapling install")
            return []

        seen_ids: set[str] = set()
        results: list[SupplierDTO] = []

        for kw in keywords:
            if len(results) >= limit:
                break
            try:
                page = DynamicFetcher.fetch(
                    _gbk_url(kw),
                    headless=self.headless,
                    proxy=_playwright_proxy(self._proxy),
                    network_idle=True,
                    timeout=60_000,
                    useragent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    extra_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
                    locale="zh-CN",
                )
                batch = self._parse_scrapling_page(page, limit - len(results))
                for dto in batch:
                    if dto.alibaba_offer_id not in seen_ids:
                        seen_ids.add(dto.alibaba_offer_id)
                        results.append(dto)
                logger.info(f"[1688-kw] '{kw}' → {len(batch)} 条")
            except Exception as e:
                logger.warning(f"[1688-kw] '{kw}' 失败: {e}")

        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[1688-kw] 共 {len(results)} 条（关键词 {len(keywords)} 个）")
        return results[:limit]

    def _image_search(self, image_url: str, limit: int) -> list[SupplierDTO]:
        try:
            from scrapling.fetchers import DynamicFetcher
        except ImportError:
            logger.error("Scrapling 未安装：pip install 'scrapling[fetchers]' && scrapling install")
            return []

        url = f"{_SEARCH_BASE}?imageAddress={quote(image_url, safe=':/')}"
        logger.info(f"[1688-img] {url[:80]}...")

        page = DynamicFetcher.fetch(
            url,
            headless=self.headless,
            proxy=_playwright_proxy(self._proxy),
            network_idle=True,
            timeout=60_000,
            useragent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            extra_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
            locale="zh-CN",
        )

        page_url = getattr(page, 'url', '') or ''
        if "login" in page_url.lower() or "passport" in page_url.lower():
            logger.warning("[1688-img] 跳转登录页，Session 过期")
            return []

        results = self._parse_scrapling_page(page, limit)
        for dto in results:
            dto.image_similarity = 0.85
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


def _card_full_text(card) -> str:
    text_nodes = card.css("::text").getall() if hasattr(card, 'css') else []
    return "\n".join(t.strip() for t in text_nodes if t.strip()) if text_nodes else ""


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
        raw_data={"title_cn": title, "full_text": full_text[:200]},
    )


def _parse_price(text: str) -> Optional[float]:
    t = (text or "").replace("\n", "").replace(" ", "")
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
    return cookies_file.exists() and cookies_file.stat().st_size > 10_000

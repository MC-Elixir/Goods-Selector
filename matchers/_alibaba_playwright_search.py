"""
1688 关键词搜索 — Playwright 版
=============================
无需 API Key，无需登录，直接爬 1688 公开搜索页面。

用法：
    from matchers._alibaba_playwright_search import search_by_keyword
    offers = search_by_keyword("折叠桌", limit=10)
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


def search_by_keyword(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    """1688 关键词搜索，返回货源列表。

    Returns:
        list[dict]: offer_id, title_cn, url, image_url, price_cny, moq
    """
    from playwright.sync_api import sync_playwright

    offers: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = ctx.new_page()

        try:
            search_url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote(keyword)}&n=y&netType=1%2C11&spm=a260k.dacugeneral.search.0"
            logger.info("[1688-kw] searching: %s", keyword)
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(4)

            # 检查是否跳转到登录
            if "login" in page.url.lower():
                logger.warning("[1688-kw] redirected to login")
                return offers

            # 查找结果项
            items = _find_items(page)
            logger.info("[1688-kw] found %d items for '%s'", len(items), keyword)

            for item in items:
                if len(offers) >= limit:
                    break
                try:
                    offer = _parse_offer(item)
                    if offer:
                        offers.append(offer)
                except Exception as e:
                    logger.debug("[1688-kw] parse error: %s", e)

        finally:
            browser.close()

    logger.info("[1688-kw] '%s' → %d offers", keyword, len(offers))
    return offers


# ── 选择器 ────────────────────────────────────────────────

_ITEM_SELECTORS = [
    "div.offer_list > div[class*='offer']",
    "div.sm-offer-item",
    "div[class*='offer_item']",
    "div.offer-item",
    "div[class*='list'] > div[class*='item']",
]

_TITLE_SELS = [
    "a.sm-offer-title",
    "a.offer-title",
    "a[class*='title']",
    "h3 a",
    "a[href*='detail.1688.com']",
]

_PRICE_SELS = [
    "span.sm-offer-priceNum",
    "span[class*='priceNum']",
    "span.price",
    "em.price",
    "span[class*='price']",
]

_IMAGE_SELS = [
    "img.sm-offer-image",
    "img[class*='offer']",
    "img[src*='alicdn']",
    "div[class*='img'] img",
    "img",
]


def _find_items(page):
    for sel in _ITEM_SELECTORS:
        items = page.query_selector_all(sel)
        if items and len(items) > 0:
            return items
    # 兜底：找所有包含 detail.1688.com 的链接
    return page.query_selector_all("a[href*='detail.1688.com/offer/']")


def _parse_offer(item) -> dict[str, Any] | None:
    # 标题
    title = ""
    offer_url = ""
    for sel in _TITLE_SELS:
        el = item.query_selector(sel)
        if el:
            title = el.inner_text().strip()
            offer_url = el.get_attribute("href") or ""
            break

    if not title or len(title) < 3:
        return None

    # 价格
    price = 0.0
    for sel in _PRICE_SELS:
        el = item.query_selector(sel)
        if el:
            text = el.inner_text().strip()
            # "¥12.50" or "12.50"
            m = re.search(r"(\d+\.?\d*)", text.replace(",", ""))
            if m:
                try:
                    price = float(m.group(1))
                    break
                except ValueError:
                    pass

    # 图片
    img_url = ""
    for sel in _IMAGE_SELS:
        el = item.query_selector(sel)
        if el:
            src = el.get_attribute("src") or el.get_attribute("data-src") or ""
            if src and ("alicdn" in src or "img" in src.lower()):
                if src.startswith("//"):
                    src = f"https:{src}"
                img_url = src
                break

    # 链接补全
    if offer_url and not offer_url.startswith("http"):
        offer_url = f"https:{offer_url}" if offer_url.startswith("//") else f"https://detail.1688.com{offer_url}"

    # 起订量
    moq = 1
    for sel in ["span[class*='moq']", "span[class*='minimum']", "span[class*='quantity']"]:
        el = item.query_selector(sel)
        if el:
            digits = "".join(c for c in el.inner_text() if c.isdigit())
            if digits:
                moq = int(digits)
                break

    offer_id = hashlib.md5((title + (offer_url or "")).encode()).hexdigest()[:12]

    return {
        "offer_id": offer_id,
        "title_cn": title,
        "url": offer_url or None,
        "image_url": img_url or None,
        "price_cny": price,
        "moq": moq,
    }
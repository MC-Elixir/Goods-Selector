"""
1688 图搜 — Playwright 持久化浏览器版
=====================================
使用已登录的浏览器 Profile 进行 1688 以图搜货。
Profile 位于 data/browser_profiles/1688/

前置条件：Profile 中已有 1688 登录态（从 Best-Seller-Search-Engine 移植）。

用法：
    from matchers._pailitao_playwright import search_by_image
    offers = search_by_image(image_url="https://...", limit=10)
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = _PROJECT_ROOT / "data" / "browser_profiles" / "1688"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def _launch_persistent(headless: bool = True):
    """启动持久化浏览器上下文（复用登录态）。"""
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
    )
    return p, context


def search_by_image(image_url: str, limit: int = 10) -> list[dict[str, Any]]:
    """使用已登录 Profile 进行 1688 以图搜货。

    Returns:
        list[dict]: 每个 dict 含 offer_id, title_cn, url, image_url, price_cny, moq
    """
    p, context = _launch_persistent(headless=True)
    offers: list[dict[str, Any]] = []

    try:
        page = context.new_page()

        search_url = (
            f"https://s.1688.com/selloffer/offer_search.htm"
            f"?imageAddress={image_url}&n=y"
        )
        logger.info("[1688-img] searching: %s...", image_url[:60])
        page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
        time.sleep(6)

        final_url = page.url
        if "login" in final_url.lower():
            logger.warning(
                "[1688-img] redirected to login — session expired"
            )
            return offers

        items = _find_result_items(page)
        logger.info("[1688-img] found %d items", len(items))

        for item in items[: limit * 2]:
            if len(offers) >= limit:
                break
            try:
                offer = _parse_item(item)
                if offer:
                    offers.append(offer)
            except Exception as e:
                logger.debug("[1688-img] parse error: %s", e)

    finally:
        for pg in context.pages:
            pg.close()
        context.close()
        p.stop()

    logger.info("[1688-img] got %d offers", len(offers))
    return offers[:limit]


# ── 解析辅助 ──────────────────────────────────────────────

_OFFER_SELECTORS = [
    "div.offer_item",
    "div[class*='offer'] div[class*='item']",
    "li.offer_item",
    "div.sm-offer-item",
    "a[href*='detail.1688.com']",
    "div[class*='list-item']",
    "div[class*='card'] a[href*='detail.1688.com']",
]

_TITLE_SEL = [
    "a.offer_title",
    "a[class*='title']",
    "div[class*='title'] a",
    "h3 a",
    "a[href*='detail.1688.com']",
]

_PRICE_SEL = [
    "span.price",
    "span[class*='price']",
    "em.price",
    "div.price span",
    "span.sm-offer-priceNum",
]

_IMAGE_SEL = [
    "img.offer_img",
    "img[class*='img']",
    "div[class*='pic'] img",
    "img[src*='alicdn']",
]


def _find_result_items(page):
    items = []
    for sel in _OFFER_SELECTORS:
        items = page.query_selector_all(sel)
        if items:
            break

    if not items:
        for container in page.query_selector_all("div.offer_list, div[data-module]"):
            for sel in _OFFER_SELECTORS:
                inner = container.query_selector_all(sel)
                if inner:
                    items.extend(inner)
            if items:
                break

    return items


def _parse_item(item) -> dict[str, Any] | None:
    # 标题
    title = ""
    title_url = ""
    for sel in _TITLE_SEL:
        el = item.query_selector(sel)
        if el:
            title = el.inner_text().strip()
            title_url = el.get_attribute("href") or ""
            break

    if not title or len(title) < 4:
        return None

    # 价格
    price = 0.0
    for sel in _PRICE_SEL:
        el = item.query_selector(sel)
        if el:
            text = el.inner_text().strip()
            match = re.search(r"(\d+\.?\d*)", text.replace(",", "").replace("¥", "").replace("￥", ""))
            if match:
                try:
                    price = float(match.group(1))
                    break
                except ValueError:
                    pass

    # 图片
    img_url = ""
    for sel in _IMAGE_SEL:
        el = item.query_selector(sel)
        if el:
            img_url = (
                el.get_attribute("src")
                or el.get_attribute("data-src")
                or ""
            )
            if img_url:
                if img_url.startswith("//"):
                    img_url = f"https:{img_url}"
                break

    # 链接
    if not title_url:
        for a in item.query_selector_all("a[href*='detail.1688.com']"):
            title_url = a.get_attribute("href") or ""
            if title_url:
                break

    if title_url and not title_url.startswith("http"):
        title_url = (
            f"https:{title_url}"
            if title_url.startswith("//")
            else f"https://detail.1688.com{title_url}"
        )

    # 起订量
    moq = 1
    moq_el = item.query_selector("span[class*='moq'], span[class*='minimum']")
    if moq_el:
        digits = "".join(c for c in moq_el.inner_text() if c.isdigit())
        if digits:
            moq = int(digits)

    offer_id = hashlib.md5(title.encode()).hexdigest()[:12]

    return {
        "offer_id": offer_id,
        "title_cn": title,
        "url": title_url or None,
        "image_url": img_url or None,
        "price_cny": price,
        "moq": moq,
    }
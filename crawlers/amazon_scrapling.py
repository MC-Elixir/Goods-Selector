"""
Amazon Best Seller 爬虫 — Scrapling 后端
==========================================

用 Scrapling 的 StealthySession（patchright 修补的 chromium + 反检测）抓
Amazon BSR 页面与产品详情页。

字段提取逻辑全部在 crawlers/_amazon_extractors.py（共享模块，与 Playwright 后端
共用同一份解析代码）。本文件只负责：
    1. 启动 StealthySession（page-pool 复用）
    2. 遍历 BSR 列表页 → 抓每个 ASIN 详情
    3. 限速 + 验证码检测
    4. 加载 / 持久化 cookies（data/amazon_cookies.json）
    5. HTML 缓存（data/cache/amazon/，diskcache 24h TTL）

限速：详情页间隔 2–5 秒随机；BSR 列表页 1.5–3 秒。
验证码：检测 <title> 包含 "robot check" / "captcha" 时自动停止并返回已收集数据，
同时清空当前页缓存（避免 captcha 页被错误地缓存）。
"""
from __future__ import annotations

import math
import random
import re
import time
from pathlib import Path

from loguru import logger

from crawlers._amazon_cache import bsr_key, delete as cache_delete, detail_key, get_html, set_html
from crawlers._amazon_cookies import cookie_path, load_cookies, save_cookies
from crawlers._amazon_extractors import (
    extract_brand,
    extract_bsr,
    extract_dimensions,
    extract_image,
    extract_price,
    extract_rating,
    extract_reviews,
    extract_title,
    is_captcha,
    parse_bsr_page,
)
from crawlers._amazon_page import ScraplingPage
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

_DEFAULT_COOKIES: list[dict] = [
    {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"},
    {"name": "lc-main",    "value": "en_US", "domain": ".amazon.com", "path": "/"},
]

_BSR_PER_PAGE = 50


# ============================================================
# 主爬虫类
# ============================================================
class AmazonScraplingScraper:
    """Scrapling-based Amazon Best Sellers 爬虫。

    用法：
        scraper = AmazonScraplingScraper()
        products = scraper.scrape_best_sellers("Home & Kitchen", limit=50)
    """

    def __init__(
        self,
        headless: bool = True,
        rate_min: float = 2.0,
        rate_max: float = 5.0,
        cookies: list[dict] | None = None,
        cookies_path: Path | None = None,
        extra_headers: dict[str, str] | None = None,
        solve_cloudflare: bool = True,
        hide_canvas: bool = True,
        block_webrtc: bool = True,
        use_cache: bool = True,
    ):
        self.headless = headless
        self.rate_min = rate_min
        self.rate_max = rate_max
        self.cookies_path = cookies_path
        self.use_cache = use_cache
        # 优先级：显式 cookies 参数 > data/amazon_cookies.json > 默认 i18n cookies
        if cookies is not None:
            self.cookies = cookies
        else:
            loaded = load_cookies(cookies_path)
            self.cookies = loaded if loaded is not None else list(_DEFAULT_COOKIES)
        self.extra_headers = extra_headers or {"Accept-Language": "en-US,en;q=0.9"}
        self.solve_cloudflare = solve_cloudflare
        self.hide_canvas = hide_canvas
        self.block_webrtc = block_webrtc

    # --------------------------------------------------------
    def scrape_best_sellers(
        self,
        category: str,
        limit: int = 100,
        marketplace: str = "US",
    ) -> list[ProductDTO]:
        """抓取指定类目 BSR 前 limit 名产品。"""
        from scrapling.fetchers import StealthySession

        base_url = _MARKETPLACE_DOMAINS.get(marketplace, _MARKETPLACE_DOMAINS["US"])
        slug = _CATEGORY_SLUGS.get(category)
        if not slug:
            logger.warning(
                f"未找到类目 {category!r} 的 URL slug，"
                f"可用类目：{list(_CATEGORY_SLUGS.keys())}"
            )
            slug = category.lower().replace(" & ", "-").replace(" ", "-")

        session = StealthySession(
            headless=self.headless,
            cookies=self.cookies,
            extra_headers=self.extra_headers,
            locale="en-US",
            timezone_id="America/New_York",
            useragent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            solve_cloudflare=self.solve_cloudflare,
            hide_canvas=self.hide_canvas,
            block_webrtc=self.block_webrtc,
            block_ads=True,
        )
        session.start()

        try:
            asins = self._collect_asins(session, base_url, slug, limit, marketplace)
            logger.info(f"[scrapling] 收集到 {len(asins)} 个 ASIN，开始抓详情...")

            products: list[ProductDTO] = []
            for i, asin in enumerate(asins[:limit], 1):
                try:
                    dto = self._scrape_product(session, base_url, asin, marketplace, category)
                    products.append(dto)
                    logger.debug(f"[scrapling] [{i}/{len(asins)}] {asin} OK")
                except Exception as e:
                    logger.warning(f"[scrapling] {asin} 详情失败，跳过: {e}")

                if i < len(asins[:limit]):
                    time.sleep(random.uniform(self.rate_min, self.rate_max))

            logger.info(f"[scrapling] 完成，共抓取 {len(products)} 个产品")
            return products

        finally:
            self._save_cookies_from_session(session)
            session.close()

    # --------------------------------------------------------
    def _collect_asins(
        self, session, base_url: str, slug: str, limit: int, marketplace: str
    ) -> list[str]:
        """从 BSR 分页列表中收集 ASIN，不重复。"""
        asins: list[str] = []
        seen: set[str] = set()
        pages_needed = math.ceil(limit / _BSR_PER_PAGE)

        for pg in range(1, pages_needed + 1):
            if len(asins) >= limit:
                break
            url = f"{base_url}/Best-Sellers/zgbs/{slug}/ref=zg_bs_pg_{pg}?ie=UTF8&pg={pg}"
            cache_k = bsr_key(slug, pg, marketplace)

            # 1. 缓存命中
            html = get_html(cache_k) if self.use_cache else None
            if html:
                from scrapling.parser import Adaptor
                page = Adaptor(html)
                logger.debug(f"[scrapling] BSR 第 {pg} 页 走缓存")
            else:
                try:
                    page = session.fetch(
                        url,
                        timeout=60_000,
                        wait=1.5,
                        network_idle=False,
                    )
                except Exception as e:
                    logger.warning(f"[scrapling] BSR 第 {pg} 页失败: {e}")
                    break
                # 抓取成功后写缓存
                try:
                    set_html(cache_k, page.html_content)
                except Exception:
                    pass

            sp = ScraplingPage(page)
            if is_captcha(sp):
                logger.warning(f"[scrapling] 遇到验证码，已停止（已收集 {len(asins)} 个）")
                # 删掉 captcha 页缓存，避免污染
                cache_delete(cache_k)
                break
            new = parse_bsr_page(sp)
            for a in new:
                if a not in seen:
                    seen.add(a)
                    asins.append(a)
            logger.debug(f"[scrapling] BSR 第 {pg} 页，新增 {len(new)} 个 ASIN")
            time.sleep(random.uniform(1.5, 3.0))

        return asins

    # --------------------------------------------------------
    def _scrape_product(
        self, session, base_url: str, asin: str, marketplace: str, category: str
    ) -> ProductDTO:
        """爬取单个产品详情页，返回 ProductDTO。"""
        url = f"{base_url}/dp/{asin}?language=en_US&currency=USD"
        cache_k = detail_key(asin, marketplace)

        # 1. 缓存命中
        html = get_html(cache_k) if self.use_cache else None
        if html:
            from scrapling.parser import Adaptor
            page = Adaptor(html)
            logger.debug(f"[scrapling] {asin} 走详情缓存")
        else:
            page = session.fetch(
                url,
                timeout=60_000,
                wait=random.randint(800, 1500) / 1000,
                network_idle=False,
            )
            try:
                set_html(cache_k, page.html_content)
            except Exception:
                pass

        sp = ScraplingPage(page)
        if is_captcha(sp):
            cache_delete(cache_k)
            raise RuntimeError("验证码页面")

        weight_kg, length_cm, width_cm, height_cm = extract_dimensions(sp)

        return ProductDTO(
            asin=asin,
            marketplace=marketplace,
            title=extract_title(sp, fallback=asin),
            category=category,
            brand=extract_brand(sp),
            price=extract_price(sp),
            bsr_rank=extract_bsr(sp),
            rating=extract_rating(sp),
            review_count=extract_reviews(sp),
            weight_kg=weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            main_image_url=extract_image(sp),
            listing_url=url,
        )

    # --------------------------------------------------------
    def _save_cookies_from_session(self, session) -> None:
        """从 session.context 导出 cookies 写回文件。失败不应影响主流程。"""
        try:
            ctx = getattr(session, "context", None)
            if ctx is None:
                return
            cookies = ctx.cookies()
            if cookies:
                save_cookies(cookies, self.cookies_path)
        except Exception as e:
            logger.debug(f"[scrapling] 导出 cookies 失败: {e}")

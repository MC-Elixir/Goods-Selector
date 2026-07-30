"""
Amazon Best Seller Playwright 爬虫
====================================

无需 API Key，用 Playwright 浏览器直接爬取 Amazon BSR 页面。

字段提取逻辑与 amazon_scrapling.py 100% 一致（共享 crawlers/_amazon_extractors.py），
只是用 Playwright 的 query_selector / inner_text 替代 Scrapling 的 Adaptor.css。

限速：产品详情页间隔 2–5 秒随机延时，避免触发反爬。
验证码检测：遇到 Robot Check 自动停止并返回已收集数据。

用法：
    scraper = AmazonPlaywrightScraper()
    products = scraper.scrape_best_sellers("Home & Kitchen", limit=50)
"""
from __future__ import annotations

import math
import random
import time

from loguru import logger

from crawlers._amazon_extractors import (
    extract_amazon_detail,
    is_captcha,
    parse_bsr_page,
)
from crawlers._amazon_page import PlaywrightPage
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
            ctx.add_cookies([
                {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"},
                {"name": "lc-main",    "value": "en_US", "domain": ".amazon.com", "path": "/"},
            ])
            page = ctx.new_page()
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
                pp = PlaywrightPage(page)
                if is_captcha(pp):
                    logger.warning(f"[playwright] 遇到验证码，已停止（已收集 {len(asins)} 个）")
                    break
                page.wait_for_timeout(1500)
                new = parse_bsr_page(pp)
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

    # --------------------------------------------------------
    def _scrape_product(
        self, page, base_url: str, asin: str, marketplace: str, category: str
    ) -> ProductDTO:
        """爬取单个产品详情页，返回 ProductDTO。"""
        url = f"{base_url}/dp/{asin}?language=en_US&currency=USD"
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        pp = PlaywrightPage(page)
        if is_captcha(pp):
            raise RuntimeError("验证码页面")
        page.wait_for_timeout(random.randint(800, 1500))

        product = ProductDTO(
            asin=asin,
            marketplace=marketplace,
            title=asin,
            category=category,
            listing_url=url,
        )
        from crawlers.amazon_search import apply_detail_evidence
        return apply_detail_evidence(product, extract_amazon_detail(pp, source_ref=url))

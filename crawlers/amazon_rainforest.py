"""
Rainforest API 客户端
======================
REST API，按次计费，无需安装 SDK。

环境变量：
    RAINFOREST_API_KEY

文档：https://www.rainforestapi.com/docs
费率：约 $0.001/次，按量付费，适合低频使用。

类目 URL 直接用 Amazon BSR 页面 URL 传入 Rainforest，
比 Keepa 的数字 ID 更直观。
"""
from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from crawlers.amazon_bsr import ProductDTO

_BASE_URL = "https://api.rainforestapi.com/request"
_MARKETPLACE_DOMAINS = {
    "US": "amazon.com",
    "UK": "amazon.co.uk",
    "DE": "amazon.de",
    "JP": "amazon.co.jp",
}

# Amazon 类目 BSR 页面 URL（Rainforest 直接传 URL）
_CATEGORY_BSR_URLS: dict[str, str] = {
    "Home & Kitchen":           "https://www.amazon.com/Best-Sellers/zgbs/home-garden/",
    "Electronics":              "https://www.amazon.com/Best-Sellers/zgbs/electronics/",
    "Toys & Games":             "https://www.amazon.com/Best-Sellers/zgbs/toys-and-games/",
    "Beauty & Personal Care":   "https://www.amazon.com/Best-Sellers/zgbs/beauty/",
    "Clothing":                 "https://www.amazon.com/Best-Sellers/zgbs/clothing-shoes-jewelry/",
    "Sports & Outdoors":        "https://www.amazon.com/Best-Sellers/zgbs/sporting-goods/",
    "Baby":                     "https://www.amazon.com/Best-Sellers/zgbs/baby-products/",
    "Books":                    "https://www.amazon.com/Best-Sellers/zgbs/books/",
    "Health & Household":       "https://www.amazon.com/Best-Sellers/zgbs/hpc/",
    "Tools & Home Improvement": "https://www.amazon.com/Best-Sellers/zgbs/hi/",
    "Office Products":          "https://www.amazon.com/Best-Sellers/zgbs/office-products/",
    "Pet Supplies":             "https://www.amazon.com/Best-Sellers/zgbs/pet-supplies/",
    "Automotive":               "https://www.amazon.com/Best-Sellers/zgbs/automotive/",
}


class RainforestClient:
    """Rainforest API 客户端。"""

    def __init__(self, api_key: Optional[str] = None):
        self._key = api_key or settings.rainforest_api_key
        if not self._key:
            raise ValueError("RAINFOREST_API_KEY 未配置，请在 .env 中设置")

    # --------------------------------------------------------
    def get_best_sellers(
        self,
        category: str,
        limit: int = 100,
        marketplace: str = "US",
    ) -> list[ProductDTO]:
        bsr_url = _CATEGORY_BSR_URLS.get(category)
        if not bsr_url:
            raise ValueError(
                f"未找到类目 {category!r} 的 BSR URL，"
                f"可用类目：{list(_CATEGORY_BSR_URLS.keys())}"
            )

        domain = _MARKETPLACE_DOMAINS.get(marketplace, "amazon.com")
        products: list[ProductDTO] = []
        page = 1

        while len(products) < limit:
            try:
                raw = self._fetch_bestsellers_page(bsr_url, domain, page)
                items = raw.get("bestsellers") or []
                if not items:
                    break
                for item in items:
                    if len(products) >= limit:
                        break
                    try:
                        products.append(_rainforest_to_dto(item, category, marketplace))
                    except Exception as e:
                        logger.debug(f"[rainforest] 解析失败，跳过: {e}")
                page += 1
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"[rainforest] 第 {page} 页失败: {e}")
                break

        logger.info(f"[rainforest] 完成，共 {len(products)} 个产品")
        return products

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def _fetch_bestsellers_page(self, url: str, domain: str, page: int) -> dict:
        params = {
            "api_key": self._key,
            "type": "bestsellers",
            "url": url,
            "amazon_domain": domain,
            "page": page,
        }
        resp = requests.get(_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()


# ============================================================
# Rainforest 响应 → ProductDTO
# ============================================================
def _rainforest_to_dto(item: dict, category: str, marketplace: str) -> ProductDTO:
    asin = item.get("asin", "")

    # 价格（多种格式）
    price = None
    price_raw = item.get("price") or {}
    if isinstance(price_raw, dict):
        price = price_raw.get("value")
    elif isinstance(price_raw, (int, float)):
        price = float(price_raw)

    rating = item.get("rating")
    reviews = item.get("ratings_total")

    # 图片
    img = None
    images = item.get("images") or []
    if images:
        img = images[0].get("link") if isinstance(images[0], dict) else images[0]
    elif item.get("image"):
        img = item["image"]

    return ProductDTO(
        asin=asin,
        marketplace=marketplace,
        title=item.get("title", ""),
        category=category,
        brand=item.get("brand"),
        price=float(price) if price else None,
        bsr_rank=item.get("bestseller_rank"),
        rating=float(rating) if rating else None,
        review_count=int(reviews) if reviews else None,
        main_image_url=img,
        listing_url=item.get("link") or f"https://www.amazon.com/dp/{asin}",
        raw_data={"source": "rainforest"},
    )

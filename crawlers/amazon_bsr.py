"""
Amazon Best Seller 数据采集层
==============================

统一入口：crawl_best_sellers(category, limit, marketplace, backend)

backend 选项：
    "auto"        根据已配置的 Key 自动选择（playwright → keepa → rainforest）
    "playwright"  无需 API Key，Playwright 浏览器爬取（需安装 playwright）
    "keepa"       Keepa API（需 KEEPA_API_KEY，$19/月起，数据最全）
    "rainforest"  Rainforest API（需 RAINFOREST_API_KEY，按次计费）

ProductDTO 是各后端的统一输出 DTO，属性名与 ORM Product 模型完全对应。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from loguru import logger

from config.settings import settings


# ============================================================
# 统一 DTO（各后端输出相同结构）
# ============================================================
@dataclass
class ProductDTO:
    asin: str
    marketplace: str
    title: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[float] = None
    bsr_rank: Optional[int] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    review_velocity_30d: Optional[int] = None   # 30 天评论增速
    weight_kg: Optional[float] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    main_image_url: Optional[str] = None
    listing_url: Optional[str] = None
    raw_data: dict = field(default_factory=dict)


# ============================================================
# 统一入口
# ============================================================
Backend = Literal["auto", "scrapling", "playwright", "keepa", "rainforest"]


def crawl_best_sellers(
    category: str,
    limit: int = 100,
    marketplace: str = "US",
    backend: Backend = "auto",
) -> list[ProductDTO]:
    """抓取 Amazon Best Sellers，返回 ProductDTO 列表。

    Args:
        category    Amazon 一级类目名，如 "Home & Kitchen"
        limit       抓取产品数量
        marketplace 站点代码：US / UK / DE / JP
        backend     数据后端，"auto" 时按以下优先级选择：
                    scrapling（默认，无 Key 即可）→ keepa（有 Key）→
                    rainforest（有 Key）→ playwright（兜底）
    """
    resolved = _resolve_backend(backend)
    logger.info(f"[crawl] backend={resolved} category={category!r} limit={limit}")

    if resolved == "scrapling":
        from crawlers.amazon_scrapling import AmazonScraplingScraper
        return AmazonScraplingScraper().scrape_best_sellers(category, limit, marketplace)

    if resolved == "playwright":
        from crawlers.amazon_playwright import AmazonPlaywrightScraper
        return AmazonPlaywrightScraper().scrape_best_sellers(category, limit, marketplace)

    if resolved == "keepa":
        from crawlers.amazon_keepa import KeepaClient
        return KeepaClient().get_best_sellers(category, limit, marketplace)

    if resolved == "rainforest":
        from crawlers.amazon_rainforest import RainforestClient
        return RainforestClient().get_best_sellers(category, limit, marketplace)

    raise ValueError(f"未知 backend: {resolved}")


def _resolve_backend(backend: Backend) -> str:
    if backend != "auto":
        return backend
    # auto：优先 scrapling（无需 Key，patchright 抗检测），有 API Key 时用 API
    if settings.keepa_api_key:
        return "keepa"
    if settings.rainforest_api_key:
        return "rainforest"
    return "scrapling"

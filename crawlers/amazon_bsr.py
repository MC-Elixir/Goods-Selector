"""
Amazon Best Seller 抓取
======================

输入：
    category    一级类目，如 "Home & Kitchen"
    limit       抓取数量，默认 100

输出：
    list[ProductDTO]  统一的产品 DTO

实现方式：
    优先用 Keepa API，失败 fallback 到 Rainforest

TODO:
    1. 接入 Keepa SDK
    2. 加缓存（diskcache）
    3. 异常重试（tenacity）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class ProductDTO:
    """跨爬虫统一的产品 DTO。"""
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
    review_velocity_30d: Optional[int] = None
    weight_kg: Optional[float] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    main_image_url: Optional[str] = None
    listing_url: Optional[str] = None
    raw_data: dict = field(default_factory=dict)


def crawl_best_sellers(
    category: str,
    limit: int = 100,
    marketplace: str = "US",
) -> list[ProductDTO]:
    """抓取 Best Seller 榜单。

    Returns:
        统一的 ProductDTO 列表
    """
    logger.info(f"[crawl] category={category} limit={limit} marketplace={marketplace}")
    raise NotImplementedError("接入 Keepa / Rainforest 后实现")

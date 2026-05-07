"""
卖家精灵（Sellersprite）API 客户端
==================================

API 文档（按官方为准）：
    https://www.sellersprite.com/cn/api-docs

环境变量：
    MJJL_API_KEY
    MJJL_API_BASE

接口暴露：
    MaijiajinglingClient.analyze_market(asin) -> MarketAnalysisDTO
    MaijiajinglingClient.keyword_research(keyword) -> KeywordDataDTO
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings


# ============================================================
# DTO
# ============================================================
@dataclass
class MarketAnalysisDTO:
    main_keyword: Optional[str] = None
    search_volume_monthly: Optional[int] = None
    keyword_difficulty: Optional[float] = None
    competing_listings: Optional[int] = None
    top10_revenue_share: Optional[float] = None
    avg_review_count_top10: Optional[int] = None
    avg_price_top10: Optional[float] = None
    opportunity_score: Optional[float] = None
    seasonality: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)


# ============================================================
# Client
# ============================================================
class MaijiajinglingClient:
    """卖家精灵 API 客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.mjjl_api_key
        self.base_url = (base_url or settings.mjjl_api_base).rstrip("/")
        if not self.api_key:
            logger.warning("MJJL_API_KEY 未配置")

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # --------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def analyze_market(self, asin: str, marketplace: str = "US") -> MarketAnalysisDTO:
        """以 ASIN 为输入，反查关键词 + 市场容量 + 头部集中度。"""
        raise NotImplementedError("接入卖家精灵 API")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def keyword_research(self, keyword: str, marketplace: str = "US") -> dict:
        """关键词研究：搜索量、难度、季节性。"""
        raise NotImplementedError("接入卖家精灵 API")

    def close(self) -> None:
        self._client.close()

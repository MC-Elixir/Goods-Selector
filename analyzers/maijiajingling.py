"""
卖家精灵（Sellersprite）API 客户端
==================================

API 文档：https://open.sellersprite.com/api/1
网关：https://api.sellersprite.com
认证方式：secret-key 请求头（非 Bearer Token）

环境变量：
    MJJL_API_KEY       卖家精灵 API 密钥
    MJJL_API_BASE      API 网关地址（可选，默认 https://api.sellersprite.com）

清单（本模块已对接的接口）：
  编号  名称                    MCP Code             方法
  ---   ----                   --------             ----
  3     ASIN 详情              asin_detail          asin_detail()
  26    BSR 销量预测           bsr_prediction       bsr_prediction()
  1     查竞品                 competitor_lookup    competitor_lookup()
  10    关键词选品             keyword_research     keyword_research()
  9     查产品类目             category_lookup      category_lookup()
  25    查评论                 review               review()
  56    ASIN 优惠趋势          asin_discount        asin_discount()
  -     剩余调用次数查询       -                    get_visits()

analyze_market() 编排：ASIN 详情 → BSR 预测 → 竞品分析 → 组装 MarketAnalysisDTO
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings


# ============================================================
# DTOs
# ============================================================

@dataclass
class MarketAnalysisDTO:
    """市场分析结果——由 analyze_market() 组合多个 API 产出。"""
    # ---- 基础信息 ----
    asin: str = ""
    marketplace: str = "US"
    brand: Optional[str] = None
    seller_name: Optional[str] = None
    title: Optional[str] = None

    # ---- 销量 ----
    bsr: Optional[int] = None
    bsr_category: Optional[str] = None  # 类目名称
    est_daily_sales: Optional[int] = None       # BSR 预测日销量
    est_monthly_sales: Optional[int] = None     # BSR 预测月销量

    # ---- 价格 / 评分 ----
    price: Optional[float] = None
    currency: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None

    # ---- 上架 ----
    available_date: Optional[datetime] = None
    has_a_plus: bool = False
    is_best_seller: bool = False
    is_amazon_choice: bool = False

    # ---- 竞品数据（从 competitor_lookup 汇总） ----
    competing_listings: Optional[int] = None
    avg_price_top10: Optional[float] = None
    avg_review_count_top10: Optional[int] = None
    top10_revenue_share: Optional[float] = None  # 头部集中度

    # ---- 关键词 ----
    main_keyword: Optional[str] = None
    search_volume_monthly: Optional[int] = None
    keyword_difficulty: Optional[float] = None
    opportunity_score: Optional[float] = None
    seasonality: dict = field(default_factory=dict)

    # ---- 原始返回 ----
    raw_data: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        """没有 ASIN 视为空结果。"""
        return bool(self.asin)


@dataclass
class AsinDetailDTO:
    """ASIN 详情 (API 3) 返回。"""
    asin: str = ""
    marketplace: str = ""
    asin_url: str = ""

    # 标识
    is_best_seller: bool = False
    is_amazon_choice: bool = False
    is_new_release: bool = False
    has_a_plus: bool = False
    has_video: bool = False

    # 品牌 / 卖家
    brand: Optional[str] = None
    brand_url: Optional[str] = None
    seller_name: Optional[str] = None
    seller_url: Optional[str] = None
    fulfilled_by_amazon: bool = False

    # 定价
    price: Optional[float] = None
    list_price: Optional[float] = None
    currency: Optional[str] = None

    # 评分
    rating: Optional[float] = None
    review_count: Optional[int] = None
    answered_count: Optional[int] = None

    # BSR
    bsr: Optional[int] = None
    bsr_category_id: Optional[str] = None
    bsr_category_name: Optional[str] = None

    # 详情
    title: Optional[str] = None
    description: Optional[str] = None
    bullet_points: list[str] = field(default_factory=list)
    available_date: Optional[datetime] = None
    main_image: Optional[str] = None
    images: list[str] = field(default_factory=list)
    dimensions: Optional[str] = None
    weight: Optional[str] = None

    # 类目
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    category_path: Optional[str] = None

    # 变体
    variation_count: Optional[int] = None
    parent_asin: Optional[str] = None

    raw: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.asin)


@dataclass
class BsrPredictionDTO:
    """BSR 销量预测 (API 26) 返回。"""
    marketplace: str = ""
    bsr: int = 0
    category_label: str = ""
    category_id: str = ""
    est_daily_sales: int = 0
    est_monthly_sales: int = 0
    items: list[dict] = field(default_factory=list)  # [{bsr, estDailySales, estMonthSales}, ...]

    def __bool__(self) -> bool:
        return self.est_monthly_sales > 0


@dataclass
class CompetitorItem:
    """竞品列表中的单条产品。"""
    asin: str = ""
    title: str = ""
    price: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    total_units: Optional[int] = None       # 月销量
    total_revenue: Optional[float] = None   # 月销额
    bsr: Optional[int] = None
    brand: Optional[str] = None
    seller_name: Optional[str] = None


# ============================================================
# Client
# ============================================================

class MaijiajinglingClient:
    """卖家精灵 API 客户端。

    用法：

        with MaijiajinglingClient() as client:
            detail = client.asin_detail("US", "B08GHW4TBS")
            pred = client.bsr_prediction("US", bsr=1024, category_id="11260432011")
            market = client.analyze_market("B08GHW4TBS", "US")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.mjjl_api_key
        # 不要带 /v1 后缀——httpx 会拼接完整路径
        self.base_url = (base_url or settings.mjjl_api_base).rstrip("/")

        # 如果 .env 里配了带 /v1 的地址，自动去掉避免双写
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]

        self._configured: bool = bool(self.api_key)
        if not self._configured:
            logger.warning("MJJL_API_KEY 未配置 — 所有 API 调用将跳过")

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "secret-key": self.api_key,
                "Content-Type": "application/json;charset=utf-8",
                "x-request-id": str(uuid4()),
            },
            timeout=30.0,
        )

    # --------------------------------------------------------
    # 公共方法：analyze_market（编排多个 API）
    # --------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def analyze_market(self, asin: str, marketplace: str = "US") -> MarketAnalysisDTO:
        """编排三个 API 产出市场分析结果。

        链式调用：
            1. ASIN 详情（API 3）      → 基础信息 + BSR + 类目
            2. BSR 预测（API 26）      → 日/月销量估计
            3. 查竞品（API 1）         → 竞品集中度
        """
        if not self._configured:
            logger.warning("MJJL_API_KEY 未配置，跳过市场分析")
            return MarketAnalysisDTO()

        # ---- 1. ASIN 详情 ----
        detail = self.asin_detail(marketplace, asin)
        if not detail:
            return MarketAnalysisDTO(asin=asin, marketplace=marketplace)

        dto = MarketAnalysisDTO(
            asin=detail.asin,
            marketplace=detail.marketplace,
            brand=detail.brand,
            seller_name=detail.seller_name,
            title=detail.title,
            bsr=detail.bsr,
            bsr_category=detail.bsr_category_name,
            price=detail.price or detail.list_price,
            currency=detail.currency,
            rating=detail.rating,
            review_count=detail.review_count,
            available_date=detail.available_date,
            has_a_plus=detail.has_a_plus,
            is_best_seller=detail.is_best_seller,
            is_amazon_choice=detail.is_amazon_choice,
        )

        # ---- 2. BSR 销量预测 ----
        if detail.bsr is not None and detail.bsr_category_id:
            try:
                pred = self.bsr_prediction(marketplace, detail.bsr, detail.bsr_category_id)
                if pred:
                    dto.est_daily_sales = pred.est_daily_sales
                    dto.est_monthly_sales = pred.est_monthly_sales
            except Exception as e:
                logger.debug(f"BSR 预测失败 asin={asin}: {e}")

        # ---- 3. 竞品分析 ----
        try:
            comp_data = self.competitor_lookup(
                marketplace=marketplace,
                asins=[asin],
                size=10,
            )
            items = comp_data.get("data", {}).get("items") or comp_data.get("data", {}).get("list") or []
            if items:
                prices = [i.get("price") or i.get("listPrice", {}).get("amount") for i in items if i.get("price") or (i.get("listPrice") or {}).get("amount")]
                reviews = [i.get("reviewCount") or i.get("review_count") or 0 for i in items]
                total_revenue = sum(
                    (i.get("totalRevenue") or i.get("total_revenue") or 0)
                    for i in items
                )
                if prices:
                    dto.avg_price_top10 = round(sum(prices) / len(prices), 2)
                if reviews:
                    dto.avg_review_count_top10 = round(sum(reviews) / len(reviews))
                dto.competing_listings = len(items)
                # 头部集中度：当前 ASIN 销额 ÷ 前10销额和
                target_revenue = items[0].get("totalRevenue") or items[0].get("total_revenue") or 0
                if total_revenue > 0 and target_revenue > 0:
                    dto.top10_revenue_share = round(target_revenue / total_revenue, 4)
        except Exception as e:
            logger.debug(f"竞品查询失败 asin={asin}: {e}")

        # 保留原始数据
        dto.raw_data = {"asin_detail": detail.raw}
        return dto

    # --------------------------------------------------------
    # 单 API 方法
    # --------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def asin_detail(self, marketplace: str, asin: str) -> AsinDetailDTO:
        """ASIN 详情（API 3）— GET /v1/asin/{marketplace}/{asin}"""
        if not self._configured:
            return AsinDetailDTO()

        resp = self._client.get(f"/v1/asin/{marketplace}/{asin}")
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"ASIN 详情 API 返回错误: {body.get('message')}")

        d = body.get("data") or {}
        badge = d.get("badge") or {}
        lp = d.get("listPrice") or {}
        bsr_cat = d.get("bsrCategory") or {}
        cat = d.get("category") or {}

        # 时间戳转 datetime
        avail_ts = d.get("availableDate")
        available_date = None
        if avail_ts:
            try:
                available_date = datetime.fromtimestamp(avail_ts / 1000, tz=timezone.utc)
            except (TypeError, OSError, ValueError):
                pass

        return AsinDetailDTO(
            asin=d.get("asin") or asin,
            marketplace=marketplace,
            asin_url=d.get("asinUrl") or "",
            is_best_seller=badge.get("bestSeller") == "Y",
            is_amazon_choice=badge.get("amazonChoice") == "Y",
            is_new_release=badge.get("newRelease") == "Y",
            has_a_plus=badge.get("ebc") == "Y",
            has_video=badge.get("video") == "Y",
            brand=d.get("brand"),
            brand_url=d.get("brandUrl"),
            seller_name=d.get("sellerName"),
            seller_url=d.get("sellerUrl"),
            fulfilled_by_amazon=d.get("fulfilledByAmazon") == "Y",
            price=d.get("price"),
            list_price=lp.get("amount"),
            currency=lp.get("currency"),
            rating=d.get("rating"),
            review_count=d.get("reviewCount"),
            answered_count=d.get("answeredCount"),
            bsr=d.get("bsr"),
            bsr_category_id=bsr_cat.get("id"),
            bsr_category_name=bsr_cat.get("name"),
            title=d.get("title") or d.get("productTitle"),
            description=d.get("description"),
            bullet_points=d.get("bulletPoints") or [],
            available_date=available_date,
            main_image=d.get("mainImage"),
            images=d.get("images") or [],
            dimensions=d.get("dimensions"),
            weight=d.get("weight"),
            category_id=cat.get("id"),
            category_name=cat.get("name"),
            category_path=cat.get("nodePath"),
            variation_count=d.get("variationCount"),
            parent_asin=d.get("parentAsin"),
            raw=d,
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def bsr_prediction(
        self,
        marketplace: str,
        bsr: int,
        category_id: str,
    ) -> BsrPredictionDTO:
        """BSR 销量预测（API 26）— GET /v1/sales/prediction/bsr"""
        if not self._configured:
            return BsrPredictionDTO()

        resp = self._client.get(
            "/v1/sales/prediction/bsr",
            params={"marketplace": marketplace, "bsr": bsr, "categoryId": category_id},
        )
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"BSR 预测 API 返回错误: {body.get('message')}")

        d = body.get("data") or {}
        return BsrPredictionDTO(
            marketplace=d.get("marketplace") or marketplace,
            bsr=d.get("bsr") or bsr,
            category_label=d.get("categoryLabel") or "",
            category_id=category_id,
            est_daily_sales=d.get("estDailySales") or 0,
            est_monthly_sales=d.get("estMonthSales") or 0,
            items=d.get("itemList") or [],
        )

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def competitor_lookup(
        self,
        marketplace: str,
        asins: Optional[list[str]] = None,
        keyword: Optional[str] = None,
        brand: Optional[str] = None,
        seller_name: Optional[str] = None,
        node_id_path: Optional[str] = None,
        month: Optional[str] = None,
        page: int = 1,
        size: int = 20,
        **extra_params,
    ) -> dict:
        """查竞品（API 1）— POST /v1/product/competitor-lookup

        返回原始 dict（结构较复杂，保持灵活）。
        """
        if not self._configured:
            return {"code": "SKIP", "data": {"items": []}}

        payload: dict[str, Any] = {
            "marketplace": marketplace,
            "page": page,
            "size": min(size, 100),
        }
        if month:
            payload["month"] = month
        if asins:
            payload["asins"] = asins
        if keyword:
            payload["keyword"] = keyword
        if brand:
            payload["brand"] = brand
        if seller_name:
            payload["sellerName"] = seller_name
        if node_id_path:
            payload["nodeIdPath"] = node_id_path
        payload.update(extra_params)

        resp = self._client.post("/v1/product/competitor-lookup", json=payload)
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"竞品查询 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def keyword_research(
        self,
        keyword: str,
        marketplace: str = "US",
        month: Optional[str] = None,
        min_searches: Optional[int] = None,
        max_searches: Optional[int] = None,
        min_purchases: Optional[int] = None,
        max_purchases: Optional[int] = None,
        min_purchase_rate: Optional[float] = None,
        max_purchase_rate: Optional[float] = None,
        departments: Optional[list[str]] = None,
        **extra_params,
    ) -> dict:
        """关键词选品（API 10）— POST /v1/keyword-research"""
        if not self._configured:
            return {"code": "SKIP", "data": {"items": []}}

        payload: dict[str, Any] = {
            "marketplace": marketplace,
            "keywords": keyword,
        }
        if month:
            payload["month"] = month
        if min_searches is not None:
            payload["minSearches"] = min_searches
        if max_searches is not None:
            payload["maxSearches"] = max_searches
        if min_purchases is not None:
            payload["minPurchases"] = min_purchases
        if max_purchases is not None:
            payload["maxPurchases"] = max_purchases
        if min_purchase_rate is not None:
            payload["minPurchaseRate"] = min_purchase_rate
        if max_purchase_rate is not None:
            payload["maxPurchaseRate"] = max_purchase_rate
        if departments:
            payload["departments"] = departments
        payload.update(extra_params)

        resp = self._client.post("/v1/keyword-research", json=payload)
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"关键词选品 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def category_lookup(
        self,
        marketplace: str,
        keyword: Optional[str] = None,
        parent_id: Optional[str] = None,
        depth: int = 2,
    ) -> dict:
        """查产品类目（API 9）— POST /v1/product/category-lookup"""
        if not self._configured:
            return {"code": "SKIP", "data": {"items": []}}

        payload: dict[str, Any] = {
            "marketplace": marketplace,
            "depth": min(depth, 3),
        }
        if keyword:
            payload["keyword"] = keyword
        if parent_id:
            payload["parentId"] = parent_id

        resp = self._client.post("/v1/product/category-lookup", json=payload)
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"类目查询 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def review(
        self,
        marketplace: str,
        asin: str,
        star_list: Optional[list[int]] = None,
        page: int = 1,
        size: int = 10,
    ) -> dict:
        """查评论（API 25）— POST /v1/review"""
        if not self._configured:
            return {"code": "SKIP", "data": {"items": []}}

        payload: dict[str, Any] = {
            "marketplace": marketplace,
            "asin": asin,
            "page": page,
            "size": min(size, 10),
        }
        if star_list:
            payload["starList"] = star_list

        resp = self._client.post("/v1/review", json=payload)
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"评论 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def asin_discount(
        self,
        marketplace: str,
        asin: str,
        month: Optional[str] = None,
    ) -> dict:
        """ASIN 优惠趋势（API 56）— POST /v1/discount/asin"""
        if not self._configured:
            return {"code": "SKIP", "data": {}}

        payload: dict[str, Any] = {"marketplace": marketplace, "asin": asin}
        if month:
            payload["month"] = month

        resp = self._client.post("/v1/discount/asin", json=payload)
        resp.raise_for_status()
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"优惠趋势 API 返回错误: {body.get('message')}")
        return body

    # --------------------------------------------------------
    # 额度查询
    # --------------------------------------------------------

    def get_visits(self) -> dict:
        """查询当前月份剩余调用次数。"""
        if not self._configured:
            return {"code": "SKIP", "message": "API key not configured"}

        resp = self._client.get("/v1/visits")
        resp.raise_for_status()
        return resp.json()

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MaijiajinglingClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

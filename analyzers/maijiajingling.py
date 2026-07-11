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

analyze_market() 编排：ASIN 详情 → BSR 预测 → 竞品分析 → 关键词选品 → 组装 MarketAnalysisDTO
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
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
    monthly_purchases: Optional[int] = None
    purchase_rate: Optional[float] = None
    keyword_difficulty: Optional[float] = None
    opportunity_score: Optional[float] = None
    seasonality: dict = field(default_factory=dict)

    # ---- 原始返回 ----
    raw_data: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        """没有 ASIN 视为空结果。"""
        return bool(self.asin)


@dataclass
class MarketEvidenceResult:
    status: str
    data: MarketAnalysisDTO | None
    missing_fields: list[str] = field(default_factory=list)
    error_code: str | None = None
    diagnostic: str | None = None


class MarketDataError(RuntimeError):
    """Stable, sanitized failure raised at the SellerSprite boundary."""

    def __init__(self, error_code: str, diagnostic: str):
        self.error_code = error_code
        self.diagnostic = diagnostic
        super().__init__(f"{error_code}: {diagnostic}")

    @classmethod
    def from_exception(cls, exc: BaseException) -> "MarketDataError":
        if isinstance(exc, cls):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return cls("TIMEOUT", "SellerSprite request timed out")
        if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
            return cls("MISSING_REQUIRED_DATA", "SellerSprite response was not valid JSON")
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                return cls("AUTH_REQUIRED", f"SellerSprite authentication failed ({status})")
            if status == 429:
                return cls("RATE_LIMITED", "SellerSprite rate limit reached")
            return cls("UPSTREAM_ERROR", f"SellerSprite HTTP failure ({status})")
        return cls("UPSTREAM_ERROR", f"SellerSprite request failed ({type(exc).__name__})")


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


def _choose_keyword(keyword: Optional[str], detail: AsinDetailDTO) -> Optional[str]:
    """选择关键词选品 API 的查询词，优先使用人工传入，其次用类目名。"""
    candidates = [
        keyword,
        detail.category_name,
        detail.bsr_category_name,
        detail.category_path.split(">")[-1].strip() if detail.category_path else None,
    ]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()[:120]
    return None


def _extract_keyword_metrics(body: dict) -> dict[str, Any]:
    """从关键词选品返回中提取评分需要的稳定字段。

    卖家精灵不同接口/版本的字段命名可能略有差异，这里只做宽松读取；
    若没有显式机会指数，则用搜索量、购买率、竞争度做一个保守估算。
    """
    items = _extract_items(body)
    if not items:
        return {}

    best = max(items, key=lambda i: _to_int(_pick(i, _SEARCH_VOLUME_KEYS)) or 0)
    search_volume = _to_int(_pick(best, _SEARCH_VOLUME_KEYS))
    difficulty = _to_float(_pick(best, _DIFFICULTY_KEYS))
    opportunity = _to_float(_pick(best, _OPPORTUNITY_KEYS))

    if opportunity is None:
        opportunity = _estimate_opportunity_score(best, search_volume, difficulty)

    return {
        "main_keyword": _pick(best, _KEYWORD_KEYS),
        "search_volume_monthly": search_volume,
        "monthly_purchases": _to_int(_pick(best, _PURCHASE_KEYS)),
        "purchase_rate": _to_float(_pick(best, _PURCHASE_RATE_KEYS)),
        "keyword_difficulty": difficulty,
        "opportunity_score": opportunity,
        "seasonality": _extract_seasonality(best),
    }


def _top_node_id(node_id_path: Optional[str]) -> Optional[str]:
    """Return the top-level numeric node id needed by BSR prediction."""
    if not node_id_path:
        return None
    first = str(node_id_path).split(":", 1)[0].strip()
    return first or None


_KEYWORD_KEYS = ("keyword", "keywords", "keywrod", "keywordText", "searchTerm", "phrase")
_SEARCH_VOLUME_KEYS = (
    "search",
    "searches",
    "searchVolume",
    "searchVolumeMonthly",
    "monthlySearches",
    "search_volume_monthly",
    "searchesMonthly",
)
_PURCHASE_KEYS = ("purchase", "purchases", "monthlyPurchases", "purchaseCount")
_DIFFICULTY_KEYS = (
    "keywordDifficulty",
    "difficulty",
    "competition",
    "competingProducts",
    "competingProductCount",
)
_OPPORTUNITY_KEYS = ("opportunityScore", "opportunity_score", "opportunity")
_PURCHASE_RATE_KEYS = ("purchaseRate", "purchase_rate", "conversionRate", "conversion_rate")


def _extract_items(body: dict) -> list[dict]:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)]
    if isinstance(data, dict):
        for key in ("items", "list", "records", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
        if data:
            return [data]
    return []


def _competitor_items(body: dict) -> list[dict]:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        for key in ("items", "list", "records", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
    if isinstance(data, list):
        return [i for i in data if isinstance(i, dict)]
    return []


def _item_float(item: dict, *keys: str) -> Optional[float]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("amount")
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _item_int(item: dict, *keys: str) -> Optional[int]:
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("amount")
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return None


def _pick(item: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        text = str(value).replace(",", "").strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100
        return float(text)
    except (TypeError, ValueError):
        return None


def _estimate_opportunity_score(
    item: dict,
    search_volume: Optional[int],
    difficulty: Optional[float],
) -> Optional[float]:
    if not search_volume:
        return None

    volume_score = min(search_volume / 10_000, 1.0)
    purchase_rate = _to_float(_pick(item, _PURCHASE_RATE_KEYS))
    purchase_score = min(purchase_rate, 1.0) if purchase_rate is not None else 0.5

    if difficulty is None:
        difficulty_score = 0.5
    elif difficulty > 1:
        difficulty_score = max(0.0, 1 - min(difficulty / 100_000, 1.0))
    else:
        difficulty_score = max(0.0, 1 - difficulty)

    return round(volume_score * 0.45 + purchase_score * 0.30 + difficulty_score * 0.25, 4)


def _extract_seasonality(item: dict) -> dict:
    trend = item.get("seasonality") or item.get("searchesTrend") or item.get("trend")
    if isinstance(trend, dict):
        return trend
    if isinstance(trend, list):
        values = [_to_int(v) for v in trend[:12]]
        return {
            f"month_{idx}": value
            for idx, value in enumerate(values, 1)
            if value is not None
        }
    return {}


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
        self._response_diagnostics: list[dict[str, str]] = []
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

    def _request(self, method: str, endpoint: str, **kwargs) -> tuple[dict, dict]:
        """Request JSON with stable errors and non-sensitive diagnostics."""
        try:
            response = self._client.request(method, endpoint, **kwargs)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise MarketDataError.from_exception(exc) from exc
        if not isinstance(body, dict):
            raise MarketDataError("MISSING_REQUIRED_DATA", "SellerSprite response was not an object")
        code = str(body.get("code") or "")
        message = str(body.get("message") or "")
        normalized = f"{code} {message}".lower()
        if any(token in normalized for token in ("invalid key", "invalid secret", "unauthorized", "forbidden")):
            raise MarketDataError("AUTH_REQUIRED", "SellerSprite credentials were rejected")
        if "rate" in normalized and ("limit" in normalized or "429" in normalized):
            raise MarketDataError("RATE_LIMITED", "SellerSprite rate limit reached")
        if code and code != "OK":
            raise MarketDataError("MISSING_REQUIRED_DATA", f"SellerSprite API returned code {code}")
        if "data" not in body:
            raise MarketDataError("MISSING_REQUIRED_DATA", "SellerSprite response omitted data")
        received_at = datetime.now(timezone.utc)
        safe_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return body, {
            "endpoint": endpoint,
            "response_timestamp": received_at.isoformat(),
            "response_hash": safe_hash,
        }

    def _send(self, method: str, endpoint: str, **kwargs):
        """Compatibility response helper used by existing DTO parsers."""
        try:
            response = getattr(self._client, method.lower())(endpoint, **kwargs)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise MarketDataError.from_exception(exc) from exc
        if not isinstance(body, dict):
            raise MarketDataError("MISSING_REQUIRED_DATA", "SellerSprite response was not an object")
        normalized = f"{body.get('code', '')} {body.get('message', '')}".lower()
        if any(token in normalized for token in ("invalid key", "invalid secret", "unauthorized", "forbidden")):
            raise MarketDataError("AUTH_REQUIRED", "SellerSprite credentials were rejected")
        if "rate" in normalized and ("limit" in normalized or "429" in normalized):
            raise MarketDataError("RATE_LIMITED", "SellerSprite rate limit reached")
        code = str(body.get("code") or "")
        if code and code != "OK":
            raise MarketDataError("MISSING_REQUIRED_DATA", f"SellerSprite API returned code {code}")
        if endpoint != "/v1/visits" and "data" not in body:
            raise MarketDataError("MISSING_REQUIRED_DATA", "SellerSprite response omitted data")
        self._response_diagnostics.append({
            "endpoint": endpoint,
            "response_timestamp": datetime.now(timezone.utc).isoformat(),
            "response_hash": hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        })
        return response

    def analyze_market_evidence(
        self,
        asin: str,
        marketplace: str = "US",
        keyword: Optional[str] = None,
    ) -> MarketEvidenceResult:
        if (marketplace or "US").upper() != "US":
            return MarketEvidenceResult(
                status="failed", data=None, error_code="UNSUPPORTED_MARKETPLACE",
                diagnostic="Amazon market evidence currently supports US only",
            )
        if not self._configured:
            return MarketEvidenceResult(
                status="failed", data=None, error_code="AUTH_REQUIRED",
                diagnostic="SellerSprite API key is not configured",
            )
        try:
            data = self.analyze_market(
                asin, marketplace=marketplace, keyword=keyword, strict=True
            )
        except Exception as exc:
            error = MarketDataError.from_exception(exc)
            return MarketEvidenceResult(
                status="failed", data=None, error_code=error.error_code,
                diagnostic=error.diagnostic,
            )
        if not data or not data.asin:
            return MarketEvidenceResult(
                status="failed", data=None, error_code="MISSING_REQUIRED_DATA",
                diagnostic="SellerSprite returned no market analysis",
            )
        required = (
            "est_monthly_sales", "competing_listings",
            "search_volume_monthly", "top10_revenue_share",
        )
        missing = [name for name in required if getattr(data, name, None) is None]
        return MarketEvidenceResult(
            status="partial" if missing else "success",
            data=data,
            missing_fields=missing,
        )

    # --------------------------------------------------------
    # 公共方法：analyze_market（编排多个 API）
    # --------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def analyze_market(
        self,
        asin: str,
        marketplace: str = "US",
        keyword: Optional[str] = None,
        strict: bool = False,
    ) -> MarketAnalysisDTO:
        """编排多个 API 产出市场分析结果。

        链式调用：
            1. ASIN 详情（API 3）      → 基础信息 + BSR + 类目
            2. BSR 预测（API 26）      → 日/月销量估计
            3. 查竞品（API 1）         → 竞品集中度
            4. 关键词选品（API 10）     → 搜索量 + 机会指数
        """
        if not self._configured:
            logger.warning("MJJL_API_KEY 未配置，跳过市场分析")
            return MarketAnalysisDTO()

        self._response_diagnostics = []
        dto = MarketAnalysisDTO(asin=asin, marketplace=marketplace)

        # ---- 1. ASIN 详情 ----
        detail = AsinDetailDTO(asin=asin, marketplace=marketplace)
        try:
            detail = self.asin_detail(marketplace, asin)
            if detail:
                dto.brand = detail.brand
                dto.seller_name = detail.seller_name
                dto.title = detail.title
                dto.bsr = detail.bsr
                dto.bsr_category = detail.bsr_category_name
                dto.price = detail.price or detail.list_price
                dto.currency = detail.currency
                dto.rating = detail.rating
                dto.review_count = detail.review_count
                dto.available_date = detail.available_date
                dto.has_a_plus = detail.has_a_plus
                dto.is_best_seller = detail.is_best_seller
                dto.is_amazon_choice = detail.is_amazon_choice
                dto.raw_data["asin_detail"] = detail.raw
        except Exception as e:
            if strict and isinstance(e, MarketDataError):
                raise
            dto.raw_data["asin_detail_error"] = str(e)
            logger.debug(f"ASIN 详情失败 asin={asin}: {e}")

        # ---- 2. BSR 销量预测 ----
        if detail.bsr is not None and detail.bsr_category_id:
            try:
                pred = self.bsr_prediction(marketplace, detail.bsr, detail.bsr_category_id)
                if pred:
                    dto.est_daily_sales = pred.est_daily_sales
                    dto.est_monthly_sales = pred.est_monthly_sales
                    dto.raw_data["bsr_prediction"] = {
                        "estDailySales": pred.est_daily_sales,
                        "estMonthSales": pred.est_monthly_sales,
                        "items": pred.items,
                    }
            except Exception as e:
                if strict and isinstance(e, MarketDataError):
                    raise
                logger.debug(f"BSR 预测失败 asin={asin}: {e}")

        # ---- 3. 竞品分析 ----
        try:
            comp_data = self.competitor_lookup(
                marketplace=marketplace,
                asins=[asin],
                size=10,
            )
            dto.raw_data["competitor_lookup"] = comp_data
            items = _competitor_items(comp_data)
            if items:
                prices = [
                    value for value in (
                        _item_float(i, "price", "listPrice", "buyBoxPrice", "averagePrice")
                        for i in items
                    )
                    if value is not None
                ]
                reviews = [
                    value for value in (
                        _item_int(i, "reviewCount", "review_count", "reviews", "ratings")
                        for i in items
                    )
                    if value is not None
                ]
                total_revenue = sum(
                    _item_float(i, "totalRevenue", "total_revenue", "monthlyRevenue", "revenue", "amzSales") or 0
                    for i in items
                )
                if prices:
                    dto.avg_price_top10 = round(sum(prices) / len(prices), 2)
                if reviews:
                    dto.avg_review_count_top10 = round(sum(reviews) / len(reviews))
                dto.competing_listings = len(items)
                # 头部集中度：当前 ASIN 销额 ÷ 前10销额和
                target_revenue = _item_float(
                    items[0],
                    "totalRevenue",
                    "total_revenue",
                    "monthlyRevenue",
                    "revenue",
                    "amzSales",
                ) or 0
                if total_revenue > 0 and target_revenue > 0:
                    dto.top10_revenue_share = round(target_revenue / total_revenue, 4)
                target = next(
                    (i for i in items if str(i.get("asin") or "").upper() == asin.upper()),
                    items[0],
                )
                dto.title = dto.title or target.get("title") or target.get("productTitle")
                dto.brand = dto.brand or target.get("brand")
                dto.seller_name = dto.seller_name or target.get("sellerName") or target.get("seller_name")
                dto.price = dto.price or _item_float(target, "price", "listPrice", "buyBoxPrice")
                dto.rating = dto.rating or _item_float(target, "rating", "ratingValue")
                dto.review_count = dto.review_count or _item_int(
                    target,
                    "reviewCount",
                    "review_count",
                    "reviews",
                    "ratings",
                )
                dto.bsr = dto.bsr or _item_int(target, "bsr", "bsrRank")
                monthly_units = _item_int(
                    target,
                    "units",
                    "amzUnit",
                    "totalUnits",
                    "total_units",
                    "monthlySales",
                    "monthly_sales",
                )
                if monthly_units is not None:
                    dto.est_monthly_sales = dto.est_monthly_sales or monthly_units
                    dto.est_daily_sales = dto.est_daily_sales or max(round(monthly_units / 30), 1)
        except Exception as e:
            if strict and isinstance(e, MarketDataError):
                raise
            logger.debug(f"竞品查询失败 asin={asin}: {e}")
            dto.raw_data["competitor_lookup_error"] = str(e)

        # ---- 4. 关键词选品 ----
        keyword_candidate = _choose_keyword(keyword, detail)
        if keyword_candidate:
            try:
                kw_data = self.keyword_research(
                    keyword=keyword_candidate,
                    marketplace=marketplace,
                )
                dto.raw_data["keyword_research"] = kw_data
                metrics = _extract_keyword_metrics(kw_data)
                dto.main_keyword = metrics.get("main_keyword") or keyword_candidate
                dto.search_volume_monthly = metrics.get("search_volume_monthly")
                dto.monthly_purchases = metrics.get("monthly_purchases")
                dto.purchase_rate = metrics.get("purchase_rate")
                dto.keyword_difficulty = metrics.get("keyword_difficulty")
                dto.opportunity_score = metrics.get("opportunity_score")
                dto.seasonality = metrics.get("seasonality") or {}
            except Exception as e:
                if strict and isinstance(e, MarketDataError):
                    raise
                logger.debug(f"关键词选品失败 asin={asin} keyword={keyword_candidate!r}: {e}")
                try:
                    trend_data = self.keyword_research_trends(
                        keyword=keyword_candidate,
                        marketplace=marketplace,
                    )
                    dto.raw_data["keyword_research_trends"] = trend_data
                    metrics = _extract_keyword_metrics(trend_data)
                    dto.main_keyword = metrics.get("main_keyword") or keyword_candidate
                    dto.search_volume_monthly = metrics.get("search_volume_monthly")
                    dto.monthly_purchases = metrics.get("monthly_purchases")
                    dto.purchase_rate = metrics.get("purchase_rate")
                    dto.seasonality = metrics.get("seasonality") or {}
                except Exception as trend_exc:
                    if strict and isinstance(trend_exc, MarketDataError):
                        raise
                    logger.debug(
                        f"关键词趋势失败 asin={asin} keyword={keyword_candidate!r}: {trend_exc}"
                    )

        if self._response_diagnostics:
            dto.raw_data["seller_sprite_diagnostics"] = list(self._response_diagnostics)
        return dto

    # --------------------------------------------------------
    # 单 API 方法
    # --------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def asin_detail(self, marketplace: str, asin: str) -> AsinDetailDTO:
        """ASIN 详情（API 3）— GET /v1/asin/{marketplace}/{asin}"""
        if not self._configured:
            return AsinDetailDTO()

        resp = self._send("GET", f"/v1/asin/{marketplace}/{asin}")
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"ASIN 详情 API 返回错误: {body.get('message')}")

        d = body.get("data") or {}
        if not d:
            raise MarketDataError("MISSING_REQUIRED_DATA", "SellerSprite ASIN detail omitted data")
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
            fulfilled_by_amazon=d.get("fulfilledByAmazon") == "Y" or d.get("fulfillment") == "FBA",
            price=d.get("price"),
            list_price=lp.get("amount"),
            currency=lp.get("currency"),
            rating=d.get("rating"),
            review_count=d.get("reviewCount") or d.get("reviews") or d.get("ratings"),
            answered_count=d.get("answeredCount"),
            bsr=d.get("bsr") or d.get("bsrRank"),
            bsr_category_id=bsr_cat.get("id") or _top_node_id(d.get("nodeIdPath")) or d.get("bsrId"),
            bsr_category_name=bsr_cat.get("name") or d.get("bsrLabel"),
            title=d.get("title") or d.get("productTitle"),
            description=d.get("description"),
            bullet_points=d.get("bulletPoints") or d.get("features") or [],
            available_date=available_date,
            main_image=d.get("mainImage") or d.get("imageUrl"),
            images=d.get("images") or [],
            dimensions=d.get("dimensions"),
            weight=d.get("weight"),
            category_id=cat.get("id") or d.get("nodeId"),
            category_name=cat.get("name") or d.get("nodeLabel"),
            category_path=cat.get("nodePath") or d.get("nodeLabelPath"),
            variation_count=d.get("variationCount") or d.get("variations"),
            parent_asin=d.get("parentAsin") or d.get("parent"),
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

        resp = self._send("GET",
            "/v1/sales/prediction/bsr",
            params={"marketplace": marketplace, "bsr": bsr, "categoryId": category_id},
        )
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

        resp = self._send("POST", "/v1/product/competitor-lookup", json=payload)
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

        resp = self._send("POST", "/v1/keyword-research", json=payload)
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"关键词选品 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def keyword_research_trends(
        self,
        keyword: str,
        marketplace: str = "US",
    ) -> dict:
        """关键词选品-趋势数据（API 11）— POST /v1/keyword-research/trends"""
        if not self._configured:
            return {"code": "SKIP", "data": []}

        resp = self._send("POST",
            "/v1/keyword-research/trends",
            json={"marketplace": marketplace, "keyword": keyword},
        )
        body: dict = resp.json()
        if body.get("code") != "OK":
            raise RuntimeError(f"关键词趋势 API 返回错误: {body.get('message')}")
        return body

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def category_lookup(
        self,
        marketplace: str,
        keyword: Optional[str] = None,
        parent_id: Optional[str] = None,
        depth: int = 2,
    ) -> dict:
        """查产品类目（API 9）— GET /v1/product/node"""
        if not self._configured:
            return {"code": "SKIP", "data": {"items": []}}

        params: dict[str, Any] = {
            "marketplace": marketplace,
        }
        if keyword:
            params["keyword"] = keyword
        if parent_id:
            params["nodeIdPath"] = parent_id

        resp = self._send("GET", "/v1/product/node", params=params)
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

        resp = self._send("POST", "/v1/review", json=payload)
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

        resp = self._send("POST", "/v1/discount/asin", json=payload)
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

        resp = self._send("GET", "/v1/visits")
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

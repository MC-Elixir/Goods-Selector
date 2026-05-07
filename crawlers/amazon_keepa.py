"""
Keepa API 客户端
================
通过 keepa Python SDK 获取 Amazon Best Sellers 数据。

依赖：
    pip install keepa

环境变量：
    KEEPA_API_KEY

Keepa 定价：https://keepa.com/#!api
  - 每次 best_sellers_query 消耗约 50 token
  - 每次 product query（含 stats）消耗约 10 token/产品
  - 250 token 包约 $19/月

类目 ID 来源：https://keepa.com/#!categorySearch（Domain=1 即 US）
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from crawlers.amazon_bsr import ProductDTO

# ============================================================
# US 站主要类目 ID（Keepa Domain=1）
# ============================================================
_KEEPA_CATEGORY_IDS: dict[str, int] = {
    "Home & Kitchen":           1055398,
    "Electronics":              172282,
    "Toys & Games":             165793011,
    "Beauty & Personal Care":   3760911,
    "Clothing":                 7141123011,
    "Sports & Outdoors":        3375251,
    "Baby":                     165796011,
    "Books":                    283155,
    "Health & Household":       3760901,
    "Tools & Home Improvement": 228013,
    "Automotive":               15684181,
    "Office Products":          1064954,
    "Pet Supplies":             2619534011,
    "Garden & Outdoor":         2972638011,
    "Musical Instruments":      11091801,
    "Industrial & Scientific":  384082011,
    "Video Games":              468642,
    "Grocery & Gourmet Food":   16310101,
}

# Keepa 数据数组索引（keepa.Product.csv 的列）
_IDX_PRICE         = 0    # 单位：美分
_IDX_RATING        = 16   # 1-50，除以 10 得星级
_IDX_REVIEW_COUNT  = 17

# 1 inch = 2.54 cm；Keepa 尺寸单位为 mm
_MM_TO_CM = 0.1
_G_TO_KG  = 0.001


# ============================================================
# Keepa 客户端
# ============================================================
class KeepaClient:
    """封装 Keepa Python SDK，提供与其他爬虫相同的接口。"""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.keepa_api_key
        if not key:
            raise ValueError("KEEPA_API_KEY 未配置，请在 .env 中设置")
        try:
            import keepa as _keepa
        except ImportError:
            raise ImportError("请先安装：pip install keepa")
        self._api = _keepa.Keepa(accesskey=key)
        logger.debug("KeepaClient 初始化完成")

    # --------------------------------------------------------
    def get_best_sellers(
        self,
        category: str,
        limit: int = 100,
        marketplace: str = "US",
    ) -> list[ProductDTO]:
        """获取指定类目的 Best Sellers 列表。"""
        domain = _marketplace_to_domain(marketplace)
        cat_id = _KEEPA_CATEGORY_IDS.get(category)
        if not cat_id:
            raise ValueError(
                f"未找到 Keepa 类目 ID for {category!r}，"
                f"可用类目：{list(_KEEPA_CATEGORY_IDS.keys())}"
            )

        # Step 1: 获取 BSR ASIN 列表
        logger.info(f"[keepa] 查询类目 {category}（id={cat_id}）Best Sellers...")
        asins = self._query_best_sellers(cat_id, domain, limit)
        logger.info(f"[keepa] 获取到 {len(asins)} 个 ASIN")

        # Step 2: 批量获取产品详情
        products = self._query_products(asins, domain, category)
        logger.info(f"[keepa] 产品详情解析完成，共 {len(products)} 个")
        return products

    # --------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def _query_best_sellers(self, cat_id: int, domain: int, limit: int) -> list[str]:
        result = self._api.best_sellers_query(category=cat_id, domain=domain)
        # result 是 ASIN 字符串列表
        return list(result)[:limit]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    def _query_products(
        self, asins: list[str], domain: int, category: str
    ) -> list[ProductDTO]:
        if not asins:
            return []
        # Keepa 建议每批 ≤ 100 个 ASIN
        batch_size = 100
        all_products: list[ProductDTO] = []
        for i in range(0, len(asins), batch_size):
            batch = asins[i: i + batch_size]
            try:
                raw = self._api.query(
                    batch,
                    domain=domain,
                    stats=90,      # 返回近 90 天统计
                    offers=0,      # 不查 offer（省 token）
                )
                for p in raw:
                    try:
                        all_products.append(_keepa_to_dto(p, category))
                    except Exception as e:
                        logger.debug(f"[keepa] 解析产品失败，跳过: {e}")
            except Exception as e:
                logger.warning(f"[keepa] 批量查询失败（{len(batch)} 个）: {e}")
        return all_products


# ============================================================
# Keepa 产品数据 → ProductDTO
# ============================================================
def _keepa_to_dto(p: dict, category: str) -> ProductDTO:
    asin: str = p.get("asin", "")

    # 价格：csv[0] 最新值，单位美分，-1 表示无数据
    price = None
    csv = p.get("csv") or []
    if csv and len(csv) > _IDX_PRICE:
        price_cents = _latest(csv[_IDX_PRICE])
        if price_cents and price_cents > 0:
            price = price_cents / 100.0

    # 评分 & 评论数
    rating = None
    review_count = None
    if len(csv) > _IDX_RATING:
        raw_rating = _latest(csv[_IDX_RATING])
        if raw_rating and raw_rating > 0:
            rating = raw_rating / 10.0
    if len(csv) > _IDX_REVIEW_COUNT:
        rc = _latest(csv[_IDX_REVIEW_COUNT])
        if rc and rc > 0:
            review_count = rc

    # BSR（主类目）
    bsr_rank = None
    sales_ranks = p.get("salesRanks") or {}
    if sales_ranks:
        # 取值最小的那个（主类目排名最靠前）
        min_rank = min(
            (v[-1] if isinstance(v, list) and v else v)
            for v in sales_ranks.values()
            if v
        )
        bsr_rank = int(min_rank) if min_rank else None

    # 尺寸重量（mm → cm，g → kg）
    weight_g    = p.get("packageWeight")    # grams
    height_mm   = p.get("packageHeight")   # mm
    length_mm   = p.get("packageLength")
    width_mm    = p.get("packageWidth")

    weight_kg   = weight_g  * _G_TO_KG  if weight_g  else None
    height_cm   = height_mm * _MM_TO_CM if height_mm else None
    length_cm   = length_mm * _MM_TO_CM if length_mm else None
    width_cm    = width_mm  * _MM_TO_CM if width_mm  else None

    # 主图
    images_csv: str = p.get("imagesCSV", "")
    main_image_url = None
    if images_csv:
        first_id = images_csv.split(",")[0].strip()
        if first_id:
            main_image_url = f"https://images-na.ssl-images-amazon.com/images/I/{first_id}"

    return ProductDTO(
        asin=asin,
        marketplace=_domain_to_marketplace(p.get("domainId", 1)),
        title=p.get("title", ""),
        category=category,
        subcategory=None,
        brand=p.get("brand"),
        price=price,
        bsr_rank=bsr_rank,
        rating=rating,
        review_count=review_count,
        weight_kg=weight_kg,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        main_image_url=main_image_url,
        listing_url=f"https://www.amazon.com/dp/{asin}",
        raw_data={"source": "keepa"},
    )


# ============================================================
# Helpers
# ============================================================

def _latest(series: Optional[list]) -> Optional[int]:
    """取 Keepa 时间序列（[ts, val, ts, val, ...]）的最新值。"""
    if not series or len(series) < 2:
        return None
    # 奇数索引为值
    val = series[-1]
    return val if val != -1 else None


def _marketplace_to_domain(marketplace: str) -> int:
    return {"US": 1, "UK": 2, "DE": 3, "JP": 5}.get(marketplace, 1)


def _domain_to_marketplace(domain_id: int) -> str:
    return {1: "US", 2: "UK", 3: "DE", 5: "JP"}.get(domain_id, "US")

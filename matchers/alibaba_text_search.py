"""
1688 关键词搜索客户端
====================
输入中文关键词列表，逐词搜索 1688，去重合并返回 SupplierDTO 列表。

认证方式与拍立淘完全相同（APP_KEY / APP_SECRET / ACCESS_TOKEN）。
体积重和交期字段由详情接口补充；如未调详情，交期默认填 None。

1688 开放平台文档：https://open.1688.com/
API 方法名：alibaba.china.trade.product.search
  （如方法名有变更，修改 _SEARCH_METHOD 常量即可）
"""
from __future__ import annotations

import hashlib
import time
from typing import Optional

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from matchers.alibaba_pailitao import SupplierDTO, md5_sign

# ============================================================
# 常量（按 1688 开放平台实际接口名修改）
# ============================================================
_SEARCH_METHOD = "alibaba.china.trade.product.search"
_PAGE_SIZE = 20          # 每次搜索取前 20 条
_MIN_SIMILARITY = 0.0    # 文字搜索无图片相似度，统一置 None


# ============================================================
# 1688 文字搜索客户端
# ============================================================
class Alibaba1688TextSearch:
    """按关键词搜索 1688 货源，返回 SupplierDTO 列表。"""

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        gateway: Optional[str] = None,
    ):
        self.app_key = app_key or settings.alibaba_app_key
        self.app_secret = app_secret or settings.alibaba_app_secret
        self.access_token = access_token or settings.alibaba_access_token
        self.gateway = (gateway or settings.alibaba_api_gateway).rstrip("/")

        if not self.app_key or not self.app_secret:
            logger.warning("Alibaba app key/secret 未配置，1688 搜索会失败")

        self._cache = _make_cache("text_search")

    # --------------------------------------------------------
    def search(
        self,
        keywords: list[str],
        top_k: int = 20,
    ) -> list[SupplierDTO]:
        """对多个关键词逐一搜索，去重合并，按月销量排序，返回前 top_k 条。

        Args:
            keywords  视觉分析器输出的 keywords_zh，从精准到宽泛
            top_k     最终返回数量上限
        """
        seen_offer_ids: set[str] = set()
        results: list[SupplierDTO] = []

        for kw in keywords:
            if len(results) >= top_k:
                break
            try:
                batch = self._search_one_keyword(kw)
                for dto in batch:
                    if dto.alibaba_offer_id not in seen_offer_ids:
                        seen_offer_ids.add(dto.alibaba_offer_id)
                        results.append(dto)
            except Exception as e:
                logger.warning(f"[1688] keyword={kw!r} 搜索失败: {e}")

        # 按月销量降序
        results.sort(key=lambda d: d.monthly_sales or 0, reverse=True)
        logger.info(f"[1688] 搜索完成，共 {len(results)} 条结果（关键词数={len(keywords)}）")
        return results[:top_k]

    # --------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _search_one_keyword(self, keyword: str) -> list[SupplierDTO]:
        cache_key = f"ts_{hashlib.md5(keyword.encode()).hexdigest()[:16]}"
        if self._cache is not None and cache_key in self._cache:
            logger.debug(f"[1688] cache hit keyword={keyword!r}")
            return self._cache[cache_key]

        params = self._build_params(
            method=_SEARCH_METHOD,
            extra={
                "keywords": keyword,
                "beginPage": 1,
                "pageSize": _PAGE_SIZE,
                "orderby": "monthlySales_desc",   # 按月销量排
            },
        )

        logger.debug(f"[1688] search keyword={keyword!r}")
        resp = requests.post(
            f"{self.gateway}/{_SEARCH_METHOD}/",  # gateway 已 rstrip("/")，需补一个 /
            data=params,
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
        _check_error(raw, keyword)

        dtos = _parse_search_response(raw)
        if self._cache is not None:
            self._cache.set(cache_key, dtos, expire=settings.cache_ttl_seconds)
        return dtos

    # --------------------------------------------------------
    def _build_params(self, method: str, extra: dict) -> dict:
        """构造带签名的请求参数。"""
        params: dict = {
            "method": method,
            "app_key": self.app_key,
            "timestamp": str(int(time.time() * 1000)),
            "format": "json",
            "v": "2",
            "sign_method": "md5",
            "access_token": self.access_token,
            **extra,
        }
        params["sign"] = md5_sign(params, self.app_secret)
        return params


# ============================================================
# 解析 1688 响应
# ============================================================
def _check_error(raw: dict, keyword: str) -> None:
    """检查 1688 API 错误，统一抛出 RuntimeError。"""
    if raw.get("success") is False or "error_code" in raw:
        code = raw.get("error_code", "unknown")
        msg = raw.get("error_message") or raw.get("message", "")
        raise RuntimeError(f"1688 API 错误 [{code}] keyword={keyword!r}: {msg}")


def _parse_search_response(raw: dict) -> list[SupplierDTO]:
    """将 1688 搜索结果解析为 SupplierDTO 列表。

    响应结构参考（不同 API 版本字段名可能略有差异）：
    {
      "result": {
        "offerList": [{
          "offerId": "...",
          "subject": "产品标题",
          "saleInfo": {
            "minOrderQuantity": 50,
            "priceRangeList": [{"startQuantity": 1, "price": 12.5}, ...]
          },
          "supplierInfo": {
            "supplierName": "...",
            "supplierUrl": "...",
            "isFactory": true
          },
          "productInfo": {"mainPictUrl": "..."},
          "tradeInfo": {"monthlyOrderNum": 300, "repeatPurchaseRate": 0.35}
        }]
      }
    }
    """
    offer_list = (
        raw.get("result", {}).get("offerList")
        or raw.get("offerList")
        or []
    )

    dtos: list[SupplierDTO] = []
    for item in offer_list:
        try:
            dtos.append(_item_to_dto(item))
        except Exception as e:
            logger.debug(f"[1688] 解析 offer 失败，跳过: {e}")
    return dtos


def _item_to_dto(item: dict) -> SupplierDTO:
    offer_id = str(item.get("offerId", ""))
    subject = item.get("subject", "")

    sale = item.get("saleInfo") or {}
    moq = sale.get("minOrderQuantity") or None
    price_ranges = sale.get("priceRangeList") or []
    price_tiers = [
        {"qty": p.get("startQuantity", 1), "price": p.get("price", 0)}
        for p in price_ranges
    ]
    # 取阶梯价中位（第二档，没有则第一档）
    base_price = None
    if price_tiers:
        mid_idx = min(1, len(price_tiers) - 1)
        base_price = price_tiers[mid_idx].get("price")

    sup = item.get("supplierInfo") or {}
    trade = item.get("tradeInfo") or {}
    prod = item.get("productInfo") or {}

    return SupplierDTO(
        alibaba_offer_id=offer_id,
        supplier_name=sup.get("supplierName"),
        offer_url=f"https://detail.1688.com/offer/{offer_id}.html",
        offer_image_url=prod.get("mainPictUrl"),
        image_similarity=None,    # 文字搜索无图片相似度
        text_similarity=None,     # 可后续用关键词重合度计算
        moq=int(moq) if moq else None,
        base_price_cny=float(base_price) if base_price else None,
        price_tiers=price_tiers,
        monthly_sales=trade.get("monthlyOrderNum"),
        repeat_buyer_rate=trade.get("repeatPurchaseRate"),
        is_factory=bool(sup.get("isFactory", False)),
        delivery_days=None,       # 需调详情接口补充
        fba_ready=None,           # 需人工确认或详情接口
        title_cn=subject or None,
        raw_data={**item, "source": "alibaba_text_search"},
    )


# ============================================================
# Helpers
# ============================================================
def _make_cache(ns: str):
    if not settings.enable_api_cache:
        return None
    try:
        import diskcache as dc
        return dc.Cache(str(settings.cache_dir / ns))
    except ImportError:
        return None

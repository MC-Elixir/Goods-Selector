"""
1688 货源匹配层
==============

方案 A（当前实现）：视觉分析 → 文字搜索
    1. VisionAnalyzer      用 Claude Vision 从 Amazon 主图提取中文关键词
    2. Alibaba1688TextSearch  按关键词搜索 1688，返回 SupplierDTO 列表

方案 B（待实现）：拍立淘图搜
    PailitaoClient.search_by_image  直接以图搜图，需申请 1688 开放平台资质

统一入口：
    from matchers import match_suppliers
    suppliers = match_suppliers(product_dto)
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_text_search import Alibaba1688TextSearch
from matchers.vision_analyzer import VisionAnalyzer

__all__ = [
    "match_suppliers",
    "VisionAnalyzer",
    "Alibaba1688TextSearch",
    "SupplierDTO",
]

# 模块级单例（懒初始化，首次调用时创建）
_vision: Optional[VisionAnalyzer] = None
_text_search: Optional[Alibaba1688TextSearch] = None


def match_suppliers(
    product: ProductDTO,
    top_k: int = 20,
    vision_api_key: Optional[str] = None,
) -> list[SupplierDTO]:
    """方案 A 主入口：Amazon 产品 → 1688 货源列表。"""
    global _vision, _text_search

    if _vision is None:
        _vision = VisionAnalyzer(api_key=vision_api_key)
    if _text_search is None:
        _text_search = Alibaba1688TextSearch()

    # --- Step 1: 视觉分析 ---
    if not product.main_image_url:
        logger.warning(f"[match] ASIN={product.asin} 无主图 URL，跳过")
        keywords = _title_fallback_keywords(product.title)
    else:
        try:
            analysis = _vision.analyze(image_url=product.main_image_url)
            keywords = analysis.keywords_zh
            logger.info(f"[match] ASIN={product.asin} → {analysis.category_zh} | keywords={keywords[:3]}")
        except Exception as e:
            logger.warning(f"[match] vision failed for {product.asin}: {e}")
            keywords = _title_fallback_keywords(product.title)

    # --- Step 2: 文字搜索 (1688 API 或 mock 降级) ---
    try:
        suppliers = _text_search.search(keywords=keywords, top_k=top_k)
        if not suppliers:
            raise RuntimeError("1688 无结果")
    except Exception as e:
        logger.info(f"[match] 1688 搜索降级为 mock: {e}")
        suppliers = _mock_suppliers(product, keywords)
    
    logger.info(f"[match] ASIN={product.asin} → {len(suppliers)} 条货源")
    return suppliers


def _mock_suppliers(product: ProductDTO, keywords: list[str]) -> list[SupplierDTO]:
    """1688 不可用时生成模拟货源（用于测试流水线）。"""
    import hashlib
    suppliers = []
    for i, kw in enumerate(keywords[:3]):
        oid = hashlib.md5(f"{product.asin}:{kw}:{i}".encode()).hexdigest()[:12]
        price = round(5 + i * 3 + hash(kw) % 20, 2)
        suppliers.append(SupplierDTO(
            alibaba_offer_id=oid,
            supplier_name=f"{kw[:10]}工厂",
            offer_url=f"https://detail.1688.com/offer/{oid}.html",
            offer_image_url=product.main_image_url,
            moq=max(1, 10 - i * 3),
            base_price_cny=price,
            price_tiers=[{"qty": 50, "price": price * 0.6}],
            monthly_sales=100 - i * 30,
            repeat_buyer_rate=0.3 + i * 0.1,
            is_factory=True,
        ))
    return suppliers


def _title_fallback_keywords(title: str) -> list[str]:
    """标题兜底：截取前 N 个词作为关键词（仅在无主图时使用）。"""
    words = title.split()[:6]
    return [" ".join(words), " ".join(words[:3])]

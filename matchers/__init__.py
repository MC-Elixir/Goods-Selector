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
    """方案 A 主入口：Amazon 产品 → 1688 货源列表。

    流程：
        product.main_image_url
            ↓  VisionAnalyzer（Claude Vision）
        keywords_zh（中文关键词列表）
            ↓  Alibaba1688TextSearch
        list[SupplierDTO]（按月销量降序）

    Args:
        product       Amazon 产品 DTO，需要 main_image_url 或 title
        top_k         最多返回多少条货源
        vision_api_key  覆盖 .env 中的 ANTHROPIC_API_KEY
    """
    global _vision, _text_search

    if _vision is None:
        _vision = VisionAnalyzer(api_key=vision_api_key)
    if _text_search is None:
        _text_search = Alibaba1688TextSearch()

    # --- Step 1: 视觉分析 ---
    if not product.main_image_url:
        logger.warning(f"[match] ASIN={product.asin} 无主图 URL，跳过视觉分析，用标题兜底")
        keywords = _title_fallback_keywords(product.title)
    else:
        analysis = _vision.analyze(image_url=product.main_image_url)
        keywords = analysis.keywords_zh
        logger.info(
            f"[match] ASIN={product.asin} → {analysis.category_zh} | "
            f"keywords={keywords[:3]}"
        )

    # --- Step 2: 文字搜索 ---
    suppliers = _text_search.search(keywords=keywords, top_k=top_k)
    logger.info(f"[match] ASIN={product.asin} → {len(suppliers)} 条货源")
    return suppliers


def _title_fallback_keywords(title: str) -> list[str]:
    """标题兜底：截取前 N 个词作为关键词（仅在无主图时使用）。"""
    words = title.split()[:6]
    return [" ".join(words), " ".join(words[:3])]

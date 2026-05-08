"""
1688 货源匹配层
==============

降级链（自动按顺序尝试）：
  1. VisionAnalyzer → Alibaba1688TextSearch  视觉识别 + 1688 官方 API
  2. Alibaba1688PlaywrightMatcher            Playwright 图搜（需登录 Profile）
                                              → 自动降级关键词 Playwright 爬取
  3. mock                                    单元测试 / 完全离线兜底

统一入口：
    from matchers import match_suppliers
    suppliers = match_suppliers(product_dto)
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_playwright import Alibaba1688PlaywrightMatcher
from matchers.alibaba_text_search import Alibaba1688TextSearch
from matchers.vision_analyzer import VisionAnalyzer

__all__ = [
    "match_suppliers",
    "VisionAnalyzer",
    "Alibaba1688TextSearch",
    "Alibaba1688PlaywrightMatcher",
    "SupplierDTO",
]

# 模块级单例（懒初始化）
_vision: Optional[VisionAnalyzer] = None
_text_search: Optional[Alibaba1688TextSearch] = None
_playwright: Optional[Alibaba1688PlaywrightMatcher] = None


def match_suppliers(
    product: ProductDTO,
    top_k: int = 20,
    vision_api_key: Optional[str] = None,
) -> list[SupplierDTO]:
    """Amazon 产品 → 1688 货源列表。

    降级链：
      官方 API → Playwright（图搜 + 关键词）→ mock
    """
    global _vision, _text_search, _playwright

    # ── Step 1: 视觉分析（提取中文关键词） ──────────────────
    keywords: list[str] = []
    if not product.main_image_url:
        logger.warning(f"[match] ASIN={product.asin} 无主图 URL")
        keywords = _title_fallback_keywords(product.title)
    else:
        if _vision is None:
            _vision = VisionAnalyzer(api_key=vision_api_key)
        try:
            analysis = _vision.analyze(image_url=product.main_image_url)
            keywords = analysis.keywords_zh
            logger.info(
                f"[match] ASIN={product.asin} → {analysis.category_zh} "
                f"| keywords={keywords[:3]}"
            )
        except Exception as e:
            logger.warning(f"[match] vision 失败 ({product.asin}): {e}")
            keywords = _title_fallback_keywords(product.title)

    # ── Step 2a: 1688 官方 API ───────────────────────────────
    suppliers: list[SupplierDTO] = []
    if _text_search is None:
        _text_search = Alibaba1688TextSearch()
    try:
        suppliers = _text_search.search(keywords=keywords, top_k=top_k)
    except Exception as e:
        logger.info(f"[match] 1688 API 不可用 ({e})，尝试 Playwright")

    # ── Step 2b: Playwright 爬取（图搜 → 关键词） ────────────
    if not suppliers:
        if _playwright is None:
            _playwright = Alibaba1688PlaywrightMatcher()
        try:
            if product.main_image_url:
                suppliers = _playwright.search_by_image(
                    image_url=product.main_image_url,
                    keywords=keywords,
                    limit=top_k,
                )
            else:
                suppliers = _playwright.search_by_keyword(keywords, limit=top_k)
        except Exception as e:
            logger.warning(f"[match] Playwright 搜索失败 ({product.asin}): {e}")

    # ── Step 3: mock 兜底（仅最后手段） ─────────────────────
    if not suppliers:
        logger.info(f"[match] ASIN={product.asin} 全部方式无结果，使用 mock")
        suppliers = _mock_suppliers(product, keywords)

    logger.info(f"[match] ASIN={product.asin} → {len(suppliers)} 条货源")
    return suppliers


# ============================================================
# 内部工具
# ============================================================

def _mock_suppliers(product: ProductDTO, keywords: list[str]) -> list[SupplierDTO]:
    """所有方式均不可用时生成模拟货源（保证流水线不中断）。"""
    import hashlib
    suppliers = []
    for i, kw in enumerate(keywords[:3]):
        oid = hashlib.md5(f"{product.asin}:{kw}:{i}".encode()).hexdigest()[:12]
        price = round(5 + i * 3 + hash(kw) % 20, 2)
        suppliers.append(SupplierDTO(
            alibaba_offer_id=oid,
            supplier_name=f"{kw[:10]}工厂（mock）",
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
    """无主图时从英文标题截取关键词（效果有限，仅作应急）。"""
    words = title.split()[:6]
    return [" ".join(words), " ".join(words[:3])]

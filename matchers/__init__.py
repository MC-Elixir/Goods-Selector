"""
1688 货源匹配层
==============

降级链（自动按顺序尝试）：
  1. VisionAnalyzer → Alibaba1688TextSearch  视觉识别 + 1688 官方 API（需 key，默认未配）
  2. Alibaba1688ScraplingMatcher             Scrapling HTTP 路径（被 TMD 拦，默认禁用）
  3. Alibaba1688PlaywrightMatcher            Playwright 兜底（图搜 + 关键词）← 默认主路径
  4. mock                                    单元测试 / 完全离线兜底

匹配验证：
  搜索结果经 Verifier 启发式验证后过滤低匹配度货源。

统一入口：
    from matchers import match_suppliers
    suppliers = match_suppliers(product_dto)
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_playwright import Alibaba1688PlaywrightMatcher
from matchers.alibaba_text_search import Alibaba1688TextSearch
from matchers.vision_analyzer import VisionAnalyzer
from matchers.verifier import Alibaba1688Verifier, LLMVisualVerifier
from matchers.alibaba_result_cache import (
    circuit_is_open,
    load_cached_suppliers,
    make_cache_key,
    is_real_supplier,
    open_circuit,
    reset_circuit,
    save_cached_suppliers,
)

# Scrapling 优先（patchright 修补的 chromium + curl_cffi TLS 指纹伪装，更快更抗检测）
try:
    from matchers.alibaba_scrapling import Alibaba1688ScraplingMatcher
    _SCRAPLING_AVAILABLE = True
except ImportError:
    Alibaba1688ScraplingMatcher = None  # type: ignore
    _SCRAPLING_AVAILABLE = False

__all__ = [
    "match_suppliers",
    "VisionAnalyzer",
    "Alibaba1688TextSearch",
    "Alibaba1688ScraplingMatcher",
    "Alibaba1688PlaywrightMatcher",
    "SupplierDTO",
]

# 模块级单例（懒初始化，整条流水线复用）
_vision: Optional[VisionAnalyzer] = None
_text_search: Optional[Alibaba1688TextSearch] = None
_scrapling: Optional[Alibaba1688ScraplingMatcher] = None
_playwright: Optional[Alibaba1688PlaywrightMatcher] = None
_verifier: Optional[Alibaba1688Verifier] = None
_llm_verifier: Optional[LLMVisualVerifier] = None


def match_suppliers(
    product: ProductDTO,
    top_k: int = 20,
    vision_api_key: Optional[str] = None,
) -> list[SupplierDTO]:
    """Amazon 产品 → 1688 货源列表。

    降级链（默认仅走 Playwright；官方 API 需配 key、Scrapling 需 settings.enable_scrapling_matcher=True）：
      官方 API → Scrapling → Playwright（图搜 + 关键词）→ mock
    匹配验证：
      1. 启发式验证（默认）
      2. LLM 视觉验证（可选，通过 settings.enable_llm_verification 开启）

    提示：1688 搜索页强制要求登录态。如果 data/1688_cookies.json 不存在，
    浏览器路径会被 redirect 到 login.taobao.com，官方 API 也可能因权限返回 4xx。
    首次使用请跑 `python setup_1688_login.py` 完成一次手动登录。
    """
    global _vision, _text_search, _scrapling, _playwright, _verifier, _llm_verifier

    # ── Step 0: 从标题提取规格关键词 ──────────────────────
    dim_keywords = _extract_dimensional_keywords(
        product.title,
        product.weight_kg,
        (product.length_cm, product.width_cm, product.height_cm),
    )

    # ── Step 1: 视觉分析（提取中文关键词） ──────────────────
    analysis = None
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
                f"| keywords={keywords[:3]} | material={analysis.material}"
            )
        except Exception as e:
            logger.warning(f"[match] vision 失败 ({product.asin}): {e}")
            keywords = _title_fallback_keywords(product.title)

    # 合并规格关键词（前置，提高精准度）
    enriched_keywords = _build_enriched_keywords(dim_keywords, keywords)

    # ── Step 2a: 1688 官方 API ─────────────────────────────
    from config.settings import settings as _cfg
    cache_key = make_cache_key(product, enriched_keywords, top_k)
    cached_suppliers = load_cached_suppliers(
        cache_key,
        ttl_seconds=_cfg.alibaba_real_result_cache_ttl_seconds,
    )
    if cached_suppliers:
        return cached_suppliers[:top_k]

    suppliers: list[SupplierDTO] = []
    if _cfg.alibaba_app_key and _cfg.alibaba_app_secret:
        if _text_search is None:
            _text_search = Alibaba1688TextSearch()
        try:
            suppliers = _text_search.search(keywords=enriched_keywords, top_k=top_k)
        except Exception as e:
            logger.info(f"[match] 1688 API 不可用 ({e})，尝试 Scrapling")
    else:
        logger.debug(f"[match] ASIN={product.asin} 跳过 1688 API（未配置 key）")

    # ── Step 2b: Scrapling 爬取（默认禁用：HTTP header cookies 被 1688 TMD 拦、0 结果；
    #        直接降级 Playwright。待修好后 settings.enable_scrapling_matcher=True） ──
    if not suppliers and _SCRAPLING_AVAILABLE and _cfg.enable_scrapling_matcher:
        if _scrapling is None:
            _scrapling = Alibaba1688ScraplingMatcher(page_wait=5)
        try:
            if product.main_image_url:
                suppliers = _scrapling.search_by_image(
                    image_url=product.main_image_url,
                    keywords=enriched_keywords[:2],
                    limit=top_k,
                )
            else:
                suppliers = _scrapling.search_by_keyword(enriched_keywords[:2], limit=top_k)
        except Exception as e:
            logger.warning(f"[match] Scrapling 搜索失败 ({product.asin}): {e}，降级到 Playwright")

    # ── Step 2c: Playwright 兜底 ─────────────────────────────
    if not suppliers and not circuit_is_open():
        if _playwright is None:
            _playwright = Alibaba1688PlaywrightMatcher(page_wait=5)
        try:
            if product.main_image_url:
                suppliers = _playwright.search_by_image(
                    image_url=product.main_image_url,
                    keywords=enriched_keywords[:2],
                    limit=top_k,
                )
            else:
                suppliers = _playwright.search_by_keyword(enriched_keywords[:2], limit=top_k)
        except Exception as e:
            logger.warning(f"[match] Playwright 搜索失败 ({product.asin}): {e}")

    # ── Step 3: mock 兜底 ──────────────────────────────────
    if not suppliers:
        open_circuit(
            _cfg.alibaba_block_cooldown_seconds,
            reason="no real suppliers before mock fallback",
        )
        if not _cfg.alibaba_allow_mock_suppliers:
            logger.info(f"[match] ASIN={product.asin} no real 1688 suppliers; mock disabled")
            return []
        logger.info(f"[match] ASIN={product.asin} 全部方式无结果，使用 mock")
        suppliers = _mock_suppliers(product, enriched_keywords)

    # ── Step 4: 启发式匹配验证 ──────────────────────────────
    if _verifier is None:
        _verifier = Alibaba1688Verifier()
    suppliers = _verifier.verify(
        suppliers=suppliers,
        product=product,
        analysis=analysis,
        search_keywords=enriched_keywords,
    )

    # ── Step 5: LLM 视觉验证（可选）─────────────────────────
    from config.settings import settings as _cfg
    if getattr(_cfg, 'enable_llm_verification', False) and len(suppliers) > 1:
        try:
            if _llm_verifier is None:
                _llm_verifier = LLMVisualVerifier()
            suppliers = _llm_verifier.verify(suppliers, product, top_k=3)
            logger.info(f"[match] ASIN={product.asin} LLM 视觉验证完成")
        except Exception as e:
            logger.warning(f"[match] LLM 验证跳过 ({product.asin}): {e}")

    logger.info(f"[match] ASIN={product.asin} → {len(suppliers)} 条货源（已验证）")
    save_cached_suppliers(cache_key, suppliers)
    if any(is_real_supplier(s) for s in suppliers):
        reset_circuit()
    return suppliers


# ============================================================
# 规格关键词提取
# ============================================================

def _extract_dimensional_keywords(
    title: str,
    weight_kg: Optional[float] = None,
    dimensions_cm: tuple = (None, None, None),
) -> list[str]:
    """从 Amazon 英文标题提取规格关键词，转换为中文搜索词。

    示例：
        "24oz Stainless Steel Water Bottle" → ["750ml", "大容量"]
        "Pack of 6 Kitchen Towels"          → ["6条装", "6件套"]
    """
    t = title or ""
    keywords: list[str] = []

    # ── 容量词 ──────────────────────────────────────────
    # "24oz", "24 oz", "16.9 fl oz", "500ml", "1 gallon"
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(oz|fl\s*oz|ml|l|gallon|quart|pint)", t, re.I):
        value = float(m.group(1))
        unit = m.group(2).lower().replace(" ", "")

        ml = _to_ml(value, unit)
        if ml and 50 <= ml <= 100_000:
            if ml >= 1000:
                keywords.append(f"{ml / 1000:.0f}L" if ml % 1000 == 0 else f"{ml / 1000:.1f}L")
            else:
                keywords.append(f"{ml:.0f}ml")
            # 大容量 / 小容量标签
            if ml >= 500:
                keywords.append("大容量")
            elif ml <= 200:
                keywords.append("小容量")

    # ── 数量词 ──────────────────────────────────────────
    # "Pack of 6", "6-Pack", "12 Count", "Set of 4"
    for m in re.finditer(
        r"(?:pack\s+of|set\s+of|(\d+)\s*[- ]?pack|(\d+)\s*[- ]?count|(\d+)\s*[- ]?pcs)",
        t, re.I,
    ):
        nums = [g for g in m.groups() if g]
        if nums:
            n = int(nums[0])
            if 1 <= n <= 100:
                keywords.append(f"{n}件套")
                keywords.append(f"{n}条装")

    # ── 尺寸词（仅标记有尺寸概念）─────────────────────────
    # "10x10x5 inches", "12 inch", "30cm"
    dim_match = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(in|inch|inches|cm|mm)",
        t, re.I,
    )
    if dim_match:
        keywords.append("多尺寸规格")

    return keywords


def _to_ml(value: float, unit: str) -> Optional[float]:
    """单位转换为毫升。"""
    if unit in ("oz", "floz"):
        return value * 29.5735
    if unit == "ml":
        return value
    if unit == "l":
        return value * 1000
    if unit == "gallon":
        return value * 3785.41
    if unit == "quart":
        return value * 946.353
    if unit == "pint":
        return value * 473.176
    return None


def _build_enriched_keywords(dim_keywords: list[str], vision_keywords: list[str]) -> list[str]:
    """合并规格关键词和视觉关键词，规格词前置（更精准）。"""
    seen: set[str] = set()
    result: list[str] = []
    for kw in dim_keywords + vision_keywords:
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result


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
            title_cn=kw,
            match_quality_score=0.5,
            match_verification_method="mock",
        ))
    return suppliers


def _title_fallback_keywords(title: str) -> list[str]:
    """无主图时从英文标题截取关键词（效果有限，仅作应急）。"""
    words = title.split()[:6]
    return [" ".join(words), " ".join(words[:3])]

"""
1688 货源匹配层
==============

降级链（自动按顺序尝试）：
  1. Alibaba1688ScraplingMatcher            Scrapling HTTP 路径（被 TMD 拦，默认禁用）
  2. Alibaba1688PlaywrightMatcher           Playwright 主路径（图搜 + 关键词）
  3. mock                                   单元测试 / 完全离线兜底

遗留 Open Platform 客户端仅供显式诊断；生产匹配默认不会调用。

匹配验证：
  搜索结果经 Verifier 启发式验证后过滤低匹配度货源。

统一入口：
    from matchers import match_suppliers
    suppliers = match_suppliers(product_dto)
"""
from __future__ import annotations

import inspect
import re
from typing import Optional

from loguru import logger

from agent.cancellation import CancelCheck, CancellationRequested, raise_if_cancelled
from agent.manual_queue import enqueue_sourcing_block
from crawlers.amazon_bsr import ProductDTO
from domain.target_categories import (
    profile_from_product,
    understanding_from_target_profile,
)
from matchers.alibaba_detail import apply_1688_detail_to_supplier
from matchers.alibaba_pailitao import SupplierDTO
from matchers.alibaba_pifatuan import AlibabaPifatuanSearch
from matchers.alibaba_playwright import Alibaba1688PlaywrightMatcher
from matchers.alibaba_result_cache import (
    circuit_is_open,
    is_real_supplier,
    load_cached_offer_detail,
    load_cached_suppliers,
    make_cache_key,
    open_circuit,
    reset_circuit,
    save_cached_offer_detail,
    save_cached_suppliers,
)
from matchers.alibaba_text_search import Alibaba1688TextSearch
from matchers.imported_suppliers import find_imported_suppliers
from matchers.query_planner import generate_query_plan
from matchers.sourcing_slice import evaluate_prefetched_suppliers, serialize_sourcing_result
from matchers.verifier import Alibaba1688Verifier, LLMVisualVerifier, llm_eligible_suppliers
from matchers.vision_analyzer import VisionAnalyzer

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
    "AlibabaPifatuanSearch",
    "find_imported_suppliers",
]

# 模块级单例（懒初始化，整条流水线复用）
_vision: Optional[VisionAnalyzer] = None
_pifatuan_search: Optional[AlibabaPifatuanSearch] = None
_text_search: Optional[Alibaba1688TextSearch] = None
_scrapling: Optional[Alibaba1688ScraplingMatcher] = None
_playwright: Optional[Alibaba1688PlaywrightMatcher] = None
_verifier: Optional[Alibaba1688Verifier] = None
_llm_verifier: Optional[LLMVisualVerifier] = None


def match_suppliers(
    product: ProductDTO,
    top_k: int = 20,
    vision_api_key: Optional[str] = None,
    cancel_check: CancelCheck | None = None,
    market_keywords: list[str] | None = None,
    run_ref: str | None = None,
) -> list[SupplierDTO]:
    """Amazon 产品 → 1688 货源列表。

    降级链（默认仅走 Playwright；Scrapling 需 settings.enable_scrapling_matcher=True）：
      Scrapling → Playwright（图搜 + 关键词）→ mock
    匹配验证：
      1. 启发式验证（默认）
      2. LLM 视觉验证（可选，通过 settings.enable_llm_verification 开启）

    提示：1688 搜索页强制要求登录态。如果 data/1688_cookies.json 不存在，
    浏览器路径会被 redirect 到 login.taobao.com，官方 API 也可能因权限返回 4xx。
    首次使用请跑 `python setup_1688_login.py` 完成一次手动登录。
    """
    global _vision, _pifatuan_search, _text_search, _scrapling, _playwright, _verifier, _llm_verifier

    _check_cancel(cancel_check, "match start")

    raw_product = product.raw_data if isinstance(product.raw_data, dict) else {}
    product.raw_data = raw_product
    target_profile = profile_from_product(product)
    target_understanding = None
    target_queries = []
    query_execution: list[dict] = []
    if target_profile is not None:
        target_understanding = understanding_from_target_profile(product, target_profile)
        target_queries = generate_query_plan(target_understanding)
        raw_product["target_category_profile"] = target_profile.to_dict()
        raw_product["product_understanding"] = target_understanding.model_dump(mode="json")
        raw_product["target_query_plan"] = [query.model_dump(mode="json") for query in target_queries]

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
        _check_cancel(cancel_check, "vision analysis")
        if _vision is None:
            _vision = VisionAnalyzer(api_key=vision_api_key)
        try:
            analysis = _vision.analyze(image_url=product.main_image_url)
            _check_cancel(cancel_check, "vision analysis")
            keywords = analysis.keywords_zh
            logger.info(
                f"[match] ASIN={product.asin} → {analysis.category_zh} "
                f"| keywords={keywords[:3]} | material={analysis.material}"
            )
        except Exception as e:
            logger.warning(f"[match] vision 失败 ({product.asin}): {e}")
            keywords = _title_fallback_keywords(product.title)

    # SellerSprite Reverse-ASIN terms are translated into 1688 supply-chain
    # language before visual/title fallbacks. Specifications are modifiers and
    # are never issued as standalone searches.
    seller_keywords = _supply_chain_keywords(market_keywords or [])
    if target_queries:
        # The target-category contract owns the formal 1688 query plan. Vision
        # and SellerSprite terms remain audit context but cannot replace one of
        # the twelve deterministic, de-branded query types.
        enriched_keywords = [query.text for query in target_queries]
    else:
        enriched_keywords = _build_enriched_keywords(
            dim_keywords,
            [*seller_keywords, *keywords],
        )
        if analysis is not None:
            enriched_keywords = _build_enriched_keywords(
                enriched_keywords,
                [analysis.category_zh, analysis.title_zh],
            )

    # ── Step 2a: 1688 分销严选开放平台 ─────────────────────
    from config.settings import settings as _cfg
    if not enriched_keywords:
        reason = "no usable 1688 search keywords"
        logger.warning(f"[match] ASIN={product.asin} {reason}; stop automatic supplier search")
        _enqueue_manual_block(product, enriched_keywords, reason)
        return []

    cache_key = make_cache_key(product, enriched_keywords, top_k)
    suppliers: list[SupplierDTO] = []
    cached_suppliers = load_cached_suppliers(
        cache_key,
        ttl_seconds=_cfg.alibaba_real_result_cache_ttl_seconds,
    )
    if cached_suppliers:
        suppliers = cached_suppliers[:top_k]

    # Imported Open Platform test payloads are real 1688 candidates copied from
    # the user's console. Use them before browser/API scraping so blocked 1688
    # sessions can still produce verifiable supplier shortlists.
    if not suppliers:
        suppliers = find_imported_suppliers(enriched_keywords, top_k=top_k)
        if suppliers:
            logger.info(f"[match] ASIN={product.asin} 使用导入的 1688 候选 {len(suppliers)} 条")

    real_search_blocked = False
    if (
        not suppliers
        and _cfg.enable_alibaba_open_api_matcher
        and _cfg.alibaba_app_key
        and _cfg.alibaba_app_secret
        and _cfg.alibaba_access_token
    ):
        _check_cancel(cancel_check, "1688 pifatuan search")
        if _pifatuan_search is None:
            _pifatuan_search = AlibabaPifatuanSearch()
        try:
            suppliers = _pifatuan_search.search(keywords=enriched_keywords, top_k=top_k)
            _check_cancel(cancel_check, "1688 pifatuan search")
        except CancellationRequested:
            raise
        except Exception as e:
            logger.info(f"[match] 1688 分销严选 API 不可用 ({e})，尝试通用文字 API")

    # ── Step 2b: 1688 通用文字 API ─────────────────────────
    if (
        not suppliers
        and _cfg.enable_alibaba_open_api_matcher
        and _cfg.alibaba_app_key
        and _cfg.alibaba_app_secret
    ):
        _check_cancel(cancel_check, "1688 text search")
        if _text_search is None:
            _text_search = Alibaba1688TextSearch()
        try:
            suppliers = _text_search.search(keywords=enriched_keywords, top_k=top_k)
            _check_cancel(cancel_check, "1688 text search")
        except CancellationRequested:
            raise
        except Exception as e:
            logger.info(f"[match] 1688 API 不可用 ({e})，尝试 Scrapling")
    else:
        logger.debug(f"[match] ASIN={product.asin} 跳过 1688 Open API（默认禁用）")

    # ── Step 2c: Scrapling 爬取（默认禁用：HTTP header cookies 被 1688 TMD 拦、0 结果；
    #        直接降级 Playwright。待修好后 settings.enable_scrapling_matcher=True） ──
    if not suppliers and _SCRAPLING_AVAILABLE and _cfg.enable_scrapling_matcher:
        _check_cancel(cancel_check, "1688 scrapling search")
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
            _check_cancel(cancel_check, "1688 scrapling search")
        except CancellationRequested:
            raise
        except Exception as e:
            logger.warning(f"[match] Scrapling 搜索失败 ({product.asin}): {e}，降级到 Playwright")

    # ── Step 2d: Playwright 兜底 ───────────────────────────
    circuit_open = circuit_is_open()
    if not suppliers and circuit_open:
        real_search_blocked = True
        _enqueue_manual_block(product, enriched_keywords, "1688 search cooldown active")

    if not suppliers and not circuit_open:
        _check_cancel(cancel_check, "1688 playwright search")
        if _playwright is None:
            _playwright = Alibaba1688PlaywrightMatcher(page_wait=5)
        try:
            playwright_keywords = enriched_keywords if target_profile is not None else enriched_keywords[:5]
            exhaustive = bool(
                target_profile is not None
                and getattr(_cfg, "target_category_exhaustive_queries", True)
            )
            if product.main_image_url:
                suppliers = _call_playwright_search(
                    _playwright.search_by_image,
                    image_url=product.main_image_url,
                    keywords=playwright_keywords,
                    limit=top_k,
                    exhaustive=exhaustive,
                )
            else:
                suppliers = _call_playwright_search(
                    _playwright.search_by_keyword,
                    keywords=playwright_keywords,
                    limit=top_k,
                    exhaustive=exhaustive,
                )
            query_execution = list(getattr(_playwright, "last_query_attempts", []) or [])
            _check_cancel(cancel_check, "1688 playwright search")
        except CancellationRequested:
            raise
        except Exception as e:
            if "TMD" in str(e) or "验证码" in str(e):
                real_search_blocked = True
                open_circuit(_cfg.alibaba_block_cooldown_seconds, reason=str(e)[:200])
                _enqueue_manual_block(product, enriched_keywords, str(e)[:200])
            logger.warning(f"[match] Playwright 搜索失败 ({product.asin}): {e}")

    # ── Step 3: mock 兜底 ──────────────────────────────────
    if not suppliers:
        if real_search_blocked:
            logger.info(f"[match] ASIN={product.asin} real 1688 blocked; skip mock fallback")
            return _apply_target_strict_gate(
                product, [], target_understanding, target_queries,
                run_ref=run_ref, query_execution=query_execution,
            )
        if not _cfg.alibaba_allow_mock_suppliers:
            logger.info(f"[match] ASIN={product.asin} no real 1688 suppliers; mock disabled")
            return _apply_target_strict_gate(
                product, [], target_understanding, target_queries,
                run_ref=run_ref, query_execution=query_execution,
            )
        logger.info(f"[match] ASIN={product.asin} 全部方式无结果，使用 mock")
        suppliers = _mock_suppliers(product, enriched_keywords)

    # ── Step 4: 详情页补全（限量、缓存优先）──────────────────
    _check_cancel(cancel_check, "1688 detail enrichment")
    detail_limit = (
        int(getattr(_cfg, "target_category_detail_enrich_limit", 10) or 0)
        if target_profile is not None else None
    )
    suppliers = _enrich_supplier_details(
        suppliers,
        _cfg,
        cancel_check=cancel_check,
        limit_override=detail_limit,
    )
    _check_cancel(cancel_check, "1688 detail enrichment")

    # ── Step 5: 启发式匹配验证 ──────────────────────────────
    _check_cancel(cancel_check, "supplier verification")
    if _verifier is None:
        _verifier = Alibaba1688Verifier()
    gathered_suppliers = list(suppliers)
    verified_suppliers = _verifier.verify(
        suppliers=suppliers,
        product=product,
        analysis=analysis,
        search_keywords=enriched_keywords,
    )
    suppliers = gathered_suppliers if target_profile is not None else verified_suppliers
    for supplier in suppliers:
        supplier.raw_data["search_query_plan"] = {
            "queries": list(enriched_keywords),
            "market_keywords": list(market_keywords or []),
            "market_source": "sellersprite_browser_extension" if market_keywords else None,
        }

    # ── Step 6: LLM 视觉验证（可选）─────────────────────────
    if (
        getattr(_cfg, "enable_llm_verification", False)
        and target_profile is not None
        and suppliers
    ):
        try:
            _check_cancel(cancel_check, "target LLM visual verification")
            if _llm_verifier is None:
                _llm_verifier = LLMVisualVerifier()
            _verify_target_supplier_images(
                _llm_verifier,
                product,
                suppliers,
                top_k=int(getattr(_cfg, "target_category_llm_top_k", 5)),
                cancel_check=cancel_check,
            )
        except CancellationRequested:
            raise
        except Exception as exc:
            logger.warning(f"[match] target LLM 验证不可用 ({product.asin}): {exc}")
    elif getattr(_cfg, 'enable_llm_verification', False) and len(suppliers) > 1:
        eligible_for_llm = llm_eligible_suppliers(
            suppliers,
            min_match_quality=float(getattr(_cfg, "llm_verification_min_match_quality", 0.65)),
            min_spec_score=float(getattr(_cfg, "llm_verification_min_spec_score", 0.5)),
        )
        if not eligible_for_llm:
            logger.info(f"[match] ASIN={product.asin} LLM 视觉验证跳过：无通过规格与启发式门槛的货源")
        elif not product.main_image_url:
            logger.info(f"[match] ASIN={product.asin} LLM 视觉验证跳过：Amazon 产品无主图")
        else:
            try:
                _check_cancel(cancel_check, "LLM visual verification")
                if _llm_verifier is None:
                    _llm_verifier = LLMVisualVerifier()
                suppliers = _llm_verifier.verify(
                    suppliers,
                    product,
                    top_k=int(getattr(_cfg, "llm_verification_top_k", 2)),
                    eligible_suppliers=eligible_for_llm,
                    cancel_check=cancel_check,
                )
                _check_cancel(cancel_check, "LLM visual verification")
                logger.info(f"[match] ASIN={product.asin} LLM 视觉验证完成")
            except CancellationRequested:
                raise
            except Exception as e:
                logger.warning(f"[match] LLM 验证跳过 ({product.asin}): {e}")

    gathered_count = len(suppliers)
    save_cached_suppliers(cache_key, suppliers)
    suppliers = _apply_target_strict_gate(
        product,
        suppliers,
        target_understanding,
        target_queries,
        run_ref=run_ref,
        query_execution=query_execution,
    )
    logger.info(
        f"[match] ASIN={product.asin} → {len(suppliers)} 条货源（严格通过；原始候选 {gathered_count}）"
        if target_profile is not None
        else f"[match] ASIN={product.asin} → {len(suppliers)} 条货源（已验证）"
    )
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
        "Pack of 6 Kitchen Towels"          → ["6条装"]
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
        r"(?:pack\s+of\s*(\d+)|set\s+of\s*(\d+)|(\d+)\s*[- ]?pack|(\d+)\s*[- ]?count|(\d+)\s*[- ]?pcs|(\d+)\s*[- ]?pieces?(?:\s+set)?)",
        t, re.I,
    ):
        nums = [g for g in m.groups() if g]
        if nums:
            n = int(nums[0])
            if 1 <= n <= 100:
                lowered = t.lower()
                if any(term in lowered for term in ("bait station", "bait trap", "ant trap", "roach trap")):
                    keywords.append(f"{n}盒装")
                elif any(term in lowered for term in ("towel", "cloth", "wipe")):
                    keywords.append(f"{n}条装")
                elif "set of" in m.group(0).lower():
                    keywords.append(f"{n}件套")
                else:
                    keywords.append(f"{n}个装")

    # ── 尺寸词（仅标记有尺寸概念）─────────────────────────
    # "10x10x5 inches", "12 inch", "30cm"
    dim_match = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(in|inch|inches|cm|mm)",
        t, re.I,
    )
    if dim_match:
        keywords.append("多尺寸规格")

    return keywords


def _enqueue_manual_block(product: ProductDTO, keywords: list[str], reason: str) -> None:
    try:
        enqueue_sourcing_block(product, keywords=keywords, reason=reason, source="1688")
    except Exception as exc:
        logger.debug(f"[match] manual queue write failed asin={product.asin}: {exc}")


def _apply_target_strict_gate(
    product: ProductDTO,
    suppliers: list[SupplierDTO],
    understanding,
    queries: list,
    *,
    run_ref: str | None,
    query_execution: list[dict],
) -> list[SupplierDTO]:
    if understanding is None:
        return suppliers
    result = evaluate_prefetched_suppliers(
        product,
        suppliers,
        understanding,
        queries,
        run_ref=run_ref or f"adhoc:{product.asin}",
        query_execution=query_execution,
    )
    payload = serialize_sourcing_result(result)
    payload["amazon_completeness_basis"] = "target-category-contract-v1"
    product.raw_data["sourcing_evidence"] = payload
    return result.suppliers


def _verify_target_supplier_images(
    verifier: LLMVisualVerifier,
    product: ProductDTO,
    suppliers: list[SupplierDTO],
    *,
    top_k: int,
    cancel_check: CancelCheck | None,
) -> None:
    eligible = [
        supplier for supplier in suppliers
        if supplier.offer_image_url
        and (supplier.raw_data or {}).get("target_category_match", {}).get("decision") != "reject"
    ][:max(0, top_k)]
    for supplier in eligible:
        _check_cancel(cancel_check, "target LLM visual verification")
        try:
            visual = verifier.verify_pair(product, supplier)
            supplier.raw_data["visual_match"] = visual.model_dump(mode="json")
            if not visual.is_match:
                supplier.match_quality_score = 0.0
                supplier.match_verification_method = "llm_rejected"
        except CancellationRequested:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", "provider_failure") or "provider_failure")
            supplier.raw_data["visual_match"] = {
                "is_match": None,
                "classification_confidence": None,
                "source": "llm",
                "decision": "manual_review",
                "reason": code,
            }


def _call_playwright_search(search_func, *, exhaustive: bool, **kwargs):
    """Use exhaustive query execution when supported without breaking test doubles."""
    try:
        parameters = inspect.signature(search_func).parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if "exhaustive" in parameters or accepts_kwargs:
            kwargs["exhaustive"] = exhaustive
    except (TypeError, ValueError):
        pass
    return search_func(**kwargs)


def _enrich_supplier_details(
    suppliers: list[SupplierDTO],
    cfg,
    *,
    cancel_check: CancelCheck | None = None,
    limit_override: int | None = None,
) -> list[SupplierDTO]:
    """Fill sourcing evidence from 1688 detail pages without unbounded browsing."""
    global _playwright
    limit = (
        int(limit_override)
        if limit_override is not None
        else int(getattr(cfg, "alibaba_detail_enrich_limit", 0) or 0)
    )
    if limit <= 0 or not suppliers:
        return suppliers
    ttl_seconds = int(
        getattr(
            cfg,
            "alibaba_detail_cache_ttl_seconds",
            getattr(cfg, "alibaba_real_result_cache_ttl_seconds", 604800),
        )
        or 0
    )

    enriched = 0
    for idx, supplier in enumerate(list(suppliers)):
        _check_cancel(cancel_check, "1688 detail enrichment")
        if enriched >= limit:
            break
        if not _should_enrich_supplier_detail(supplier):
            continue
        offer_id = _supplier_offer_id(supplier)
        cached_detail = load_cached_offer_detail(offer_id, ttl_seconds) if offer_id else {}
        if cached_detail:
            suppliers[idx] = apply_1688_detail_to_supplier(supplier, cached_detail)
            suppliers[idx].raw_data["detail_enrichment"] = {
                "source": "cache",
                "offer_id": offer_id,
            }
            enriched += 1
            continue

        if not supplier.offer_url:
            continue
        try:
            _check_cancel(cancel_check, "1688 detail page")
            if _playwright is None:
                _playwright = Alibaba1688PlaywrightMatcher(page_wait=5)
            updated = _playwright.enrich_supplier_detail(supplier)
            _check_cancel(cancel_check, "1688 detail page")
            suppliers[idx] = updated
            detail = updated.raw_data.get("detail") or {}
            if detail:
                updated.raw_data["detail_enrichment"] = {
                    "source": "playwright",
                    "offer_id": offer_id,
                }
                if offer_id:
                    save_cached_offer_detail(offer_id, detail)
            enriched += 1
        except CancellationRequested:
            raise
        except Exception as exc:
            supplier.raw_data["detail_enrichment"] = {
                "source": "playwright",
                "offer_id": offer_id,
                "error": str(exc)[:200],
            }
            logger.info(f"[match] 1688 detail enrichment skipped offer={offer_id or supplier.offer_url}: {exc}")
    return suppliers


def _check_cancel(cancel_check: CancelCheck | None, context: str) -> None:
    raise_if_cancelled(cancel_check, context)


def _should_enrich_supplier_detail(supplier: SupplierDTO) -> bool:
    method = (supplier.match_verification_method or "").lower()
    source = str((supplier.raw_data or {}).get("source") or "").lower()
    if method == "mock" or source == "mock":
        return False
    if not supplier.alibaba_offer_id and not supplier.offer_url:
        return False
    return not (
        supplier.moq
        and supplier.delivery_days
        and supplier.product_dimensions_cm
        and supplier.product_weight_g
        and supplier.raw_data.get("risk_flags")
    )


def _supplier_offer_id(supplier: SupplierDTO) -> str:
    offer_id = str(supplier.alibaba_offer_id or "").strip()
    if offer_id:
        return offer_id
    match = re.search(r"/offer/(\d+)", supplier.offer_url or "")
    return match.group(1) if match else ""


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
    """合并视觉/标题关键词和规格关键词。

    搜索召回优先使用品类/功能词，数量词只做辅助。像 "12 Count"
    这类 pack 规格如果排在最前，会把 1688 搜索带到厨具/套装等泛结果。
    """
    cores = _dedupe_keywords([
        str(keyword or "").strip()
        for keyword in vision_keywords
        if not _is_spec_only_keyword(keyword)
    ])
    localized_cores = [core for core in cores if re.search(r"[\u4e00-\u9fff]", core)]
    if localized_cores:
        cores = localized_cores
    modifiers = []
    for keyword in dim_keywords:
        value = str(keyword or "").strip()
        if value and _is_spec_modifier(value) and value not in modifiers:
            modifiers.append(value)

    # A specification can narrow a semantic query, but never becomes the
    # semantic anchor itself (e.g. "12件套" previously recalled cookware).
    combined = [
        f"{core} {modifier}"
        for core in cores[:2]
        for modifier in modifiers[:2]
    ]
    # Search the product family first, then its spec-qualified variants. This
    # preserves broad same-family recall without ever searching a bare count.
    return _dedupe_keywords([*cores, *combined])


def _supply_chain_keywords(keywords: list[str]) -> list[str]:
    """Translate consumer-facing Reverse-ASIN terms into 1688 expressions."""
    result: list[str] = []
    rules = (
        (("ant trap", "ant bait", "ant killer", "bait station"), ("灭蚁饵剂", "蚂蚁诱饵盒")),
        (("mosquito repellent", "mosquito killer", "mosquito trap"), ("驱蚊用品", "灭蚊器")),
        (("cockroach bait", "roach bait", "roach killer"), ("杀蟑胶饵", "蟑螂诱饵盒")),
        (("insulated water bottle", "vacuum bottle", "thermos"), ("保温杯",)),
        (("storage box", "storage bin", "organizer box"), ("收纳盒",)),
        (("sheet set", "bed sheet", "bed sheets", "bedding set", "duvet cover"), ("床品套件",)),
        (("fitted sheet", "deep pocket", "sheet & pillowcase"), ("床笠",)),
        (("cooling sheets", "cooling bed sheets"), ("凉感床品",)),
        (("yoga mat", "exercise mat"), ("瑜伽垫",)),
        (("deck box", "outdoor storage", "patio storage"), ("户外储物箱", "庭院收纳箱")),
        (("storage shed", "garden shed"), ("户外储物棚", "庭院工具房")),
        (("patio heater", "outdoor heater", "terrace heater"), ("户外取暖器", "露台取暖器")),
        (("patio furniture", "outdoor furniture set", "conversation set"), ("户外家具套装", "庭院桌椅组合")),
        (("patio umbrella", "market umbrella"), ("庭院遮阳伞", "户外中柱伞")),
        (("cantilever umbrella", "offset umbrella"), ("户外侧立伞", "悬臂遮阳伞")),
        (("shade sail", "sun shade sail"), ("户外遮阳帆",)),
    )
    for keyword in keywords:
        value = str(keyword or "").strip()
        lowered = value.lower()
        translated = False
        for needles, replacements in rules:
            if any(needle in lowered for needle in needles):
                result.extend(replacements)
                translated = True
                break
        if re.search(r"[\u4e00-\u9fff]", value):
            result.append(value)
        elif not translated and value:
            # Retain the vendor term as lower-priority evidence when no safe
            # domain translation is known; do not invent a Chinese category.
            result.append(value)
    return _dedupe_keywords(result)


def _is_spec_modifier(keyword: str) -> bool:
    value = str(keyword or "").strip()
    return bool(re.fullmatch(
        r"\d+(?:\.\d+)?\s*(?:ml|l|oz|g|kg|cm|mm|英寸|件套|条装|盒装|只装|个装|支装|片装)",
        value,
        flags=re.I,
    ))


def _is_spec_only_keyword(keyword: str) -> bool:
    value = str(keyword or "").strip()
    return _is_spec_modifier(value) or value in {"大容量", "小容量", "多尺寸规格"}


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
            raw_data={"source": "mock"},
        ))
    return suppliers


def _title_fallback_keywords(title: str) -> list[str]:
    """Generate Chinese 1688 search keywords from an Amazon title when vision is unavailable."""
    raw = title or ""
    lowered = raw.lower()
    keywords: list[str] = []

    category_rules = (
        ("灭蚁饵剂", ("ant killer", "ant bait", "ant trap", "bait station")),
        ("驱蚊用品", ("mosquito repellent", "mosquito killer", "mosquito trap")),
        ("杀蟑胶饵", ("cockroach bait", "roach bait", "roach killer")),
        ("床品套件", ("sheet set", "bed sheet", "bed sheets", "bedding set", "fitted sheet", "duvet cover")),
        ("床笠", ("deep pocket", "fitted sheet")),
        ("保温杯", ("insulated water bottle", "vacuum bottle", "thermos", "travel mug")),
        ("水杯", ("water bottle", "tumbler", "sports bottle", "drinking bottle", "bottle")),
        ("瑜伽垫", ("yoga mat", "exercise mat", "fitness mat")),
        ("收纳盒", ("storage box", "storage bin", "organizer box", "organizer")),
        ("厨房垫", ("kitchen mat", "sink mat", "counter mat", "dish drying mat")),
        ("枕头", ("pillow", "neck pillow", "bed pillow")),
        ("手机支架", ("phone stand", "phone holder", "tablet stand")),
        ("折叠桌", ("folding table", "foldable table", "camping table")),
        ("户外储物箱", ("deck box", "outdoor storage", "patio storage", "garden storage")),
        ("户外储物棚", ("storage shed", "garden shed")),
        ("户外取暖器", ("patio heater", "outdoor heater", "terrace heater", "propane heater")),
        ("户外家具套装", ("patio furniture", "outdoor furniture set", "conversation set", "outdoor dining set")),
        ("庭院遮阳伞", ("patio umbrella", "market umbrella")),
        ("户外侧立伞", ("cantilever umbrella", "offset umbrella")),
        ("户外遮阳帆", ("shade sail", "sun shade sail")),
        ("毛巾", ("towel", "dish towel", "kitchen towel")),
    )
    for label, needles in category_rules:
        if any(_contains_fallback_term(lowered, needle) for needle in needles):
            keywords.append(label)

    material_prefix = ""
    if any(_contains_fallback_term(lowered, term) for term in ("stainless steel", "304 steel", "304 stainless")):
        material_prefix = "不锈钢"
        keywords.append("不锈钢")
    elif _contains_fallback_term(lowered, "silicone"):
        material_prefix = "硅胶"
        keywords.append("硅胶")
    elif any(_contains_fallback_term(lowered, term) for term in ("plastic", "pp", "abs")):
        material_prefix = "塑料"
        keywords.append("塑料")
    elif any(_contains_fallback_term(lowered, term) for term in ("aluminum", "aluminium")):
        material_prefix = "铝合金"
        keywords.append("铝合金")

    for category in list(keywords):
        if material_prefix and category not in {"不锈钢", "硅胶", "塑料", "铝合金"}:
            keywords.insert(0, f"{material_prefix}{category}")
            break

    feature_rules = (
        ("吸管", ("straw",)),
        ("带盖", ("with lid", "lid")),
        ("折叠", ("folding", "foldable")),
        ("防滑", ("non slip", "non-slip", "anti slip", "anti-slip")),
        ("防水", ("waterproof",)),
        ("可机洗", ("machine washable",)),
    )
    for label, needles in feature_rules:
        if any(_contains_fallback_term(lowered, needle) for needle in needles):
            keywords.append(label)

    words = [w.strip(" ,;:/()[]") for w in raw.split() if w.strip(" ,;:/()[]")]
    clean_words = [
        w for w in words
        if w.lower() not in {"with", "for", "and", "or", "the", "a", "an"}
    ]
    keywords.extend([
        " ".join(words[:8]),
        " ".join(clean_words[:7]),
        " ".join(words[:3]),
    ])
    return _dedupe_keywords(keywords)


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for keyword in keywords:
        value = str(keyword or "").strip()
        if value and not _is_noisy_search_keyword(value) and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _contains_fallback_term(text: str, term: str) -> bool:
    """Match ASCII fallback terms as words, avoiding ``solid`` -> ``lid``."""
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", text))


def _is_noisy_search_keyword(keyword: str) -> bool:
    value = str(keyword or "").strip()
    if not value:
        return True
    if value in {"大容量", "小容量", "多尺寸规格"}:
        return True
    parts = [part.strip(" ,;:/()[]") for part in value.split()]
    if len(parts) > 1 and all(_is_noisy_search_keyword(part) for part in parts):
        return True
    if re.fullmatch(r"B0[A-Z0-9]{8}", value, flags=re.I):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:ml|l|oz|fl\s*oz|gallon|quart|pint)", value, flags=re.I):
        return True
    if (
        re.fullmatch(r"[A-Z0-9]{2,12}", value, flags=re.I)
        and not re.search(r"[\u4e00-\u9fff]", value)
        and (re.search(r"\d", value) or value.isupper())
    ):
        return True
    return False

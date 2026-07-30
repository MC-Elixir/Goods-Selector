"""
主流程编排
==========

执行顺序：
    1. crawl     抓 BSR              → list[ProductDTO]
    2. match     1688 图文匹配        → list[SupplierDTO] per product
    3. profit    利润预测             → ProfitBreakdown per product（最优供应商）
    4. market    卖家精灵市场分析      → MarketAnalysisDTO per product
    5. score     评分 + 硬性筛选      → ScoreBreakdown per product
    6. filter    排序 + 取 Top N      → list[PipelineRecord]
    7. report    导出报告

阶段失败策略：
    crawl 失败 → abort 整条流水线
    其余阶段单产品失败 → 跳过该产品，记录错误，继续处理下一个
"""
from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from loguru import logger

from agent.cancellation import CancellationRequested
from analyzers.profit_model import InsufficientCostEvidence, ProfitBreakdown, predict_profit
from analyzers.scorer import ScoreBreakdown, ScoringEvidenceError, score_product
from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.models import MarketAnalysis, Product, ProfitSnapshot, RunLog, Score, Supplier
from db.session import session_scope
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.filters import rank_candidates
from reports.exporter import export_excel, export_json, export_markdown

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


class PipelineCancelled(RuntimeError):
    """Raised when a cooperative caller requests cancellation."""


class PipelineTimeout(RuntimeError):
    """Raised when a pipeline stage exceeds its configured budget."""


# ============================================================
# 数据容器
# ============================================================
@dataclass
class PipelineRecord:
    """单个产品在流水线中流转的数据容器。"""
    product: ProductDTO
    suppliers: list[SupplierDTO] = field(default_factory=list)
    profit: Optional[ProfitBreakdown] = None
    market: Optional[object] = None       # MarketAnalysisDTO
    score: Optional[ScoreBreakdown] = None
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def net_profit(self) -> float:
        return self.profit.net_profit if self.profit else 0.0

    @property
    def profit_margin(self) -> float:
        return self.profit.profit_margin if self.profit else 0.0

    @property
    def top_supplier_candidate_score(self) -> float:
        if not self.suppliers:
            return 0.0
        supplier = self.suppliers[0]
        values = [getattr(supplier, "candidate_score", None)]
        raw = getattr(supplier, "raw_data", None)
        if isinstance(raw, dict):
            values.append(raw.get("supplier_rank_score"))
            values.append(raw.get("supplier_candidate_score"))
        values.append(getattr(supplier, "match_quality_score", None))
        for value in values:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
        return 0.0


# ============================================================
# 主流水线
# ============================================================

def _run_pipeline_legacy(
    category: str,
    source_mode: str = "category",
    keyword: str | None = None,
    limit: int = 100,
    marketplace: str = "US",
    pipeline_version: str = "0.2.0",
    top_n: int = 20,
    export: bool = True,
    export_review_on_empty: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    stage_timeouts: dict[str, float] | None = None,
) -> int:
    """跑一次完整选品流水线，返回 RunLog id。

    Args:
        category    Amazon 一级类目
        source_mode category 或 keyword
        keyword     keyword 模式下的产品搜索词
        limit       抓取产品数量
        marketplace 站点
        top_n       最终输出候选品数量
        export      是否导出报告（Excel + Markdown + JSON）
    """
    site = (marketplace or "US").strip().upper()
    if site != "US":
        raise ValueError("marketplace is fixed to Amazon US")
    mode = (source_mode or "category").strip().lower()
    if mode not in {"category", "keyword"}:
        raise ValueError("source_mode must be category or keyword")
    source_query = (keyword or "").strip() if mode == "keyword" else (category or "").strip()
    if not source_query:
        raise ValueError("keyword is required" if mode == "keyword" else "category is required")

    with session_scope() as s:
        run = RunLog(
            pipeline_version=pipeline_version,
            category=category if mode == "category" else None,
            marketplace=site,
            started_at=datetime.utcnow(),
            status="running",
        )
        s.add(run)
        s.flush()
        run_id = run.id
        logger.info(f"[run #{run_id}] start | source={mode}:{source_query} limit={limit}")

    api_calls: dict = {
        "source_mode": mode,
        "source_query": source_query,
        "marketplace": site,
    }
    controls = _PipelineControls(
        run_id=run_id,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        stage_timeouts=stage_timeouts or _default_stage_timeouts(),
    )

    try:
        # === 1. crawl ===
        controls.progress("crawl", f"Crawling Amazon source: {source_query}")
        products = controls.call(
            "crawl",
            _collect_source_products,
            mode,
            source_query,
            limit,
            site,
        )
        _attach_source_metadata(products, mode, source_query)
        raw_product_count = len(products)
        products, product_duplicates_removed = _dedupe_products_by_asin(products)
        if mode == "keyword" and products:
            raw = products[0].raw_data if isinstance(products[0].raw_data, dict) else {}
            if raw.get("keyword_normalized"):
                api_calls["keyword_normalized"] = raw.get("keyword_normalized")
            if raw.get("keyword_warning"):
                api_calls["keyword_warning"] = raw.get("keyword_warning")
        api_calls["amazon_source"] = len(products)
        api_calls["amazon_source_raw"] = raw_product_count
        api_calls["amazon_duplicates_removed"] = product_duplicates_removed
        logger.info(
            f"[run #{run_id}] crawled {raw_product_count} products "
            f"({len(products)} unique, removed {product_duplicates_removed})"
        )
        _update_run(run_id, products_crawled=len(products))
        _persist_products(products)

        # === 2. match ===
        from matchers import match_suppliers
        records: list[PipelineRecord] = []
        matched = 0
        for index, p in enumerate(products, 1):
            controls.progress(
                "match",
                f"Matching suppliers for {p.asin} ({index}/{len(products)})",
                asin=p.asin,
                index=index,
                total=len(products),
            )
            try:
                sups = controls.call(
                    "match",
                    _call_match_suppliers,
                    match_suppliers,
                    p,
                    cancel_check,
                    run_ref=f"run:{run_id}",
                )
                matched += len(sups)
            except (PipelineCancelled, PipelineTimeout):
                raise
            except Exception as e:
                logger.warning(f"[run #{run_id}] match failed asin={p.asin}: {e}")
                sups = []
            _persist_suppliers_for_product(p, sups)
            records.append(PipelineRecord(product=p, suppliers=sups))

        api_calls["supplier_match_attempts"] = len(products)
        api_calls["vision_analyzer"] = len(products)
        logger.info(f"[run #{run_id}] matched {matched} suppliers")
        _update_run(run_id, suppliers_matched=matched)

        # === 3. profit ===
        calculated = 0
        supplier_duplicates_removed = 0
        for index, rec in enumerate(records, 1):
            controls.progress(
                "profit",
                f"Calculating profit for {rec.product.asin} ({index}/{len(records)})",
                asin=rec.product.asin,
                index=index,
                total=len(records),
            )
            if not rec.suppliers:
                continue
            try:
                supplier_count_before = len(rec.suppliers)
                rec.profit = controls.call(
                    "profit",
                    _rank_suppliers_by_profit,
                    rec.product,
                    rec.suppliers,
                )
                supplier_duplicates_removed += max(supplier_count_before - len(rec.suppliers), 0)
                if rec.profit is not None:
                    calculated += 1
                    _persist_profit_for_record(rec)
            except (PipelineCancelled, PipelineTimeout):
                raise
            except InsufficientCostEvidence as e:
                rec.rejection_reasons.extend(_evidence_rejection_reasons(e))
                logger.warning(
                    f"[run #{run_id}] profit insufficient asin={rec.product.asin}: {e}"
                )
            except Exception as e:
                logger.warning(f"[run #{run_id}] profit failed asin={rec.product.asin}: {e}")

        api_calls["supplier_duplicates_removed"] = supplier_duplicates_removed
        logger.info(f"[run #{run_id}] calculated {calculated} profit snapshots")
        _update_run(run_id, profits_calculated=calculated)

        # === 4. market ===
        market_cap = max(int(settings.mjjl_max_products_per_run or 0), 0)
        market_skipped_cap = max(len(records) - market_cap, 0) if records else 0
        if market_skipped_cap:
            api_calls["mjjl_skipped_cap"] = market_skipped_cap
            logger.info(
                f"[run #{run_id}] market analysis capped at {market_cap} products "
                f"(skipped {market_skipped_cap})"
            )
        if market_cap > 0:
            try:
                from analyzers.maijiajingling import MaijiajinglingClient
                with MaijiajinglingClient() as mjjl:
                    market_records = records[:market_cap]
                    for index, rec in enumerate(market_records, 1):
                        controls.progress(
                            "market",
                            f"Analyzing market for {rec.product.asin} ({index}/{len(market_records)})",
                            asin=rec.product.asin,
                            index=index,
                            total=len(market_records),
                        )
                        try:
                            rec.market = controls.call(
                                "market",
                                mjjl.analyze_market,
                                rec.product.asin,
                                site,
                                keyword=getattr(rec.product, "title", None) or source_query,
                            )
                            _persist_market_for_record(rec)
                            if getattr(mjjl, "_configured", False):
                                api_calls["mjjl"] = api_calls.get("mjjl", 0) + 1
                        except (PipelineCancelled, PipelineTimeout):
                            raise
                        except Exception as e:
                            logger.debug(f"[run #{run_id}] market skip asin={rec.product.asin}: {e}")
            except Exception:
                logger.info(f"[run #{run_id}] market analysis skipped (API not configured)")

        # === 5. score ===
        for index, rec in enumerate(records, 1):
            controls.progress(
                "score",
                f"Scoring {rec.product.asin} ({index}/{len(records)})",
                asin=rec.product.asin,
                index=index,
                total=len(records),
            )
            if rec.profit is None:
                continue
            try:
                rec.score = controls.call(
                    "score",
                    score_product,
                    product=rec.product,
                    profit_breakdown=rec.profit,
                    market_analysis=rec.market,
                    suppliers=rec.suppliers,
                )
                _persist_score_for_record(rec)
            except (PipelineCancelled, PipelineTimeout):
                raise
            except ScoringEvidenceError as e:
                rec.score = None
                rec.rejection_reasons.extend(_evidence_rejection_reasons(e))
                logger.warning(
                    f"[run #{run_id}] score insufficient asin={rec.product.asin}: {e}"
                )
            except Exception as e:
                logger.warning(f"[run #{run_id}] score failed asin={rec.product.asin}: {e}")

        # === 6. filter ===
        _finalize_sourcing_evidence(records)
        controls.progress("filter", f"Ranking {len(records)} records")
        ranked_candidates = rank_candidates(records, top_n=None)
        candidates, candidate_duplicates_removed = _dedupe_records_by_asin(ranked_candidates)
        if top_n:
            candidates = candidates[:top_n]
        api_calls["candidate_duplicates_removed"] = candidate_duplicates_removed
        logger.info(
            f"[run #{run_id}] {len(candidates)} candidates "
            f"(passed filter) out of {len(records)}"
        )
        _update_run(run_id, candidates_after_filter=len(candidates))

        # === 7. report ===
        export_records = candidates
        if export and not export_records and export_review_on_empty:
            export_records = _review_fallback_records(records, top_n=top_n)
            if export_records:
                logger.info(
                    f"[run #{run_id}] exporting {len(export_records)} rejected review records "
                    "because no candidates passed hard filters"
                )

        if export and export_records:
            try:
                controls.progress("export", f"Exporting {len(export_records)} records")
                controls.call("export", export_excel, export_records)
                controls.call("export", export_markdown, export_records)
                controls.call("export", export_json, export_records)
            except Exception as e:
                logger.warning(f"[run #{run_id}] export partial failure: {e}")

        # --- 更新 RunLog ---
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "success"
            run.finished_at = datetime.utcnow()
            run.api_calls = api_calls
        logger.info(f"[run #{run_id}] success | candidates={len(candidates)}")
        return run_id

    except PipelineCancelled as e:
        logger.warning(f"[run #{run_id}] cancelled: {e}")
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "cancelled"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.utcnow()
            run.api_calls = api_calls
        raise
    except PipelineTimeout as e:
        logger.warning(f"[run #{run_id}] timeout: {e}")
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.utcnow()
            run.api_calls = api_calls
        raise
    except Exception as e:
        logger.exception(f"[run #{run_id}] failed: {e}")
        try:
            from crawlers.amazon_search import search_failure_details
            api_calls.update(search_failure_details(e))
        except Exception:
            pass
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.utcnow()
            run.api_calls = api_calls
        raise


# ============================================================
# Helpers
# ============================================================

def _update_run(run_id: int, **kwargs) -> None:
    """部分更新 RunLog 计数字段。"""
    with session_scope() as s:
        run = s.get(RunLog, run_id)
        if run:
            for k, v in kwargs.items():
                setattr(run, k, v)


class _PipelineControls:
    def __init__(
        self,
        *,
        run_id: int,
        progress_callback: ProgressCallback | None,
        cancel_check: CancelCheck | None,
        stage_timeouts: dict[str, float],
    ) -> None:
        self.run_id = run_id
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.stage_timeouts = stage_timeouts
        self._stage_started: dict[str, float] = {}

    def progress(self, stage: str, message: str, **extra: Any) -> None:
        self.check(stage)
        if not self.progress_callback:
            return
        event = {
            "run_id": self.run_id,
            "stage": stage,
            "message": message,
            **extra,
        }
        self.progress_callback(event)

    def call(self, stage: str, func: Callable, *args: Any, **kwargs: Any) -> Any:
        self.check(stage)
        try:
            result = func(*args, **kwargs)
        except TimeoutError as exc:
            raise PipelineTimeout(f"{stage} stage timed out: {exc}") from exc
        self.check(stage)
        return result

    def check(self, stage: str) -> None:
        if self.cancel_check and self.cancel_check():
            raise PipelineCancelled(f"{stage} stage cancelled")
        timeout = float(self.stage_timeouts.get(stage) or 0)
        if timeout <= 0:
            return
        started = self._stage_started.setdefault(stage, time.monotonic())
        elapsed = time.monotonic() - started
        if elapsed > timeout:
            raise PipelineTimeout(f"{stage} stage timed out after {elapsed:.1f}s")


def _default_stage_timeouts() -> dict[str, float]:
    return {
        "crawl": settings.pipeline_crawl_timeout_seconds,
        "match": settings.pipeline_match_timeout_seconds,
        "profit": settings.pipeline_profit_timeout_seconds,
        "market": settings.pipeline_market_timeout_seconds,
        "score": settings.pipeline_score_timeout_seconds,
        "export": settings.pipeline_export_timeout_seconds,
    }


def _call_match_suppliers(
    match_func: Callable,
    product: ProductDTO,
    cancel_check: CancelCheck | None,
    market_keywords: list[str] | None = None,
    run_ref: str | None = None,
) -> list[SupplierDTO]:
    try:
        params = inspect.signature(match_func).parameters
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
        )
        accepts_cancel = "cancel_check" in params or accepts_kwargs
        accepts_market_keywords = "market_keywords" in params or accepts_kwargs
        accepts_run_ref = "run_ref" in params or accepts_kwargs
    except (TypeError, ValueError):
        accepts_cancel = False
        accepts_market_keywords = False
        accepts_run_ref = False
    try:
        kwargs = {}
        if accepts_cancel:
            kwargs["cancel_check"] = cancel_check
        if accepts_market_keywords:
            kwargs["market_keywords"] = market_keywords or []
        if accepts_run_ref:
            kwargs["run_ref"] = run_ref
        return match_func(product, **kwargs)
    except CancellationRequested as exc:
        raise PipelineCancelled(str(exc)) from exc


def _persist_products(products: list[ProductDTO]) -> dict[str, int]:
    ids: dict[str, int] = {}
    with session_scope() as s:
        for product in products:
            row = _upsert_product(s, product)
            ids[_product_key(product)] = row.id
    return ids


def _persist_suppliers_for_product(product: ProductDTO, suppliers: list[SupplierDTO]) -> None:
    with session_scope() as s:
        product_row = _upsert_product(s, product)
        for supplier in suppliers:
            _upsert_supplier(s, product_row.id, supplier)
        raw = product.raw_data if isinstance(product.raw_data, dict) else {}
        evidence = raw.get("sourcing_evidence")
        if isinstance(evidence, dict):
            from matchers.sourcing_slice import persist_serialized_sourcing_evidence
            persist_serialized_sourcing_evidence(evidence, s)


def _finalize_sourcing_evidence(records: list[PipelineRecord]) -> None:
    from matchers.sourcing_slice import (
        finalize_record_sourcing_evidence,
        persist_serialized_sourcing_evidence,
    )
    for record in records:
        payload = finalize_record_sourcing_evidence(record)
        if not isinstance(payload, dict):
            continue
        with session_scope() as session:
            _upsert_product(session, record.product)
            persist_serialized_sourcing_evidence(payload, session)


def _persist_profit_for_record(record: PipelineRecord) -> None:
    if record.profit is None or not record.suppliers:
        return
    with session_scope() as s:
        product_row = _upsert_product(s, record.product)
        supplier_row = _upsert_supplier(s, product_row.id, record.suppliers[0])
        profit = record.profit
        s.add(ProfitSnapshot(
            product_id=product_row.id,
            supplier_id=supplier_row.id,
            selling_price=float(getattr(profit, "selling_price", None) or getattr(record.product, "price", None) or 0.0),
            batch_qty=int(getattr(profit, "batch_qty", None) or 200),
            purchase_cost=float(getattr(profit, "purchase_cost", 0.0) or 0.0),
            shipping_cost=float(getattr(profit, "shipping_cost", 0.0) or 0.0),
            fba_fee=float(getattr(profit, "fba_fee", 0.0) or 0.0),
            commission=float(getattr(profit, "commission", 0.0) or 0.0),
            ad_cost=float(getattr(profit, "ad_cost", 0.0) or 0.0),
            return_loss=float(getattr(profit, "return_loss", 0.0) or 0.0),
            exchange_loss=float(getattr(profit, "exchange_loss", 0.0) or 0.0),
            other_costs=float(getattr(profit, "other_costs", 0.0) or 0.0),
            total_cost=float(getattr(profit, "total_cost", 0.0) or 0.0),
            net_profit=float(getattr(profit, "net_profit", 0.0) or 0.0),
            profit_margin=float(getattr(profit, "profit_margin", 0.0) or 0.0),
            params_version="runtime",
        ))


def _persist_market_for_record(record: PipelineRecord) -> None:
    if record.market is None:
        return
    market = record.market
    with session_scope() as s:
        product_row = _upsert_product(s, record.product)
        s.add(MarketAnalysis(
            product_id=product_row.id,
            main_keyword=getattr(market, "main_keyword", None),
            search_volume_monthly=getattr(market, "search_volume_monthly", None),
            keyword_difficulty=getattr(market, "keyword_difficulty", None),
            competing_listings=getattr(market, "competing_listings", None),
            top10_revenue_share=getattr(market, "top10_revenue_share", None),
            avg_review_count_top10=getattr(market, "avg_review_count_top10", None),
            avg_price_top10=getattr(market, "avg_price_top10", None),
            opportunity_score=getattr(market, "opportunity_score", None),
            seasonality=getattr(market, "seasonality", None),
            raw_data=getattr(market, "raw_data", None),
        ))


def _persist_score_for_record(record: PipelineRecord) -> None:
    if record.score is None:
        return
    score = record.score
    with session_scope() as s:
        product_row = _upsert_product(s, record.product)
        s.add(Score(
            product_id=product_row.id,
            profit_score=float(getattr(score, "profit_score", 0.0) or 0.0),
            demand_score=float(getattr(score, "demand_score", 0.0) or 0.0),
            competition_score=float(getattr(score, "competition_score", 0.0) or 0.0),
            supply_score=float(getattr(score, "supply_score", 0.0) or 0.0),
            logistics_score=float(getattr(score, "logistics_score", 0.0) or 0.0),
            risk_score=float(getattr(score, "risk_score", 0.0) or 0.0),
            total_score=float(getattr(score, "total_score", 0.0) or 0.0),
            passed_hard_filter=bool(getattr(score, "passed_hard_filter", False)),
            rejection_reasons=list(getattr(score, "rejection_reasons", None) or []),
            weights_version="runtime",
        ))


def _upsert_product(session, product: ProductDTO) -> Product:
    row = (
        session.query(Product)
        .filter_by(asin=product.asin, marketplace=(product.marketplace or "US"))
        .one_or_none()
    )
    if row is None:
        row = Product(asin=product.asin, marketplace=product.marketplace or "US", title=product.title or "")
        session.add(row)
        session.flush()
    row.category = product.category
    row.subcategory = product.subcategory
    row.title = product.title or row.title
    row.brand = product.brand
    row.price = product.price
    row.bsr_rank = product.bsr_rank
    row.rating = product.rating
    row.review_count = product.review_count
    row.review_velocity_30d = product.review_velocity_30d
    row.weight_kg = product.weight_kg
    row.length_cm = product.length_cm
    row.width_cm = product.width_cm
    row.height_cm = product.height_cm
    row.main_image_url = product.main_image_url
    row.listing_url = product.listing_url
    row.raw_data = product.raw_data if isinstance(product.raw_data, dict) else {}
    session.flush()
    return row


def _upsert_supplier(session, product_id: int, supplier: SupplierDTO) -> Supplier:
    offer_id = str(supplier.alibaba_offer_id or supplier.offer_url or "unknown").strip()
    row = (
        session.query(Supplier)
        .filter_by(product_id=product_id, alibaba_offer_id=offer_id)
        .one_or_none()
    )
    if row is None:
        row = Supplier(product_id=product_id, alibaba_offer_id=offer_id)
        session.add(row)
        session.flush()
    row.supplier_name = supplier.supplier_name
    row.offer_url = supplier.offer_url
    row.offer_image_url = supplier.offer_image_url
    row.image_similarity = supplier.image_similarity
    row.text_similarity = supplier.text_similarity
    row.moq = supplier.moq
    row.price_tiers = supplier.price_tiers
    row.base_price_cny = supplier.base_price_cny
    row.monthly_sales = supplier.monthly_sales
    row.repeat_buyer_rate = supplier.repeat_buyer_rate
    row.is_factory = supplier.is_factory
    row.title_cn = supplier.title_cn
    row.product_dimensions_cm = supplier.product_dimensions_cm
    row.product_weight_g = supplier.product_weight_g
    row.material = supplier.material
    row.color = supplier.color
    row.match_quality_score = supplier.match_quality_score
    row.match_verification_method = supplier.match_verification_method
    session.flush()
    return row


def _product_key(product: ProductDTO) -> str:
    return f"{product.marketplace or 'US'}:{product.asin}"


def _collect_source_products(
    source_mode: str,
    source_query: str,
    limit: int,
    marketplace: str,
) -> list[ProductDTO]:
    if source_mode == "keyword":
        from crawlers.amazon_search import search_amazon_products
        return search_amazon_products(source_query, marketplace=marketplace, limit=limit)

    from crawlers.amazon_bsr import crawl_best_sellers
    return crawl_best_sellers(source_query, limit, marketplace)


def _attach_source_metadata(products: list[ProductDTO], source_mode: str, source_query: str) -> None:
    for index, product in enumerate(products, 1):
        raw = product.raw_data if isinstance(product.raw_data, dict) else {}
        product.raw_data = raw
        raw.setdefault("source_mode", source_mode)
        raw.setdefault("source_query", source_query)
        if source_mode == "category":
            raw.setdefault("source_category", source_query)
            raw.setdefault("source_rank", getattr(product, "bsr_rank", None) or index)


def _dedupe_products_by_asin(products: list[ProductDTO]) -> tuple[list[ProductDTO], int]:
    """Deduplicate source products before expensive downstream stages."""
    selected: dict[str, ProductDTO] = {}
    order: list[str] = []
    passthrough: list[ProductDTO] = []

    for product in products:
        asin = str(getattr(product, "asin", "") or "").strip().upper()
        if not asin:
            passthrough.append(product)
            continue
        if asin not in selected:
            selected[asin] = product
            order.append(asin)
            continue
        if _product_dedupe_key(product) > _product_dedupe_key(selected[asin]):
            selected[asin] = product

    deduped = [selected[asin] for asin in order] + passthrough
    return deduped, max(len(products) - len(deduped), 0)


def _product_dedupe_key(product: ProductDTO) -> tuple:
    rank = _safe_float(_source_rank(product))
    completeness = sum(
        1
        for attr in (
            "title",
            "price",
            "bsr_rank",
            "rating",
            "review_count",
            "main_image_url",
            "listing_url",
        )
        if getattr(product, attr, None) not in (None, "", [], {})
    )
    # Lower source rank / BSR is better; invert it so larger tuple wins.
    rank_score = -rank if rank is not None else float("-inf")
    return (rank_score, completeness)


def _source_rank(product: ProductDTO):
    raw = getattr(product, "raw_data", None)
    if isinstance(raw, dict):
        for key in ("source_rank", "bsr_rank"):
            if raw.get(key) is not None:
                return raw.get(key)
    return getattr(product, "bsr_rank", None)


def _rank_suppliers_by_profit(product: ProductDTO, suppliers: list[SupplierDTO]) -> Optional[ProfitBreakdown]:
    """Add supplier-level profit evidence and reorder by sourceability."""
    ranked: list[tuple[float, float, float, float, int, SupplierDTO, ProfitBreakdown | None]] = []

    evidence_error: InsufficientCostEvidence | None = None
    for idx, supplier in enumerate(suppliers):
        base_score = _supplier_candidate_score(supplier)
        profit: ProfitBreakdown | None = None
        profit_score = 0.0
        try:
            profit = predict_profit(product, supplier)
            profit_score = _supplier_profit_score(profit.profit_margin)
            raw = supplier.raw_data if isinstance(supplier.raw_data, dict) else {}
            supplier.raw_data = raw
            raw["supplier_profit_margin"] = round(profit.profit_margin, 4)
            raw["supplier_net_profit"] = round(profit.net_profit, 4)
            raw["supplier_purchase_cost"] = round(profit.purchase_cost, 4)
            raw["supplier_profit_score"] = profit_score
        except InsufficientCostEvidence as exc:
            evidence_error = exc
            logger.debug(
                f"[profit-rank] supplier profit insufficient asin={getattr(product, 'asin', '?')} "
                f"offer={getattr(supplier, 'alibaba_offer_id', '?')}: {exc}"
            )
        except Exception as exc:
            logger.debug(
                f"[profit-rank] supplier profit skipped asin={getattr(product, 'asin', '?')} "
                f"offer={getattr(supplier, 'alibaba_offer_id', '?')}: {exc}"
            )

        rank_score = round(0.70 * base_score + 0.30 * profit_score, 4)
        raw = supplier.raw_data if isinstance(supplier.raw_data, dict) else {}
        supplier.raw_data = raw
        raw["supplier_rank_score"] = rank_score
        ranked.append((
            rank_score,
            base_score,
            profit.profit_margin if profit else -1.0,
            profit.net_profit if profit else -1.0,
            -idx,
            supplier,
            profit,
        ))

    ranked.sort(reverse=True)
    deduped_ranked = _dedupe_ranked_suppliers(ranked)
    suppliers[:] = [item[5] for item in deduped_ranked]
    for _rank_score, _base_score, _margin, _net, _idx, _supplier, profit in deduped_ranked:
        if profit is not None:
            return profit
    if evidence_error is not None:
        raise evidence_error
    return None


def _dedupe_ranked_suppliers(
    ranked: list[tuple[float, float, float, float, int, SupplierDTO, ProfitBreakdown | None]]
) -> list[tuple[float, float, float, float, int, SupplierDTO, ProfitBreakdown | None]]:
    seen: set[str] = set()
    deduped = []
    for item in ranked:
        supplier = item[5]
        key = _supplier_dedupe_key(supplier, fallback=str(item[4]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _supplier_dedupe_key(supplier: SupplierDTO, fallback: str = "") -> str:
    offer_id = str(getattr(supplier, "alibaba_offer_id", "") or "").strip()
    if offer_id:
        return f"offer:{offer_id}"
    offer_url = str(getattr(supplier, "offer_url", "") or "").strip().lower()
    if offer_url:
        return f"url:{offer_url}"
    return f"row:{fallback}"


def _supplier_candidate_score(supplier: SupplierDTO) -> float:
    raw = supplier.raw_data if isinstance(supplier.raw_data, dict) else {}
    for value in (
        raw.get("supplier_candidate_score"),
        getattr(supplier, "candidate_score", None),
        getattr(supplier, "match_quality_score", None),
    ):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return 0.0


def _supplier_profit_score(margin: float) -> float:
    if margin <= 0:
        return 0.0
    if margin >= 0.40:
        return 1.0
    return round(max(0.0, min(1.0, margin / 0.40)), 4)


def _dedupe_records_by_asin(records: list[PipelineRecord]) -> tuple[list[PipelineRecord], int]:
    selected: dict[str, PipelineRecord] = {}
    order: list[str] = []
    passthrough: list[PipelineRecord] = []

    for record in records:
        product = getattr(record, "product", None)
        asin = str(getattr(product, "asin", "") or "").strip().upper()
        if not asin:
            passthrough.append(record)
            continue
        if asin not in selected:
            selected[asin] = record
            order.append(asin)
            continue
        if _record_dedupe_key(record) > _record_dedupe_key(selected[asin]):
            selected[asin] = record

    deduped = [selected[asin] for asin in order] + passthrough
    return deduped, max(len(records) - len(deduped), 0)


def _record_dedupe_key(record: PipelineRecord) -> tuple:
    score_value = getattr(record.score, "total_score", None) if record.score else None
    return (
        _safe_float(score_value) or 0.0,
        record.top_supplier_candidate_score,
        record.net_profit,
        _product_completeness(record.product),
    )


def _product_completeness(product: ProductDTO) -> int:
    return sum(
        1
        for attr in (
            "title",
            "brand",
            "category",
            "price",
            "rating",
            "review_count",
            "main_image_url",
            "listing_url",
        )
        if getattr(product, attr, None) not in (None, "", [], {})
    )


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evidence_rejection_reasons(
    error: InsufficientCostEvidence | ScoringEvidenceError,
) -> list[str]:
    fields = set(error.fields)
    if isinstance(error, InsufficientCostEvidence):
        if "purchase_price" in fields:
            return ["missing_purchase_price"]
        if fields & {"weight_kg", "length_cm", "width_cm", "height_cm"}:
            return ["missing_logistics_dimensions"]
    if error.dimension == "competition":
        return ["missing_market_evidence"]
    if error.dimension == "logistics":
        return ["missing_logistics_dimensions"]
    if error.dimension == "supply":
        reasons = []
        if "purchase_price" in fields:
            reasons.append("missing_purchase_price")
        if "moq" in fields:
            reasons.append("missing_moq")
        return reasons or ["missing_supply_evidence"]
    return [f"missing_{field}" for field in error.fields]


def _review_fallback_records(records: list[PipelineRecord], top_n: int = 5) -> list[PipelineRecord]:
    """Return scored real-supplier records for human review when hard filters reject all."""
    reviewable = [
        rec for rec in records
        if rec.suppliers and (
            (rec.score is not None and rec.profit is not None)
            or bool(getattr(rec, "rejection_reasons", None))
        )
    ]
    reviewable.sort(
        key=lambda rec: (
            rec.score.total_score if rec.score is not None else float("-inf"),
            rec.net_profit,
        ),
        reverse=True,
    )
    deduped, _removed = _dedupe_records_by_asin(reviewable)
    return deduped[:top_n]


# Public compatibility entry. The implementation lives outside this legacy
# business module so recoverability does not turn orchestrator.py into a state
# machine. Imports are intentionally late to keep existing monkeypatch points
# and avoid circular imports while pipeline/recoverable.py uses the helpers
# above as the unchanged business adapter.
def run_pipeline(
    category: str,
    source_mode: str = "category",
    keyword: str | None = None,
    limit: int = 100,
    marketplace: str = "US",
    pipeline_version: str = "0.3.0",
    top_n: int = 20,
    export: bool = True,
    export_review_on_empty: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    stage_timeouts: dict[str, float] | None = None,
    seed_products: list[dict] | None = None,
) -> int:
    from pipeline.recoverable import run_recoverable_pipeline

    return run_recoverable_pipeline(
        category=category,
        source_mode=source_mode,
        keyword=keyword,
        limit=limit,
        marketplace=marketplace,
        pipeline_version=pipeline_version,
        top_n=top_n,
        export=export,
        export_review_on_empty=export_review_on_empty,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
        stage_timeouts=stage_timeouts,
        seed_products=seed_products,
    )


def resume_pipeline(
    run_id: int,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> int:
    from pipeline.recoverable import resume_recoverable_pipeline

    return resume_recoverable_pipeline(
        run_id,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def retry_node(run_id: int, asin: str, stage: str, *, reason: str = "manual retry") -> dict:
    """Move one failed ASIN node back to pending without creating a new Run."""
    from execution.repository import ExecutionRepository

    repository = ExecutionRepository(session_context=session_scope)
    node = repository.find_node(
        int(run_id), scope_type="asin", scope_key=str(asin), stage=str(stage)
    )
    if node is None:
        raise KeyError((run_id, asin, stage))
    repository.retry_node(
        int(node["id"]), reason=reason,
        expected_resume_token=node.get("resume_token"),
    )
    repository.update_run_status(int(run_id))
    return repository.get_node(int(node["id"]))


def force_rerun_node(
    run_id: int,
    asin: str,
    stage: str,
    reason: str,
) -> dict:
    """Invalidate one terminal ASIN node; a non-empty audit reason is mandatory."""
    from execution.repository import ExecutionRepository

    if not str(reason).strip():
        raise ValueError("force rerun reason is required")
    repository = ExecutionRepository(session_context=session_scope)
    node = repository.find_node(
        int(run_id), scope_type="asin", scope_key=str(asin), stage=str(stage)
    )
    if node is None:
        raise KeyError((run_id, asin, stage))
    repository.force_rerun(
        int(node["id"]), reason=str(reason),
        expected_resume_token=node.get("resume_token"),
    )
    repository.update_run_status(int(run_id))
    return repository.get_node(int(node["id"]))


def execution_nodes(run_id: int) -> list[dict]:
    from execution.repository import ExecutionRepository
    return ExecutionRepository(session_context=session_scope).list_nodes(int(run_id))


def execution_attempts(run_id: int, node_id: int) -> list[dict]:
    from execution.repository import ExecutionRepository

    repository = ExecutionRepository(session_context=session_scope)
    node = repository.get_node(int(node_id))
    if node is None or int(node["run_id"]) != int(run_id):
        raise KeyError(node_id)
    return repository.list_attempts(int(node_id))

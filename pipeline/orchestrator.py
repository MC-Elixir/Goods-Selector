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

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from analyzers.profit_model import ProfitBreakdown, predict_profit
from analyzers.scorer import ScoreBreakdown, score_product
from crawlers.amazon_bsr import ProductDTO
from db.models import RunLog
from db.session import session_scope
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.filters import rank_candidates
from reports.exporter import export_excel, export_json, export_markdown


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

    @property
    def net_profit(self) -> float:
        return self.profit.net_profit if self.profit else 0.0

    @property
    def profit_margin(self) -> float:
        return self.profit.profit_margin if self.profit else 0.0


# ============================================================
# 主流水线
# ============================================================

def run_pipeline(
    category: str,
    limit: int = 100,
    marketplace: str = "US",
    pipeline_version: str = "0.2.0",
    top_n: int = 20,
    export: bool = True,
) -> int:
    """跑一次完整选品流水线，返回 RunLog id。

    Args:
        category    Amazon 一级类目
        limit       抓取产品数量
        marketplace 站点
        top_n       最终输出候选品数量
        export      是否导出报告（Excel + Markdown + JSON）
    """
    with session_scope() as s:
        run = RunLog(
            pipeline_version=pipeline_version,
            category=category,
            marketplace=marketplace,
            started_at=datetime.utcnow(),
            status="running",
        )
        s.add(run)
        s.flush()
        run_id = run.id
        logger.info(f"[run #{run_id}] start | cat={category} limit={limit}")

    api_calls: dict = {}

    try:
        # === 1. crawl ===
        from crawlers.amazon_bsr import crawl_best_sellers
        products = crawl_best_sellers(category, limit, marketplace)
        api_calls["keepa"] = len(products)
        logger.info(f"[run #{run_id}] crawled {len(products)} products")
        _update_run(run_id, products_crawled=len(products))

        # === 2. match ===
        from matchers import match_suppliers
        records: list[PipelineRecord] = []
        matched = 0
        for p in products:
            try:
                sups = match_suppliers(p)
                matched += len(sups)
            except Exception as e:
                logger.warning(f"[run #{run_id}] match failed asin={p.asin}: {e}")
                sups = []
            records.append(PipelineRecord(product=p, suppliers=sups))

        api_calls["alibaba_text_search"] = len(products)
        api_calls["vision_analyzer"] = len(products)
        logger.info(f"[run #{run_id}] matched {matched} suppliers")
        _update_run(run_id, suppliers_matched=matched)

        # === 3. profit ===
        calculated = 0
        for rec in records:
            if not rec.suppliers:
                continue
            best_sup = rec.suppliers[0]   # 按月销量已排序，取第一个
            try:
                rec.profit = predict_profit(rec.product, best_sup)
                calculated += 1
            except Exception as e:
                logger.warning(f"[run #{run_id}] profit failed asin={rec.product.asin}: {e}")

        logger.info(f"[run #{run_id}] calculated {calculated} profit snapshots")
        _update_run(run_id, profits_calculated=calculated)

        # === 4. market ===
        try:
            from analyzers.maijiajingling import MaijiajinglingClient
            mjjl = MaijiajinglingClient()
            for rec in records:
                try:
                    rec.market = mjjl.analyze_market(rec.product.asin, marketplace)
                    api_calls["mjjl"] = api_calls.get("mjjl", 0) + 1
                except Exception as e:
                    logger.debug(f"[run #{run_id}] market skip asin={rec.product.asin}: {e}")
        except Exception:
            logger.info(f"[run #{run_id}] market analysis skipped (API not configured)")

        # === 5. score ===
        for rec in records:
            if rec.profit is None:
                continue
            try:
                rec.score = score_product(
                    product=rec.product,
                    profit_breakdown=rec.profit,
                    market_analysis=rec.market,
                    suppliers=rec.suppliers,
                )
            except Exception as e:
                logger.warning(f"[run #{run_id}] score failed asin={rec.product.asin}: {e}")

        # === 6. filter ===
        candidates = rank_candidates(records, top_n=top_n)
        logger.info(
            f"[run #{run_id}] {len(candidates)} candidates "
            f"(passed filter) out of {len(records)}"
        )
        _update_run(run_id, candidates_after_filter=len(candidates))

        # === 7. report ===
        if export and candidates:
            try:
                export_excel(candidates)
                export_markdown(candidates)
                export_json(candidates)
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

    except Exception as e:
        logger.exception(f"[run #{run_id}] failed: {e}")
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.utcnow()
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

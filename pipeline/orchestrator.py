"""
主流程编排
==========

执行顺序：
    1. crawl     抓 BSR              → products
    2. match     1688 图文匹配         → suppliers
    3. profit    利润预测              → profit_snapshots
    4. market    卖家精灵市场分析      → market_analyses
    5. score     评分 + 硬性筛选        → scores
    6. filter    Top N 筛选             → 候选选品池
    7. report    导出报告

每一阶段失败后果分级：
    crawl 失败 → 整条流水线 abort
    其余阶段单产品失败 → 记录错误继续，不影响其他产品
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from loguru import logger

from db.models import RunLog
from db.session import session_scope


def run_pipeline(
    category: str,
    limit: int = 100,
    marketplace: str = "US",
    pipeline_version: str = "0.1.0",
) -> int:
    """跑一次完整流水线，返回 RunLog id。"""
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

    try:
        # === 1. crawl ===
        # products = crawl_best_sellers(category, limit, marketplace)
        # _persist_products(products)

        # === 2. match ===
        # for p in products:
        #     suppliers = pailitao.search_by_image(p.main_image_url)
        #     _persist_suppliers(p, suppliers)

        # === 3. profit ===
        # for p in products:
        #     for sup in p.suppliers:
        #         pb = predict_profit(p, sup)
        #         _persist_profit(p, sup, pb)

        # === 4. market ===
        # for p in products:
        #     ma = mjjl.analyze_market(p.asin)
        #     _persist_market(p, ma)

        # === 5. score ===
        # for p in products:
        #     sb = score_product(p, ...)
        #     _persist_score(p, sb)

        # === 6. filter ===
        # candidates = filter_topn(...)

        # === 7. report ===
        # export_report(candidates, run_id)

        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "success"
            run.finished_at = datetime.utcnow()
        logger.info(f"[run #{run_id}] success")
        return run_id

    except Exception as e:
        logger.exception(f"[run #{run_id}] failed: {e}")
        with session_scope() as s:
            run = s.get(RunLog, run_id)
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.utcnow()
        raise

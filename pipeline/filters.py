"""
筛选规则
========

硬性筛选（apply_hard_filters）：阈值不达标直接淘汰，配置在 scoring_weights.yaml 的
hard_filters 节点。

软性排序（rank_candidates）：按 total_score 降序，可叠加二级排序键如 net_profit。
"""
from __future__ import annotations

from typing import Optional


def rank_candidates(
    scored_products: list,
    top_n: Optional[int] = None,
    secondary_key: str = "net_profit",
) -> list:
    """对通过硬筛的产品按总分排序，取 Top N。"""
    candidates = [p for p in scored_products if p.score.passed_hard_filter]
    candidates.sort(
        key=lambda p: (p.score.total_score, getattr(p, secondary_key, 0)),
        reverse=True,
    )
    return candidates[:top_n] if top_n else candidates

"""
评分引擎
========

输入：一个 product 的全部数据（profit、market、supplier 等）
输出：6 个维度归一化得分 + 综合分（0-100）+ 是否通过硬性筛选

权重和曲线参数：config/scoring_weights.yaml（可热加载）

设计原则：
    1. 每个维度的归一化函数纯函数无副作用，方便单测
    2. 权重存 YAML，调参不动代码
    3. 总分 = sum(dim_score × weight) × 100
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from config.settings import CONFIG_DIR


# ============================================================
# DTO
# ============================================================
@dataclass
class ScoreBreakdown:
    profit_score: float = 0.0
    demand_score: float = 0.0
    competition_score: float = 0.0
    supply_score: float = 0.0
    logistics_score: float = 0.0
    risk_score: float = 0.0
    total_score: float = 0.0
    passed_hard_filter: bool = False
    rejection_reasons: list[str] = field(default_factory=list)


# ============================================================
# 配置加载
# ============================================================
_WEIGHTS_CACHE: Optional[dict] = None


def load_weights_config(path: Optional[Path] = None) -> dict:
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    path = path or CONFIG_DIR / "scoring_weights.yaml"
    with open(path, "r", encoding="utf-8") as f:
        _WEIGHTS_CACHE = yaml.safe_load(f)
    # 校验权重和
    weights = _WEIGHTS_CACHE["weights"]
    s = sum(weights.values())
    if abs(s - 1.0) > 1e-6:
        raise ValueError(f"权重和必须为 1.0，当前 {s}")
    logger.debug(f"Loaded scoring weights from {path}")
    return _WEIGHTS_CACHE


def reload_weights_config() -> None:
    global _WEIGHTS_CACHE
    _WEIGHTS_CACHE = None


# ============================================================
# 单维度归一化函数（纯函数，便于单测）
# ============================================================
def score_profit(profit_margin: float, curve: dict) -> float:
    """利润率 → [0,1]，sigmoid 形状。"""
    raise NotImplementedError


def score_demand(bsr_rank: int, monthly_sales: Optional[int], curve: dict) -> float:
    """BSR + 月销量 → [0,1]。"""
    raise NotImplementedError


def score_competition(
    competing_listings: int,
    top10_share: Optional[float],
    curve: dict,
) -> float:
    """卖家数 + 头部集中度 → [0,1]，越激烈越低。"""
    raise NotImplementedError


def score_supply(suppliers: list, curve: dict) -> float:
    """货源数量 + 平均回头率 + MOQ → [0,1]。"""
    raise NotImplementedError


def score_logistics(weight_kg, longest_side_cm, attrs, curve: dict) -> float:
    """体积重 + 危险属性 → [0,1]。"""
    raise NotImplementedError


def score_risk(category: str, brand: Optional[str], curve: dict) -> float:
    """品牌侵权 + 类目认证 → [0,1]。"""
    raise NotImplementedError


# ============================================================
# 硬性筛选
# ============================================================
def apply_hard_filters(
    profit_margin: float,
    total_score: float,
    moq: Optional[int],
    supplier_count: int,
    brand: Optional[str],
    config: dict,
) -> tuple[bool, list[str]]:
    """返回 (是否通过, 拒绝原因列表)。"""
    raise NotImplementedError


# ============================================================
# 主函数
# ============================================================
def score_product(
    product,
    profit_breakdown,
    market_analysis,
    suppliers: list,
    config: Optional[dict] = None,
) -> ScoreBreakdown:
    """对单个产品打分。"""
    config = config or load_weights_config()
    raise NotImplementedError("拼装上面的 score_* + apply_hard_filters")

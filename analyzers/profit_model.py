"""
利润预测模型
============

公式：
    净利润 = 售价
           - (1688采购价 + 头程物流 + FBA费用 + 平台佣金 + 广告费 + 退货损耗 + 汇率损耗)
    净利率 = 净利润 / 售价

参数来源：config/profit_params.yaml（可热加载）

使用：
    snapshot = predict_profit(product, supplier, batch_qty=200)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from config.settings import CONFIG_DIR


# ============================================================
# DTO
# ============================================================
@dataclass
class ProfitBreakdown:
    selling_price: float
    purchase_cost: float
    shipping_cost: float
    fba_fee: float
    commission: float
    ad_cost: float
    return_loss: float
    exchange_loss: float
    other_costs: float = 0.0

    @property
    def total_cost(self) -> float:
        return sum([
            self.purchase_cost, self.shipping_cost, self.fba_fee,
            self.commission, self.ad_cost, self.return_loss,
            self.exchange_loss, self.other_costs,
        ])

    @property
    def net_profit(self) -> float:
        return self.selling_price - self.total_cost

    @property
    def profit_margin(self) -> float:
        return self.net_profit / self.selling_price if self.selling_price else 0.0


# ============================================================
# 参数加载
# ============================================================
_PARAMS_CACHE: Optional[dict] = None


def load_profit_params(path: Optional[Path] = None) -> dict:
    """从 YAML 加载利润参数，带模块级缓存。"""
    global _PARAMS_CACHE
    if _PARAMS_CACHE is not None:
        return _PARAMS_CACHE
    path = path or CONFIG_DIR / "profit_params.yaml"
    with open(path, "r", encoding="utf-8") as f:
        _PARAMS_CACHE = yaml.safe_load(f)
    logger.debug(f"Loaded profit params from {path}")
    return _PARAMS_CACHE


def reload_profit_params() -> None:
    """清缓存，下次调用重新加载（用于热更新）。"""
    global _PARAMS_CACHE
    _PARAMS_CACHE = None


# ============================================================
# 各项成本计算（独立函数，方便单测）
# ============================================================
def calc_purchase_cost(supplier, batch_qty: int, params: dict) -> float:
    """根据 1688 阶梯价 × 汇率算采购成本（USD）。"""
    raise NotImplementedError


def calc_shipping_cost(product, params: dict) -> float:
    """头程物流费 = max(实重, 体积重) × 单价 + 基础费。"""
    raise NotImplementedError


def calc_fba_fee(product, params: dict) -> float:
    """根据尺寸重量分档查 FBA 费用表。"""
    raise NotImplementedError


def calc_commission(product, params: dict) -> float:
    """平台佣金 = 售价 × 类目佣金率。"""
    raise NotImplementedError


def calc_ad_cost(product, params: dict) -> float:
    """广告费 = 售价 × ACOS × 广告流量占比。"""
    raise NotImplementedError


def calc_return_loss(product, params: dict) -> float:
    """退货损耗 = 售价 × 退货率 × 损耗率。"""
    raise NotImplementedError


# ============================================================
# 主函数
# ============================================================
def predict_profit(
    product,
    supplier,
    batch_qty: Optional[int] = None,
    params: Optional[dict] = None,
) -> ProfitBreakdown:
    """对一组 (product, supplier) 预测利润。

    Returns:
        ProfitBreakdown，可直接 .net_profit / .profit_margin 拿结果
    """
    params = params or load_profit_params()
    batch_qty = batch_qty or params["sourcing"]["default_batch_qty"]

    raise NotImplementedError(
        "把上面 6 个 calc_* 函数拼起来即可"
    )

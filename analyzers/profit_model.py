"""
利润预测模型
============

公式：
    净利润 = 售价
           - (采购成本 + 头程物流 + FBA费用 + 平台佣金 + 广告费 + 退货损耗 + 汇率损耗)
    净利率 = 净利润 / 售价

参数来源：config/profit_params.yaml（可热加载）

用法：
    pb = predict_profit(product, supplier, batch_qty=200)
    pb.profit_margin   # 净利率
    pb.net_profit      # 净利润 USD
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from loguru import logger

from config.settings import CONFIG_DIR

CM_TO_IN = 0.393701
KG_TO_OZ = 35.274


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
    global _PARAMS_CACHE
    _PARAMS_CACHE = None


# ============================================================
# 各项成本计算（纯函数，方便单测）
# ============================================================

def calc_purchase_cost(supplier, batch_qty: int, params: dict) -> float:
    """采购成本（USD） = 1688 阶梯价 × 汇率。

    按 batch_qty 匹配阶梯价：选不超过 batch_qty 的最大起订量档。
    无阶梯价时退回 base_price_cny。
    """
    cny_to_usd: float = params["defaults"]["cny_to_usd"]

    price_tiers: list = getattr(supplier, "price_tiers", None) or []
    price_cny: Optional[float] = None

    if price_tiers:
        # 按起订量升序，找 <= batch_qty 的最高档
        eligible = [t for t in price_tiers if t.get("qty", 0) <= batch_qty]
        if eligible:
            best = max(eligible, key=lambda t: t.get("qty", 0))
            price_cny = best.get("price")
        else:
            # batch_qty 小于最低起订量，用最低档价
            price_cny = min(price_tiers, key=lambda t: t.get("qty", 0)).get("price")

    if price_cny is None:
        price_cny = getattr(supplier, "base_price_cny", None)

    if not price_cny:
        logger.warning("supplier 无价格信息，采购成本返回 0")
        return 0.0

    return float(price_cny) * cny_to_usd


def calc_shipping_cost(product, params: dict) -> float:
    """头程物流费（USD） = max(实重, 体积重) × 单价 + 基础费。

    体积重(kg) = L×W×H(cm) / volumetric_divisor。
    """
    shipping = params["shipping"]
    method: str = shipping["default_method"]
    rate: dict = shipping["rates"][method]

    weight_kg: float = getattr(product, "weight_kg", None) or 0.5
    length_cm: float = getattr(product, "length_cm", None) or 0.0
    width_cm: float = getattr(product, "width_cm", None) or 0.0
    height_cm: float = getattr(product, "height_cm", None) or 0.0

    divisor: float = shipping.get("volumetric_divisor", 6000)
    if length_cm and width_cm and height_cm:
        volumetric_kg = (length_cm * width_cm * height_cm) / divisor
    else:
        volumetric_kg = 0.0

    chargeable_kg = max(weight_kg, volumetric_kg, rate.get("min_chargeable_kg", 0.5))
    return rate["base_fee"] + rate["per_kg"] * chargeable_kg


def calc_fba_fee(product, params: dict) -> float:
    """FBA 配送费（USD），按尺寸重量分档查表。"""
    fba = params["fba"]
    tiers: dict = fba["fulfillment_fees"]

    weight_kg: float = getattr(product, "weight_kg", None) or 0.5
    length_cm: float = getattr(product, "length_cm", None) or 20.0
    width_cm: float = getattr(product, "width_cm", None) or 15.0
    height_cm: float = getattr(product, "height_cm", None) or 5.0

    longest_in = max(length_cm, width_cm, height_cm) * CM_TO_IN
    weight_oz = weight_kg * KG_TO_OZ

    for name in ("small_standard", "large_standard", "small_oversize", "medium_oversize"):
        t = tiers[name]
        if longest_in <= t["max_longest_side_in"] and weight_oz <= t["max_weight_oz"]:
            return t["fee_usd"]

    return tiers["medium_oversize"]["fee_usd"]


def calc_commission(product, params: dict) -> float:
    """平台佣金（USD） = 售价 × 类目佣金率。"""
    rates: dict = params["commission_rates"]
    category: str = getattr(product, "category", "") or ""
    rate: float = rates["by_category"].get(category, rates["default"])
    price: float = getattr(product, "price", None) or 0.0
    return price * rate


def calc_ad_cost(product, params: dict) -> float:
    """广告费（USD） = 售价 × ACOS × 广告流量占比。"""
    ad = params["ad_cost"]
    price: float = getattr(product, "price", None) or 0.0
    return price * ad["default_acos"] * ad["ad_spend_ratio"]


def calc_return_loss(product, params: dict) -> float:
    """退货损耗（USD） = 售价 × 退货率 × 不可二次销售比例。"""
    returns = params["returns"]
    category: str = getattr(product, "category", "") or ""
    return_rate: float = returns["by_category"].get(category, returns["default_return_rate"])
    price: float = getattr(product, "price", None) or 0.0
    return price * return_rate * returns["return_loss_ratio"]


# ============================================================
# 主函数
# ============================================================

def predict_profit(
    product,
    supplier,
    batch_qty: Optional[int] = None,
    params: Optional[dict] = None,
) -> ProfitBreakdown:
    """对 (product, supplier) 组合预测利润。

    product / supplier 可以是 DTO 或 ORM 对象（属性名相同）。
    """
    params = params or load_profit_params()
    batch_qty = batch_qty or params["sourcing"]["default_batch_qty"]

    price: float = getattr(product, "price", None) or 0.0

    purchase = calc_purchase_cost(supplier, batch_qty, params)
    shipping = calc_shipping_cost(product, params)
    fba = calc_fba_fee(product, params)
    commission = calc_commission(product, params)
    ad = calc_ad_cost(product, params)
    ret = calc_return_loss(product, params)
    exchange = price * params["defaults"]["exchange_loss_rate"]

    pb = ProfitBreakdown(
        selling_price=price,
        purchase_cost=purchase,
        shipping_cost=shipping,
        fba_fee=fba,
        commission=commission,
        ad_cost=ad,
        return_loss=ret,
        exchange_loss=exchange,
    )
    logger.debug(
        f"profit | price={price:.2f} margin={pb.profit_margin:.1%} "
        f"net={pb.net_profit:.2f}"
    )
    return pb

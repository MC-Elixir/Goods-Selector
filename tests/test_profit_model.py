"""利润模型单测。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from analyzers import profit_model
from analyzers.profit_model import (
    InsufficientCostEvidence,
    ProfitBreakdown,
    calc_ad_cost,
    calc_commission,
    calc_fba_fee,
    calc_purchase_cost,
    calc_return_loss,
    calc_shipping_cost,
    predict_profit,
)


# ============================================================
# 测试用 mock 对象
# ============================================================
@dataclass
class _MockProduct:
    price: float = 29.99
    category: str = "Home & Kitchen"
    weight_kg: float = 0.8
    length_cm: float = 30.0
    width_cm: float = 20.0
    height_cm: float = 10.0


@dataclass
class _MockSupplier:
    base_price_cny: float = 35.0
    moq: int = 100
    price_tiers: list = field(default_factory=lambda: [
        {"qty": 50, "price": 40.0},
        {"qty": 100, "price": 35.0},
        {"qty": 200, "price": 30.0},
    ])


# ============================================================
# 参数加载
# ============================================================
def test_profit_params_loadable():
    p = profit_model.load_profit_params()
    assert "shipping" in p
    assert "fba" in p
    assert "commission_rates" in p


# ============================================================
# ProfitBreakdown 数学一致性
# ============================================================
def test_profit_breakdown_math():
    pb = ProfitBreakdown(
        selling_price=20.0,
        purchase_cost=3.0,
        shipping_cost=2.0,
        fba_fee=4.0,
        commission=3.0,
        ad_cost=2.5,
        return_loss=0.5,
        exchange_loss=0.2,
    )
    assert pb.total_cost == pytest.approx(15.2)
    assert pb.net_profit == pytest.approx(4.8)
    assert pb.profit_margin == pytest.approx(0.24)


def test_profit_breakdown_zero_price():
    pb = ProfitBreakdown(
        selling_price=0.0,
        purchase_cost=5.0, shipping_cost=2.0, fba_fee=3.0,
        commission=0.0, ad_cost=0.0, return_loss=0.0, exchange_loss=0.0,
    )
    assert pb.profit_margin == 0.0


# ============================================================
# calc_purchase_cost
# ============================================================
def test_calc_purchase_cost_uses_matching_tier():
    params = profit_model.load_profit_params()
    sup = _MockSupplier()
    cost = calc_purchase_cost(sup, batch_qty=100, params=params)
    cny_rate = params["defaults"]["cny_to_usd"]
    # 100 件对应 35.0 CNY
    assert cost == pytest.approx(35.0 * cny_rate)


def test_calc_purchase_cost_uses_best_eligible_tier():
    params = profit_model.load_profit_params()
    sup = _MockSupplier()
    cost = calc_purchase_cost(sup, batch_qty=200, params=params)
    cny_rate = params["defaults"]["cny_to_usd"]
    assert cost == pytest.approx(30.0 * cny_rate)


def test_calc_purchase_cost_below_min_tier():
    params = profit_model.load_profit_params()
    sup = _MockSupplier()
    # batch_qty < 最低起订量，用最低档价 40.0
    cost = calc_purchase_cost(sup, batch_qty=10, params=params)
    cny_rate = params["defaults"]["cny_to_usd"]
    assert cost == pytest.approx(40.0 * cny_rate)


def test_calc_purchase_cost_no_tiers_fallback():
    params = profit_model.load_profit_params()
    sup = _MockSupplier(price_tiers=[], base_price_cny=50.0)
    cost = calc_purchase_cost(sup, batch_qty=100, params=params)
    cny_rate = params["defaults"]["cny_to_usd"]
    assert cost == pytest.approx(50.0 * cny_rate)


def test_purchase_cost_requires_real_price():
    params = profit_model.load_profit_params()
    supplier = _MockSupplier(base_price_cny=None, price_tiers=[])
    with pytest.raises(InsufficientCostEvidence, match="purchase_price"):
        calc_purchase_cost(supplier, 200, params)


def test_purchase_cost_accepts_extracted_tier_schema():
    params = profit_model.load_profit_params()
    supplier = _MockSupplier(
        base_price_cny=None,
        price_tiers=[{"min_qty": 100, "price_cny": 32.0}],
    )
    assert calc_purchase_cost(supplier, 200, params) == pytest.approx(
        32.0 * params["defaults"]["cny_to_usd"]
    )


@pytest.mark.parametrize("invalid", ["nan", float("nan"), "inf", float("inf"), "-inf", float("-inf")])
@pytest.mark.parametrize("field", ["min_qty", "price_cny"])
def test_purchase_cost_rejects_nonfinite_tier_values(field, invalid):
    params = profit_model.load_profit_params()
    tier = {"min_qty": 10, "price_cny": 20}
    tier[field] = invalid
    supplier = _MockSupplier(base_price_cny=None, price_tiers=[tier])

    with pytest.raises(InsufficientCostEvidence, match="purchase_price"):
        calc_purchase_cost(supplier, 200, params)


@pytest.mark.parametrize("invalid", ["nan", float("nan"), "inf", float("inf"), "-inf", float("-inf")])
def test_purchase_cost_rejects_nonfinite_base_price(invalid):
    params = profit_model.load_profit_params()
    supplier = _MockSupplier(base_price_cny=invalid, price_tiers=[])

    with pytest.raises(InsufficientCostEvidence, match="purchase_price"):
        calc_purchase_cost(supplier, 200, params)


# ============================================================
# calc_shipping_cost
# ============================================================
def test_calc_shipping_cost_uses_real_weight_when_larger():
    params = profit_model.load_profit_params()
    # 体积重 = 30×20×10/6000 = 1.0 kg，实重 = 1.5 kg → 用实重
    prod = _MockProduct(weight_kg=1.5, length_cm=30, width_cm=20, height_cm=10)
    cost = calc_shipping_cost(prod, params)
    rate = params["shipping"]["rates"]["sea_lcl"]
    expected = rate["base_fee"] + rate["per_kg"] * 1.5
    assert cost == pytest.approx(expected)


def test_calc_shipping_cost_uses_volumetric_when_larger():
    params = profit_model.load_profit_params()
    # 体积重 = 60×40×30/6000 = 12 kg，实重 = 0.5 kg → 用体积重
    prod = _MockProduct(weight_kg=0.5, length_cm=60, width_cm=40, height_cm=30)
    cost = calc_shipping_cost(prod, params)
    rate = params["shipping"]["rates"]["sea_lcl"]
    expected = rate["base_fee"] + rate["per_kg"] * 12.0
    assert cost == pytest.approx(expected)


def test_shipping_requires_weight_and_dimensions():
    params = profit_model.load_profit_params()
    product = _MockProduct(weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
    with pytest.raises(InsufficientCostEvidence, match="weight_kg") as exc_info:
        calc_shipping_cost(product, params)
    assert exc_info.value.fields == ["weight_kg", "length_cm", "width_cm", "height_cm"]


# ============================================================
# calc_fba_fee
# ============================================================
def test_calc_fba_fee_small_standard():
    params = profit_model.load_profit_params()
    # 最长边 20cm(7.87in) < 15in 不成立，应落入 large_standard
    prod = _MockProduct(weight_kg=0.3, length_cm=20, width_cm=15, height_cm=5)
    fee = calc_fba_fee(prod, params)
    assert fee > 0


def test_calc_fba_fee_large_product():
    params = profit_model.load_profit_params()
    # 120cm 最长边 = 47.2in < 60in → small_oversize；160cm = 63in > 60in → medium_oversize
    prod_small_os = _MockProduct(weight_kg=10.0, length_cm=120, width_cm=60, height_cm=40)
    assert calc_fba_fee(prod_small_os, params) == pytest.approx(
        params["fba"]["fulfillment_fees"]["small_oversize"]["fee_usd"]
    )

    prod_medium_os = _MockProduct(weight_kg=10.0, length_cm=160, width_cm=60, height_cm=40)
    assert calc_fba_fee(prod_medium_os, params) == pytest.approx(
        params["fba"]["fulfillment_fees"]["medium_oversize"]["fee_usd"]
    )


def test_fba_fee_requires_weight_and_dimensions():
    params = profit_model.load_profit_params()
    product = _MockProduct(weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
    with pytest.raises(InsufficientCostEvidence) as exc_info:
        calc_fba_fee(product, params)
    assert exc_info.value.fields == ["weight_kg", "length_cm", "width_cm", "height_cm"]


# ============================================================
# calc_commission
# ============================================================
def test_calc_commission_default_category():
    params = profit_model.load_profit_params()
    prod = _MockProduct(price=30.0, category="Unknown")
    fee = calc_commission(prod, params)
    assert fee == pytest.approx(30.0 * params["commission_rates"]["default"])


def test_calc_commission_electronics():
    params = profit_model.load_profit_params()
    prod = _MockProduct(price=100.0, category="Electronics")
    fee = calc_commission(prod, params)
    assert fee == pytest.approx(100.0 * 0.08)


# ============================================================
# calc_ad_cost
# ============================================================
def test_calc_ad_cost():
    params = profit_model.load_profit_params()
    prod = _MockProduct(price=40.0)
    cost = calc_ad_cost(prod, params)
    ad = params["ad_cost"]
    expected = 40.0 * ad["default_acos"] * ad["ad_spend_ratio"]
    assert cost == pytest.approx(expected)


# ============================================================
# calc_return_loss
# ============================================================
def test_calc_return_loss_home_kitchen():
    params = profit_model.load_profit_params()
    prod = _MockProduct(price=30.0, category="Home & Kitchen")
    loss = calc_return_loss(prod, params)
    returns = params["returns"]
    rate = returns["by_category"]["Home & Kitchen"]
    expected = 30.0 * rate * returns["return_loss_ratio"]
    assert loss == pytest.approx(expected)


# ============================================================
# predict_profit 集成
# ============================================================
def test_predict_profit_end_to_end():
    pb = predict_profit(_MockProduct(), _MockSupplier())
    assert pb.selling_price == pytest.approx(29.99)
    assert pb.total_cost > 0
    assert -1.0 < pb.profit_margin < 1.0   # 利润率在合理区间


def test_predict_profit_margin_reasonable():
    """标准小件产品利润率应在 -20% ~ 70% 之间。"""
    pb = predict_profit(_MockProduct(), _MockSupplier())
    assert -0.20 < pb.profit_margin < 0.70


@pytest.mark.parametrize("price", [None, 0, float("nan"), float("inf")])
def test_predict_profit_rejects_missing_or_invalid_selling_price(price):
    product = _MockProduct(price=price)
    with pytest.raises(InsufficientCostEvidence) as exc_info:
        predict_profit(product, _MockSupplier())
    assert exc_info.value.fields == ["selling_price"]

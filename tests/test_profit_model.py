"""利润模型单测。"""
import pytest

from analyzers import profit_model


def test_profit_params_loadable():
    p = profit_model.load_profit_params()
    assert "shipping" in p
    assert "fba" in p
    assert "commission_rates" in p


def test_profit_breakdown_math():
    """ProfitBreakdown 的派生属性应数学一致。"""
    pb = profit_model.ProfitBreakdown(
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

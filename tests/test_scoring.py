"""评分引擎单测。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from analyzers import scorer
from analyzers.scorer import (
    ScoreBreakdown,
    apply_hard_filters,
    load_weights_config,
    score_competition,
    score_demand,
    score_logistics,
    score_profit,
    score_product,
    score_risk,
    score_supply,
)
from analyzers.profit_model import ProfitBreakdown


# ============================================================
# Mock 对象
# ============================================================
@dataclass
class _MockProduct:
    asin: str = "B0TEST1234"
    title: str = "Test Product"
    brand: str = "Generic"
    category: str = "Home & Kitchen"
    price: float = 29.99
    bsr_rank: int = 5000
    rating: float = 4.3
    review_count: int = 150
    weight_kg: float = 0.8
    length_cm: float = 30.0
    width_cm: float = 20.0
    height_cm: float = 10.0
    listing_url: Optional[str] = None
    main_image_url: Optional[str] = None


@dataclass
class _MockSupplier:
    alibaba_offer_id: str = "sup001"
    moq: int = 100
    repeat_buyer_rate: float = 0.35
    base_price_cny: float = 35.0
    is_factory: bool = True
    delivery_days: Optional[int] = 20
    fba_ready: Optional[bool] = True
    monthly_sales: int = 400


@dataclass
class _MockMarket:
    opportunity_score: float = 0.08
    search_volume_monthly: int = 3000
    est_daily_sales: Optional[int] = 20
    est_monthly_sales: Optional[int] = 600
    competing_listings: int = 60
    top10_revenue_share: float = 0.5
    seasonality: Optional[dict] = None


def _make_profit(margin: float = 0.30, price: float = 29.99) -> ProfitBreakdown:
    net = price * margin
    cost = price - net
    return ProfitBreakdown(
        selling_price=price,
        purchase_cost=cost * 0.5,
        shipping_cost=cost * 0.15,
        fba_fee=cost * 0.20,
        commission=cost * 0.10,
        ad_cost=cost * 0.03,
        return_loss=cost * 0.01,
        exchange_loss=cost * 0.01,
    )


# ============================================================
# 权重校验
# ============================================================
def test_weights_sum_to_one():
    config = load_weights_config()
    weights = config["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-6


# ============================================================
# score_profit
# ============================================================
class TestScoreProfit:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["profit"]

    def test_below_floor_returns_zero(self):
        assert score_profit(0.05, self._curve()) == 0.0

    def test_at_floor_returns_zero(self):
        assert score_profit(0.10, self._curve()) == 0.0

    def test_at_ceiling_returns_one(self):
        assert score_profit(0.50, self._curve()) == 1.0

    def test_above_ceiling_returns_one(self):
        assert score_profit(0.80, self._curve()) == 1.0

    def test_at_target_returns_approx_half(self):
        s = score_profit(0.30, self._curve())
        assert 0.45 < s < 0.55

    def test_monotone_increasing(self):
        c = self._curve()
        scores = [score_profit(m / 100, c) for m in range(0, 60, 5)]
        assert scores == sorted(scores)

    def test_output_in_range(self):
        c = self._curve()
        for m in [0.0, 0.15, 0.25, 0.30, 0.45, 0.60]:
            s = score_profit(m, c)
            assert 0.0 <= s <= 1.0


# ============================================================
# score_demand
# ============================================================
class TestScoreDemand:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["demand"]

    def test_high_opportunity_gives_high_score(self):
        s = score_demand(
            bsr_rank=1000, monthly_sales=500, curve=self._curve(),
            opportunity_score=0.15, daily_revenue_top100=80,
            search_volume_monthly=5000,
        )
        assert s > 0.7

    def test_no_opportunity_low_score(self):
        s = score_demand(
            bsr_rank=40000, monthly_sales=50, curve=self._curve(),
            opportunity_score=0.01, search_volume_monthly=300,
        )
        assert s < 0.4

    def test_google_trends_bonus(self):
        c = self._curve()
        base = score_demand(1000, 300, c, opportunity_score=0.06)
        with_bonus = score_demand(1000, 300, c, opportunity_score=0.06, google_trends_up=True)
        assert with_bonus >= base

    def test_price_below_floor_caps_score(self):
        s = score_demand(
            bsr_rank=500, monthly_sales=1000, curve=self._curve(),
            opportunity_score=0.20, search_volume_monthly=10000,
            price=10.0,
        )
        assert s <= 0.5

    def test_output_in_range(self):
        c = self._curve()
        for bsr, ms in [(100, 2000), (5000, 300), (50000, 50)]:
            assert 0.0 <= score_demand(bsr, ms, c) <= 1.0


# ============================================================
# score_competition
# ============================================================
class TestScoreCompetition:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["competition"]

    def test_low_sellers_high_score(self):
        s = score_competition(10, 0.4, self._curve())
        assert s > 0.8

    def test_many_sellers_low_score(self):
        s = score_competition(300, 0.3, self._curve())
        assert s < 0.3

    def test_brand_monopoly_penalty(self):
        c = self._curve()
        normal = score_competition(50, 0.4, c)
        penalized = score_competition(50, 0.4, c, has_brand_monopoly=True)
        assert penalized < normal

    def test_top4_concentration_penalty(self):
        c = self._curve()
        normal = score_competition(50, 0.4, c, top4_sales_share=0.30)
        penalized = score_competition(50, 0.4, c, top4_sales_share=0.60)
        assert penalized < normal

    def test_low_review_opportunity_bonus(self):
        c = self._curve()
        base = score_competition(50, 0.4, c, bsr20_low_review_count=3)
        bonus = score_competition(50, 0.4, c, bsr20_low_review_count=6)
        assert bonus >= base

    def test_output_in_range(self):
        c = self._curve()
        for n, share in [(5, 0.3), (100, 0.6), (300, 0.9)]:
            assert 0.0 <= score_competition(n, share, c) <= 1.0


# ============================================================
# score_supply
# ============================================================
class TestScoreSupply:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["supply"]

    def test_empty_suppliers_zero(self):
        assert score_supply([], self._curve()) == 0.0

    def test_good_suppliers_high_score(self):
        sups = [_MockSupplier() for _ in range(4)]
        s = score_supply(sups, self._curve())
        assert s > 0.6

    def test_high_moq_reduces_score(self):
        c = self._curve()
        low = [_MockSupplier(moq=50)]
        high = [_MockSupplier(moq=600)]
        assert score_supply(low, c) > score_supply(high, c)

    def test_fba_ready_bonus(self):
        c = self._curve()
        no_fba = [_MockSupplier(fba_ready=False)]
        with_fba = [_MockSupplier(fba_ready=True)]
        assert score_supply(with_fba, c) >= score_supply(no_fba, c)

    def test_output_in_range(self):
        c = self._curve()
        for n in [1, 3, 6]:
            s = score_supply([_MockSupplier() for _ in range(n)], c)
            assert 0.0 <= s <= 1.0


# ============================================================
# score_logistics
# ============================================================
class TestScoreLogistics:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["logistics"]

    def test_dangerous_attr_returns_zero(self):
        assert score_logistics(0.5, 10, 10, 5, ["battery"], self._curve()) == 0.0

    def test_liquid_returns_zero(self):
        assert score_logistics(0.3, 8, 8, 4, ["liquid"], self._curve()) == 0.0

    def test_light_small_product_high_score(self):
        s = score_logistics(0.3, 15, 10, 5, [], self._curve())
        assert s > 0.7

    def test_heavy_large_product_low_score(self):
        s = score_logistics(5.0, 80, 60, 40, [], self._curve())
        assert s < 0.4

    def test_bad_volumetric_ratio_reduces_score(self):
        c = self._curve()
        # 体积重 = 60×40×30/6000 = 12kg，实重 0.5kg，比 24
        bad = score_logistics(0.5, 60, 40, 30, [], c)
        # 体积重 = 10×10×10/6000 = 0.17kg，实重 0.5kg，比 0.33
        good = score_logistics(0.5, 10, 10, 10, [], c)
        assert good > bad

    def test_output_in_range(self):
        c = self._curve()
        for w, l, wd, h in [(0.3, 15, 10, 5), (1.5, 35, 25, 15), (3.0, 60, 40, 30)]:
            s = score_logistics(w, l, wd, h, [], c)
            assert 0.0 <= s <= 1.0


# ============================================================
# score_risk
# ============================================================
class TestScoreRisk:
    def _curve(self):
        return load_weights_config()["scoring_curves"]["risk"]

    def test_clean_product_full_score(self):
        s = score_risk("Home & Kitchen", "Generic Brand", self._curve())
        assert s == pytest.approx(1.0)

    def test_known_brand_penalized(self):
        s = score_risk("Electronics", "Apple", self._curve())
        assert s < 0.6

    def test_cert_category_penalized(self):
        s = score_risk("Toys & Games > Infant Toys", "Generic", self._curve())
        assert s < 0.8

    def test_seasonal_product_penalized(self):
        seasonal = {f"month_{i}": (100 if i in (11, 12) else 5) for i in range(1, 13)}
        s = score_risk("Home", "Generic", self._curve(), seasonality=seasonal)
        assert s < 0.8

    def test_output_in_range(self):
        c = self._curve()
        for cat, brand in [
            ("Home & Kitchen", "SomeBrand"),
            ("Toys & Games > Infant Toys", "Kids Co"),
            ("Electronics", "apple"),
        ]:
            s = score_risk(cat, brand, c)
            assert 0.0 <= s <= 1.0


# ============================================================
# apply_hard_filters
# ============================================================
class TestApplyHardFilters:
    def _cfg(self):
        return load_weights_config()

    def test_all_good_passes(self):
        passed, reasons = apply_hard_filters(
            profit_margin=0.30, total_score=70,
            moq=100, supplier_count=3, brand="Generic",
            config=self._cfg(), monthly_sales=500, selling_price=25.0,
        )
        assert passed is True
        assert reasons == []

    def test_low_margin_rejected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.10, total_score=70,
            moq=100, supplier_count=3, brand="Generic",
            config=self._cfg(),
        )
        assert "margin_too_low" in reasons

    def test_low_score_rejected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.30, total_score=40,
            moq=100, supplier_count=3, brand="Generic",
            config=self._cfg(),
        )
        assert "score_too_low" in reasons

    def test_high_moq_rejected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.30, total_score=70,
            moq=600, supplier_count=3, brand="Generic",
            config=self._cfg(),
        )
        assert "moq_exceeded" in reasons

    def test_no_supplier_rejected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.30, total_score=70,
            moq=None, supplier_count=0, brand="Generic",
            config=self._cfg(),
        )
        assert "no_supplier" in reasons

    def test_low_monthly_sales_rejected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.30, total_score=70,
            moq=100, supplier_count=3, brand="Generic",
            config=self._cfg(), monthly_sales=50,
        )
        assert "monthly_sales_too_low" in reasons

    def test_multiple_failures_collected(self):
        _, reasons = apply_hard_filters(
            profit_margin=0.05, total_score=30,
            moq=600, supplier_count=0, brand="Generic",
            config=self._cfg(),
        )
        assert len(reasons) >= 3


# ============================================================
# score_product 集成
# ============================================================
class TestScoreProduct:
    def test_returns_score_breakdown(self):
        sb = score_product(
            product=_MockProduct(),
            profit_breakdown=_make_profit(0.30),
            market_analysis=_MockMarket(),
            suppliers=[_MockSupplier() for _ in range(3)],
        )
        assert isinstance(sb, ScoreBreakdown)
        assert 0 <= sb.total_score <= 100

    def test_high_quality_product_passes(self):
        sb = score_product(
            product=_MockProduct(bsr_rank=2000, price=35.0, weight_kg=0.5),
            profit_breakdown=_make_profit(0.35),
            market_analysis=_MockMarket(opportunity_score=0.10, search_volume_monthly=5000),
            suppliers=[_MockSupplier() for _ in range(3)],
        )
        assert sb.total_score > 50

    def test_known_brand_fails_filter(self):
        sb = score_product(
            product=_MockProduct(brand="Apple"),
            profit_breakdown=_make_profit(0.30),
            market_analysis=_MockMarket(),
            suppliers=[_MockSupplier()],
        )
        assert sb.passed_hard_filter is False
        assert "brand_excluded" in sb.rejection_reasons

    def test_no_market_data_still_works(self):
        sb = score_product(
            product=_MockProduct(),
            profit_breakdown=_make_profit(0.25),
            market_analysis=None,
            suppliers=[_MockSupplier()],
        )
        assert isinstance(sb, ScoreBreakdown)

    def test_low_estimated_monthly_sales_rejected(self):
        sb = score_product(
            product=_MockProduct(),
            profit_breakdown=_make_profit(0.35),
            market_analysis=_MockMarket(est_monthly_sales=50, search_volume_monthly=10000),
            suppliers=[_MockSupplier() for _ in range(3)],
        )
        assert sb.passed_hard_filter is False
        assert "monthly_sales_too_low" in sb.rejection_reasons

    def test_search_volume_does_not_count_as_monthly_sales(self):
        sb = score_product(
            product=_MockProduct(),
            profit_breakdown=_make_profit(0.35),
            market_analysis=_MockMarket(est_monthly_sales=None, search_volume_monthly=50),
            suppliers=[_MockSupplier() for _ in range(3)],
        )
        assert "monthly_sales_too_low" not in sb.rejection_reasons

    def test_all_dimension_scores_in_range(self):
        sb = score_product(
            product=_MockProduct(),
            profit_breakdown=_make_profit(0.30),
            market_analysis=_MockMarket(),
            suppliers=[_MockSupplier() for _ in range(3)],
        )
        for dim in (sb.profit_score, sb.demand_score, sb.competition_score,
                    sb.supply_score, sb.logistics_score, sb.risk_score):
            assert 0.0 <= dim <= 1.0

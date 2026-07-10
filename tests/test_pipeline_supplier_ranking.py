from __future__ import annotations

from crawlers.amazon_bsr import ProductDTO
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.orchestrator import _rank_suppliers_by_profit


def test_supplier_profit_signal_can_reorder_close_matches():
    product = ProductDTO(
        asin="BPROFIT",
        marketplace="US",
        title="Test product",
        price=29.99,
        weight_kg=0.4,
        length_cm=10,
        width_cm=8,
        height_cm=6,
    )
    expensive = SupplierDTO(
        alibaba_offer_id="100000001",
        supplier_name="Expensive closer match",
        base_price_cny=120,
        match_quality_score=0.70,
        raw_data={"supplier_candidate_score": 0.70},
    )
    profitable = SupplierDTO(
        alibaba_offer_id="100000002",
        supplier_name="Profitable good match",
        base_price_cny=15,
        match_quality_score=0.62,
        raw_data={"supplier_candidate_score": 0.62},
    )
    suppliers = [expensive, profitable]

    best_profit = _rank_suppliers_by_profit(product, suppliers)

    assert suppliers[0].alibaba_offer_id == "100000002"
    assert best_profit is not None
    assert suppliers[0].raw_data["supplier_profit_margin"] > suppliers[1].raw_data["supplier_profit_margin"]
    assert suppliers[0].raw_data["supplier_rank_score"] > suppliers[1].raw_data["supplier_rank_score"]
    assert "supplier_net_profit" in suppliers[0].raw_data

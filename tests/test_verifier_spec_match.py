"""1688 verifier spec match integration tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.cancellation import CancellationRequested
from matchers.alibaba_pailitao import SupplierDTO
from matchers.verifier import Alibaba1688Verifier, LLMVisualVerifier, llm_eligible_suppliers


def _product():
    return SimpleNamespace(
        asin="B0TEST",
        title="Stainless Steel Insulated Water Bottle 24oz 2 Pack",
        category="Home & Kitchen",
        brand="Generic",
        price=29.99,
        weight_kg=0.4,
        length_cm=7.6,
        width_cm=7.6,
        height_cm=25.4,
    )


def _analysis():
    return SimpleNamespace(
        category_zh="保温杯",
        material="不锈钢",
        color=None,
        key_features=["保温", "吸管"],
        has_dangerous_attr=False,
    )


def test_verifier_records_spec_match_and_penalizes_conflicts():
    suppliers = [
        SupplierDTO(
            alibaba_offer_id="1001",
            supplier_name="匹配工厂",
            title_cn="304不锈钢保温杯 700ml 2只装 带吸管",
            base_price_cny=20,
            raw_data={"full_text": "304不锈钢保温杯 700ml 2只装 带吸管 7.5x7.5x25cm"},
        ),
        SupplierDTO(
            alibaba_offer_id="1002",
            supplier_name="冲突工厂",
            title_cn="304不锈钢保温杯 350ml 1只装",
            base_price_cny=12,
            raw_data={"full_text": "304不锈钢保温杯 350ml 1只装"},
        ),
    ]

    result = Alibaba1688Verifier(threshold_demote=0.0).verify(
        suppliers,
        _product(),
        _analysis(),
        ["不锈钢保温杯", "保温杯"],
    )

    assert result[0].alibaba_offer_id == "1001"
    assert result[0].raw_data["spec_match"]["score"] > result[1].raw_data["spec_match"]["score"]
    assert result[0].raw_data["target_spec"]["category"] == "保温杯"
    assert result[0].raw_data["target_spec"]["material"] == "不锈钢"
    assert "capacity" in result[1].raw_data["spec_match"]["conflicts"]
    assert "pack_count" in result[1].raw_data["spec_match"]["conflicts"]
    assert (result[0].match_quality_score or 0) > (result[1].match_quality_score or 0)


def test_all_low_quality_suppliers_are_not_reintroduced():
    supplier = SupplierDTO(
        alibaba_offer_id="irrelevant",
        supplier_name="无关工厂",
        title_cn="完全无关的工业轴承",
        base_price_cny=10,
    )

    result = Alibaba1688Verifier(threshold_demote=0.4).verify(
        [supplier],
        _product(),
        analysis=_analysis(),
        search_keywords=["瑜伽垫"],
    )

    assert result == []
    assert supplier.match_verification_method == "heuristic_rejected"


def test_pest_control_category_gate_rejects_high_sales_cookware():
    product = SimpleNamespace(
        asin="B00E4GACB8",
        title="TERRO Liquid Ant Killer Bait Stations, 12 Count",
        category="Home & Kitchen",
        brand="TERRO",
        main_image_url="https://example.test/terro.jpg",
        weight_kg=None,
        length_cm=None,
        width_cm=None,
        height_cm=None,
    )
    cookware = SupplierDTO(
        alibaba_offer_id="cookware-12",
        supplier_name="厨具工厂",
        title_cn="硅胶锅铲厨具12件套厨房烹饪工具",
        monthly_sales=50000,
        offer_image_url="https://example.test/cookware.jpg",
        raw_data={"full_text": "硅胶锅铲厨具12件套厨房烹饪工具"},
    )
    bait = SupplierDTO(
        alibaba_offer_id="ant-bait",
        supplier_name="灭虫用品工厂",
        title_cn="室内灭蚁饵剂蚂蚁诱饵盒12只装",
        monthly_sales=100,
        raw_data={"full_text": "室内灭蚁饵剂蚂蚁诱饵盒12只装 液体"},
    )

    result = Alibaba1688Verifier(threshold_demote=0.0).verify(
        [cookware, bait],
        product,
        analysis=None,
        search_keywords=["灭蚁饵剂 12件套", "灭蚁饵剂"],
    )

    assert [supplier.alibaba_offer_id for supplier in result] == ["ant-bait"]
    assert cookware.match_quality_score == 0.0
    assert "category" in cookware.raw_data["spec_match"]["conflicts"]


def test_bedding_category_gate_rejects_kitchen_container():
    product = SimpleNamespace(
        asin="B00Q7OAPM6",
        title="Microfiber 4 Piece Bed Sheet Set with Deep Pockets",
        category="Home & Kitchen",
        brand="Amazon Basics",
        main_image_url=None,
        weight_kg=1.1,
        length_cm=22.86,
        width_cm=22.86,
        height_cm=8.25,
    )
    supplier = SupplierDTO(
        alibaba_offer_id="bowl-1",
        supplier_name="餐盒工厂",
        title_cn="玻璃保鲜盒便当盒带盖餐盒",
        monthly_sales=50000,
        raw_data={"full_text": "玻璃保鲜盒便当盒带盖餐盒"},
    )

    result = Alibaba1688Verifier(threshold_demote=0.0).verify(
        [supplier], product, analysis=None, search_keywords=["床品套件", "床笠"]
    )

    assert result == []
    assert "category" in supplier.raw_data["spec_match"]["conflicts"]


def test_verifier_uses_visual_similarity_as_ranking_signal():
    suppliers = [
        SupplierDTO(
            alibaba_offer_id="low-image",
            supplier_name="低图像相似工厂",
            title_cn="304不锈钢保温杯 700ml 2只装 带吸管",
            image_similarity=0.25,
            base_price_cny=20,
            raw_data={"full_text": "304不锈钢保温杯 700ml 2只装 带吸管"},
        ),
        SupplierDTO(
            alibaba_offer_id="high-image",
            supplier_name="高图像相似工厂",
            title_cn="304不锈钢保温杯 700ml 2只装 带吸管",
            image_similarity=0.95,
            base_price_cny=21,
            raw_data={"full_text": "304不锈钢保温杯 700ml 2只装 带吸管"},
        ),
    ]

    result = Alibaba1688Verifier(threshold_demote=0.0).verify(
        suppliers,
        _product(),
        _analysis(),
        ["不锈钢保温杯", "保温杯"],
    )

    assert result[0].alibaba_offer_id == "high-image"
    assert result[0].raw_data["visual_match"] == {
        "score": 0.95,
        "source": "image_similarity",
    }
    assert (result[0].match_quality_score or 0) > (result[1].match_quality_score or 0)


def test_verifier_uses_supplier_quality_as_candidate_tiebreaker():
    suppliers = [
        SupplierDTO(
            alibaba_offer_id="trader-low-quality",
            supplier_name="贸易商",
            title_cn="304不锈钢保温杯 700ml 2只装 带吸管",
            image_similarity=0.9,
            base_price_cny=20,
            moq=300,
            monthly_sales=20,
            repeat_buyer_rate=0.05,
            is_factory=False,
            delivery_days=35,
            raw_data={"full_text": "304不锈钢保温杯 700ml 2只装 带吸管"},
        ),
        SupplierDTO(
            alibaba_offer_id="factory-high-quality",
            supplier_name="源头工厂",
            title_cn="304不锈钢保温杯 700ml 2只装 带吸管",
            image_similarity=0.9,
            base_price_cny=20,
            moq=50,
            monthly_sales=3500,
            repeat_buyer_rate=0.48,
            is_factory=True,
            delivery_days=7,
            raw_data={"full_text": "304不锈钢保温杯 700ml 2只装 带吸管"},
        ),
    ]

    result = Alibaba1688Verifier(threshold_demote=0.0).verify(
        suppliers,
        _product(),
        _analysis(),
        ["不锈钢保温杯", "保温杯"],
    )

    assert result[0].alibaba_offer_id == "factory-high-quality"
    assert result[0].raw_data["supplier_quality_score"] > result[1].raw_data["supplier_quality_score"]
    assert result[0].raw_data["supplier_candidate_score"] > result[1].raw_data["supplier_candidate_score"]


def test_llm_visual_verifier_honors_cancel_check_before_network(monkeypatch):
    monkeypatch.setattr(LLMVisualVerifier, "__init__", lambda self: None)
    verifier = LLMVisualVerifier()
    product = SimpleNamespace(main_image_url="https://example.com/amazon.jpg")
    supplier = SupplierDTO(
        alibaba_offer_id="cancel-llm",
        supplier_name="可取消工厂",
        offer_image_url="https://example.com/supplier.jpg",
    )

    with pytest.raises(CancellationRequested):
        verifier.verify([supplier], product, cancel_check=lambda: True)


def test_llm_eligibility_requires_heuristic_and_spec_evidence():
    good = SupplierDTO(
        alibaba_offer_id="good",
        supplier_name="Good",
        offer_image_url="https://example.com/good.jpg",
        match_quality_score=0.72,
        raw_data={"spec_match": {"score": 0.66, "conflicts": []}},
    )
    weak = SupplierDTO(
        alibaba_offer_id="weak",
        supplier_name="Weak",
        offer_image_url="https://example.com/weak.jpg",
        match_quality_score=0.51,
        raw_data={"spec_match": {"score": 0.66, "conflicts": []}},
    )
    conflict = SupplierDTO(
        alibaba_offer_id="conflict",
        supplier_name="Conflict",
        offer_image_url="https://example.com/conflict.jpg",
        match_quality_score=0.84,
        raw_data={"spec_match": {"score": 0.8, "conflicts": ["category"]}},
    )

    assert llm_eligible_suppliers([good, weak, conflict], min_match_quality=0.65, min_spec_score=0.5) == [good]

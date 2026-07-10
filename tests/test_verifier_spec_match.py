"""1688 verifier spec match integration tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.cancellation import CancellationRequested
from matchers.alibaba_pailitao import SupplierDTO
from matchers.verifier import Alibaba1688Verifier, LLMVisualVerifier


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


def test_verifier_keeps_rejected_fallback_for_manual_review():
    supplier = SupplierDTO(
        alibaba_offer_id="123456789",
        supplier_name="低相关工厂",
        title_cn="木质桌面收纳盒",
        base_price_cny=10,
    )

    result = Alibaba1688Verifier().verify(
        [supplier],
        _product(),
        _analysis(),
        ["不锈钢保温杯"],
    )

    assert len(result) == 1
    assert result[0].match_verification_method == "heuristic_rejected"
    assert result[0].raw_data["target_spec"]["category"] == "保温杯"
    assert result[0].raw_data["spec_match"]["conflicts"] == ["title_relevance"]


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

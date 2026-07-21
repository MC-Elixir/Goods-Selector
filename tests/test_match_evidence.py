from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from matchers.alibaba_pailitao import SupplierDTO
from matchers.match_evidence import build_match_evidence
from schemas.sourcing import AmazonProductUnderstanding, VisionMatchResult


def _understanding(**updates):
    values = {
        "asin": "B000TEST",
        "original_title_en": "four replacement filters",
        "generic_product_name": "净水滤芯",
        "supply_chain_name_cn": "净水器替换滤芯",
        "category": "净水设备配件",
        "function": ["过滤饮用水"],
        "material": ["活性炭"],
        "components": ["滤芯"],
        "package_quantity": 4,
        "dimensions_visible": ["容量 700ml"],
        "replaceable_part_or_full_product": "replacement",
        "excluded_brand_tokens": ["Acme"],
        "model_provider": "fake",
        "model_name": "fake-v1",
        "prompt_version": "amazon-understanding-v1",
    }
    values.update(updates)
    return AmazonProductUnderstanding(**values)


def _supplier(detail=None, **updates):
    values = {
        "alibaba_offer_id": "123",
        "title_cn": "通用活性炭净水器替换滤芯 4只装 700ml",
        "base_price_cny": 12.5,
        "moq": 20,
        "raw_data": {"detail": detail if detail is not None else {
            "product_type": "replacement",
            "package_quantity": 4,
            "function": "过滤饮用水",
            "brand_compatibility": "universal",
            "capacity_ml": 700,
        }},
    }
    values.update(updates)
    supplier = SupplierDTO(**values)
    detail_data = supplier.raw_data["detail"]
    observed = datetime.now(timezone.utc).isoformat()
    evidence_values = {
        **detail_data,
        "base_price_cny": detail_data.get("base_price_cny", supplier.base_price_cny),
        "price_tiers": detail_data.get("price_tiers", supplier.price_tiers),
        "moq": detail_data.get("moq", supplier.moq),
    }
    detail_data["provenance"] = {
        key: {"status": "extracted", "source_type": "offer_detail", "source_ref": "artifact:offer-123",
              "observed_at": observed, "confidence": 0.95}
        for key, value in evidence_values.items() if value is not None and key != "provenance"
    }
    for key in ("base_price_cny", "price_tiers", "moq"):
        if evidence_values[key] is not None:
            detail_data.setdefault(key, evidence_values[key])
    return supplier


def test_replacement_filter_does_not_match_full_machine():
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": "full_product", "package_quantity": 4, "function": "过滤饮用水"}),
    )
    assert result.decision == "reject"
    assert "accessory_full_product_conflict" in result.mismatch_reasons


def test_single_item_does_not_match_four_pack():
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": "replacement", "package_quantity": 1, "function": "过滤饮用水"}),
    )
    assert result.decision == "reject"
    assert "package_quantity_conflict" in result.mismatch_reasons


def test_different_core_function_is_a_hard_conflict():
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": "replacement", "package_quantity": 4, "function": "装饰水杯"}),
    )
    assert result.decision == "reject"
    assert "core_function_conflict" in result.mismatch_reasons


def test_brand_exclusive_part_does_not_match_generic_requirement():
    result = build_match_evidence(
        _understanding(),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "过滤饮用水", "brand_compatibility": "Acme only",
        }),
    )
    assert result.decision == "reject"
    assert "brand_exclusive_conflict" in result.mismatch_reasons


def test_missing_function_and_pack_cannot_receive_high_confidence():
    result = build_match_evidence(_understanding(), _supplier({}, title_cn="活性炭滤芯"))
    assert result.decision in {"retry", "manual_review"}
    assert result.overall_confidence <= 0.49
    assert {"function", "package_quantity"} <= set(result.missing_evidence)


@pytest.mark.parametrize(("field", "updates"), [
    ("price", {"base_price_cny": None, "price_tiers": []}),
    ("moq", {"moq": None}),
])
def test_missing_commercial_evidence_cannot_keep(field, updates):
    result = build_match_evidence(_understanding(), _supplier(**updates))
    assert result.decision in {"retry", "manual_review"}
    assert result.overall_confidence <= 0.49
    assert field in result.missing_evidence


def test_detail_base_price_is_used_even_when_price_tiers_are_malformed():
    supplier = _supplier(base_price_cny=None, price_tiers={"broken": True})
    supplier.raw_data["detail"]["base_price_cny"] = 13.5
    supplier.raw_data["detail"]["provenance"]["base_price_cny"] = {
        "status": "extracted", "source_type": "offer_detail", "source_ref": "artifact:offer-123",
        "observed_at": datetime.now(timezone.utc).isoformat(), "confidence": 0.95,
    }
    result = build_match_evidence(_understanding(), supplier)
    assert "price" in result.passed_reasons
    assert "price" not in result.missing_evidence


@pytest.mark.parametrize("tier", [
    {"min_qty": 10, "price_cny": math.nan},
    {"min_qty": math.inf, "price_cny": 12},
    {"price_cny": 12},
    {"min_qty": 10},
])
def test_malformed_price_tier_is_not_price_evidence(tier):
    result = build_match_evidence(
        _understanding(),
        _supplier(base_price_cny=None, price_tiers=[tier]),
    )
    assert "price" in result.missing_evidence
    assert result.decision in {"retry", "manual_review"}


def test_valid_price_tier_requires_positive_finite_quantity_and_price():
    result = build_match_evidence(
        _understanding(),
        _supplier(base_price_cny=None, price_tiers=[{"min_qty": 10, "price_cny": 12}]),
    )
    assert "price" in result.passed_reasons


def test_explicit_key_spec_conflict_is_hard_negative():
    result = build_match_evidence(
        _understanding(),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "过滤饮用水", "capacity_ml": 350,
        }),
    )
    assert result.decision == "reject"
    assert "specification_conflict:capacity" in result.mismatch_reasons


def test_short_chinese_function_does_not_reverse_match_specific_requirement():
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": "replacement", "package_quantity": 4, "function": "水"}),
    )
    assert result.function_match == 0.0
    assert result.decision == "reject"


def test_ascii_function_requires_token_boundaries():
    result = build_match_evidence(
        _understanding(function=["filter water"]),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "prefilter watering attachment",
        }),
    )
    assert result.function_match == 0.0
    assert result.decision == "reject"


def test_expected_function_phrase_can_match_longer_observed_text():
    result = build_match_evidence(
        _understanding(function=["filter water"]),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "replacement cartridge to filter water for drinking",
        }),
    )
    assert result.function_match == 1.0


def test_title_alone_is_not_decision_grade_function_evidence():
    result = build_match_evidence(
        _understanding(function=["filter water"]),
        _supplier(
            {"product_type": "replacement", "package_quantity": 4},
            title_cn="replacement cartridge to filter water for drinking",
        ),
    )
    assert result.function_match is None
    assert "function" in result.missing_evidence
    assert result.decision != "keep"


def test_same_product_type_group_uses_semantics_not_literal_label():
    result = build_match_evidence(
        _understanding(replaceable_part_or_full_product="replacement"),
        _supplier({"product_type": "component", "package_quantity": 4, "function": "过滤饮用水"}),
    )
    assert result.accessory_vs_full_product_match == 1.0
    assert "accessory_full_product_conflict" not in result.mismatch_reasons


@pytest.mark.parametrize("supplier_type", [None, "unknown", "???", 123])
def test_unknown_or_malformed_product_type_is_missing_not_hard_conflict(supplier_type):
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": supplier_type, "package_quantity": 4, "function": "过滤饮用水"}),
    )
    assert result.accessory_vs_full_product_match is None
    assert "product_type" in result.missing_evidence
    assert "accessory_full_product_conflict" not in result.mismatch_reasons


def test_full_machine_alias_still_hard_conflicts_with_component_side():
    result = build_match_evidence(
        _understanding(),
        _supplier({"product_type": "整机", "package_quantity": 4, "function": "过滤饮用水"}),
    )
    assert result.accessory_vs_full_product_match == 0.0
    assert result.decision == "reject"


def test_visual_false_is_hard_negative_and_classification_confidence_is_not_similarity():
    result = build_match_evidence(
        _understanding(), _supplier(),
        visual={"is_match": False, "classification_confidence": 0.99, "score": 0.0},
    )
    assert result.decision == "reject"
    assert result.visual_is_match is False
    assert result.visual_confidence == 0.99
    assert "visual_mismatch" in result.mismatch_reasons
    assert result.image_similarity is None


def test_visual_accessory_full_product_false_maps_to_hard_type_mismatch():
    visual = VisionMatchResult(
        same_product_type=True,
        same_core_function=True,
        same_accessory_full_product_relation=False,
        same_structure=True,
        same_material=True,
        same_package_quantity=True,
        major_visual_differences=["替换件与整机"],
        potential_mismatch=["产品关系冲突"],
        confidence=0.99,
        evidence=["Amazon 是替换件，1688 是整机"],
        provider="fake",
        model="fake",
        prompt_version="supplier-visual-match-v1",
    ).model_dump()
    result = build_match_evidence(_understanding(), _supplier(), visual=visual)
    assert result.decision == "reject"
    assert result.accessory_vs_full_product_match == 0.0
    assert "accessory_full_product_conflict" in result.mismatch_reasons


def test_complete_positive_evidence_passes_minimum_threshold():
    result = build_match_evidence(
        _understanding(), _supplier(),
        visual={"is_match": True, "classification_confidence": 0.9},
    )
    assert result.decision == "keep"
    assert result.overall_confidence >= 0.7
    assert not result.mismatch_reasons
    assert not result.missing_evidence
    assert {"function", "package_quantity", "product_type", "price", "moq"} <= set(result.passed_reasons)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_non_finite_commercial_values_fail_closed(bad_value):
    result = build_match_evidence(
        _understanding(),
        _supplier(base_price_cny=bad_value, moq=bad_value),
    )
    assert result.decision in {"retry", "manual_review"}
    assert result.overall_confidence <= 0.49
    assert {"price", "moq"} <= set(result.missing_evidence)


@pytest.mark.parametrize("visual", [
    {"is_match": "false", "classification_confidence": 0.9},
    {"is_match": True, "classification_confidence": math.nan},
])
def test_malformed_visual_detail_fails_closed(visual):
    result = build_match_evidence(_understanding(), _supplier(), visual=visual)
    assert result.decision == "manual_review"
    assert result.overall_confidence <= 0.49
    assert "visual" in result.missing_evidence


def test_legacy_image_similarity_metadata_is_consumed_without_treating_it_as_classification():
    supplier = _supplier(image_similarity=0.82)
    supplier.raw_data["visual_match"] = {"score": 0.82, "source": "image_similarity"}
    result = build_match_evidence(_understanding(), supplier)
    assert result.image_similarity == 0.82
    assert result.visual_is_match is None
    assert result.decision == "keep"


@pytest.mark.parametrize(("excluded", "compatibility"), [
    (["Acme"], "Acmeology only"),
    (["A"], "Acme only"),
])
def test_exclusive_brand_uses_public_token_boundaries(excluded, compatibility):
    result = build_match_evidence(
        _understanding(excluded_brand_tokens=excluded),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "过滤饮用水", "brand_compatibility": compatibility,
        }),
    )
    assert "brand_exclusive_conflict" not in result.mismatch_reasons


def test_brand_mention_without_exclusive_structure_is_not_hard_rejected():
    result = build_match_evidence(
        _understanding(),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "过滤饮用水", "brand_compatibility": "compatible with Acme and others",
        }),
    )
    assert "brand_exclusive_conflict" not in result.mismatch_reasons


def test_separate_exclusive_structure_marks_brand_specific_part():
    result = build_match_evidence(
        _understanding(),
        _supplier({
            "product_type": "replacement", "package_quantity": 4,
            "function": "过滤饮用水", "brand_compatibility": "Acme",
            "exclusive": "only",
        }),
    )
    assert result.decision == "reject"
    assert "brand_exclusive_conflict" in result.mismatch_reasons


def test_target_category_diameter_conflict_precedes_generic_similarity():
    product = ProductDTO(
        asin="B000PATIO",
        marketplace="US",
        title="6 FT Beach Umbrella, Polyester Canopy",
    )
    target_profile = profile_from_product(product)
    candidate_profile = profile_from_text("85cm 涤纶沙滩伞")
    assert target_profile is not None and candidate_profile is not None
    understanding = understanding_from_target_profile(product, target_profile)
    supplier = _supplier({
        "product_type": "full_product",
        "function": "户外遮阳",
        "category_profile": candidate_profile.to_dict(),
    }, title_cn="85cm 涤纶沙滩伞")

    result = build_match_evidence(
        understanding,
        supplier,
        target_profile=target_profile,
    )

    assert result.decision == "reject"
    assert result.dimension_match == 0.0
    assert "target_category_conflict:canopy_diameter_cm" in result.mismatch_reasons


def test_target_category_exact_single_product_does_not_require_invented_pack_count():
    product = ProductDTO(
        asin="B000PATIO",
        marketplace="US",
        title="9 FT Market Patio Umbrella, Polyester Canopy",
    )
    target_profile = profile_from_product(product)
    candidate_profile = profile_from_text("274cm 涤纶户外中柱遮阳伞")
    assert target_profile is not None and candidate_profile is not None
    understanding = understanding_from_target_profile(product, target_profile)
    assert understanding.package_quantity is None
    supplier = _supplier({
        "product_type": "full_product",
        "function": "户外遮阳",
        "category_profile": candidate_profile.to_dict(),
        "factory_evidence": {"supplier_type": "生产厂家"},
    }, title_cn="274cm 涤纶户外中柱遮阳伞")

    result = build_match_evidence(
        understanding,
        supplier,
        target_profile=target_profile,
    )

    assert result.decision == "keep"
    assert "manufacturer" in result.passed_reasons
    assert "package_quantity" not in result.missing_evidence
    assert result.dimension_match == 1.0


def test_target_category_missing_critical_supplier_parameter_requires_review():
    product = ProductDTO(
        asin="B000HEATER",
        marketplace="US",
        title="48,000 BTU Propane Pyramid Patio Heater",
    )
    target_profile = profile_from_product(product)
    candidate_profile = profile_from_text("丙烷金字塔户外取暖器")
    assert target_profile is not None and candidate_profile is not None
    understanding = understanding_from_target_profile(product, target_profile)
    supplier = _supplier({
        "product_type": "full_product",
        "function": "户外取暖",
        "category_profile": candidate_profile.to_dict(),
    }, title_cn="丙烷金字塔户外取暖器")

    result = build_match_evidence(
        understanding,
        supplier,
        target_profile=target_profile,
    )

    assert result.decision == "manual_review"
    assert result.overall_confidence <= 0.49
    assert "target_category:candidate.heat_output_btu" in result.missing_evidence
from crawlers.amazon_bsr import ProductDTO
from domain.target_categories import profile_from_product, profile_from_text, understanding_from_target_profile

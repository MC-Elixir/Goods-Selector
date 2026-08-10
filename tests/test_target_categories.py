from __future__ import annotations

import pytest

from crawlers.amazon_bsr import ProductDTO
from domain.target_categories import (
    classify_target_category,
    compare_target_profiles,
    profile_from_product,
    profile_from_supplier,
    profile_from_text,
    target_query_matches_product,
    understanding_from_target_profile,
)
from matchers.alibaba_pailitao import SupplierDTO


def _supplier(title: str, detail_text: str | None = None) -> SupplierDTO:
    return SupplierDTO(
        alibaba_offer_id="123",
        title_cn=title,
        raw_data={"detail": {"raw_text": detail_text or title}},
    )


@pytest.mark.parametrize(
    ("text", "category_id", "subtype", "relation"),
    [
        ("120 Gallon Resin Outdoor Deck Box", "outdoor_storage", "deck_box", "full_product"),
        ("48,000 BTU Propane Pyramid Patio Heater", "patio_heater", "pyramid_heater", "full_product"),
        ("5-Piece Outdoor Conversation Patio Furniture Set", "patio_furniture_sets", "conversation_set", "full_product"),
        ("9 FT Market Patio Umbrella", "patio_umbrellas_shade", "market_umbrella", "full_product"),
        ("9 FT Patio Umbrella Replacement Canopy Only", "patio_umbrellas_shade", "replacement_canopy", "replacement"),
    ],
)
def test_four_category_contract_classifies_subtype_and_relation(text, category_id, subtype, relation):
    profile = profile_from_text(text)
    assert profile is not None
    assert profile.category_id == category_id
    assert profile.subtype == subtype
    assert profile.relation == relation


def test_umbrella_diameter_is_normalized_and_hard_conflicts():
    target = profile_from_text("6 FT Beach Umbrella, Polyester Canopy")
    candidate = profile_from_text("85cm 涤纶沙滩伞")
    assert target is not None and candidate is not None
    assert target.numeric["canopy_diameter_cm"] == pytest.approx(182.88)
    assert candidate.numeric["canopy_diameter_cm"] == pytest.approx(85.0)

    result = compare_target_profiles(target, candidate)

    assert result.decision == "reject"
    assert "canopy_diameter_cm" in result.conflicts


def test_full_umbrella_never_matches_replacement_canopy():
    result = compare_target_profiles(
        profile_from_text("9 FT Market Patio Umbrella"),
        profile_from_text("9 FT Patio Umbrella Replacement Canopy Only"),
    )
    assert result.decision == "reject"
    assert "relation" in result.conflicts


def test_storage_capacity_converts_gallons_to_liters():
    target = profile_from_text("120 Gallon Resin Outdoor Deck Box")
    candidate = profile_from_text("454升树脂户外储物箱 甲板箱")
    assert target is not None and candidate is not None
    assert target.numeric["capacity_l"] == pytest.approx(454.25, abs=0.01)

    result = compare_target_profiles(target, candidate)

    assert result.decision == "keep"
    assert "capacity_l" in result.matched


def test_heater_fuel_and_output_are_decision_grade_hard_gates():
    target = profile_from_text("48,000 BTU Propane Pyramid Patio Heater")
    exact = profile_from_text("48000BTU 丙烷金字塔户外取暖器")
    electric = profile_from_text("1500W 电热壁挂户外取暖器")
    assert target is not None and exact is not None and electric is not None
    assert compare_target_profiles(target, exact).decision == "keep"

    mismatch = compare_target_profiles(target, electric)
    assert mismatch.decision == "reject"
    assert {"fuel_type", "subtype"} & set(mismatch.conflicts)


def test_furniture_piece_count_is_exact_not_fuzzy():
    target = profile_from_text("5-Piece Outdoor Conversation Patio Furniture Set with Sofa Chairs and Table")
    exact = profile_from_text("户外休闲桌椅5件套 沙发 椅子 茶几")
    wrong = profile_from_text("户外休闲桌椅4件套 沙发 椅子 茶几")
    assert target is not None and exact is not None and wrong is not None
    assert compare_target_profiles(target, exact).decision == "keep"

    mismatch = compare_target_profiles(target, wrong)
    assert mismatch.decision == "reject"
    assert "piece_count" in mismatch.conflicts


def test_shade_sail_dimensions_are_unit_normalized():
    target = profile_from_text("10 x 12 FT Rectangular Patio Shade Sail")
    candidate = profile_from_text("305x366cm 长方形户外遮阳帆")
    assert target is not None and candidate is not None
    assert target.numeric["dimensions_cm"] == pytest.approx([304.8, 365.76])
    assert compare_target_profiles(target, candidate).decision == "keep"


def test_missing_target_critical_fields_stays_manual_review():
    target = profile_from_text("Freestanding Patio Heater")
    candidate = profile_from_text("户外立式取暖器")
    assert target is not None and candidate is not None

    result = compare_target_profiles(target, candidate)

    assert result.decision == "manual_review"
    assert {"target.fuel_type", "target.heat_output"} <= set(result.missing)


def test_amazon_target_query_filters_accessories_and_wrong_umbrella_subtypes():
    assert target_query_matches_product("outdoor patio umbrella", "9 FT Market Patio Umbrella")
    assert not target_query_matches_product("outdoor patio umbrella", "9 FT Replacement Canopy for Patio Umbrella")
    assert not target_query_matches_product("outdoor patio umbrella", "6 FT Beach Umbrella")
    assert target_query_matches_product("Patio Umbrellas & Shade", "10 FT Cantilever Patio Umbrella")


def test_classify_table_umbrella_with_reordered_outdoor_patio_words():
    assert classify_target_category(
        "9FT Umbrella Outdoor Patio, Table Umbrella Waterproof UV Protection"
    ) == "patio_umbrellas_shade"


def test_product_and_supplier_profiles_consume_structured_evidence():
    product = ProductDTO(
        asin="B000TARGET",
        marketplace="US",
        title="Outdoor Patio Furniture",
        raw_data={
            "bullet_points": ["5-piece conversation set", "sofa, chairs and table"],
            "attributes": {"Material": "PE rattan", "Seats": "4 person"},
        },
    )
    supplier = _supplier("户外休闲桌椅5件套", "PE藤编 沙发 椅子 茶几 5件套 户外家具")

    target = profile_from_product(product)
    candidate = profile_from_supplier(supplier)

    assert target is not None and candidate is not None
    assert target.numeric["piece_count"] == 5
    assert "rattan" in target.materials
    assert compare_target_profiles(target, candidate).decision == "keep"


def test_deterministic_understanding_generates_debranded_supplier_contract():
    product = ProductDTO(
        asin="B000TARGET",
        marketplace="US",
        title="Acme 9 FT Market Patio Umbrella with 8 Ribs",
        brand="Acme",
    )
    profile = profile_from_product(product)
    assert profile is not None

    understanding = understanding_from_target_profile(product, profile)

    assert understanding.category == "patio_umbrellas_shade"
    assert understanding.subcategory == "market_umbrella"
    assert understanding.replaceable_part_or_full_product == "full_product"
    assert understanding.model_provider == "deterministic"
    assert understanding.excluded_brand_tokens == ["Acme"]
    assert all("Acme" not in value for value in understanding.likely_supplier_keywords_cn)

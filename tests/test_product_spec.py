"""Product spec extraction and matching tests."""
from __future__ import annotations

from types import SimpleNamespace

from matchers.product_spec import (
    ProductSpec,
    compare_specs,
    spec_from_product,
    spec_from_supplier,
    spec_from_text,
)


def test_spec_from_text_extracts_common_amazon_parameters():
    spec = spec_from_text(
        "Stainless Steel Insulated Water Bottle 24oz with Straw Lid, 2 Pack, "
        "3 x 3 x 10 inch black"
    )

    assert spec.category == "保温杯"
    assert spec.material == "不锈钢"
    assert spec.color == "黑色"
    assert spec.capacity_ml == 709.8
    assert spec.pack_count == 2
    assert spec.dimensions_cm == (7.62, 7.62, 25.4)
    assert "保温" in spec.features
    assert "吸管" in spec.features


def test_spec_from_supplier_extracts_chinese_offer_parameters():
    supplier = SimpleNamespace(
        title_cn="304不锈钢保温杯 700ml 黑色 带吸管 2只装",
        supplier_name="永兴工厂",
        material=None,
        color=None,
        product_dimensions_cm="7.5x7.5x25cm",
        product_weight_g=380,
        raw_data={},
    )

    spec = spec_from_supplier(supplier)

    assert spec.category == "保温杯"
    assert spec.material == "不锈钢"
    assert spec.color == "黑色"
    assert spec.capacity_ml == 700
    assert spec.pack_count == 2
    assert spec.dimensions_cm == (7.5, 7.5, 25.0)


def test_spec_from_supplier_extracts_nested_1688_attributes():
    supplier = SimpleNamespace(
        title_cn="保温杯",
        supplier_name="永兴工厂",
        material=None,
        color=None,
        product_dimensions_cm=None,
        product_weight_g=None,
        raw_data={
            "productAttributeList": [
                {"attributeName": "材质", "value": "304不锈钢"},
                {"attributeName": "容量", "value": "700ml"},
                {"attributeName": "颜色", "value": "黑色"},
                {"attributeName": "包装", "value": "2只装"},
            ],
            "skuInfo": {
                "specs": [
                    {"specName": "尺寸", "specValue": "7.5x7.5x25cm"},
                    {"specName": "净重", "specValue": "380g"},
                ]
            },
        },
    )

    spec = spec_from_supplier(supplier)

    assert spec.material == "不锈钢"
    assert spec.color == "黑色"
    assert spec.capacity_ml == 700
    assert spec.pack_count == 2
    assert spec.dimensions_cm == (7.5, 7.5, 25.0)
    assert spec.weight_g == 380


def test_spec_from_text_extracts_bedding_set_parameters():
    spec = spec_from_text(
        "Queen Size 4 Piece Sheet Set Comfy Breathable Cooling Sheets "
        "Deep Pockets Extra Soft Wrinkle Free White Microfiber"
    )

    assert spec.category == "床品套件"
    assert spec.material == "聚酯纤维"
    assert spec.color == "白色"
    assert spec.pack_count == 4
    assert "床单式" in spec.features
    assert "深口袋" in spec.features
    assert "透气" in spec.features
    assert "凉感" in spec.features
    assert "柔软" in spec.features
    assert "防皱" in spec.features


def test_spec_from_supplier_extracts_chinese_bedding_offer_parameters():
    supplier = SimpleNamespace(
        title_cn="纯色床单四件套 现代简约风 外贸跨境床品 厂家直销一件代发",
        supplier_name="南通纺织品有限公司",
        material=None,
        color=None,
        product_dimensions_cm=None,
        product_weight_g=None,
        raw_data={"full_text": "纯色床单四件套\\n化纤\\n｜\\n磨毛\\n｜\\n床单式"},
    )

    spec = spec_from_supplier(supplier)

    assert spec.category == "床品套件"
    assert spec.material == "聚酯纤维"
    assert spec.color is None
    assert spec.pack_count == 4
    assert "床单式" in spec.features
    assert "磨毛" in spec.features
    assert "纯色" in spec.features


def test_compare_specs_scores_close_match_high():
    target = spec_from_text("Stainless Steel Water Bottle 24oz 2 Pack 3 x 3 x 10 inch")
    candidate = spec_from_text("304不锈钢保温杯 700ml 2只装 7.5x7.5x25cm")

    result = compare_specs(target, candidate)

    assert result.score >= 0.75
    assert "material" in result.matched
    assert "capacity" in result.matched
    assert "pack_count" in result.matched
    assert not result.conflicts


def test_compare_specs_scores_bedding_match_above_manual_review_floor():
    target = spec_from_text("Queen Size 4 Piece Sheet Set White Microfiber Deep Pockets")
    candidate = spec_from_text("纯色床单四件套 化纤 磨毛 床单式")

    result = compare_specs(target, candidate)

    assert result.score >= 0.55
    assert "category" in result.matched
    assert "material" in result.matched
    assert "pack_count" in result.matched


def test_compare_specs_matches_bedding_category_and_multi_material_aliases():
    target = ProductSpec(category="四件套", material="棉/微纤维", pack_count=4, features=["床单式"])
    candidate = spec_from_text("纯色床单四件套 化纤 磨毛 床单式")

    result = compare_specs(target, candidate)

    assert "category" in result.matched
    assert "material" in result.matched
    assert "pack_count" in result.matched
    assert "category" not in result.conflicts
    assert "material" not in result.conflicts


def test_compare_specs_reports_conflicts_for_wrong_capacity_and_pack_count():
    target = spec_from_text("Stainless Steel Water Bottle 24oz 2 Pack")
    candidate = spec_from_text("304不锈钢保温杯 350ml 1只装")

    result = compare_specs(target, candidate)

    assert result.score < 0.75
    assert "capacity" in result.conflicts
    assert "pack_count" in result.conflicts


def test_spec_from_product_uses_product_dimensions_and_analysis():
    product = SimpleNamespace(
        title="Generic Pillow 2 Pack",
        category="Home & Kitchen",
        brand="Generic",
        weight_kg=0.8,
        length_cm=50,
        width_cm=30,
        height_cm=10,
    )
    analysis = SimpleNamespace(
        category_zh="枕头",
        material="记忆棉",
        color="白色",
        key_features=["可机洗"],
        has_dangerous_attr=False,
    )

    spec = spec_from_product(product, analysis)

    assert spec.category == "枕头"
    assert spec.material == "记忆棉"
    assert spec.color == "白色"
    assert spec.weight_g == 800
    assert spec.dimensions_cm == (50.0, 30.0, 10.0)
    assert "可机洗" in spec.features


def test_spec_from_text_supports_target_outdoor_categories_and_units():
    storage = spec_from_text("120 Gallon Resin Outdoor Deck Box, 45 x 24 x 25 inches, 35 pounds")
    heater = spec_from_text("48,000 BTU Propane Pyramid Patio Heater, powder coated steel")
    furniture = spec_from_text("5 Piece PE Rattan Outdoor Conversation Patio Furniture Set")
    umbrella = spec_from_text("9 FT Market Patio Umbrella, Polyester Canopy")

    assert storage.category == "户外储物"
    assert storage.material == "树脂"
    assert storage.capacity_ml == 454249.4
    assert storage.dimensions_cm == (114.3, 60.96, 63.5)
    assert storage.weight_g == 15875.7
    assert heater.category == "户外取暖器"
    assert heater.material == "钢"
    assert furniture.category == "户外家具套装"
    assert furniture.material == "藤编"
    assert umbrella.category == "户外遮阳"


def test_spec_from_product_consumes_hydrated_amazon_evidence():
    product = SimpleNamespace(
        title="Outdoor Patio Furniture",
        category="Patio",
        brand=None,
        weight_kg=None,
        length_cm=None,
        width_cm=None,
        height_cm=None,
        raw_data={
            "bullet_points": ["5 Piece Outdoor Conversation Set"],
            "description": "PE rattan sofa chairs and table",
            "attributes": {"Material": "PE rattan"},
        },
    )

    spec = spec_from_product(product)

    assert spec.category == "户外家具套装"
    assert spec.material == "藤编"
    assert spec.pack_count == 5

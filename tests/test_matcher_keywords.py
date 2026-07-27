"""Matcher keyword generation tests."""
from __future__ import annotations

from matchers import _build_enriched_keywords, _extract_dimensional_keywords, _title_fallback_keywords


def test_title_fallback_keywords_translate_common_amazon_title_to_1688_terms():
    keywords = _title_fallback_keywords(
        "24 oz Stainless Steel Insulated Water Bottle with Straw Lid, 2 Pack"
    )

    assert keywords[0] == "不锈钢保温杯"
    assert "保温杯" in keywords
    assert "水杯" in keywords
    assert "不锈钢" in keywords
    assert "吸管" in keywords
    assert "24 oz Stainless Steel Insulated Water Bottle" in keywords


def test_title_fallback_keywords_cover_non_bottle_categories():
    keywords = _title_fallback_keywords("Extra Thick Non-Slip Yoga Mat for Home Fitness")

    assert "瑜伽垫" in keywords
    assert "防滑" in keywords


def test_title_fallback_keywords_drop_asin_only_titles():
    assert _title_fallback_keywords("B07984JN3L") == []


def test_enriched_keywords_drop_bare_capacity_and_generic_dimension_terms():
    assert _build_enriched_keywords(["3L", "大容量"], []) == []


def test_enriched_keywords_prioritize_product_terms_before_pack_counts():
    dim_keywords = _extract_dimensional_keywords(
        "Liquid Ant Killer Bait Stations for Indoor Ant Control, 12 Count"
    )
    keywords = _build_enriched_keywords(
        dim_keywords,
        ["液体蚂蚁诱饵盒", "家用灭蚁药", "杀虫饵剂"],
    )

    assert keywords[:3] == ["液体蚂蚁诱饵盒", "家用灭蚁药", "杀虫饵剂"]
    assert "12件套" not in keywords
    assert "12条装" not in keywords
    assert "液体蚂蚁诱饵盒 12盒装" in keywords[3:]
    assert "家用灭蚁药 12盒装" in keywords[3:]

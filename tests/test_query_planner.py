from matchers.query_planner import (
    QUERY_TYPES,
    generate_query_plan,
    rewrite_low_relevance_queries,
)
from schemas.sourcing import AmazonProductUnderstanding


def _understanding(**updates):
    data = {
        "asin": "B000TEST",
        "original_title_en": "Acme Home A-100 four pack filters",
        "generic_product_name": "净水滤芯",
        "supply_chain_name_cn": "净水器替换滤芯",
        "category": "净水设备配件",
        "function": ["过滤饮用水"],
        "material": ["活性炭"],
        "components": ["滤芯外壳"],
        "package_quantity": 4,
        "dimensions_visible": ["10英寸"],
        "use_case": ["厨房净水"],
        "replaceable_part_or_full_product": "replacement",
        "likely_supplier_keywords_cn": ["滤芯厂家", "净水耗材"],
        "excluded_brand_tokens": ["Acme Home", "A-100", "AcmeCo"],
        "model_provider": "fake",
        "model_name": "fake-v1",
        "prompt_version": "amazon-understanding-v1",
    }
    data.update(updates)
    return AmazonProductUnderstanding(**data)


def test_query_plan_covers_all_twelve_types_with_evidence_and_unique_text():
    queries = generate_query_plan(_understanding())

    assert len(queries) == len(QUERY_TYPES) == 12
    assert {q.query_type for q in queries} == set(QUERY_TYPES)
    assert len({q.text.casefold() for q in queries}) == 12
    assert all(len(q.text) >= 2 for q in queries)
    assert all(q.reason and q.source_evidence_refs for q in queries)


def test_queries_remove_full_brand_words_model_and_excluded_aliases():
    understanding = _understanding(
        generic_product_name="ACME filter",
        supply_chain_name_cn="Acme Home AcmeCo A-100 替换滤芯",
        function=["ACME HOME 过滤"],
        likely_supplier_keywords_cn=["仿 Acme 同款厂家", "通用滤芯工厂"],
    )

    joined = " ".join(q.text.casefold() for q in generate_query_plan(understanding))

    for token in ("acme", "home", "acmeco", "a-100"):
        assert token not in joined
    assert "仿" not in joined
    assert "同款" not in joined


def test_missing_optional_fields_still_produce_meaningful_unique_queries():
    understanding = _understanding(
        category=None,
        function=[],
        material=[],
        components=[],
        package_quantity=None,
        dimensions_visible=[],
        use_case=[],
        likely_supplier_keywords_cn=[],
        replaceable_part_or_full_product="unknown",
    )

    queries = generate_query_plan(understanding)

    assert len(queries) == 12
    assert len({q.text.casefold() for q in queries}) == 12
    assert all(len(q.text.strip()) >= 2 for q in queries)
    assert all(q.text not in {"1688", "None", "unknown"} for q in queries)


def test_query_generation_is_deterministic_and_ids_are_unique():
    first = generate_query_plan(_understanding())
    second = generate_query_plan(_understanding())

    assert first == second
    assert len({q.query_id for q in first}) == 12


def test_low_relevance_rewrites_are_bounded_lineaged_and_non_repeating():
    understanding = _understanding()
    initial = generate_query_plan(understanding)
    low = initial[0]

    first = rewrite_low_relevance_queries(
        understanding, initial, {low.query_id: 0.0}, iteration=1
    )
    assert len(first) == 1
    assert first[0].retry_of == low.query_id
    assert first[0].text.casefold() not in {q.text.casefold() for q in initial}

    second = rewrite_low_relevance_queries(
        understanding, [*initial, *first], {first[0].query_id: 0.0}, iteration=2
    )
    assert len(second) == 1
    assert second[0].retry_of == first[0].query_id
    assert second[0].text.casefold() not in {
        q.text.casefold() for q in [*initial, *first]
    }
    assert rewrite_low_relevance_queries(
        understanding, [*initial, *first, *second], {second[0].query_id: 0.0}, iteration=3
    ) == []


def test_rewrite_skips_high_relevance_unknown_and_duplicate_fingerprints():
    understanding = _understanding()
    initial = generate_query_plan(understanding)

    assert rewrite_low_relevance_queries(
        understanding, initial, {initial[0].query_id: 0.2}, iteration=1
    ) == []
    assert rewrite_low_relevance_queries(understanding, initial, {}, iteration=1) == []

    first = rewrite_low_relevance_queries(
        understanding, initial, {initial[0].query_id: 0.0}, iteration=1
    )
    assert rewrite_low_relevance_queries(
        understanding, [*initial, *first], {initial[0].query_id: 0.0}, iteration=1
    ) == []

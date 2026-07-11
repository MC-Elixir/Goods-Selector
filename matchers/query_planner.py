"""Deterministic, de-branded supplier query planning."""
from __future__ import annotations

import hashlib
import re

from matchers.brand_safety import brand_tokens, remove_brand_terms
from schemas.sourcing import AmazonProductUnderstanding, QueryPlan


QUERY_TYPES = (
    "generic_name",
    "supply_chain_name",
    "function",
    "material",
    "structure",
    "use_case",
    "specification",
    "package_quantity",
    "replacement_consumable",
    "debranded_description",
    "factory_synonym",
    "alibaba_category",
)

_TYPE_QUALIFIERS = {
    "generic_name": "通用产品",
    "supply_chain_name": "供应链",
    "function": "功能款",
    "material": "材质款",
    "structure": "结构件",
    "use_case": "应用场景",
    "specification": "规格款",
    "package_quantity": "包装批发",
    "replacement_consumable": "替换耗材",
    "debranded_description": "产品描述",
    "factory_synonym": "生产厂家",
    "alibaba_category": "1688类目",
}


def _clean(text: str, excluded: list[str]) -> str:
    value = remove_brand_terms(text, brand_tokens("", excluded))
    value = re.sub(r"仿(?:牌|款)?|同款|高仿|复刻", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" ,，-_/|")[:120]


def _fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _query_id(asin: str, query_type: str, text: str, retry_of: str | None = None) -> str:
    raw = f"{asin}|{query_type}|{_fingerprint(text)}|{retry_of or ''}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _parts(values: list[str], limit: int) -> str:
    return " ".join(value.strip() for value in values[:limit] if value.strip())


def _base_values(u: AmazonProductUnderstanding) -> dict[str, str]:
    generic = u.generic_product_name
    supply = u.supply_chain_name_cn
    relation = {
        "replacement": "替换件",
        "consumable": "耗材",
        "full_product": "整机",
        "unknown": "通用产品",
    }[u.replaceable_part_or_full_product]
    function = _parts(u.function, 2)
    material = _parts(u.material, 2)
    structure = _parts(u.components, 3)
    use_case = _parts(u.use_case, 2)
    specification = _parts(u.dimensions_visible, 2)
    package = f"{u.package_quantity}件装" if u.package_quantity else "包装批发"
    factory = _parts(u.likely_supplier_keywords_cn, 3)
    category = u.category or u.subcategory or "工业品"
    return {
        "generic_name": f"{generic} 通用产品",
        "supply_chain_name": f"{supply} 供应链",
        "function": f"{function or generic} {generic} 功能款",
        "material": f"{material or generic} {generic} 材质款",
        "structure": f"{structure or generic} {generic} 结构件",
        "use_case": f"{use_case or generic} {generic} 应用场景",
        "specification": f"{specification or generic} {generic} 规格款",
        "package_quantity": f"{package} {generic}",
        "replacement_consumable": f"{relation} {supply}",
        "debranded_description": (
            f"{material} {function} {structure} {generic} 产品描述"
        ),
        "factory_synonym": f"{factory or supply} 生产厂家",
        "alibaba_category": f"1688 {category} {supply}",
    }


def generate_query_plan(u: AmazonProductUnderstanding) -> list[QueryPlan]:
    """Create one safe, meaningful query for every canonical query type."""
    values = _base_values(u)
    result: list[QueryPlan] = []
    seen: set[str] = set()
    evidence_ref = f"understanding:{u.asin}:{u.prompt_version}"
    for query_type in QUERY_TYPES:
        text = _clean(values[query_type], u.excluded_brand_tokens)
        if len(text) < 2:
            text = _TYPE_QUALIFIERS[query_type]
        fingerprint = _fingerprint(text)
        counter = 1
        base_text = text
        while fingerprint in seen:
            suffix = f" 查询{counter}"
            text = _clean(
                f"{base_text[:120 - len(suffix)]}{suffix}",
                u.excluded_brand_tokens,
            )
            fingerprint = _fingerprint(text)
            counter += 1
        seen.add(fingerprint)
        result.append(QueryPlan(
            query_id=_query_id(u.asin, query_type, text),
            asin=u.asin,
            query_type=query_type,
            text=text,
            reason=f"derive {query_type} query from structured Amazon evidence",
            excluded_brand_tokens=list(u.excluded_brand_tokens),
            source_evidence_refs=[evidence_ref, f"{evidence_ref}:{query_type}"],
        ))
    return result


def rewrite_low_relevance_queries(
    u: AmazonProductUnderstanding,
    queries: list[QueryPlan],
    hit_rates: dict[str, float],
    iteration: int,
) -> list[QueryPlan]:
    """Rewrite explicitly low-relevance queries for at most two iterations."""
    if iteration not in (1, 2):
        return []
    existing_fingerprints = {_fingerprint(query.text) for query in queries}
    existing_ids = {query.query_id for query in queries}
    by_id = {query.query_id: query for query in queries}
    output: list[QueryPlan] = []
    for query in queries:
        rate = hit_rates.get(query.query_id)
        if rate is None or rate >= 0.2:
            continue
        if iteration == 1 and query.retry_of is not None:
            continue
        if iteration == 2:
            parent = by_id.get(query.retry_of or "")
            if parent is None or parent.retry_of is not None:
                continue
        suffix = "精准厂家" if iteration == 1 else "源头工厂"
        text = _clean(
            f"{u.supply_chain_name_cn} {u.generic_product_name} "
            f"{_TYPE_QUALIFIERS[query.query_type]} {suffix}",
            u.excluded_brand_tokens,
        )
        fingerprint = _fingerprint(text)
        query_id = _query_id(u.asin, query.query_type, text, query.query_id)
        if len(text) < 2 or fingerprint in existing_fingerprints or query_id in existing_ids:
            continue
        existing_fingerprints.add(fingerprint)
        existing_ids.add(query_id)
        output.append(query.model_copy(update={
            "query_id": query_id,
            "text": text,
            "retry_of": query.query_id,
            "reason": (
                f"rewrite low-relevance {query.query_type} query "
                f"at iteration {iteration}"
            ),
        }))
    return output

"""Deterministic supplier match evidence with hard-negative precedence."""
from __future__ import annotations

import math
from statistics import mean
from typing import Any

from matchers.product_spec import ProductSpec, compare_specs, spec_from_supplier, spec_from_text
from schemas.sourcing import AmazonProductUnderstanding, MatchEvidence


CRITICAL_EVIDENCE = ("function", "package_quantity", "product_type", "price", "moq")
HARD_SPEC_CONFLICTS = {"capacity", "dimensions", "material", "pack_count"}


def _finite_number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _normalized(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def _equal(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return 1.0 if _normalized(left) == _normalized(right) else 0.0


def _function_match(required: list[str], observed: Any) -> float | None:
    wanted = [_normalized(item) for item in required if _normalized(item)]
    actual = _normalized(observed) if isinstance(observed, str) else ""
    if not wanted or not actual:
        return None
    return float(any(term in actual or actual in term for term in wanted))


def _price_present(supplier: Any, detail: dict[str, Any]) -> bool:
    if _finite_number(getattr(supplier, "base_price_cny", None), positive=True) is not None:
        return True
    tiers = getattr(supplier, "price_tiers", None) or detail.get("price_tiers")
    if not isinstance(tiers, list):
        return False
    for tier in tiers:
        if isinstance(tier, dict) and any(
            _finite_number(tier.get(key), positive=True) is not None
            for key in ("price", "price_cny", "unit_price", "unit_price_cny")
        ):
            return True
    return _finite_number(detail.get("base_price_cny"), positive=True) is not None


def _moq_present(supplier: Any, detail: dict[str, Any]) -> bool:
    value = getattr(supplier, "moq", None)
    if value is None:
        value = detail.get("moq")
    return _finite_number(value, positive=True) is not None


def _target_spec(u: AmazonProductUnderstanding) -> ProductSpec:
    target = spec_from_text(" ".join(filter(None, [
        u.generic_product_name,
        u.category or "",
        *u.material,
        *u.components,
        *u.dimensions_visible,
    ])))
    target.category = u.category or target.category
    target.material = u.material[0] if u.material else target.material
    target.pack_count = u.package_quantity or target.pack_count
    target.features = list(dict.fromkeys([*target.features, *u.function, *u.distinguishing_features]))
    return target


def _supplier_spec(supplier: Any, detail: dict[str, Any]) -> ProductSpec:
    candidate = spec_from_supplier(supplier)
    if _finite_number(detail.get("capacity_ml"), positive=True) is not None:
        candidate.capacity_ml = float(detail["capacity_ml"])
    if detail.get("material"):
        candidate.material = str(detail["material"])
    if _finite_number(detail.get("package_quantity"), positive=True) is not None:
        candidate.pack_count = int(float(detail["package_quantity"]))
    if detail.get("dimensions"):
        parsed = spec_from_text(str(detail["dimensions"]))
        candidate.dimensions_cm = parsed.dimensions_cm
    return candidate


def _brand_exclusive(u: AmazonProductUnderstanding, detail: dict[str, Any]) -> bool:
    compatibility = _normalized(detail.get("brand_compatibility"))
    if not compatibility or compatibility in {"universal", "generic", "通用"}:
        return False
    exclusive_markers = (" only", "only ", "专用", "原装", "exclusive")
    if any(marker in compatibility for marker in exclusive_markers):
        return True
    return any(_normalized(token) in compatibility for token in u.excluded_brand_tokens if token)


def _visual_evidence(
    supplier: Any, supplied: dict[str, Any] | None
) -> tuple[bool | None, float | None, bool]:
    """Return classification, confidence, and malformed status.

    Classification confidence is deliberately not returned as image similarity.
    """
    candidate: Any = supplied
    if candidate is None and isinstance(getattr(supplier, "raw_data", None), dict):
        legacy = supplier.raw_data.get("visual_match")
        if isinstance(legacy, dict) and "is_match" in legacy:
            candidate = legacy
    if candidate is None:
        return None, None, False
    if not isinstance(candidate, dict) or type(candidate.get("is_match")) is not bool:
        return None, None, True
    confidence = candidate.get("classification_confidence", candidate.get("confidence"))
    if confidence is not None:
        confidence = _finite_number(confidence)
        if confidence is None or not 0 <= confidence <= 1:
            return None, None, True
    return candidate["is_match"], confidence, False


def build_match_evidence(
    understanding: AmazonProductUnderstanding,
    supplier: Any,
    visual: dict[str, Any] | None = None,
) -> MatchEvidence:
    raw = supplier.raw_data if isinstance(getattr(supplier, "raw_data", None), dict) else {}
    detail_value = raw.get("detail", {})
    detail = detail_value if isinstance(detail_value, dict) else {}

    target_type = understanding.replaceable_part_or_full_product
    supplier_type = detail.get("product_type")
    type_match = None if target_type == "unknown" else _equal(target_type, supplier_type)
    pack_match = _equal(understanding.package_quantity, detail.get("package_quantity"))
    function_match = _function_match(understanding.function, detail.get("function"))

    spec = compare_specs(_target_spec(understanding), _supplier_spec(supplier, detail))
    hard_spec_conflicts = sorted(set(spec.conflicts) & HARD_SPEC_CONFLICTS)

    mismatch: list[str] = []
    if type_match == 0:
        mismatch.append("accessory_full_product_conflict")
    if pack_match == 0:
        mismatch.append("package_quantity_conflict")
    if function_match == 0:
        mismatch.append("core_function_conflict")
    if _brand_exclusive(understanding, detail):
        mismatch.append("brand_exclusive_conflict")
    mismatch.extend(f"specification_conflict:{name}" for name in hard_spec_conflicts)

    states = {
        "function": function_match,
        "package_quantity": pack_match,
        "product_type": type_match,
        "price": 1.0 if _price_present(supplier, detail) else None,
        "moq": 1.0 if _moq_present(supplier, detail) else None,
    }
    missing = [name for name, value in states.items() if value is None]
    passed = [name for name, value in states.items() if value == 1.0]

    visual_is_match, visual_confidence, malformed_visual = _visual_evidence(supplier, visual)
    if visual_is_match is False:
        mismatch.append("visual_mismatch")
    elif visual_is_match is True:
        passed.append("visual")
    elif malformed_visual:
        missing.append("visual")

    scores = [value for value in states.values() if value is not None]
    scores.append(spec.score)
    confidence = mean(scores) if scores else 0.0
    if mismatch:
        decision = "reject"
    elif malformed_visual:
        decision = "manual_review"
        confidence = min(confidence, 0.49)
    elif any(name in missing for name in CRITICAL_EVIDENCE):
        decision = "retry"
        confidence = min(confidence, 0.49)
    else:
        decision = "keep" if confidence >= 0.70 else "manual_review"

    image_similarity = _finite_number(getattr(supplier, "image_similarity", None))
    if image_similarity is not None and not 0 <= image_similarity <= 1:
        image_similarity = None

    return MatchEvidence(
        amazon_ref=f"asin:{understanding.asin}",
        supplier_ref=f"offer:{supplier.alibaba_offer_id}",
        function_match=function_match,
        package_quantity_match=pack_match,
        accessory_vs_full_product_match=type_match,
        specification_similarity=spec.score,
        image_similarity=image_similarity,
        visual_is_match=visual_is_match,
        visual_confidence=visual_confidence,
        overall_confidence=round(max(0.0, min(confidence, 1.0)), 4),
        mismatch_reasons=list(dict.fromkeys(mismatch)),
        missing_evidence=sorted(set(missing)),
        passed_reasons=list(dict.fromkeys(passed)),
        decision=decision,
    )

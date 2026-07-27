from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _is_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _complete_numeric_values(
    reviewed: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Any]],
    field: str,
) -> list[float] | None:
    values = [predictions[item["case_id"]].get(field) for item in reviewed]
    if not values or not all(_is_number(value) for value in values):
        return None
    return [float(value) for value in values]


def evaluate(
    labels: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]
) -> dict[str, int | float | None]:
    """Evaluate predictions against reviewed labels without inventing denominators.

    A case is eligible only when a reviewer explicitly approved the label and a
    prediction exists. Metrics whose prediction evidence is missing remain
    ``None``; explicit zero values remain measurable values.
    """

    reviewed = [
        item
        for item in labels
        if item.get("reviewed") is True and item.get("case_id") in predictions
    ]

    match_cases = [
        item
        for item in reviewed
        if item.get("no_match") is False
        and isinstance(item.get("correct_offer_ids"), list)
        and bool(item["correct_offer_ids"])
        and isinstance(predictions[item["case_id"]].get("ranked_offer_ids"), list)
    ]
    no_match_cases = [
        item
        for item in reviewed
        if item.get("no_match") is True
        and isinstance(predictions[item["case_id"]].get("ranked_offer_ids"), list)
    ]

    p1 = sum(
        bool(
            set(predictions[item["case_id"]]["ranked_offer_ids"][:1])
            & set(item["correct_offer_ids"])
        )
        for item in match_cases
    )
    p5 = sum(
        bool(
            set(predictions[item["case_id"]]["ranked_offer_ids"][:5])
            & set(item["correct_offer_ids"])
        )
        for item in match_cases
    )
    false_matches = sum(
        bool(predictions[item["case_id"]]["ranked_offer_ids"])
        for item in no_match_cases
    )

    statuses_known = bool(reviewed) and all(
        isinstance(predictions[item["case_id"]].get("recommendation_status"), str)
        for item in reviewed
    )
    recommendation_labeled = [
        item
        for item in reviewed
        if item.get("recommendation_label") in {"recommend", "reject"}
        and isinstance(
            predictions[item["case_id"]].get("recommendation_status"), str
        )
    ]
    recommended = [
        item
        for item in recommendation_labeled
        if predictions[item["case_id"]]["recommendation_status"] == "recommend"
    ]
    correct_recommendations = sum(
        item.get("recommendation_label") == "recommend" for item in recommended
    )

    completeness = _complete_numeric_values(reviewed, predictions, "field_completeness")
    retries = _complete_numeric_values(reviewed, predictions, "retries")
    costs = _complete_numeric_values(reviewed, predictions, "cost")
    supplier_counts = _complete_numeric_values(reviewed, predictions, "supplier_count")
    mock_counts = _complete_numeric_values(reviewed, predictions, "mock_count")

    supplier_total: float | None = None
    mock_total: float | None = None
    if supplier_counts is not None and mock_counts is not None and all(
        supplier >= 0 and 0 <= mock <= supplier
        for supplier, mock in zip(supplier_counts, mock_counts, strict=True)
    ):
        supplier_total = sum(supplier_counts)
        mock_total = sum(mock_counts)

    success_values = [
        predictions[item["case_id"]].get("pipeline_success") for item in reviewed
    ]
    successes_known = bool(success_values) and all(
        isinstance(value, bool) for value in success_values
    )

    approved_count = len(recommended) if statuses_known else 0
    return {
        "reviewed_case_count": len(reviewed),
        "supplier_precision_at_1": _ratio(p1, len(match_cases)),
        "supplier_precision_at_5": _ratio(p5, len(match_cases)),
        "false_match_rate": _ratio(false_matches, len(no_match_cases)),
        "no_match_accuracy": _ratio(
            len(no_match_cases) - false_matches, len(no_match_cases)
        ),
        "field_completeness": (
            _ratio(sum(completeness), len(completeness))
            if completeness is not None
            else None
        ),
        "real_supplier_rate": (
            _ratio(supplier_total - mock_total, supplier_total)
            if supplier_total is not None and mock_total is not None
            else None
        ),
        "mock_contamination_rate": (
            _ratio(mock_total, supplier_total)
            if supplier_total is not None and mock_total is not None
            else None
        ),
        "recommendation_precision": (
            _ratio(correct_recommendations, len(recommended))
            if recommendation_labeled
            else None
        ),
        "manual_review_rate": (
            _ratio(
                sum(
                    predictions[item["case_id"]]["recommendation_status"]
                    == "needs_manual_review"
                    for item in reviewed
                ),
                len(reviewed),
            )
            if statuses_known
            else None
        ),
        "cost_per_approved_candidate": (
            _ratio(sum(costs), approved_count)
            if costs is not None and statuses_known
            else None
        ),
        "average_retries": (
            _ratio(sum(retries), len(retries)) if retries is not None else None
        ),
        "quality_pipeline_success_rate": (
            _ratio(sum(success_values), len(success_values))
            if successes_known
            else None
        ),
    }

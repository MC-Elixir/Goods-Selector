"""Evaluate the deterministic four-category contract against explicit cases."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crawlers.amazon_bsr import ProductDTO
from domain.target_categories import (
    understanding_from_target_profile,
    profile_from_product,
    profile_from_text,
)
from matchers.alibaba_pailitao import SupplierDTO
from matchers.match_evidence import build_match_evidence


DEFAULT_FIXTURE = Path(__file__).parent / "fixtures" / "target_category_contract_gold.json"

_FUNCTIONS = {
    "outdoor_storage": "户外储物",
    "patio_heater": "户外取暖",
    "patio_furniture_sets": "户外坐卧",
    "patio_umbrellas_shade": "户外遮阳",
}


def _normalized_decision(value: str) -> str:
    return "review" if value in {"retry", "manual_review"} else value


def _predict(case: dict[str, Any]) -> dict[str, Any]:
    product = ProductDTO(
        asin=case["case_id"][:20],
        marketplace="US",
        title=case["target_text"],
        category=case["category_id"],
    )
    target = profile_from_product(product)
    candidate = profile_from_text(case["candidate_text"])
    if target is None or candidate is None:
        return {
            "decision": "invalid_profile",
            "mismatch_reasons": [],
            "missing_evidence": [
                name for name, value in (("target_profile", target), ("candidate_profile", candidate))
                if value is None
            ],
        }
    understanding = understanding_from_target_profile(product, target)
    detail: dict[str, Any] = {
        "product_type": "full_product" if candidate.relation == "full_product" else candidate.relation,
        "function": _FUNCTIONS[candidate.category_id],
        "category_profile": candidate.to_dict(),
        "base_price_cny": 100.0,
        "moq": 20,
    }
    if candidate.numeric.get("piece_count") is not None:
        detail["package_quantity"] = int(candidate.numeric["piece_count"])
    if case.get("supplier_type") is not None:
        detail["factory_evidence"] = {"supplier_type": case["supplier_type"]}
    observed = datetime.now(timezone.utc).isoformat()
    detail["provenance"] = {
        key: {
            "status": "extracted",
            "source_type": "synthetic_contract_fixture",
            "source_ref": f"fixture:{case['case_id']}",
            "observed_at": observed,
            "confidence": 1.0,
        }
        for key, value in detail.items()
        if key != "provenance" and value is not None
    }
    supplier = SupplierDTO(
        alibaba_offer_id=case["case_id"],
        title_cn=case["candidate_text"],
        base_price_cny=100.0,
        moq=20,
        raw_data={"detail": detail},
    )
    evidence = build_match_evidence(
        understanding,
        supplier,
        target_profile=target,
    )
    payload = evidence.model_dump(mode="json")
    payload["decision"] = _normalized_decision(evidence.decision)
    return payload


def evaluate_contract(dataset: dict[str, Any]) -> dict[str, Any]:
    if dataset.get("ground_truth_type") != "synthetic_contract":
        raise ValueError("target contract evaluator accepts synthetic_contract fixtures only")
    cases = dataset.get("cases") or []
    predictions: list[dict[str, Any]] = []
    category_totals: Counter[str] = Counter()
    category_correct: Counter[str] = Counter()
    keep_predictions = 0
    correct_keep_predictions = 0
    expected_rejects = 0
    caught_rejects = 0
    reason_cases = 0
    correct_reasons = 0

    for case in cases:
        prediction = _predict(case)
        expected = case["expected_decision"]
        predicted = prediction["decision"]
        correct = predicted == expected
        category = case["category_id"]
        category_totals[category] += 1
        category_correct[category] += int(correct)
        if predicted == "keep":
            keep_predictions += 1
            correct_keep_predictions += int(expected == "keep")
        if expected == "reject":
            expected_rejects += 1
            caught_rejects += int(predicted == "reject")
        expected_reason = case.get("expected_reason")
        reason_ok = None
        if expected_reason:
            reason_cases += 1
            reason_ok = expected_reason in (prediction.get("mismatch_reasons") or [])
            correct_reasons += int(reason_ok)
        predictions.append({
            "case_id": case["case_id"],
            "category_id": category,
            "expected_decision": expected,
            "predicted_decision": predicted,
            "decision_correct": correct,
            "expected_reason": expected_reason,
            "reason_correct": reason_ok,
            "mismatch_reasons": prediction.get("mismatch_reasons") or [],
            "missing_evidence": prediction.get("missing_evidence") or [],
        })

    total = len(cases)
    correct_total = sum(item["decision_correct"] for item in predictions)
    return {
        "schema_version": "1.0",
        "dataset_id": dataset.get("dataset_id"),
        "ground_truth_type": dataset.get("ground_truth_type"),
        "case_count": total,
        "decision_accuracy": correct_total / total if total else None,
        "strict_keep_precision": (
            correct_keep_predictions / keep_predictions if keep_predictions else None
        ),
        "hard_reject_recall": caught_rejects / expected_rejects if expected_rejects else None,
        "expected_reason_accuracy": correct_reasons / reason_cases if reason_cases else None,
        "category_decision_accuracy": {
            category: category_correct[category] / count
            for category, count in sorted(category_totals.items())
        },
        "predictions": predictions,
        "human_live_accuracy": None,
        "human_live_accuracy_note": "No reviewed live labels are available; the live review queue remains unlabeled.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.fixture.read_text(encoding="utf-8"))
    result = evaluate_contract(dataset)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if result["decision_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

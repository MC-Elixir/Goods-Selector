import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.evaluate import evaluate
from benchmarks.evaluate_target_contract import evaluate_contract
from domain.target_categories import compare_target_profiles, profile_from_text

FIXTURES = Path(__file__).parents[1] / "benchmarks" / "fixtures"


def test_synthetic_target_contract_gold_covers_all_categories_and_gates():
    dataset = json.loads(
        (FIXTURES / "target_category_contract_gold.json").read_text(encoding="utf-8")
    )

    result = evaluate_contract(dataset)

    assert result["case_count"] == 20
    assert result["decision_accuracy"] == 1.0
    assert result["strict_keep_precision"] == 1.0
    assert result["hard_reject_recall"] == 1.0
    assert result["expected_reason_accuracy"] == 1.0
    assert set(result["category_decision_accuracy"]) == {
        "outdoor_storage",
        "patio_heater",
        "patio_furniture_sets",
        "patio_umbrellas_shade",
    }
    assert result["human_live_accuracy"] is None


def test_unreviewed_live_queue_cannot_produce_accuracy_metrics():
    dataset = json.loads(
        (FIXTURES / "target_category_human_review_queue.json").read_text(encoding="utf-8")
    )
    labels = dataset["cases"]
    predictions = {
        case["case_id"]: {"ranked_offer_ids": case["candidate_offer_ids"]}
        for case in labels
    }

    result = evaluate(labels, predictions)

    assert result["reviewed_case_count"] == 0
    assert result["supplier_precision_at_1"] is None
    assert result["false_match_rate"] is None
    assert result["recommendation_precision"] is None


def test_live_queue_artifacts_are_pinned_and_known_numeric_conflict_is_detected():
    dataset = json.loads(
        (FIXTURES / "target_category_human_review_queue.json").read_text(encoding="utf-8")
    )
    by_id = {case["case_id"]: case for case in dataset["cases"]}
    case = by_id["live-umbrella-B0DT4VNHCC"]

    artifact = Path(__file__).parents[1] / case["artifact_path"]
    if not artifact.is_file():
        pytest.skip("optional ignored live artifact is not present in this checkout")
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == case["artifact_sha256"]

    target = profile_from_text(case["amazon_title"])
    candidate = profile_from_text(case["candidate_titles"][0])
    assert target is not None and candidate is not None
    comparison = compare_target_profiles(target, candidate)

    # This checks deterministic conflict detection only. The case remains
    # unreviewed and therefore contributes no claimed live accuracy metric.
    assert target.numeric["canopy_diameter_cm"] == 182.88
    assert candidate.numeric["canopy_diameter_cm"] == 85.0
    assert comparison.decision == "reject"
    assert comparison.conflicts == ["canopy_diameter_cm"]


def test_target_contract_live_metrics_use_only_explicitly_reviewed_cases():
    dataset = {
        "schema_version": "1.0",
        "dataset_id": "reviewed-live-test",
        "ground_truth_type": "unreviewed_live_queue",
        "cases": [
            {
                "case_id": "reviewed",
                "reviewed": True,
                "category_id": "outdoor_storage",
                "amazon_title": "120 Gallon Resin Deck Box Outdoor Storage",
                "candidate_offer_ids": ["1"],
                "candidate_titles": ["户外储物箱 50 Gallon 树脂"],
                "correct_offer_ids": [],
                "no_match": True,
            },
            {
                "case_id": "unreviewed",
                "reviewed": False,
                "category_id": "outdoor_storage",
                "amazon_title": "120 Gallon Resin Deck Box Outdoor Storage",
                "candidate_offer_ids": ["2"],
                "candidate_titles": ["户外储物箱 454L 树脂"],
                "correct_offer_ids": ["2"],
                "no_match": False,
            },
        ],
    }

    result = evaluate_contract(dataset)

    assert result["case_count"] == 2
    assert result["reviewed_case_count"] == 1
    assert result["reviewed_candidate_count"] == 1
    assert result["decision_accuracy"] == 1.0
    assert result["human_live_accuracy"] == 1.0
    assert [item["case_id"] for item in result["predictions"]] == ["reviewed"]

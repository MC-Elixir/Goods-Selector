import json
import subprocess
import sys
from pathlib import Path

from benchmarks.evaluate import evaluate


ROOT = Path(__file__).resolve().parents[1]


def test_metrics_use_only_reviewed_labels():
    labels = [
        {
            "case_id": "a",
            "reviewed": True,
            "correct_offer_ids": ["1"],
            "no_match": False,
            "recommendation_label": "recommend",
        },
        {
            "case_id": "b",
            "reviewed": True,
            "correct_offer_ids": [],
            "no_match": True,
            "recommendation_label": "reject",
        },
        {
            "case_id": "c",
            "reviewed": False,
            "correct_offer_ids": ["9"],
            "no_match": False,
            "recommendation_label": "recommend",
        },
    ]
    predictions = {
        "a": {
            "ranked_offer_ids": ["1", "2"],
            "recommendation_status": "recommend",
            "mock_count": 0,
            "supplier_count": 2,
            "field_completeness": 0.8,
            "retries": 1,
            "cost": 2.0,
            "pipeline_success": True,
        },
        "b": {
            "ranked_offer_ids": [],
            "recommendation_status": "reject",
            "mock_count": 0,
            "supplier_count": 0,
            "field_completeness": 0.6,
            "retries": 0,
            "cost": 1.0,
            "pipeline_success": True,
        },
    }

    result = evaluate(labels, predictions)

    assert result["reviewed_case_count"] == 2
    assert result["supplier_precision_at_1"] == 1.0
    assert result["supplier_precision_at_5"] == 1.0
    assert result["false_match_rate"] == 0.0
    assert result["no_match_accuracy"] == 1.0
    assert result["field_completeness"] == 0.7
    assert result["real_supplier_rate"] == 1.0
    assert result["recommendation_precision"] == 1.0
    assert result["mock_contamination_rate"] == 0.0
    assert result["manual_review_rate"] == 0.0
    assert result["cost_per_approved_candidate"] == 3.0
    assert result["average_retries"] == 0.5
    assert result["quality_pipeline_success_rate"] == 1.0


def test_empty_or_unreviewed_cases_do_not_claim_quality_metrics():
    labels = [
        {
            "case_id": "unreviewed",
            "reviewed": False,
            "correct_offer_ids": ["1"],
            "no_match": False,
            "recommendation_label": "recommend",
        }
    ]

    result = evaluate(labels, {})

    assert result["reviewed_case_count"] == 0
    assert all(value is None for key, value in result.items() if key != "reviewed_case_count")


def test_zero_suppliers_keeps_supplier_rates_unknown():
    labels = [
        {
            "case_id": "none",
            "reviewed": True,
            "correct_offer_ids": [],
            "no_match": True,
            "recommendation_label": "reject",
        }
    ]
    predictions = {
        "none": {
            "ranked_offer_ids": [],
            "recommendation_status": "reject",
            "supplier_count": 0,
            "mock_count": 0,
        }
    }

    result = evaluate(labels, predictions)

    assert result["no_match_accuracy"] == 1.0
    assert result["real_supplier_rate"] is None
    assert result["mock_contamination_rate"] is None


def test_missing_numeric_evidence_is_not_coerced_to_zero():
    labels = [
        {
            "case_id": "missing",
            "reviewed": True,
            "correct_offer_ids": ["1"],
            "no_match": False,
            "recommendation_label": "recommend",
        }
    ]
    predictions = {
        "missing": {
            "ranked_offer_ids": ["1"],
            "recommendation_status": "recommend",
        }
    }

    result = evaluate(labels, predictions)

    assert result["supplier_precision_at_1"] == 1.0
    assert result["field_completeness"] is None
    assert result["real_supplier_rate"] is None
    assert result["mock_contamination_rate"] is None
    assert result["cost_per_approved_candidate"] is None
    assert result["average_retries"] is None
    assert result["quality_pipeline_success_rate"] is None


def test_real_zero_values_remain_measured_values():
    labels = [
        {
            "case_id": "zero",
            "reviewed": True,
            "correct_offer_ids": ["1"],
            "no_match": False,
            "recommendation_label": "reject",
        }
    ]
    predictions = {
        "zero": {
            "ranked_offer_ids": ["2"],
            "recommendation_status": "needs_manual_review",
            "supplier_count": 2,
            "mock_count": 0,
            "field_completeness": 0.0,
            "retries": 0,
            "cost": 0.0,
            "pipeline_success": False,
        }
    }

    result = evaluate(labels, predictions)

    assert result["supplier_precision_at_1"] == 0.0
    assert result["field_completeness"] == 0.0
    assert result["mock_contamination_rate"] == 0.0
    assert result["average_retries"] == 0.0
    assert result["quality_pipeline_success_rate"] == 0.0
    assert result["manual_review_rate"] == 1.0
    assert result["cost_per_approved_candidate"] is None


def test_seed_preserves_unreviewed_historical_pairs_without_ground_truth():
    seed = json.loads(
        (ROOT / "benchmarks/fixtures/sourcing_quality_seed.json").read_text(
            encoding="utf-8"
        )
    )

    assert seed["schema_version"] == "1.0"
    assert len(seed["cases"]) == 12
    for case in seed["cases"]:
        assert case["reviewed"] is False
        assert case["correct_offer_ids"] == []
        assert case["artifact_sha256"]
        assert case["asin_family"]
        assert case["candidate_offer_ids"]
        assert "mismatch_types" in case
        assert case["reviewer"] == {
            "reviewer_id": None,
            "reviewed_at": None,
            "notes": "",
        }


def test_cli_writes_deterministic_null_metrics_for_empty_predictions(tmp_path):
    output = tmp_path / "metrics.json"
    command = [
        sys.executable,
        str(ROOT / "scripts/evaluate_sourcing_quality.py"),
        "--labels",
        str(ROOT / "benchmarks/fixtures/sourcing_quality_seed.json"),
        "--predictions",
        str(ROOT / "benchmarks/fixtures/empty_predictions.json"),
        "--output",
        str(output),
    ]

    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    first = output.read_text(encoding="utf-8")
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)

    assert output.read_text(encoding="utf-8") == first
    assert first.endswith("\n")
    assert json.loads(first) == {
        "average_retries": None,
        "cost_per_approved_candidate": None,
        "false_match_rate": None,
        "field_completeness": None,
        "manual_review_rate": None,
        "mock_contamination_rate": None,
        "no_match_accuracy": None,
        "quality_pipeline_success_rate": None,
        "real_supplier_rate": None,
        "recommendation_precision": None,
        "reviewed_case_count": 0,
        "supplier_precision_at_1": None,
        "supplier_precision_at_5": None,
    }


def test_recommendation_precision_excludes_missing_ground_truth():
    labels = [
        {
            "case_id": "unknown-label",
            "reviewed": True,
            "correct_offer_ids": ["1"],
            "no_match": False,
            "recommendation_label": None,
        }
    ]
    predictions = {
        "unknown-label": {
            "ranked_offer_ids": ["1"],
            "recommendation_status": "recommend",
        }
    }

    result = evaluate(labels, predictions)

    assert result["recommendation_precision"] is None


def test_supplier_precision_excludes_match_label_without_correct_offers():
    labels = [
        {
            "case_id": "incomplete-match-label",
            "reviewed": True,
            "correct_offer_ids": [],
            "no_match": False,
            "recommendation_label": "reject",
        }
    ]
    predictions = {
        "incomplete-match-label": {
            "ranked_offer_ids": ["unexpected"],
            "recommendation_status": "reject",
        }
    }

    result = evaluate(labels, predictions)

    assert result["supplier_precision_at_1"] is None
    assert result["supplier_precision_at_5"] is None

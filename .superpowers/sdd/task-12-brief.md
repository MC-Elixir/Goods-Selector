### Task 12: Benchmark Dataset Contract and Metric Evaluator

**Files:**
- Create: `benchmarks/__init__.py`
- Create: `benchmarks/evaluate.py`
- Create: `benchmarks/fixtures/sourcing_quality_seed.json`
- Create: `benchmarks/fixtures/empty_predictions.json`
- Create: `scripts/evaluate_sourcing_quality.py`
- Test: `tests/test_benchmark_evaluate.py`

**Interfaces:**
- Consumes: versioned reviewed labels plus run predictions.
- Produces: precision@1/@5, false-match rate, no-match accuracy, completeness, real/mock rates, recommendation precision, manual-review rate, retry/cost/success metrics.

- [ ] **Step 1: Write exact metric tests**

```python
# tests/test_benchmark_evaluate.py
from benchmarks.evaluate import evaluate


def test_metrics_use_only_reviewed_labels():
    labels = [
        {"case_id": "a", "reviewed": True, "correct_offer_ids": ["1"], "no_match": False, "recommendation_label": "recommend"},
        {"case_id": "b", "reviewed": True, "correct_offer_ids": [], "no_match": True, "recommendation_label": "reject"},
        {"case_id": "c", "reviewed": False, "correct_offer_ids": ["9"], "no_match": False, "recommendation_label": "recommend"},
    ]
    predictions = {
        "a": {"ranked_offer_ids": ["1", "2"], "recommendation_status": "recommend", "mock_count": 0, "supplier_count": 2, "field_completeness": 0.8, "retries": 1, "cost": 2.0, "pipeline_success": True},
        "b": {"ranked_offer_ids": [], "recommendation_status": "reject", "mock_count": 0, "supplier_count": 0, "field_completeness": 0.6, "retries": 0, "cost": 1.0, "pipeline_success": True},
    }
    result = evaluate(labels, predictions)
    assert result["reviewed_case_count"] == 2
    assert result["supplier_precision_at_1"] == 1.0
    assert result["no_match_accuracy"] == 1.0
    assert result["recommendation_precision"] == 1.0
    assert result["mock_contamination_rate"] == 0.0
```

- [ ] **Step 2: Run test and confirm evaluator absence**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_benchmark_evaluate.py -v`

Expected: collection fails because `benchmarks.evaluate` does not exist.

- [ ] **Step 3: Implement denominator-safe reviewed-label metrics**

```python
# benchmarks/evaluate.py
from __future__ import annotations


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate(labels: list[dict], predictions: dict[str, dict]) -> dict:
    reviewed = [item for item in labels if item.get("reviewed") is True and item["case_id"] in predictions]
    match_cases = [item for item in reviewed if not item.get("no_match")]
    no_match_cases = [item for item in reviewed if item.get("no_match")]
    p1 = sum(bool(set(predictions[item["case_id"]].get("ranked_offer_ids", [])[:1]) & set(item["correct_offer_ids"])) for item in match_cases)
    p5 = sum(bool(set(predictions[item["case_id"]].get("ranked_offer_ids", [])[:5]) & set(item["correct_offer_ids"])) for item in match_cases)
    false_matches = sum(bool(predictions[item["case_id"]].get("ranked_offer_ids")) for item in no_match_cases)
    recommendation_cases = [item for item in reviewed if item.get("recommendation_label") == "recommend"]
    correct_recommendations = sum(predictions[item["case_id"]].get("recommendation_status") == "recommend" for item in recommendation_cases)
    supplier_total = sum(predictions[item["case_id"]].get("supplier_count", 0) for item in reviewed)
    mock_total = sum(predictions[item["case_id"]].get("mock_count", 0) for item in reviewed)
    approved = sum(predictions[item["case_id"]].get("recommendation_status") == "recommend" for item in reviewed)
    return {
        "reviewed_case_count": len(reviewed),
        "supplier_precision_at_1": _ratio(p1, len(match_cases)),
        "supplier_precision_at_5": _ratio(p5, len(match_cases)),
        "false_match_rate": _ratio(false_matches, len(no_match_cases)),
        "no_match_accuracy": _ratio(len(no_match_cases) - false_matches, len(no_match_cases)),
        "field_completeness": _ratio(sum(predictions[item["case_id"]].get("field_completeness", 0) for item in reviewed), len(reviewed)),
        "real_supplier_rate": _ratio(supplier_total - mock_total, supplier_total),
        "mock_contamination_rate": _ratio(mock_total, supplier_total) or 0.0,
        "recommendation_precision": _ratio(correct_recommendations, len(recommendation_cases)),
        "manual_review_rate": _ratio(sum(predictions[item["case_id"]].get("recommendation_status") == "needs_manual_review" for item in reviewed), len(reviewed)),
        "cost_per_approved_candidate": _ratio(sum(predictions[item["case_id"]].get("cost", 0) for item in reviewed), approved),
        "average_retries": _ratio(sum(predictions[item["case_id"]].get("retries", 0) for item in reviewed), len(reviewed)),
        "quality_pipeline_success_rate": _ratio(sum(bool(predictions[item["case_id"]].get("pipeline_success")) for item in reviewed), len(reviewed)),
    }
```

The seed JSON must include the audited historical LLM top pairs as `reviewed: false`, artifact hashes, ASIN family, candidate offer ids, mismatch types, and blank reviewer metadata. Do not convert audit inference into ground truth. `scripts/evaluate_sourcing_quality.py` accepts label and prediction paths and writes deterministic JSON with sorted keys.

- [ ] **Step 4: Run evaluator tests and CLI fixture check**

Run: `TEMP=/tmp TMP=/tmp TMPDIR=/tmp pytest tests/test_benchmark_evaluate.py -v`

Create `benchmarks/fixtures/empty_predictions.json` with the exact content `{}`.

Run: `python scripts/evaluate_sourcing_quality.py --labels benchmarks/fixtures/sourcing_quality_seed.json --predictions benchmarks/fixtures/empty_predictions.json --output /tmp/sourcing_metrics.json`

Expected: unit test passes; CLI reports `reviewed_case_count: 0` and null label-dependent precision values rather than claiming improvement.

- [ ] **Step 5: Commit benchmark infrastructure**

```bash
git add benchmarks scripts/evaluate_sourcing_quality.py tests/test_benchmark_evaluate.py
git commit -m "test: add sourcing quality benchmark metrics"
```

---


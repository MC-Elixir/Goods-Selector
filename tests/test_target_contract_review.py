from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent import target_contract_review


def _queue(artifact_path: Path, artifact_sha256: str) -> dict:
    return {
        "schema_version": "1.0",
        "dataset_id": "review-test",
        "ground_truth_type": "unreviewed_live_queue",
        "cases": [
            {
                "case_id": "case-1",
                "reviewed": False,
                "category_id": "patio_umbrellas_shade",
                "asin": "B000TEST01",
                "amazon_title": "6ft Beach Umbrella with Sand Anchor",
                "artifact_path": artifact_path.as_posix(),
                "artifact_sha256": artifact_sha256,
                "candidate_offer_ids": ["101", "202"],
                "candidate_titles": ["183cm 沙滩伞", "户外帐篷支架"],
                "correct_offer_ids": [],
                "no_match": None,
                "recommendation_label": None,
                "review_notes": "",
            }
        ],
    }


@pytest.fixture
def review_store(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact.json"
    artifact.write_text(
        json.dumps(
            [
                {
                    "product": {
                        "asin": "B000TEST01",
                        "title": "Stored Amazon title",
                        "listing_url": "https://www.amazon.com/dp/B000TEST01",
                    },
                    "suppliers": [
                        {
                            "alibaba_offer_id": "101",
                            "title_cn": "Stored supplier title",
                            "offer_url": "https://detail.1688.com/offer/101.html",
                            "base_price_cny": 88,
                            "moq": 2,
                            "raw_data": {"spec_match": {"conflicts": []}},
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(
        json.dumps(_queue(artifact.relative_to(tmp_path), digest), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(target_contract_review, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(target_contract_review, "_QUEUE_FILE", queue_file)
    monkeypatch.setattr(target_contract_review, "_REVIEWS_FILE", tmp_path / "reviews.json")
    return tmp_path


def test_review_requires_complete_candidate_decisions_or_explicit_no_match(review_store):
    partial = target_contract_review.save_target_contract_review(
        "case-1", "accept", offer_id="101", note="looks right"
    )
    assert partial["reviewed"] is False
    assert partial["correct_offer_ids"] == ["101"]

    complete = target_contract_review.save_target_contract_review(
        "case-1", "reject", offer_id="202", note="second is a frame"
    )
    assert complete["reviewed"] is True
    assert complete["no_match"] is False
    assert complete["recommendation_label"] == "recommend"
    assert complete["correct_offer_ids"] == ["101"]

    persisted = target_contract_review.reviewed_target_contract_dataset()["cases"][0]
    assert persisted["reviewed"] is True
    assert "stored_evidence" not in str(persisted)
    assert not list(review_store.glob(".reviews.json.*"))


def test_all_rejections_stay_unreviewed_until_no_match_is_explicit(review_store):
    target_contract_review.save_target_contract_review(
        "case-1", "reject", offer_id="101"
    )
    rejected = target_contract_review.save_target_contract_review(
        "case-1", "reject", offer_id="202"
    )
    assert rejected["reviewed"] is False
    assert rejected["no_match"] is None

    no_match = target_contract_review.save_target_contract_review("case-1", "no_match")
    assert no_match["reviewed"] is True
    assert no_match["no_match"] is True
    assert no_match["correct_offer_ids"] == []
    assert no_match["recommendation_label"] == "reject"


def test_pinned_artifact_evidence_is_exposed_only_after_checksum_verification(
    review_store, monkeypatch
):
    queue = target_contract_review.list_target_contract_reviews()
    case = queue["cases"][0]
    assert case["artifact"]["sha256_verified"] is True
    assert case["amazon_evidence"]["title"] == "Stored Amazon title"
    assert case["candidates"][0]["stored_evidence"]["base_price_cny"] == 88
    assert case["candidates"][1]["stored_evidence"] is None

    queue_payload = json.loads(target_contract_review._QUEUE_FILE.read_text(encoding="utf-8"))
    queue_payload["cases"][0]["artifact_sha256"] = "0" * 64
    target_contract_review._QUEUE_FILE.write_text(
        json.dumps(queue_payload), encoding="utf-8"
    )
    mismatched = target_contract_review.list_target_contract_reviews()["cases"][0]
    assert mismatched["artifact"]["sha256_verified"] is False
    assert mismatched["candidates"][0]["stored_evidence"] is None


def test_review_rejects_unknown_candidate(review_store):
    with pytest.raises(ValueError, match="not a candidate"):
        target_contract_review.save_target_contract_review(
            "case-1", "accept", offer_id="999"
        )


def test_corrupt_review_store_is_never_silently_overwritten(review_store):
    target_contract_review._REVIEWS_FILE.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        target_contract_review.save_target_contract_review(
            "case-1", "accept", offer_id="101"
        )

    assert target_contract_review._REVIEWS_FILE.read_text(encoding="utf-8") == "{bad json"

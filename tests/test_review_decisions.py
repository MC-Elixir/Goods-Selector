"""Manual supplier review decision persistence."""
from __future__ import annotations

import pytest

from agent import review_decisions


def test_supplier_review_decision_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(review_decisions, "_DECISIONS_FILE", tmp_path / "reviews.json")

    result = review_decisions.set_supplier_review("run:B0TEST:1001", "accepted")

    assert result["saved"] is True
    assert review_decisions.load_supplier_reviews()["run:B0TEST:1001"]["status"] == "accepted"

    cleared = review_decisions.set_supplier_review("run:B0TEST:1001", "pending")

    assert cleared["saved"] is False
    assert review_decisions.load_supplier_reviews() == {}


def test_supplier_review_rejects_bad_status(tmp_path, monkeypatch):
    monkeypatch.setattr(review_decisions, "_DECISIONS_FILE", tmp_path / "reviews.json")

    with pytest.raises(ValueError):
        review_decisions.set_supplier_review("run:B0TEST:1001", "maybe")


def test_supplier_review_key_prefers_offer_id():
    key = review_decisions.supplier_review_key(
        "run:B0TEST",
        {"alibaba_offer_id": "1001", "offer_url": "https://detail.1688.com/offer/1001.html"},
        1,
    )

    assert key == "run:B0TEST:1001"

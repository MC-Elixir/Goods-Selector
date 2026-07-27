from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent.provenance import critical_evidence_gaps, evidence
from schemas.sourcing import EvidenceStatus, FieldEvidence, MatchEvidence, RecommendationStatus


def test_missing_field_evidence_confidence_remains_unknown():
    item = FieldEvidence(
        value=None,
        status=EvidenceStatus.MISSING,
        source_provider="1688",
    )
    assert item.confidence is None


def test_missing_evidence_cannot_carry_a_value():
    with pytest.raises(ValidationError):
        evidence(value=12.5, status=EvidenceStatus.MISSING, source_provider="1688")


def test_extracted_evidence_requires_source_and_timestamp():
    item = evidence(
        value=12.5,
        status=EvidenceStatus.EXTRACTED,
        source_provider="1688_playwright",
        source_type="offer_detail",
        source_ref="https://detail.1688.com/offer/123.html",
        observed_at=datetime.now(timezone.utc),
        confidence=0.94,
    )
    assert item.value == 12.5
    assert item.status is EvidenceStatus.EXTRACTED


@pytest.mark.parametrize("status", [EvidenceStatus.EXTRACTED, EvidenceStatus.VERIFIED])
@pytest.mark.parametrize("missing_field", ["source_type", "source_ref", "observed_at"])
def test_extracted_and_verified_evidence_require_all_source_metadata(status, missing_field):
    metadata = {
        "source_type": "offer_detail",
        "source_ref": "artifact:offer-123",
        "observed_at": datetime.now(timezone.utc),
    }
    metadata.pop(missing_field)

    with pytest.raises(ValidationError):
        evidence(value=12.5, status=status, source_provider="1688", **metadata)


@pytest.mark.parametrize("datetime_field", ["observed_at", "expires_at"])
def test_evidence_rejects_naive_datetimes(datetime_field):
    timestamps = {
        "observed_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    timestamps[datetime_field] = datetime.now()

    with pytest.raises(ValidationError):
        evidence(
            value=12.5,
            status=EvidenceStatus.EXTRACTED,
            source_provider="1688",
            source_type="offer_detail",
            source_ref="artifact:offer-123",
            **timestamps,
        )


def test_stale_critical_evidence_is_a_gap():
    old = datetime.now(timezone.utc) - timedelta(days=31)
    fields = {
        "price": evidence(
            value=12.5,
            status=EvidenceStatus.EXTRACTED,
            source_provider="1688",
            source_type="offer_detail",
            source_ref="artifact:offer-123",
            observed_at=old,
            expires_at=old + timedelta(days=7),
            confidence=0.9,
        )
    }
    assert critical_evidence_gaps(fields, {"price"}) == ["price:stale"]


def test_critical_evidence_without_confidence_is_a_gap():
    fields = {
        "price": evidence(
            value=12.5,
            status=EvidenceStatus.EXTRACTED,
            source_provider="1688",
            source_type="offer_detail",
            source_ref="artifact:offer-123",
            observed_at=datetime.now(timezone.utc),
        )
    }
    assert critical_evidence_gaps(fields, {"price"}) == ["price:untrusted"]


def test_negative_visual_classification_cannot_be_a_match():
    result = MatchEvidence(
        amazon_ref="asin:B000TEST",
        supplier_ref="offer:123",
        function_match=0.95,
        accessory_vs_full_product_match=1.0,
        package_quantity_match=1.0,
        visual_is_match=False,
        visual_confidence=0.99,
        mismatch_reasons=["visual_core_function_conflict"],
        decision="reject",
        overall_confidence=0.99,
    )
    assert result.decision == "reject"
    assert result.visual_is_match is False
    assert RecommendationStatus.RECOMMEND.value == "recommend"


def test_negative_visual_classification_requires_reject_decision():
    with pytest.raises(ValidationError):
        MatchEvidence(
            amazon_ref="asin:B000TEST",
            supplier_ref="offer:123",
            visual_is_match=False,
            decision="keep",
            overall_confidence=0.99,
        )

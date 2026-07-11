from types import SimpleNamespace

from analyzers.profit_model import InsufficientCostEvidence
from analyzers.scorer import ScoringEvidenceError
from pipeline.orchestrator import _evidence_rejection_reasons, _review_fallback_records


def _record(total_score, net_profit, has_profit=True, has_suppliers=True):
    return SimpleNamespace(
        score=SimpleNamespace(total_score=total_score),
        profit=object() if has_profit else None,
        suppliers=[object()] if has_suppliers else [],
        net_profit=net_profit,
    )


def test_review_fallback_records_rank_rejected_reviewable_items():
    low = _record(40, 20)
    high = _record(70, 1)
    tie = _record(70, 5)
    no_profit = _record(99, 99, has_profit=False)
    no_supplier = _record(98, 98, has_suppliers=False)
    no_score = SimpleNamespace(score=None, profit=object(), suppliers=[object()], net_profit=100)

    records = _review_fallback_records([low, high, tie, no_profit, no_supplier, no_score], top_n=2)

    assert records == [tie, high]


def test_typed_evidence_errors_map_to_explicit_rejection_reasons():
    assert _evidence_rejection_reasons(
        InsufficientCostEvidence(["purchase_price"])
    ) == ["missing_purchase_price"]
    assert _evidence_rejection_reasons(
        InsufficientCostEvidence(["weight_kg", "length_cm"])
    ) == ["missing_logistics_dimensions"]
    assert _evidence_rejection_reasons(
        ScoringEvidenceError("competition", ["competing_listings", "top10_share"])
    ) == ["missing_market_evidence"]
    assert _evidence_rejection_reasons(
        ScoringEvidenceError("supply", ["moq"])
    ) == ["missing_moq"]
    assert _evidence_rejection_reasons(
        ScoringEvidenceError("supply", ["purchase_price", "moq"])
    ) == ["missing_purchase_price", "missing_moq"]


def test_review_fallback_includes_explicitly_insufficient_records_without_snapshots():
    insufficient = SimpleNamespace(
        score=None,
        profit=None,
        suppliers=[object()],
        rejection_reasons=["missing_purchase_price"],
        net_profit=0,
    )

    assert _review_fallback_records([insufficient], top_n=1) == [insufficient]

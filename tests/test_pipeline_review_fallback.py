from types import SimpleNamespace

from pipeline.orchestrator import _review_fallback_records


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

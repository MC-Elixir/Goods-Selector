"""Candidate filter tests."""
from __future__ import annotations

from types import SimpleNamespace

from pipeline.filters import rank_candidates


def _record(score=None, net_profit=0, top_supplier_candidate_score=0):
    return SimpleNamespace(
        score=score,
        net_profit=net_profit,
        top_supplier_candidate_score=top_supplier_candidate_score,
    )


def _score(total_score, passed=True):
    return SimpleNamespace(total_score=total_score, passed_hard_filter=passed)


def test_rank_candidates_skips_unscored_records():
    records = [
        _record(score=None),
        _record(score=_score(80), net_profit=5),
        _record(score=_score(90, passed=False), net_profit=20),
    ]

    assert rank_candidates(records) == [records[1]]


def test_rank_candidates_sorts_by_score_then_secondary_key():
    records = [
        _record(score=_score(80), net_profit=5),
        _record(score=_score(90), net_profit=1),
        _record(score=_score(80), net_profit=10),
    ]

    assert rank_candidates(records) == [records[1], records[2], records[0]]


def test_rank_candidates_prefers_top_supplier_candidate_score_before_profit():
    records = [
        _record(score=_score(80), net_profit=20, top_supplier_candidate_score=0.30),
        _record(score=_score(80), net_profit=5, top_supplier_candidate_score=0.90),
        _record(score=_score(80), net_profit=10, top_supplier_candidate_score=0.60),
    ]

    assert rank_candidates(records) == [records[1], records[2], records[0]]

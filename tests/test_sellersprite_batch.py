from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.sellersprite_batch import run_reverse_keyword_batch
from agent.sellersprite_models import SellerSpriteContext, SellerSpriteResult


def _result(asin: str, status: str = "SUCCESS", error_code: str | None = None):
    return SellerSpriteResult(
        status=status,
        context=SellerSpriteContext.create(asin),
        data={"row_count": 1, "manifest_id": "00000000-0000-0000-0000-000000000001"} if status == "SUCCESS" else {},
        error_code=error_code,
    )


def test_batch_deduplicates_and_preserves_order(monkeypatch):
    calls = []

    def fake(asin, **_kwargs):
        calls.append(asin)
        return _result(asin)

    monkeypatch.setattr("agent.sellersprite_batch.run_reverse_keyword_export", fake)
    deps = SimpleNamespace(min_interval_seconds=0, is_cancelled=lambda: False)
    batch = run_reverse_keyword_batch(["b00q7oan50", "B00Q7OAN50", "B01M16WBW1"], dependencies=deps)
    assert calls == ["B00Q7OAN50", "B01M16WBW1"]
    assert batch.success_count == 2
    assert not batch.stopped


def test_batch_stops_on_human_terminal(monkeypatch):
    calls = []

    def fake(asin, **_kwargs):
        calls.append(asin)
        return _result(asin, "NEEDS_HUMAN", "CAPTCHA")

    monkeypatch.setattr("agent.sellersprite_batch.run_reverse_keyword_export", fake)
    deps = SimpleNamespace(min_interval_seconds=0, is_cancelled=lambda: False)
    batch = run_reverse_keyword_batch(["B00Q7OAN50", "B01M16WBW1"], dependencies=deps)
    assert calls == ["B00Q7OAN50"]
    assert batch.stopped and batch.stop_reason == "CAPTCHA"


def test_batch_rejects_more_than_bound():
    asins = [f"B00Q7O{index:04d}" for index in range(21)]
    with pytest.raises(ValueError, match="limited"):
        run_reverse_keyword_batch(asins)

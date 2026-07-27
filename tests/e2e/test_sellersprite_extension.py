"""Opt-in live verification for the SellerSprite browser-export boundary.

This test deliberately has no fixture that starts Chrome or changes browser
state.  It is collected but skipped unless the operator explicitly approves a
signed-in live run with ``SELLERSPRITE_E2E=1``.
"""
from __future__ import annotations

import os
from uuid import UUID

import pytest

from agent.sellersprite_service import run_reverse_keyword_export


@pytest.mark.skipif(
    os.getenv("SELLERSPRITE_E2E") != "1",
    reason="requires a signed-in Chrome profile and explicit user approval",
)
def test_reverse_keyword_export_live() -> None:
    """A user-approved live export publishes only the current public contract."""
    result = run_reverse_keyword_export("B00Q7OAN50")

    assert result.status == "SUCCESS"
    assert result.data["row_count"] > 0
    assert len(result.data["keyword_rows"]) == min(20, result.data["row_count"])
    assert len(result.data["file_sha256"]) == 64
    assert result.data["file_sha256"] == result.data["file_sha256"].lower()
    assert str(UUID(result.data["manifest_id"])) == result.data["manifest_id"]

"""Bounded SellerSprite browser-export batch orchestration.

The extension remains the source of truth.  This module only sequences the
already validated single-ASIN workflow, preserving its immutable manifest and
human-terminal semantics for every item.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Callable

from agent.sellersprite_models import SellerSpriteResult
from agent.sellersprite_policy import validate_sellersprite_asin
from agent.sellersprite_service import SellerSpriteDependencies, run_reverse_keyword_export


MAX_BATCH_SIZE = 20
_STOP_CODES = frozenset({
    "NEEDS_HUMAN",
    "SELLERSPRITE_LOGIN_REQUIRED",
    "SELLERSPRITE_PERMISSION_REQUIRED",
    "SELLERSPRITE_QUOTA_EXCEEDED",
    "CAPTCHA",
})


@dataclass(frozen=True)
class SellerSpriteBatchResult:
    results: tuple[SellerSpriteResult, ...]
    stopped: bool = False
    stop_reason: str | None = None

    @property
    def success_count(self) -> int:
        return sum(result.status == "SUCCESS" for result in self.results)

    @property
    def human_required_count(self) -> int:
        return sum(result.status == "NEEDS_HUMAN" for result in self.results)


def run_reverse_keyword_batch(
    asins: list[str] | tuple[str, ...],
    *,
    sourcing_run_id: str | None = None,
    dependencies: SellerSpriteDependencies | None = None,
    max_batch_size: int = MAX_BATCH_SIZE,
    cancel_check: Callable[[], bool] | None = None,
) -> SellerSpriteBatchResult:
    """Run a small, deduplicated batch with an explicit human stop gate."""
    if not isinstance(asins, (list, tuple)):
        raise ValueError("asins must be a list")
    if not asins:
        raise ValueError("at least one ASIN is required")
    if max_batch_size < 1:
        raise ValueError("max_batch_size must be positive")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in asins:
        asin = validate_sellersprite_asin(raw)
        if asin not in seen:
            normalized.append(asin)
            seen.add(asin)
    if len(normalized) > max_batch_size:
        raise ValueError(f"batch is limited to {max_batch_size} ASINs")

    deps = dependencies or SellerSpriteDependencies()
    cancel = cancel_check or deps.is_cancelled or (lambda: False)
    results: list[SellerSpriteResult] = []
    stopped = False
    stop_reason: str | None = None
    for index, asin in enumerate(normalized):
        if cancel():
            stopped = True
            stop_reason = "CANCELLED"
            break
        result = run_reverse_keyword_export(
            asin,
            sourcing_run_id=sourcing_run_id,
            dependencies=deps,
        )
        results.append(result)
        if result.status in _STOP_CODES:
            stopped = True
            stop_reason = result.error_code or result.status
            break
        if index < len(normalized) - 1 and deps.min_interval_seconds:
            # Keep the extension usage human-paced between separate exports.
            getattr(deps, "sleeper", sleep)(float(deps.min_interval_seconds))
    return SellerSpriteBatchResult(tuple(results), stopped, stop_reason)

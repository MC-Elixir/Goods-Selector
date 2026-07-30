"""Shared cooperative cancellation helpers."""
from __future__ import annotations

from typing import Callable

CancelCheck = Callable[[], bool]


class CancellationRequested(RuntimeError):
    """Raised when a long-running helper should stop for a user cancel."""


def raise_if_cancelled(cancel_check: CancelCheck | None, context: str = "operation") -> None:
    if cancel_check and cancel_check():
        raise CancellationRequested(f"{context} cancelled")

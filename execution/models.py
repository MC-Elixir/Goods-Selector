"""Execution state types with explicit transition semantics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_WAIT = "retry_wait"
    HUMAN_REQUIRED = "human_required"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class ErrorDisposition(str, Enum):
    RETRYABLE = "retryable"
    HUMAN_REQUIRED = "human_required"
    PERMANENT = "permanent"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


ALLOWED_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.PENDING: {NodeStatus.RUNNING, NodeStatus.CANCELLED, NodeStatus.SKIPPED},
    NodeStatus.RUNNING: {
        NodeStatus.SUCCEEDED,
        NodeStatus.FAILED,
        NodeStatus.RETRY_WAIT,
        NodeStatus.HUMAN_REQUIRED,
        NodeStatus.CANCELLED,
        NodeStatus.TIMED_OUT,
    },
    NodeStatus.RETRY_WAIT: {NodeStatus.PENDING, NodeStatus.CANCELLED},
    NodeStatus.HUMAN_REQUIRED: {NodeStatus.PENDING, NodeStatus.CANCELLED},
    NodeStatus.FAILED: {NodeStatus.PENDING, NodeStatus.CANCELLED},
    NodeStatus.SUCCEEDED: set(),
    NodeStatus.CANCELLED: set(),
    NodeStatus.SKIPPED: set(),
    NodeStatus.TIMED_OUT: {NodeStatus.PENDING, NodeStatus.CANCELLED},
}


def validate_transition(before: str | NodeStatus, after: str | NodeStatus) -> None:
    source = NodeStatus(before)
    target = NodeStatus(after)
    if target not in ALLOWED_TRANSITIONS[source]:
        raise ValueError(f"illegal execution transition: {source.value} -> {target.value}")


class LeaseLost(RuntimeError):
    """Raised when an old or concurrent worker can no longer commit a node."""


class HumanActionRequired(RuntimeError):
    """Structured handoff for login, captcha, TMD, permission, or review."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        instructions: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.instructions = instructions or message
        self.evidence_refs = list(evidence_refs or [])

    def payload(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": str(self),
            "instructions": self.instructions,
            "evidence_refs": self.evidence_refs,
        }


@dataclass(frozen=True)
class Claim:
    node_id: int
    run_id: int
    scope_type: str
    scope_key: str
    stage: str
    attempt_id: int
    attempt_no: int
    generation: int
    lease_token: str
    worker_id: str
    deadline: datetime | None
    input_fingerprint: str | None
    input_snapshot: dict[str, Any] | None


@dataclass(frozen=True)
class StageContext:
    node_id: int
    attempt_id: int
    run_id: int
    asin: str | None
    attempt_no: int
    generation: int
    lease_token: str
    worker_id: str
    deadline: datetime | None
    cancel_check: Callable[[], bool] | None
    heartbeat: Callable[[], None]
    input_snapshot: dict[str, Any] | None

    def raise_if_cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            from agent.cancellation import CancellationRequested
            raise CancellationRequested("execution cancelled")

    def raise_if_deadline_exceeded(self, now: datetime | None = None) -> None:
        if self.deadline is not None and (now or datetime.utcnow()) >= self.deadline:
            raise TimeoutError("execution deadline exceeded")

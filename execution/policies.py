"""Bounded retry, backoff, and execution error classification."""
from __future__ import annotations

from dataclasses import dataclass

from agent.cancellation import CancellationRequested
from execution.models import ErrorDisposition, HumanActionRequired


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 2.0
    maximum_backoff_seconds: float = 60.0

    def backoff_seconds(self, attempt_count: int) -> float:
        exponent = max(int(attempt_count) - 1, 0)
        return min(
            self.initial_backoff_seconds * (2 ** exponent),
            self.maximum_backoff_seconds,
        )


@dataclass(frozen=True)
class ClassifiedError:
    disposition: ErrorDisposition
    error_code: str
    detail: str
    human_action: dict | None = None


def classify_error(exc: BaseException) -> ClassifiedError:
    if isinstance(exc, HumanActionRequired):
        return ClassifiedError(
            ErrorDisposition.HUMAN_REQUIRED,
            exc.error_code,
            str(exc),
            exc.payload(),
        )
    if isinstance(exc, CancellationRequested):
        return ClassifiedError(ErrorDisposition.CANCELLED, "CANCELLED", str(exc))
    error_code = str(getattr(exc, "error_code", "") or "").strip().upper()
    name = exc.__class__.__name__.upper()
    message = str(exc)
    combined = f"{error_code} {name} {message}".lower()
    human_markers = (
        "captcha", "login_required", "login required", "auth_required",
        "authentication required", "permission_required", "permission required",
        "unauthorized", "tmd", "human action", "manual confirmation",
        "verification required",
    )
    if error_code in {
        "CAPTCHA", "AUTH_REQUIRED", "LOGIN_REQUIRED", "SELLERSPRITE_LOGIN_REQUIRED",
        "PERMISSION_REQUIRED", "SELLERSPRITE_PERMISSION_REQUIRED", "TMD_BLOCKED",
        "UNAUTHORIZED",
    } or any(marker in combined for marker in human_markers):
        instructions = str(getattr(exc, "instructions", "") or message)
        evidence_refs = list(getattr(exc, "evidence_refs", None) or [])
        stable_code = error_code or "HUMAN_ACTION_REQUIRED"
        return ClassifiedError(
            ErrorDisposition.HUMAN_REQUIRED,
            stable_code,
            message,
            {
                "error_code": stable_code,
                "message": message,
                "instructions": instructions,
                "evidence_refs": evidence_refs,
            },
        )
    if isinstance(exc, TimeoutError) or "TIMEOUT" in name or "TIMEOUT" in error_code:
        return ClassifiedError(ErrorDisposition.TIMED_OUT, "STAGE_TIMEOUT", str(exc))
    if (
        isinstance(exc, (ConnectionError, OSError))
        and not isinstance(exc, (PermissionError, FileNotFoundError))
        or error_code in {"RATE_LIMIT", "TOO_MANY_REQUESTS", "HTTP_429"}
        or "rate limit" in combined
        or "temporarily unavailable" in combined
    ):
        return ClassifiedError(
            ErrorDisposition.RETRYABLE,
            error_code or name,
            str(exc),
        )
    return ClassifiedError(
        ErrorDisposition.PERMANENT,
        exc.__class__.__name__.upper(),
        str(exc),
    )

"""Typed contracts for the SellerSprite browser-export workflow."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.sellersprite_policy import normalize_sellersprite_error_code


_REQUIRED_LOCATOR_NAMES = (
    "ready",
    "login_required",
    "permission_required",
    "captcha",
    "reverse_keywords",
    "asin_input",
    "submit",
    "results_ready",
    "export",
)
_SUPPORTED_LOCATOR_PREFIXES = frozenset(
    {"css", "text", "role", "id", "name", "iframe", "shadow"}
)


@dataclass(frozen=True)
class SellerSpriteContext:
    asin: str
    sourcing_run_id: str
    call_id: str
    observed_at: str

    @classmethod
    def create(cls, asin: str, sourcing_run_id: str | None = None) -> "SellerSpriteContext":
        if sourcing_run_id is None:
            normalized_run_id = str(uuid.uuid4())
        else:
            try:
                normalized_run_id = str(uuid.UUID(str(sourcing_run_id)))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("sourcing_run_id must be a UUID") from exc
        return cls(
            asin=asin.strip().upper(),
            sourcing_run_id=normalized_run_id,
            call_id=str(uuid.uuid4()),
            observed_at=datetime.now(UTC).isoformat(),
        )


@dataclass(frozen=True)
class SellerSpriteResult:
    status: str
    context: SellerSpriteContext
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    @classmethod
    def needs_human(cls, context: SellerSpriteContext, error_code: str) -> "SellerSpriteResult":
        return cls(
            status="NEEDS_HUMAN",
            context=context,
            error_code=normalize_sellersprite_error_code(error_code),
        )


@dataclass(frozen=True)
class SellerSpriteLocatorProfile:
    ready: str
    login_required: str
    permission_required: str
    captcha: str
    reverse_keywords: str
    asin_input: str
    submit: str
    results_ready: str
    export: str

    @classmethod
    def from_json(cls, path: Path) -> "SellerSpriteLocatorProfile":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("locator profile must be a readable JSON object") from exc
        if not isinstance(payload, dict):
            raise ValueError("locator profile must be a JSON object")

        locators: dict[str, str] = {}
        for name in _REQUIRED_LOCATOR_NAMES:
            value = payload.get(name)
            if not isinstance(value, str):
                raise ValueError(f"locator '{name}' is required")
            prefix, separator, payload_value = value.partition("=")
            if (
                not separator
                or prefix not in _SUPPORTED_LOCATOR_PREFIXES
                or not payload_value.strip()
            ):
                raise ValueError(f"locator '{name}' must use a supported locator syntax")
            locators[name] = value
        return cls(**locators)

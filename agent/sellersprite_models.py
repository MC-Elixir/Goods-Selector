"""Typed contracts for the SellerSprite browser-export workflow."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


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
_COORDINATE_LOCATOR_RE = re.compile(
    r"^\s*\(?\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*\)?\s*$"
)


@dataclass(frozen=True)
class SellerSpriteContext:
    asin: str
    sourcing_run_id: str
    call_id: str
    observed_at: str

    @classmethod
    def create(cls, asin: str, sourcing_run_id: str | None = None) -> "SellerSpriteContext":
        return cls(
            asin=asin.strip().upper(),
            sourcing_run_id=sourcing_run_id or str(uuid4()),
            call_id=str(uuid4()),
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
        return cls(status="NEEDS_HUMAN", context=context, error_code=error_code)


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
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"locator '{name}' is required")
            locator = value.strip()
            if _COORDINATE_LOCATOR_RE.fullmatch(locator):
                raise ValueError(f"locator '{name}' must not use screen coordinates")
            locators[name] = locator
        return cls(**locators)

"""Typed contracts for the SellerSprite browser-export workflow."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.sellersprite_policy import (
    normalize_sellersprite_error_code,
    validate_sellersprite_asin,
    validate_sellersprite_result_status,
)

_REQUIRED_LOCATOR_NAMES = (
    "panel_open",
    "ready",
    "login_required",
    "permission_required",
    "captcha",
    "reverse_keywords",
    "asin_input",
    "submit",
    "results_ready",
    "export_menu",
    "export",
)
_SUPPORTED_LOCATOR_PREFIXES = frozenset(
    {"css", "text", "role", "id", "name", "iframe", "shadow"}
)
# Optional locators keep older profiles compatible; each is validated only when
# present.  The competitor_* group drives the «查竞品 / 选市场» export flow.
_OPTIONAL_LOCATOR_NAMES = (
    "quota_required",
    "export_overflow",
    "competitor_lookup",
    "competitor_keyword_input",
    "competitor_submit",
    "competitor_results_ready",
    "competitor_export_menu",
    "competitor_export",
    "competitor_export_overflow",
)
# The minimum locators required to run one competitor-products export.
_COMPETITOR_REQUIRED_LOCATORS = (
    "competitor_keyword_input",
    "competitor_submit",
    "competitor_results_ready",
    "competitor_export_menu",
    "competitor_export",
)


def _canonical_uuid(value: object, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


@dataclass(frozen=True)
class SellerSpriteContext:
    asin: str
    sourcing_run_id: str
    call_id: str
    observed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asin", validate_sellersprite_asin(self.asin))
        object.__setattr__(
            self,
            "sourcing_run_id",
            _canonical_uuid(self.sourcing_run_id, "sourcing_run_id"),
        )
        object.__setattr__(self, "call_id", _canonical_uuid(self.call_id, "call_id"))

    @classmethod
    def create(cls, asin: str, sourcing_run_id: str | None = None) -> "SellerSpriteContext":
        return cls(
            asin=asin,
            sourcing_run_id=sourcing_run_id if sourcing_run_id is not None else str(uuid.uuid4()),
            call_id=str(uuid.uuid4()),
            observed_at=datetime.now(UTC).isoformat(),
        )


@dataclass(frozen=True)
class SellerSpriteResult:
    status: str
    context: SellerSpriteContext
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", validate_sellersprite_result_status(self.status))
        if self.error_code is not None:
            object.__setattr__(
                self,
                "error_code",
                normalize_sellersprite_error_code(self.error_code),
            )

    @classmethod
    def needs_human(cls, context: SellerSpriteContext, error_code: str) -> "SellerSpriteResult":
        return cls(
            status="NEEDS_HUMAN",
            context=context,
            error_code=error_code,
        )


@dataclass(frozen=True)
class SellerSpriteLocatorProfile:
    panel_open: str
    ready: str
    login_required: str
    permission_required: str
    captcha: str
    reverse_keywords: str
    asin_input: str
    submit: str
    results_ready: str
    export_menu: str
    export: str
    quota_required: str = ""
    # Responsive extension layouts hide the desktop footer actions behind an
    # explicit overflow button. Empty keeps older locator profiles compatible.
    export_overflow: str = ""
    # Competitor / market export flow («查竞品 / 选市场»).  All optional so the
    # reverse-keyword-only profiles remain valid; validated when provided.
    competitor_lookup: str = ""
    competitor_keyword_input: str = ""
    competitor_submit: str = ""
    competitor_results_ready: str = ""
    competitor_export_menu: str = ""
    competitor_export: str = ""
    competitor_export_overflow: str = ""

    def has_competitor_locators(self) -> bool:
        """True for either keyword-search or current-list market export mode."""
        export_ready = all(
            getattr(self, name, "")
            for name in ("competitor_results_ready", "competitor_export_menu", "competitor_export")
        )
        search_locators = (
            self.competitor_keyword_input,
            self.competitor_submit,
        )
        # A profile may export the product list already visible in the attached
        # Amazon tab. In that mode no search field is touched; the keyword is
        # retained solely as the research label. A half-configured search flow
        # remains invalid.
        return export_ready and (all(search_locators) or not any(search_locators))

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
        optional_locators: dict[str, str] = {}
        for name in _OPTIONAL_LOCATOR_NAMES:
            value = payload.get(name, "")
            if not isinstance(value, str):
                raise ValueError(f"locator '{name}' must be a string when provided")
            if value:
                prefix, separator, payload_value = value.partition("=")
                if (
                    not separator
                    or prefix not in _SUPPORTED_LOCATOR_PREFIXES
                    or not payload_value.strip()
                ):
                    raise ValueError(f"locator '{name}' must use a supported locator syntax")
            optional_locators[name] = value
        return cls(**locators, **optional_locators)

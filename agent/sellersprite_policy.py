"""Pure validation policy for SellerSprite browser requests."""
from __future__ import annotations

import re


ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
SAFE_SELLERSPRITE_ERROR_CODES = frozenset(
    {
        "EXTENSION_UNAVAILABLE",
        "SELLERSPRITE_LOGIN_REQUIRED",
        "SELLERSPRITE_PERMISSION_REQUIRED",
        "SELLERSPRITE_QUOTA_EXCEEDED",
        "CAPTCHA",
        "ASIN_MISMATCH",
        "EXPORT_FAILED",
        "DOWNLOAD_TIMEOUT",
        "INVALID_EXPORT",
        "NEEDS_HUMAN",
        "CANCELLED",
        "AMBIGUOUS_DOWNLOAD",
        "INTERNAL",
    }
)
SAFE_SELLERSPRITE_RESULT_STATUSES = SAFE_SELLERSPRITE_ERROR_CODES | frozenset({"SUCCESS"})


def validate_sellersprite_asin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("ASIN must be exactly 10 uppercase letters or digits")
    asin = (value or "").strip().upper()
    if not ASIN_RE.fullmatch(asin):
        raise ValueError("ASIN must be exactly 10 uppercase letters or digits")
    return asin


def normalize_sellersprite_error_code(value: object) -> str:
    if not isinstance(value, str):
        return "INTERNAL"
    normalized = value.upper()
    if normalized not in SAFE_SELLERSPRITE_ERROR_CODES:
        return "INTERNAL"
    return normalized


def validate_sellersprite_result_status(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("status must be a documented SellerSprite status")
    normalized = value.upper()
    if normalized not in SAFE_SELLERSPRITE_RESULT_STATUSES:
        raise ValueError("status must be a documented SellerSprite status")
    return normalized

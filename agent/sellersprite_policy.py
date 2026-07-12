"""Pure validation policy for SellerSprite browser requests."""
from __future__ import annotations

import re


ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def validate_sellersprite_asin(value: str) -> str:
    asin = (value or "").strip().upper()
    if not ASIN_RE.fullmatch(asin):
        raise ValueError("ASIN must be exactly 10 uppercase letters or digits")
    return asin

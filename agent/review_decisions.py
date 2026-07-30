"""Persist manual supplier review decisions."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from config.settings import DATA_DIR

_DECISIONS_FILE = DATA_DIR / "agent_review_decisions.json"
_ALLOWED_STATUSES = {"accepted", "rejected", "pending"}


def load_supplier_reviews() -> dict[str, Any]:
    if not _DECISIONS_FILE.exists():
        return {}
    try:
        data = json.loads(_DECISIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def set_supplier_review(key: str, status: str, note: str | None = None) -> dict[str, Any]:
    key = (key or "").strip()
    status = (status or "").strip()
    if not key:
        raise ValueError("key is required")
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(_ALLOWED_STATUSES))}")

    data = load_supplier_reviews()
    if status == "pending":
        data.pop(key, None)
    else:
        data[key] = {
            "status": status,
            "note": (note or "").strip(),
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
    _DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DECISIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "key": key,
        "status": status,
        "saved": status != "pending",
        "review_count": len(data),
    }


def supplier_review_key(product_key: str, supplier: dict[str, Any], rank: int) -> str:
    supplier_id = (
        supplier.get("alibaba_offer_id")
        or supplier.get("offer_url")
        or (supplier.get("raw_data") or {}).get("offer_id")
        or rank
    )
    return f"{product_key}:{supplier_id}"

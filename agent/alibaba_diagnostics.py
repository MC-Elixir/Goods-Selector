"""Persist sanitized 1688 Open Platform diagnostics."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from config.settings import DATA_DIR, settings

_DIAGNOSTIC_FILE = DATA_DIR / "alibaba_open_diagnostic.json"


def load_alibaba_open_diagnostic() -> dict[str, Any]:
    """Return the last 1688 Open Platform diagnostic if it matches current config shape."""
    if not _DIAGNOSTIC_FILE.exists():
        return {}
    try:
        data = json.loads(_DIAGNOSTIC_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("app_key_length") != len(settings.alibaba_app_key or ""):
        return {}
    if data.get("access_token_length") != len(settings.alibaba_access_token or ""):
        return {}
    if data.get("configured_gateway") != (settings.alibaba_api_gateway or "").rstrip("/"):
        return {}
    if data.get("namespace") != settings.alibaba_supplier_search_namespace:
        return {}
    if data.get("method") != settings.alibaba_supplier_search_method:
        return {}
    if data.get("keyword_param") != settings.alibaba_supplier_search_keyword_param:
        return {}
    if data.get("candidates") != settings.alibaba_supplier_search_candidates:
        return {}
    return data


def save_alibaba_open_diagnostic(result: dict[str, Any]) -> dict[str, Any]:
    """Persist non-secret 1688 Open Platform evidence for preflight and WebUI."""
    sanitized = {
        "checked_at": datetime.now(UTC).isoformat(),
        "configured_gateway": (settings.alibaba_api_gateway or "").rstrip("/"),
        "gateway": result.get("gateway"),
        "namespace": result.get("namespace") or settings.alibaba_supplier_search_namespace,
        "method": result.get("method") or settings.alibaba_supplier_search_method,
        "keyword_param": result.get("keyword_param") or settings.alibaba_supplier_search_keyword_param,
        "candidates": result.get("candidates") if result.get("candidates") is not None else settings.alibaba_supplier_search_candidates,
        "app_key_length": len(settings.alibaba_app_key or ""),
        "access_token_length": len(settings.alibaba_access_token or ""),
        "keyword": result.get("keyword"),
        "count": int(result.get("count") or 0),
        "has_supplier_evidence": bool(result.get("count")),
        "error": result.get("error"),
        "attempts": [
            {
                "namespace": item.get("namespace"),
                "method": item.get("method"),
                "keyword_param": item.get("keyword_param"),
                "ok": bool(item.get("ok")),
                "count": int(item.get("count") or 0),
                "error": item.get("error"),
            }
            for item in (result.get("attempts") or [])[:8]
            if isinstance(item, dict)
        ],
        "suppliers": [
            {
                "offer_id": item.get("offer_id"),
                "supplier": item.get("supplier"),
                "title": item.get("title"),
                "price_cny": item.get("price_cny"),
                "moq": item.get("moq"),
                "monthly_sales": item.get("monthly_sales"),
                "is_factory": item.get("is_factory"),
                "source": item.get("source"),
            }
            for item in (result.get("suppliers") or [])[:3]
            if isinstance(item, dict)
        ],
    }
    _DIAGNOSTIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DIAGNOSTIC_FILE.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return sanitized


def alibaba_open_supplier_guard() -> tuple[bool, str]:
    """Return whether 1688 Open Platform has verified supplier evidence."""
    if not (settings.alibaba_app_key and settings.alibaba_app_secret and settings.alibaba_access_token):
        return False, "1688 Open Platform config missing"
    diagnostic = load_alibaba_open_diagnostic()
    if diagnostic.get("has_supplier_evidence"):
        return True, ""
    if diagnostic.get("error"):
        return False, f"1688 pifatuan check failed: {diagnostic['error']}"
    return False, "1688 pifatuan check has not passed for the current app/token"

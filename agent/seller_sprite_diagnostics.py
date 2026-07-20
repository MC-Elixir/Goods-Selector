"""Persist sanitized SellerSprite connectivity diagnostics."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from config.settings import DATA_DIR, settings

_DIAGNOSTIC_FILE = DATA_DIR / "seller_sprite_diagnostic.json"


def load_seller_sprite_diagnostic() -> dict[str, Any]:
    """Return the last diagnostic only if it matches the current key shape."""
    if not _DIAGNOSTIC_FILE.exists():
        return {}
    try:
        data = json.loads(_DIAGNOSTIC_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("key_length") != len(settings.mjjl_api_key or ""):
        return {}
    base_url = (settings.mjjl_api_base or "").rstrip("/")
    if data.get("configured_base_url") != base_url:
        return {}
    return data


def save_seller_sprite_diagnostic(result: dict[str, Any]) -> dict[str, Any]:
    """Persist non-secret diagnostic evidence for preflight and WebUI."""
    sanitized = {
        "checked_at": datetime.now(UTC).isoformat(),
        "configured_base_url": (settings.mjjl_api_base or "").rstrip("/"),
        "base_url": result.get("base_url"),
        "key_length": result.get("key_length"),
        "asin": result.get("asin"),
        "marketplace": result.get("marketplace"),
        "keyword": result.get("keyword"),
        "has_market_evidence": bool(result.get("has_market_evidence")),
        "evidence_source": result.get("evidence_source"),
        "authorized_api_count": result.get("authorized_api_count"),
        "authorized_data_api_count": result.get("authorized_data_api_count"),
        "api_checks": [
            {
                "name": item.get("name"),
                "ok": bool(item.get("ok")),
                "evidence": bool(item.get("evidence")),
                "error": item.get("error"),
            }
            for item in (result.get("api_checks") or [])[:6]
            if isinstance(item, dict)
        ],
        "error": result.get("error"),
        "bsr": result.get("bsr"),
        "review_count": result.get("review_count"),
        "est_monthly_sales": result.get("est_monthly_sales"),
        "competing_listings": result.get("competing_listings"),
    }
    _DIAGNOSTIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DIAGNOSTIC_FILE.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return sanitized


def seller_sprite_market_data_guard() -> tuple[bool, str]:
    """Return whether any configured SellerSprite source can supply market data.

    The authenticated browser extension is the primary source.  The legacy API
    diagnostic remains a fallback so an invalid retained API key cannot block a
    healthy CDP workflow.
    """
    # Import lazily because preflight itself reads the sanitized API diagnostic.
    from agent.preflight import check_seller_sprite_browser

    browser = check_seller_sprite_browser()
    if browser.get("level") == "ok":
        return True, ""
    if not settings.mjjl_api_key:
        return False, str(browser.get("detail") or "SellerSprite API key missing")
    diagnostic = load_seller_sprite_diagnostic()
    if diagnostic.get("has_market_evidence"):
        return True, ""
    if diagnostic.get("error"):
        return False, f"SellerSprite market-data check failed: {diagnostic['error']}"
    return False, "SellerSprite ASIN check has not passed for the current key"

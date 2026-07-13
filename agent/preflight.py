"""Preflight checks for the local sourcing agent."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.alibaba_diagnostics import load_alibaba_open_diagnostic
from agent.browser_agent import _resolve_cdp_ws
from agent.seller_sprite_diagnostics import load_seller_sprite_diagnostic
from agent.sellersprite_models import SellerSpriteLocatorProfile
from config.settings import DATA_DIR, settings


def run_preflight() -> dict[str, Any]:
    checks = [
        _check_ppio(),
        _check_seller_sprite(),
        _check_seller_sprite_browser(),
        _check_alibaba_open(),
        _check_amazon_cookies(),
        _check_1688_cookies(),
        _check_database(),
        _check_exports_dir(),
        _check_1688_circuit(),
        _check_disk_space(),
    ]
    blocking = [c for c in checks if c["level"] == "error"]
    warnings = [c for c in checks if c["level"] == "warning"]
    return {
        "ready": not blocking,
        "summary": "Ready to run" if not blocking else "Action required",
        "checks": checks,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
    }


def _check_ppio() -> dict[str, Any]:
    if settings.ppio_api_key or settings.anthropic_api_key:
        return _ok("vision", "Vision model key configured", "PPIO" if settings.ppio_api_key else "Anthropic")
    return _err("vision", "Vision model key missing", "Set PPIO_API_KEY or ANTHROPIC_API_KEY")


def _check_seller_sprite() -> dict[str, Any]:
    if settings.mjjl_api_key:
        diagnostic = load_seller_sprite_diagnostic()
        if diagnostic.get("has_market_evidence"):
            return _ok(
                "seller_sprite",
                "SellerSprite ASIN check passed",
                f"{diagnostic.get('asin') or '-'} · key {diagnostic.get('key_length')} chars",
            )
        if diagnostic.get("error"):
            return _warn(
                "seller_sprite",
                "SellerSprite ASIN check failed",
                str(diagnostic.get("error")),
            )
        return _warn(
            "seller_sprite",
            "SellerSprite API key configured but unverified",
            "Run SellerSprite ASIN check before requiring market data",
        )
    return _warn("seller_sprite", "SellerSprite API key missing", "Set MJJL_API_KEY")


def _check_seller_sprite_browser() -> dict[str, Any]:
    """Check the separate browser-export capability without blocking sourcing.

    This intentionally has no dependency on the SellerSprite HTTP API key or
    its market-data diagnostic.  The browser extension is a distinct,
    human-authorized local capability and remains an advisory preflight item.
    """
    key = "seller_sprite_browser"
    if not settings.sellersprite_browser_enabled:
        return _warn(key, "SellerSprite browser disabled", "Set SELLERSPRITE_BROWSER_ENABLED to enable it")

    try:
        profile_path = str(settings.sellersprite_browser_locator_profile_path or "").strip()
        if not profile_path:
            raise ValueError("missing locator profile")
        SellerSpriteLocatorProfile.from_json(Path(profile_path))
    except Exception:
        return _warn(key, "SellerSprite browser locator profile unavailable", "Configure a valid locator profile")

    try:
        _assert_sellersprite_download_dir_writable()
    except Exception:
        return _warn(key, "SellerSprite browser download directory unavailable", "Configure a writable container download directory")

    try:
        cdp_ws = _resolve_cdp_ws()
        if not _is_safe_cdp_websocket(cdp_ws):
            raise ValueError("unusable CDP websocket")
    except Exception:
        return _warn(key, "SellerSprite browser Chrome connection unavailable", "Start Chrome remote debugging and configure CDP")

    return _ok(
        key,
        "SellerSprite browser ready",
        "Chrome CDP, locator profile, and download directory verified",
    )


def _assert_sellersprite_download_dir_writable() -> None:
    raw_path = str(settings.sellersprite_browser_download_dir or "").strip()
    if not raw_path:
        raise ValueError("missing container download directory")
    path = Path(raw_path)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".sellersprite_write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _is_safe_cdp_websocket(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"ws", "wss"} and bool(parsed.hostname)


def _check_alibaba_open() -> dict[str, Any]:
    if settings.alibaba_app_key and settings.alibaba_app_secret and settings.alibaba_access_token:
        diagnostic = load_alibaba_open_diagnostic()
        if diagnostic.get("has_supplier_evidence"):
            return _ok(
                "alibaba_open",
                "1688 pifatuan check passed",
                f"{diagnostic.get('keyword') or '-'} · {diagnostic.get('count') or 0} suppliers",
            )
        if diagnostic.get("error"):
            return _warn(
                "alibaba_open",
                "1688 pifatuan check failed",
                str(diagnostic.get("error")),
            )
        return _warn(
            "alibaba_open",
            "1688 Open Platform configured but unverified",
            "Run 1688 pifatuan check before relying on API sourcing",
        )
    return _warn(
        "alibaba_open",
        "1688 Open Platform config missing",
        "Set ALIBABA_APP_KEY / ALIBABA_APP_SECRET / ALIBABA_ACCESS_TOKEN",
    )


def _check_amazon_cookies() -> dict[str, Any]:
    path = DATA_DIR / "amazon_cookies.json"
    if path.exists() and path.stat().st_size > 1000:
        return _ok("amazon_cookies", "Amazon cookies available", f"{path.stat().st_size // 1024} KB")
    return _warn("amazon_cookies", "Amazon cookies missing or small", "Run python setup_amazon_login.py")


def _check_1688_cookies() -> dict[str, Any]:
    path = DATA_DIR / "1688_cookies.json"
    api_ready = bool(load_alibaba_open_diagnostic().get("has_supplier_evidence"))
    if not path.exists():
        if api_ready:
            return _warn("1688_cookies", "1688 browser cookies missing", "Open Platform verified; Playwright fallback unavailable")
        return _err("1688_cookies", "1688 cookies missing", "Run python setup_1688_login.py")
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        if api_ready:
            return _warn("1688_cookies", "1688 browser cookies unreadable", "Open Platform verified; Playwright fallback unavailable")
        return _err("1688_cookies", "1688 cookies unreadable", str(path))
    names = {c.get("name") for c in cookies if isinstance(c, dict)}
    if "unb" in names:
        return _ok("1688_cookies", "1688 login cookie valid", f"{len(cookies)} cookies")
    if api_ready:
        return _warn("1688_cookies", "1688 browser cookie incomplete", "Open Platform verified; Playwright fallback unavailable")
    return _err("1688_cookies", "1688 login cookie incomplete", "Login cookie unb not found")


def _check_database() -> dict[str, Any]:
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        if db_path.exists():
            return _ok("database", "SQLite database found", str(db_path))
        return _warn("database", "SQLite database not initialized", "The agent can initialize it")
    return _ok("database", "Database configured", settings.database_url.split("@")[-1])


def _check_exports_dir() -> dict[str, Any]:
    try:
        settings.export_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.export_dir / ".agent_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return _ok("exports", "Exports directory writable", str(settings.export_dir))
    except Exception as exc:
        return _err("exports", "Exports directory not writable", str(exc))


def _check_1688_circuit() -> dict[str, Any]:
    path = DATA_DIR / "cache" / "1688" / "circuit_breaker.json"
    if not path.exists():
        return _ok("1688_circuit", "1688 circuit clear", "No cooldown")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _warn("1688_circuit", "1688 circuit file unreadable", str(path))
    blocked_until = float(data.get("blocked_until") or 0)
    if blocked_until > time.time():
        remaining = int(blocked_until - time.time())
        return _warn("1688_circuit", "1688 search cooldown active", f"{remaining}s remaining")
    return _ok("1688_circuit", "1688 circuit clear", data.get("reason") or "OK")


def _check_disk_space() -> dict[str, Any]:
    usage = shutil.disk_usage(str(DATA_DIR))
    free_gb = usage.free / (1024 ** 3)
    if free_gb < 1:
        return _warn("disk", "Low disk space", f"{free_gb:.1f} GB free")
    return _ok("disk", "Storage available", f"{free_gb:.1f} GB free")


def _ok(key: str, label: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "detail": detail, "level": "ok"}


def _warn(key: str, label: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "detail": detail, "level": "warning"}


def _err(key: str, label: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "detail": detail, "level": "error"}

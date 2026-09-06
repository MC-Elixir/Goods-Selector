"""Preflight checks for the local sourcing agent."""
from __future__ import annotations

import json
import os
import shutil
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.alibaba_diagnostics import load_alibaba_open_diagnostic
from agent.browser_agent import _resolve_cdp_ws
from agent.seller_sprite_diagnostics import load_seller_sprite_diagnostic
from agent.sellersprite_browser_config import load_sellersprite_browser_config, project_local_path
from agent.sellersprite_models import SellerSpriteLocatorProfile
from config.settings import DATA_DIR, PROJECT_ROOT, settings


def run_preflight() -> dict[str, Any]:
    checks = [
        _check_ppio(),
        _check_seller_sprite(),
        check_seller_sprite_browser(),
        _check_1688_browser_session(),
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
    provider = settings.vision_provider
    if provider != "none":
        return _ok("vision", "Vision model key configured", provider)
    return _err(
        "vision",
        "Vision model key missing",
        "Set ALIYUN_TOKEN_PLAN_API_KEY, ALIYUN_API_KEY, PPIO_API_KEY, or ANTHROPIC_API_KEY",
    )


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
    return _ok(
        "seller_sprite",
        "SellerSprite API skipped",
        "Market analysis uses browser export; MJJL_API_KEY is optional",
    )


def _check_seller_sprite_browser() -> dict[str, Any]:
    """Check the separate browser-export capability without blocking sourcing.

    This intentionally has no dependency on the SellerSprite HTTP API key or
    its market-data diagnostic.  The browser extension is a distinct,
    human-authorized local capability and remains an advisory preflight item.
    """
    key = "seller_sprite_browser"
    browser_config = load_sellersprite_browser_config(PROJECT_ROOT, settings)
    if not browser_config.enabled:
        return _warn(key, "SellerSprite browser disabled", "Set SELLERSPRITE_BROWSER_ENABLED to enable it")

    try:
        profile_path = str(browser_config.locator_profile_path or "").strip()
        if not profile_path:
            raise ValueError("missing locator profile")
        if profile_path.startswith("/app/data/"):
            SellerSpriteLocatorProfile.from_json(project_local_path(PROJECT_ROOT, profile_path))
        else:
            SellerSpriteLocatorProfile.from_json(Path(profile_path))
    except Exception as exc:
        return _warn(
            key,
            "SellerSprite browser locator profile unavailable",
            _diagnostic_detail(
                "Set SELLERSPRITE_BROWSER_LOCATOR_PROFILE_PATH to a reviewed JSON file under /app/data/",
                exc,
            ),
        )

    try:
        _assert_sellersprite_download_dir_writable(browser_config.download_dir)
    except Exception as exc:
        return _warn(
            key,
            "SellerSprite browser download directory unavailable",
            _diagnostic_detail(
                "Set SELLERSPRITE_BROWSER_DOWNLOAD_DIR to a writable directory under /app/data/",
                exc,
            ),
        )

    try:
        cdp_ws = _resolve_cdp_ws()
        _assert_cdp_websocket_reachable(cdp_ws)
    except Exception as exc:
        return _warn(
            key,
            "SellerSprite browser Chrome connection unavailable",
            _diagnostic_detail(
                "Run .\\start.ps1; Docker must use BU_CDP_HTTP=http://host.docker.internal:9222",
                exc,
            ),
        )

    return _ok(
        key,
        "SellerSprite browser ready",
        "Chrome CDP, locator profile, and download directory verified",
    )


def check_seller_sprite_browser() -> dict[str, Any]:
    """Formal readiness: config, both extension flows and a visible session."""
    check = _check_seller_sprite_browser()
    if check["level"] != "ok":
        return {**check, "level": "error"}
    try:
        from agent.sellersprite_service import SellerSpriteDependencies

        deps = SellerSpriteDependencies()
        if deps.profile is None or not deps.profile.has_sourcing_1688_locators():
            raise ValueError("Reviewed 1688 sourcing locators are missing")
        if os.name != "nt" and "host.docker.internal" in str(settings.bu_cdp_http):
            from pathlib import PureWindowsPath

            if not PureWindowsPath(str(deps.browser_download_dir)).is_absolute():
                raise ValueError("Set SELLERSPRITE_BROWSER_HOST_DOWNLOAD_DIR to the mounted Windows folder and recreate Compose")
        _probe_sellersprite_session(deps)
    except Exception as exc:
        return _err("seller_sprite_browser", "SellerSprite action required", _diagnostic_detail(
            "Open an Amazon product in dedicated Chrome; enable and log in to SellerSprite", exc,
        ))
    return _ok("seller_sprite_browser", "SellerSprite browser ready", "Both locator groups and visible plugin session verified")


def _probe_sellersprite_session(deps) -> None:
    """Read visible state only: no navigation, export or quota consumption."""
    with deps.session_factory() as session:
        pages = [page for context in session._browser.contexts for page in context.pages]
        for page in pages:
            if urlparse(page.url).hostname not in {"amazon.com", "www.amazon.com"}:
                continue
            session._page = page
            session._raise_if_human_terminal()
            if session._is_visible("ready"):
                return
        raise ValueError("No visible, logged-in SellerSprite panel found on an Amazon page")


def _check_1688_browser_session() -> dict[str, Any]:
    """Block runs when the configured 1688 CDP session is unavailable.

    Stored cookies remain a valid fallback when no CDP endpoint is configured.
    Once an endpoint is configured, however, the matcher deliberately uses that
    dedicated human session; silently continuing without it produces supplier-
    evidence gaps that a formal no-mock run cannot use.
    """
    key = "1688_browser"
    configured = bool(
        (os.environ.get("BU_CDP_HTTP") or "").strip()
        or (os.environ.get("BU_CDP_WS") or "").strip()
        or (settings.bu_cdp_http or "").strip()
        or (settings.bu_cdp_ws or "").strip()
    )
    if not configured:
        return _ok(key, "1688 dedicated Chrome not configured", "Using stored-cookie fallback")
    try:
        cdp_ws = _resolve_cdp_ws()
        _assert_cdp_websocket_reachable(cdp_ws)
    except Exception as exc:
        return _err(
            key,
            "1688 dedicated Chrome unavailable",
            _diagnostic_detail(
                "Run .\\start.ps1 and verify Chrome at 127.0.0.1:9222; Docker must use host.docker.internal:9222",
                exc,
            ),
        )
    return _ok(key, "1688 dedicated Chrome ready", "Chrome CDP session is reachable")


def _assert_sellersprite_download_dir_writable(raw_path: str | None = None) -> None:
    raw_path = str(raw_path if raw_path is not None else settings.sellersprite_browser_download_dir or "").strip()
    if not raw_path:
        raise ValueError("missing container download directory")
    path = project_local_path(PROJECT_ROOT, raw_path) if raw_path.startswith("/app/data/") else Path(raw_path)
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".sellersprite_write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _diagnostic_detail(action: str, exc: Exception, *, max_reason_length: int = 240) -> str:
    """Return an actionable, bounded one-line reason safe for preflight UI."""
    reason = " ".join(str(exc).split()) or exc.__class__.__name__
    if len(reason) > max_reason_length:
        reason = reason[: max_reason_length - 3] + "..."
    return f"{action}. Reason: {reason}"


def _is_safe_cdp_websocket(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"ws", "wss"} and bool(parsed.hostname)


def _assert_cdp_websocket_reachable(value: object, *, timeout_seconds: float = 2.0) -> None:
    """Perform a bounded DNS/TCP reachability check without browser actions."""
    if not _is_safe_cdp_websocket(value):
        raise ValueError("unusable CDP websocket")
    parsed = urlparse(value)
    assert parsed.hostname is not None  # Guarded by _is_safe_cdp_websocket.
    try:
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    except ValueError as exc:
        raise ValueError("unusable CDP websocket") from exc
    with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds):
        pass


def _check_alibaba_open() -> dict[str, Any]:
    if not settings.enable_alibaba_open_api_matcher:
        return _ok(
            "alibaba_open",
            "1688 Open Platform disabled",
            "Browser sourcing is the active production path",
        )
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

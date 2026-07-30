"""Human-authorized browser setup helpers for the local WebUI.

The Docker service cannot safely launch a visible browser on the host.  It can,
however, attach to a Chrome instance that the user explicitly started with a
remote-debugging port.  This module keeps that boundary explicit:

* opening a login tab is user-triggered;
* reading cookies is user-triggered and writes only to the local data volume;
* cookie values are never returned by the HTTP API;
* disconnecting Playwright never closes the user's Chrome process.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from agent.browser_agent import _resolve_cdp_ws
from config.settings import DATA_DIR, settings

_SITE_CONFIG = {
    "amazon": {
        "label": "Amazon",
        "login_url": "https://www.amazon.com/",
        "cookie_urls": ["https://www.amazon.com/"],
        "domains": ("amazon.com",),
        "path": DATA_DIR / "amazon_cookies.json",
    },
    "1688": {
        "label": "1688",
        "login_url": "https://login.1688.com/member/signin.htm",
        "cookie_urls": [
            "https://login.1688.com/",
            "https://login.taobao.com/",
            "https://work.1688.com/",
            "https://www.1688.com/",
        ],
        "domains": ("1688.com", "taobao.com"),
        "path": DATA_DIR / "1688_cookies.json",
    },
}


def get_browser_setup_status() -> dict[str, Any]:
    """Return safe, non-secret readiness and host launch guidance."""
    configured = bool(
        (os.getenv("BU_CDP_HTTP") or "").strip()
        or (os.getenv("BU_CDP_WS") or "").strip()
        or (settings.bu_cdp_http or "").strip()
        or (settings.bu_cdp_ws or "").strip()
    )
    reachable = False
    detail = "Configure BU_CDP_HTTP=http://host.docker.internal:9222"
    if configured:
        try:
            endpoint = _resolve_cdp_ws(timeout_seconds=2)
            _assert_endpoint_reachable(endpoint, timeout_seconds=2)
            reachable = True
            detail = "Chrome remote debugging is reachable"
        except Exception:
            detail = "Start the dedicated Chrome profile on port 9222"

    return {
        "configured": configured,
        "reachable": reachable,
        "detail": detail,
        "port": 9222,
        "requires_dedicated_profile": True,
        "security_note": (
            "Use a dedicated Chrome profile and keep the debugging port local. "
            "The attached agent can access pages, cookies, and logged-in sessions in that profile."
        ),
        "launch_commands": {
            "windows": (
                '$chrome = @("$env:ProgramFiles\\Google\\Chrome\\Application\\chrome.exe", '
                '"${env:ProgramFiles(x86)}\\Google\\Chrome\\Application\\chrome.exe", '
                '"$env:LOCALAPPDATA\\Google\\Chrome\\Application\\chrome.exe") '
                '| Where-Object { Test-Path $_ } | Select-Object -First 1; '
                'if (-not $chrome) { throw "Chrome executable not found" }; '
                'Start-Process -FilePath $chrome -ArgumentList '
                "'--remote-debugging-port=9222', "
                '"--user-data-dir=$env:LOCALAPPDATA\\AmazonSelector\\ChromeProfile"'
            ),
            "macos": (
                'open -na "Google Chrome" --args --remote-debugging-port=9222 '
                '--user-data-dir="$HOME/.amazon-selector/chrome-profile"'
            ),
            "linux": (
                'google-chrome --remote-debugging-port=9222 '
                '--user-data-dir="$HOME/.amazon-selector/chrome-profile"'
            ),
        },
        "sites": {
            site: _cookie_file_status(site)
            for site in _SITE_CONFIG
        },
    }


def open_login_page(
    site: str,
    *,
    playwright_factory: Callable[[], Any] | None = None,
    cdp_resolver: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Open one login tab in the user-provided CDP Chrome instance."""
    config = _site_config(site)
    playwright = None
    try:
        factory = playwright_factory or _default_playwright_factory
        playwright = factory()
        endpoint = (cdp_resolver or _resolve_cdp_ws)()
        browser = playwright.chromium.connect_over_cdp(endpoint)
        contexts = list(getattr(browser, "contexts", []) or [])
        if not contexts:
            raise RuntimeError("Chrome has no browser context available")
        page = contexts[0].new_page()
        page.goto(
            config["login_url"],
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        return {
            "ok": True,
            "status": "login_opened",
            "site": site,
            "label": config["label"],
            "message": (
                f"{config['label']} login page opened in the dedicated Chrome profile. "
                "Complete login or verification there, then save cookies."
            ),
        }
    finally:
        # Stopping the Playwright driver disconnects this client.  Deliberately
        # do not call browser.close(), context.close(), or page.close(): this is
        # the user's visible browser and the login tab must remain available.
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def capture_browser_cookies(
    site: str,
    *,
    playwright_factory: Callable[[], Any] | None = None,
    cdp_resolver: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Capture site-scoped cookies from Chrome and atomically persist them."""
    config = _site_config(site)
    playwright = None
    try:
        factory = playwright_factory or _default_playwright_factory
        playwright = factory()
        endpoint = (cdp_resolver or _resolve_cdp_ws)()
        browser = playwright.chromium.connect_over_cdp(endpoint)
        contexts = list(getattr(browser, "contexts", []) or [])
        cookies: list[dict[str, Any]] = []
        for context in contexts:
            cookies.extend(context.cookies(config["cookie_urls"]))
        cookies = _deduplicate_cookies([
            cookie for cookie in cookies
            if _cookie_matches_domains(cookie, config["domains"])
        ])
        validation_error = _cookie_validation_error(site, cookies)
        if validation_error:
            return {
                "ok": False,
                "status": "login_required",
                "site": site,
                "label": config["label"],
                "message": validation_error,
            }
        _atomic_write_cookies(config["path"], cookies)
        if site == "1688":
            # A successful human login/verification changes the external state
            # that opened the supplier-search circuit. Let a resumed node probe
            # the fresh session immediately instead of waiting out the cooldown.
            from matchers.alibaba_result_cache import reset_circuit
            reset_circuit()
        return {
            "ok": True,
            "status": "saved",
            "site": site,
            "label": config["label"],
            "cookie_count": len(cookies),
            "message": f"{config['label']} cookies saved and ready for preflight.",
        }
    finally:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def _site_config(site: str) -> dict[str, Any]:
    key = str(site or "").strip().lower()
    if key not in _SITE_CONFIG:
        raise ValueError("site must be amazon or 1688")
    return _SITE_CONFIG[key]


def _cookie_file_status(site: str) -> dict[str, Any]:
    config = _site_config(site)
    path: Path = config["path"]
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cookies = []
    if not isinstance(cookies, list):
        cookies = []
    error = _cookie_validation_error(site, cookies)
    return {
        "ready": not error and path.exists(),
        "cookie_count": len(cookies),
    }


def _cookie_validation_error(site: str, cookies: list[dict[str, Any]]) -> str:
    if site == "1688":
        if not any(cookie.get("name") == "unb" for cookie in cookies):
            return "1688 login is not complete (the required unb cookie is missing)."
        return ""
    if not cookies:
        return "No Amazon cookies were found in the dedicated Chrome profile."
    encoded = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= 1000:
        return "Amazon session cookies are incomplete; finish the page verification or login first."
    return ""


def _cookie_matches_domains(cookie: dict[str, Any], domains: tuple[str, ...]) -> bool:
    domain = str(cookie.get("domain") or "").lower().lstrip(".")
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in domains)


def _deduplicate_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict) or not cookie.get("name"):
            continue
        key = (
            str(cookie.get("name") or ""),
            str(cookie.get("domain") or ""),
            str(cookie.get("path") or "/"),
        )
        unique[key] = cookie
    return list(unique.values())


def _atomic_write_cookies(path: Path, cookies: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cookies, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _assert_endpoint_reachable(endpoint: str, *, timeout_seconds: float) -> None:
    parsed = urlparse(str(endpoint or ""))
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise RuntimeError("Chrome DevTools websocket is unavailable")
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds):
        pass


def _default_playwright_factory() -> Any:
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()

"""Optional local browser-use sidecar for human-in-the-loop sourcing work."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from config.settings import settings


class BrowserTaskProvider(Protocol):
    def run(self, *, task: str, allowed_domains: list[str]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class BrowserTask:
    task_type: str
    task: str
    target_url: str


_TASK_TYPES = {"cookie_check", "supplier_detail_enrich", "page_diagnostic"}


def run_browser_task(
    task_type: str,
    *,
    url: str = "",
    offer_url: str = "",
    asin: str = "",
    keyword: str = "",
    provider: BrowserTaskProvider | None = None,
) -> dict[str, Any]:
    """Run or prepare a constrained browser-use task.

    The main crawler pipeline stays deterministic. This helper is only for
    local diagnostics, blocked-session recovery, and missing supplier details.
    """
    task_type = (task_type or "").strip()
    if task_type not in _TASK_TYPES:
        raise ValueError(f"unsupported browser task_type: {task_type}")

    allowed = allowed_domains()
    task = _build_task(task_type, url=url, offer_url=offer_url, asin=asin, keyword=keyword)
    _assert_allowed_url(task.target_url, allowed)

    if provider is None:
        if not _browser_use_available():
            return _requires_install(task_type, task, allowed)
        provider = BrowserUseCliProvider(target_url=task.target_url)

    provider_result = provider.run(task=task.task, allowed_domains=allowed) or {}
    returncode = provider_result.get("returncode")
    ok = returncode in (None, 0)
    return {
        "ok": ok,
        "status": "success" if ok else "failed",
        "tool": "browser-use",
        "task_type": task_type,
        "target_url": task.target_url,
        "allowed_domains": allowed,
        "task": task.task,
        "provider_result": provider_result,
        **({} if ok else {"next_steps": _browser_failure_next_steps(provider_result)}),
    }


def allowed_domains() -> list[str]:
    raw = getattr(settings, "browser_agent_allowed_domains", "")
    domains = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return domains or [
        "amazon.com",
        "www.amazon.com",
        "1688.com",
        "detail.1688.com",
        "s.1688.com",
        "127.0.0.1",
        "localhost",
    ]


def browser_agent_available() -> bool:
    return _browser_use_available()


def _browser_use_available() -> bool:
    return importlib.util.find_spec("browser_use") is not None or _browser_use_command() is not None


def _browser_use_command() -> str | None:
    configured = (os.getenv("BROWSER_AGENT_COMMAND") or "").strip()
    if configured and _is_executable(configured):
        return configured
    bundled = "/opt/browser-agent/bin/browser-use"
    if _is_executable(bundled):
        return bundled
    return shutil.which("browser-use")


def _is_executable(path: str) -> bool:
    p = Path(path)
    return p.is_file() and os.access(p, os.X_OK)


class BrowserUseCliProvider:
    """Small deterministic browser-use CLI bridge.

    When browser-use is installed, this opens the target page and captures
    browser-visible page info. The high-level task text is returned so a human
    or later LLM layer can inspect exactly what was requested.
    """

    def __init__(self, *, target_url: str, timeout_seconds: int = 120) -> None:
        self.target_url = target_url
        self.timeout_seconds = timeout_seconds

    def run(self, *, task: str, allowed_domains: list[str]) -> dict[str, Any]:
        executable = _browser_use_command()
        if not executable:
            return {
                "summary": "browser-use Python package is importable, but CLI executable was not found.",
                "task": task,
                "allowed_domains": allowed_domains,
                "next_steps": ["Install browser-use CLI or run this task from a configured browser-use environment."],
            }
        try:
            cdp_ws = _resolve_cdp_ws()
        except RuntimeError as exc:
            return {
                "summary": str(exc),
                "returncode": 1,
                "task": task,
                "allowed_domains": allowed_domains,
            }
        script = "\n".join([
            f"new_tab({json.dumps(self.target_url)})",
            "print(page_info())",
        ])
        env = os.environ.copy()
        env["BROWSER_AGENT_ALLOWED_DOMAINS"] = ",".join(allowed_domains)
        if cdp_ws:
            env["BU_CDP_WS"] = cdp_ws
        completed = subprocess.run(
            [executable],
            input=script,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
            env=env,
        )
        return {
            "summary": completed.stdout.strip() or completed.stderr.strip(),
            "returncode": completed.returncode,
            "task": task,
            "allowed_domains": allowed_domains,
        }


def _resolve_cdp_ws(timeout_seconds: int = 5) -> str:
    cdp_http = (os.getenv("BU_CDP_HTTP") or "").strip().rstrip("/")
    if cdp_http:
        return _resolve_cdp_ws_from_http(cdp_http, timeout_seconds=timeout_seconds)
    return (os.getenv("BU_CDP_WS") or "").strip()


def _resolve_cdp_ws_from_http(cdp_http: str, *, timeout_seconds: int) -> str:
    version_url = f"{cdp_http}/json/version"
    headers = {"Accept": "application/json"}
    host_header = _devtools_host_header(cdp_http)
    if host_header:
        headers["Host"] = host_header
    request = urllib.request.Request(version_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Chrome DevTools endpoint unavailable at {version_url}; "
            "start Chrome with remote debugging or fix BU_CDP_HTTP."
        ) from exc

    ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if not ws_url:
        raise RuntimeError(
            f"Chrome DevTools endpoint at {version_url} did not return webSocketDebuggerUrl."
        )
    return _normalize_cdp_ws_host(ws_url, cdp_http)


def _devtools_host_header(cdp_http: str) -> str:
    parts = urlparse(cdp_http)
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if host and host not in {"localhost", "127.0.0.1", "::1"}:
        return f"127.0.0.1:{port}"
    return ""


def _normalize_cdp_ws_host(ws_url: str, cdp_http: str) -> str:
    ws_parts = urlparse(ws_url)
    netloc = _cdp_websocket_netloc(cdp_http)
    if ws_parts.hostname in {"localhost", "127.0.0.1", "::1"} and netloc:
        ws_parts = ws_parts._replace(netloc=netloc)
    return urlunparse(ws_parts)


def _cdp_websocket_netloc(cdp_http: str) -> str:
    parts = urlparse(cdp_http)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if host.lower() in {"localhost", "127.0.0.1", "::1"}:
        return parts.netloc
    try:
        candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return parts.netloc
    for family, _socktype, _proto, _canonname, sockaddr in candidates:
        if family == socket.AF_INET:
            return f"{sockaddr[0]}:{port}"
    for family, _socktype, _proto, _canonname, sockaddr in candidates:
        if family == socket.AF_INET6:
            return f"[{sockaddr[0]}]:{port}"
    return parts.netloc


def _build_task(
    task_type: str,
    *,
    url: str,
    offer_url: str,
    asin: str,
    keyword: str,
) -> BrowserTask:
    asin = (asin or "").strip().upper()
    keyword = (keyword or "").strip()
    target = (offer_url or url or "").strip()
    if task_type == "cookie_check":
        target = target or "https://s.1688.com/selloffer/offer_search.htm"
        task = "\n".join([
            "Open the target page and check whether the local browser session is usable.",
            f"Target: {target}",
            "Report login state, captcha/robot-check state, blocking popups, and whether manual action is required.",
            "Do not purchase, message sellers, or submit forms.",
        ])
    elif task_type == "supplier_detail_enrich":
        if not target:
            raise ValueError("offer_url is required for supplier_detail_enrich")
        task = "\n".join([
            "Open the 1688 supplier detail page and extract sourcing-critical facts only from the visible page.",
            f"Target: {target}",
            f"ASIN: {asin or '-'}",
            "Return MOQ, price tiers, packaging dimensions/weight, lead time, supplier type, monthly sales, and missing fields.",
            "Also report captcha, login redirect, popup, or page structure changes. Save a screenshot if possible.",
            "Do not purchase, message sellers, or submit forms.",
        ])
    else:
        if not target:
            target = "https://www.amazon.com/"
        task = "\n".join([
            "Open the target page for diagnostics.",
            f"Target: {target}",
            f"Keyword: {keyword or '-'}",
            "Report captcha/robot-check state, login redirect, popup blockers, rendered title, screenshot evidence, and DOM clues.",
            "Do not purchase, message sellers, or submit forms.",
        ])
    return BrowserTask(task_type=task_type, task=task, target_url=target)


def _requires_install(task_type: str, task: BrowserTask, allowed: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "requires_install",
        "tool": "browser-use",
        "task_type": task_type,
        "target_url": task.target_url,
        "allowed_domains": allowed,
        "task": task.task,
        "message": "browser-use is not installed in this runtime; deterministic pipeline remains available.",
        "next_steps": [
            "pip install browser-use",
            "python -m playwright install chromium",
            "Retry the browser assistant from the local WebUI after installation.",
        ],
    }


def _browser_failure_next_steps(provider_result: dict[str, Any]) -> list[str]:
    summary = str(provider_result.get("summary") or "")
    steps = [
        "Ensure the Browser Assistant can connect to a local or remote Chrome debugging endpoint.",
        "For Docker, prefer BU_CDP_HTTP=http://host.docker.internal:9222 so the current websocket id is resolved automatically.",
        "BU_CDP_WS is still supported for advanced fixed websocket endpoints.",
    ]
    if "DevToolsActivePort" in summary or "BU_CDP_WS" in summary or "BU_CDP_HTTP" in summary:
        steps.append("Example: BU_CDP_HTTP=http://host.docker.internal:9222")
    return steps


def _assert_allowed_url(raw_url: str, allowed: list[str]) -> None:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(f"browser target URL is invalid: {raw_url}")
    if not any(_host_matches(host, domain) for domain in allowed):
        raise ValueError(f"browser target domain is not allowed: {host}")


def _host_matches(host: str, domain: str) -> bool:
    domain = domain.lower().split(":", 1)[0]
    return host == domain or host.endswith(f".{domain}")

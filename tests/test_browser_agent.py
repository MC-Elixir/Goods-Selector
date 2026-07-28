from __future__ import annotations

import io
import json
import socket
import subprocess

import pytest

from agent import browser_agent
from config.settings import settings


def test_browser_agent_rejects_disallowed_domain():
    with pytest.raises(ValueError, match="not allowed"):
        browser_agent.run_browser_task(
            "page_diagnostic",
            url="https://example.org/offer/123.html",
        )


def test_browser_agent_requires_optional_dependency_when_provider_missing(monkeypatch):
    monkeypatch.setattr(browser_agent, "_browser_use_available", lambda: False)

    result = browser_agent.run_browser_task(
        "cookie_check",
        url="https://s.1688.com/selloffer/offer_search.htm",
    )

    assert result["ok"] is False
    assert result["status"] == "requires_install"
    assert result["tool"] == "browser-use"
    assert "pip install browser-use" in " ".join(result["next_steps"])
    assert "1688.com" in result["allowed_domains"]


def test_browser_agent_finds_configured_command(monkeypatch, tmp_path):
    command = tmp_path / "browser-use"
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    command.chmod(0o755)
    monkeypatch.setenv("BROWSER_AGENT_COMMAND", str(command))
    monkeypatch.setattr(browser_agent.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(browser_agent.shutil, "which", lambda name: None)

    assert browser_agent.browser_agent_available() is True
    assert browser_agent._browser_use_command() == str(command)


def test_browser_agent_uses_provider_after_domain_guard():
    calls = []

    class Provider:
        def run(self, *, task, allowed_domains):
            calls.append({"task": task, "allowed_domains": allowed_domains})
            return {
                "summary": "1688 detail page opened, MOQ and lead time found.",
                "fields": {"moq": 50, "lead_time": "7 days"},
            }

    result = browser_agent.run_browser_task(
        "supplier_detail_enrich",
        offer_url="https://detail.1688.com/offer/123456.html",
        asin="B0TEST1234",
        provider=Provider(),
    )

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["task_type"] == "supplier_detail_enrich"
    assert result["provider_result"]["fields"]["moq"] == 50
    assert calls
    assert "detail.1688.com" in calls[0]["task"]
    assert "B0TEST1234" in calls[0]["task"]
    assert "detail.1688.com" in calls[0]["allowed_domains"]


def test_browser_agent_marks_provider_nonzero_returncode_as_failed():
    class Provider:
        def run(self, *, task, allowed_domains):
            return {
                "summary": "DevToolsActivePort not found; set BU_CDP_WS",
                "returncode": 1,
            }

    result = browser_agent.run_browser_task(
        "cookie_check",
        url="https://s.1688.com/selloffer/offer_search.htm",
        provider=Provider(),
    )

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "BU_CDP_WS" in " ".join(result["next_steps"])


def test_browser_agent_resolves_current_cdp_ws_from_http_endpoint(monkeypatch):
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    monkeypatch.setenv("BU_CDP_HTTP", "http://host.docker.internal:9222")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://host.docker.internal:9222/json/version"
        assert request.get_header("Host") == "127.0.0.1:9222"
        assert timeout == 5
        payload = {
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/fresh-browser-id"
        }
        return Response(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(browser_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(browser_agent, "_running_in_wsl", lambda: False)
    monkeypatch.setattr(
        browser_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.254", 9222)),
        ],
    )

    assert (
        browser_agent._resolve_cdp_ws()
        == "ws://192.168.65.254:9222/devtools/browser/fresh-browser-id"
    )


def test_browser_agent_uses_settings_loaded_cdp_http_when_process_env_is_absent(monkeypatch):
    monkeypatch.delenv("BU_CDP_HTTP", raising=False)
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    monkeypatch.setattr(settings, "bu_cdp_http", "http://127.0.0.1:9222")
    monkeypatch.setattr(settings, "bu_cdp_ws", "")
    monkeypatch.setattr(
        browser_agent,
        "_resolve_cdp_ws_from_http",
        lambda value, *, timeout_seconds: f"resolved:{value}:{timeout_seconds}",
    )

    assert browser_agent._resolve_cdp_ws() == "resolved:http://127.0.0.1:9222:5"


def test_browser_agent_process_ws_overrides_dotenv_http(monkeypatch):
    monkeypatch.delenv("BU_CDP_HTTP", raising=False)
    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:9222/devtools/browser/explicit")
    monkeypatch.setattr(settings, "bu_cdp_http", "http://host.docker.internal:9222")

    assert (
        browser_agent._resolve_cdp_ws()
        == "ws://127.0.0.1:9222/devtools/browser/explicit"
    )


def test_browser_agent_prefers_http_resolution_over_stale_ws(monkeypatch):
    monkeypatch.setenv("BU_CDP_WS", "ws://host.docker.internal:9222/devtools/browser/stale")
    monkeypatch.setenv("BU_CDP_HTTP", "http://host.docker.internal:9222")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        payload = {
            "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/fresh-browser-id"
        }
        return Response(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(browser_agent.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(browser_agent, "_running_in_wsl", lambda: False)
    monkeypatch.setattr(
        browser_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.254", 9222)),
        ],
    )

    assert (
        browser_agent._resolve_cdp_ws()
        == "ws://192.168.65.254:9222/devtools/browser/fresh-browser-id"
    )


def test_cdp_websocket_uses_windows_loopback_inside_wsl(monkeypatch):
    monkeypatch.setattr(browser_agent, "_running_in_wsl", lambda: True)
    monkeypatch.setattr(browser_agent, "_running_in_container", lambda: False)

    assert (
        browser_agent._normalize_cdp_ws_host(
            "ws://127.0.0.1:9222/devtools/browser/current",
            "http://host.docker.internal:9222",
        )
        == "ws://127.0.0.1:9222/devtools/browser/current"
    )


def test_cdp_websocket_keeps_docker_host_inside_wsl_container(monkeypatch):
    monkeypatch.setattr(browser_agent, "_running_in_wsl", lambda: True)
    monkeypatch.setattr(browser_agent, "_running_in_container", lambda: True)
    monkeypatch.setattr(
        browser_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.254", 9222)),
        ],
    )

    assert (
        browser_agent._normalize_cdp_ws_host(
            "ws://127.0.0.1:9222/devtools/browser/current",
            "http://host.docker.internal:9222",
        )
        == "ws://192.168.65.254:9222/devtools/browser/current"
    )


def test_browser_use_provider_passes_resolved_cdp_ws_to_cli(monkeypatch, tmp_path):
    executable = tmp_path / "browser-use"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    captured = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setenv("BROWSER_AGENT_COMMAND", str(executable))
    monkeypatch.setattr(browser_agent, "_resolve_cdp_ws", lambda: "ws://host.docker.internal:9222/devtools/browser/current")
    monkeypatch.setattr(browser_agent.subprocess, "run", fake_run)

    provider = browser_agent.BrowserUseCliProvider(target_url="https://www.amazon.com/")
    result = provider.run(task="diagnose", allowed_domains=["www.amazon.com"])

    assert result["returncode"] == 0
    assert captured["env"]["BU_CDP_WS"] == "ws://host.docker.internal:9222/devtools/browser/current"


def test_browser_agent_diagnostic_task_mentions_data_gaps():
    class Provider:
        def run(self, *, task, allowed_domains):
            return {"summary": task}

    result = browser_agent.run_browser_task(
        "page_diagnostic",
        url="https://www.amazon.com/dp/B0TEST1234",
        provider=Provider(),
    )

    summary = result["provider_result"]["summary"]
    assert "captcha" in summary.lower()
    assert "popup" in summary.lower()
    assert "screenshot" in summary.lower()

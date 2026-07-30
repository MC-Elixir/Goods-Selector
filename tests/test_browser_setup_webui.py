from __future__ import annotations

import json
import threading
from http import HTTPStatus
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from agent import server
from agent.server import AgentRequestHandler

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def browser_setup_client():
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), AgentRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class Client:
        def get(self, path: str):
            request = Request(f"http://127.0.0.1:{httpd.server_port}{path}", method="GET")
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))

        def post(self, path: str, payload: dict):
            request = Request(
                f"http://127.0.0.1:{httpd.server_port}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))

    try:
        yield Client()
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def test_browser_setup_endpoints_return_only_safe_status(monkeypatch, browser_setup_client):
    monkeypatch.setattr(server, "get_browser_setup_status", lambda: {
        "configured": True,
        "reachable": True,
        "detail": "ready",
        "launch_commands": {"windows": "start chrome"},
        "sites": {"amazon": {"ready": False, "cookie_count": 0}},
    })
    monkeypatch.setattr(server, "capture_browser_cookies", lambda site: {
        "ok": True,
        "status": "saved",
        "site": site,
        "cookie_count": 12,
    })

    status_code, status = browser_setup_client.get("/api/browser-setup/status")
    save_code, saved = browser_setup_client.post(
        "/api/browser-setup",
        {"action": "save_cookies", "site": "amazon"},
    )

    assert status_code == HTTPStatus.OK
    assert status["reachable"] is True
    assert save_code == HTTPStatus.OK
    assert saved["cookie_count"] == 12
    assert "value" not in str(saved).lower()


def test_webui_prompts_for_missing_sessions_and_guides_9222_setup():
    html = (PROJECT_ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert "Windows PowerShell" in html
    assert '<input name="enabled" type="checkbox" checked>' in html
    assert 'id="sessionSetupPanel"' in html
    assert 'id="browserSetupGuide"' in html
    assert 'id="researchBrowserPrerequisite"' in html
    assert 'getJson("/api/browser-setup/status")' in js
    assert 'postJson("/api/browser-setup"' in js
    assert "action: \"save_cookies\"" in js
    assert "action: \"open_login\"" in js
    assert ".session-setup-panel" in styles
    assert ".browser-readiness-card" in styles
    assert ".browser-command-row .ghost-button" in styles

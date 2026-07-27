from __future__ import annotations

import json

from agent import browser_setup


class FakePage:
    def __init__(self) -> None:
        self.opened_url = ""

    def goto(self, url, **_kwargs):
        self.opened_url = url


class FakeContext:
    def __init__(self, cookies=None) -> None:
        self._cookies = list(cookies or [])
        self.page = FakePage()
        self.cookie_urls = None

    def new_page(self):
        return self.page

    def cookies(self, urls):
        self.cookie_urls = urls
        return list(self._cookies)


class FakeBrowser:
    def __init__(self, context) -> None:
        self.contexts = [context]
        self.close_called = False

    def close(self):
        self.close_called = True


class FakeChromium:
    def __init__(self, browser) -> None:
        self.browser = browser
        self.endpoint = ""

    def connect_over_cdp(self, endpoint):
        self.endpoint = endpoint
        return self.browser


class FakePlaywright:
    def __init__(self, browser) -> None:
        self.chromium = FakeChromium(browser)
        self.stop_called = False

    def stop(self):
        self.stop_called = True


def test_open_login_page_keeps_users_browser_and_tab_open():
    context = FakeContext()
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)

    result = browser_setup.open_login_page(
        "1688",
        playwright_factory=lambda: playwright,
        cdp_resolver=lambda: "ws://127.0.0.1:9222/devtools/browser/test",
    )

    assert result["status"] == "login_opened"
    assert context.page.opened_url == "https://login.1688.com/member/signin.htm"
    assert playwright.stop_called is True
    assert browser.close_called is False


def test_capture_1688_cookies_requires_login_cookie_and_does_not_write(tmp_path, monkeypatch):
    target = tmp_path / "1688_cookies.json"
    monkeypatch.setitem(browser_setup._SITE_CONFIG["1688"], "path", target)
    context = FakeContext([{
        "name": "cookie2",
        "value": "anonymous",
        "domain": ".1688.com",
        "path": "/",
    }])
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)

    result = browser_setup.capture_browser_cookies(
        "1688",
        playwright_factory=lambda: playwright,
        cdp_resolver=lambda: "ws://127.0.0.1:9222/devtools/browser/test",
    )

    assert result["status"] == "login_required"
    assert not target.exists()
    assert browser.close_called is False


def test_capture_1688_cookies_filters_domains_and_writes_private_file(tmp_path, monkeypatch):
    target = tmp_path / "1688_cookies.json"
    monkeypatch.setitem(browser_setup._SITE_CONFIG["1688"], "path", target)
    context = FakeContext([
        {"name": "unb", "value": "user", "domain": ".1688.com", "path": "/"},
        {"name": "cookie2", "value": "session", "domain": ".taobao.com", "path": "/"},
        {"name": "secret", "value": "ignore", "domain": ".example.com", "path": "/"},
    ])
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)

    result = browser_setup.capture_browser_cookies(
        "1688",
        playwright_factory=lambda: playwright,
        cdp_resolver=lambda: "ws://127.0.0.1:9222/devtools/browser/test",
    )

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert result == {
        "ok": True,
        "status": "saved",
        "site": "1688",
        "label": "1688",
        "cookie_count": 2,
        "message": "1688 cookies saved and ready for preflight.",
    }
    assert {item["name"] for item in saved} == {"unb", "cookie2"}
    assert target.stat().st_mode & 0o777 == 0o600
    assert browser.close_called is False


def test_browser_setup_status_exposes_commands_without_cdp_websocket(monkeypatch):
    monkeypatch.setenv("BU_CDP_HTTP", "http://host.docker.internal:9222")
    monkeypatch.setattr(
        browser_setup,
        "_resolve_cdp_ws",
        lambda timeout_seconds=2: "ws://127.0.0.1:9222/devtools/browser/private-id",
    )
    monkeypatch.setattr(browser_setup, "_assert_endpoint_reachable", lambda *_args, **_kwargs: None)

    status = browser_setup.get_browser_setup_status()

    assert status["reachable"] is True
    assert "--remote-debugging-port=9222" in status["launch_commands"]["windows"]
    assert "--user-data-dir=" in status["launch_commands"]["linux"]
    assert "private-id" not in str(status)

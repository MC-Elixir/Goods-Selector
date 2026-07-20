from __future__ import annotations

import json

from agent import preflight
from config.settings import settings


def test_seller_sprite_preflight_warns_when_configured_but_unverified(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "secret-value")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")
    monkeypatch.setattr(preflight, "load_seller_sprite_diagnostic", lambda: {})

    check = preflight._check_seller_sprite()

    assert check["level"] == "warning"
    assert check["key"] == "seller_sprite"
    assert "unverified" in check["label"]


def test_seller_sprite_preflight_warns_on_failed_diagnostic(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "secret-value")
    monkeypatch.setattr(preflight, "load_seller_sprite_diagnostic", lambda: {
        "has_market_evidence": False,
        "error": "未授权",
        "key_length": len("secret-value"),
    })

    check = preflight._check_seller_sprite()

    assert check["level"] == "warning"
    assert check["label"] == "SellerSprite ASIN check failed"
    assert check["detail"] == "未授权"


def test_seller_sprite_preflight_ok_after_successful_diagnostic(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "secret-value")
    monkeypatch.setattr(preflight, "load_seller_sprite_diagnostic", lambda: {
        "has_market_evidence": True,
        "asin": "B0TEST1234",
        "key_length": len("secret-value"),
    })

    check = preflight._check_seller_sprite()

    assert check["level"] == "ok"
    assert check["label"] == "SellerSprite ASIN check passed"
    assert "B0TEST1234" in check["detail"]


def test_seller_sprite_browser_preflight_is_warning_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", False)

    check = preflight._check_seller_sprite_browser()

    assert check["key"] == "seller_sprite_browser"
    assert check["level"] == "warning"
    assert "disabled" in check["label"].lower()


def test_seller_sprite_browser_preflight_is_independent_of_mjjl(monkeypatch, tmp_path):
    profile = tmp_path / "locators.json"
    profile.write_text(json.dumps({
        "panel_open": "css=.panel-open",
        "ready": "css=.ready",
        "login_required": "css=.login",
        "permission_required": "css=.permission",
        "captcha": "css=.captcha",
        "reverse_keywords": "css=.reverse",
        "asin_input": "css=input",
        "submit": "css=.submit",
        "results_ready": "css=.results",
        "export_menu": "css=.export-menu",
        "export": "css=.export",
    }), encoding="utf-8")
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", True)
    monkeypatch.setattr(settings, "sellersprite_browser_locator_profile_path", str(profile))
    monkeypatch.setattr(settings, "sellersprite_browser_download_dir", str(download_dir))
    monkeypatch.setattr(preflight, "_resolve_cdp_ws", lambda: "ws://127.0.0.1:9222/devtools/browser/id")
    monkeypatch.setattr(preflight, "_assert_cdp_websocket_reachable", lambda _value: None)

    check = preflight._check_seller_sprite_browser()

    assert check == {
        "key": "seller_sprite_browser",
        "label": "SellerSprite browser ready",
        "detail": "Chrome CDP, locator profile, and download directory verified",
        "level": "ok",
    }


def test_seller_sprite_browser_preflight_uses_volume_backed_browser_configuration(monkeypatch, tmp_path):
    profile = tmp_path / "data" / "locators.json"
    profile.parent.mkdir()
    profile.write_text(json.dumps({
        "panel_open": "css=.panel-open", "ready": "css=.ready", "login_required": "css=.login",
        "permission_required": "css=.permission", "captcha": "css=.captcha",
        "reverse_keywords": "css=.reverse", "asin_input": "css=input",
        "submit": "css=.submit", "results_ready": "css=.results", "export_menu": "css=.export-menu", "export": "css=.export",
    }), encoding="utf-8")
    (tmp_path / "data" / "sellersprite_browser_config.json").write_text(json.dumps({
        "enabled": True,
        "locator_profile_path": "/app/data/locators.json",
        "download_dir": "/app/data/imports/sellersprite",
        "host_download_dir": "configured",
    }), encoding="utf-8")
    monkeypatch.setattr(preflight, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", False)
    monkeypatch.setattr(preflight, "_resolve_cdp_ws", lambda: "ws://127.0.0.1:9222/devtools/browser/id")
    monkeypatch.setattr(preflight, "_assert_cdp_websocket_reachable", lambda _value: None)

    check = preflight._check_seller_sprite_browser()

    assert check["level"] == "ok"


def test_seller_sprite_browser_preflight_warns_when_raw_cdp_websocket_is_unreachable(monkeypatch, tmp_path):
    profile = tmp_path / "locators.json"
    profile.write_text(json.dumps({
        "panel_open": "css=.panel-open", "ready": "css=.ready", "login_required": "css=.login",
        "permission_required": "css=.permission", "captcha": "css=.captcha",
        "reverse_keywords": "css=.reverse", "asin_input": "css=input",
        "submit": "css=.submit", "results_ready": "css=.results", "export_menu": "css=.export-menu", "export": "css=.export",
    }), encoding="utf-8")
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", True)
    monkeypatch.setattr(settings, "sellersprite_browser_locator_profile_path", str(profile))
    monkeypatch.setattr(settings, "sellersprite_browser_download_dir", str(download_dir))
    monkeypatch.delenv("BU_CDP_HTTP", raising=False)
    monkeypatch.setenv("BU_CDP_WS", "ws://stale.example.invalid:9222/devtools/browser/id")
    attempted = []

    def reject_connection(address, timeout):
        attempted.append((address, timeout))
        raise OSError("unreachable")

    monkeypatch.setattr(preflight.socket, "create_connection", reject_connection)

    check = preflight._check_seller_sprite_browser()

    assert check["key"] == "seller_sprite_browser"
    assert check["level"] == "warning"
    assert "connection unavailable" in check["label"].lower()
    assert attempted == [(("stale.example.invalid", 9222), 2.0)]


def test_alibaba_open_preflight_ok_after_successful_diagnostic(monkeypatch):
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", True)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_app_secret", "app-secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(preflight, "load_alibaba_open_diagnostic", lambda: {
        "has_supplier_evidence": True,
        "keyword": "水杯",
        "count": 2,
    })

    check = preflight._check_alibaba_open()

    assert check["level"] == "ok"
    assert check["label"] == "1688 pifatuan check passed"
    assert "2 suppliers" in check["detail"]


def test_alibaba_open_preflight_reports_browser_only_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_alibaba_open_api_matcher", False)

    check = preflight._check_alibaba_open()

    assert check["level"] == "ok"
    assert check["label"] == "1688 Open Platform disabled"


def test_1688_cookie_missing_is_warning_when_open_platform_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "DATA_DIR", tmp_path)
    monkeypatch.setattr(preflight, "load_alibaba_open_diagnostic", lambda: {
        "has_supplier_evidence": True,
        "keyword": "水杯",
        "count": 2,
    })

    check = preflight._check_1688_cookies()

    assert check["level"] == "warning"
    assert check["key"] == "1688_cookies"
    assert "Open Platform verified" in check["detail"]


def test_1688_cookie_missing_remains_error_without_open_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "DATA_DIR", tmp_path)
    monkeypatch.setattr(preflight, "load_alibaba_open_diagnostic", lambda: {})

    check = preflight._check_1688_cookies()

    assert check["level"] == "error"
    assert check["label"] == "1688 cookies missing"

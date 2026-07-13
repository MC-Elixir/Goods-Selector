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


def test_seller_sprite_browser_preflight_is_warning_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", False)

    check = preflight._check_seller_sprite_browser()

    assert check["key"] == "seller_sprite_browser"
    assert check["level"] == "warning"
    assert "disabled" in check["label"].lower()


def test_seller_sprite_browser_preflight_is_independent_of_mjjl(monkeypatch, tmp_path):
    profile = tmp_path / "locators.json"
    profile.write_text(json.dumps({
        "ready": "css=.ready",
        "login_required": "css=.login",
        "permission_required": "css=.permission",
        "captcha": "css=.captcha",
        "reverse_keywords": "css=.reverse",
        "asin_input": "css=input",
        "submit": "css=.submit",
        "results_ready": "css=.results",
        "export": "css=.export",
    }), encoding="utf-8")
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", True)
    monkeypatch.setattr(settings, "sellersprite_browser_locator_profile_path", str(profile))
    monkeypatch.setattr(settings, "sellersprite_browser_download_dir", str(download_dir))
    monkeypatch.setattr(preflight, "_resolve_cdp_ws", lambda: "ws://127.0.0.1:9222/devtools/browser/id")

    check = preflight._check_seller_sprite_browser()

    assert check == {
        "key": "seller_sprite_browser",
        "label": "SellerSprite browser ready",
        "detail": "Chrome CDP, locator profile, and download directory verified",
        "level": "ok",
    }


def test_alibaba_open_preflight_ok_after_successful_diagnostic(monkeypatch):
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

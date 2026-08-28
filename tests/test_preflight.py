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


def test_vision_preflight_accepts_aliyun_token_plan(monkeypatch):
    monkeypatch.setattr(settings, "model_api_provider", "aliyun_token_plan")
    monkeypatch.setattr(settings, "aliyun_token_plan_api_key", "sk-sp-test")

    check = preflight._check_ppio()

    assert check["level"] == "ok"
    assert check["detail"] == "aliyun_token_plan"


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


def test_seller_sprite_preflight_skips_when_api_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "")

    check = preflight._check_seller_sprite()

    assert check["key"] == "seller_sprite"
    assert check["level"] == "ok"
    assert "skipped" in check["label"].lower()
    assert "optional" in check["detail"].lower()


def test_missing_mjjl_does_not_block_preflight_ready(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "ppio_api_key", "vision-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    def ok(key: str) -> dict:
        return preflight._ok(key, "ok", "")

    monkeypatch.setattr(preflight, "check_seller_sprite_browser", lambda: ok("seller_sprite_browser"))
    monkeypatch.setattr(preflight, "_check_1688_browser_session", lambda: ok("1688_browser"))
    monkeypatch.setattr(preflight, "_check_alibaba_open", lambda: ok("alibaba_open"))
    monkeypatch.setattr(preflight, "_check_amazon_cookies", lambda: ok("amazon_cookies"))
    monkeypatch.setattr(preflight, "_check_1688_cookies", lambda: ok("1688_cookies"))
    monkeypatch.setattr(preflight, "_check_database", lambda: ok("database"))
    monkeypatch.setattr(preflight, "_check_exports_dir", lambda: ok("exports"))
    monkeypatch.setattr(preflight, "_check_1688_circuit", lambda: ok("1688_circuit"))
    monkeypatch.setattr(preflight, "_check_disk_space", lambda: ok("disk"))

    result = preflight.run_preflight()
    sprite = next(item for item in result["checks"] if item["key"] == "seller_sprite")

    assert sprite["level"] == "ok"
    assert result["ready"] is True
    assert result["blocking_count"] == 0


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
    assert "start.ps1" in check["detail"]
    assert "host.docker.internal:9222" in check["detail"]
    assert "unreachable" in check["detail"]
    assert attempted == [(("stale.example.invalid", 9222), 2.0)]


def test_1688_browser_session_blocks_when_configured_cdp_is_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "bu_cdp_http", "http://host.docker.internal:9222")
    monkeypatch.setattr(preflight, "_resolve_cdp_ws", lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    check = preflight._check_1688_browser_session()

    assert check["key"] == "1688_browser"
    assert check["level"] == "error"
    assert "unavailable" in check["label"].lower()
    assert "start.ps1" in check["detail"]
    assert "host.docker.internal:9222" in check["detail"]
    assert "offline" in check["detail"]


def test_preflight_diagnostic_detail_is_single_line_and_bounded():
    detail = preflight._diagnostic_detail("Retry the check", RuntimeError("first\n" + "x" * 400))

    assert "\n" not in detail
    assert detail.startswith("Retry the check. Reason: first ")
    assert len(detail) < 300


def test_1688_browser_session_is_ready_when_configured_cdp_is_reachable(monkeypatch):
    monkeypatch.setattr(settings, "bu_cdp_http", "http://host.docker.internal:9222")
    monkeypatch.setattr(preflight, "_resolve_cdp_ws", lambda: "ws://host.docker.internal:9222/devtools/browser/id")
    monkeypatch.setattr(preflight, "_assert_cdp_websocket_reachable", lambda _value: None)

    check = preflight._check_1688_browser_session()

    assert check == {
        "key": "1688_browser",
        "label": "1688 dedicated Chrome ready",
        "detail": "Chrome CDP session is reachable",
        "level": "ok",
    }


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

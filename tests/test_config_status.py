"""Sanitized configuration status tests."""
from __future__ import annotations

import json

import pytest

import agent.config_status as config_status_module
from agent.config_status import (
    check_alibaba_pifatuan,
    check_seller_sprite_asin,
    check_seller_sprite_capabilities,
    configure_alibaba_supplier_search,
    configure_seller_sprite,
    configure_vision_model,
    get_config_status,
)
from config.settings import settings


def test_config_status_reports_capabilities_without_secrets(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "seller-secret")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 2)
    monkeypatch.setattr(settings, "ppio_api_key", "vision-secret")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_app_secret", "app-secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.custom")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.custom.supplier.search")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keyword")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "com.alibaba.alt|alibaba.alt.search|keywords")
    monkeypatch.setattr(settings, "browser_agent_allowed_domains", "amazon.com,1688.com,localhost")
    monkeypatch.setenv("BU_CDP_HTTP", "http://host.docker.internal:9222")
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    monkeypatch.setattr("agent.config_status.browser_agent_available", lambda: True)
    monkeypatch.setattr("agent.config_status.load_alibaba_open_diagnostic", lambda: {
        "has_supplier_evidence": True,
        "keyword": "水杯",
        "count": 2,
    })

    status = get_config_status()

    assert status["seller_sprite"]["configured"] is True
    assert status["seller_sprite"]["key_length"] == len("seller-secret")
    assert status["seller_sprite"]["max_products_per_run"] == 2
    assert status["vision"]["configured"] is True
    assert status["vision"]["provider"] == "ppio"
    assert status["alibaba_open"]["configured"] is True
    assert status["alibaba_open"]["namespace"] == "com.alibaba.custom"
    assert status["alibaba_open"]["method"] == "alibaba.custom.supplier.search"
    assert status["alibaba_open"]["keyword_param"] == "keyword"
    assert status["alibaba_open"]["candidates"] == "com.alibaba.alt|alibaba.alt.search|keywords"
    assert status["alibaba_open"]["last_check"]["count"] == 2
    assert status["browser_agent"]["configured"] is True
    assert status["browser_agent"]["tool"] == "browser-use"
    assert status["browser_agent"]["allowed_domains"] == ["amazon.com", "1688.com", "localhost"]
    assert status["browser_agent"]["cdp_http_configured"] is True
    assert status["browser_agent"]["cdp_ws_configured"] is False
    flattened = str(status)
    assert "seller-secret" not in flattened
    assert "vision-secret" not in flattened
    assert "app-secret" not in flattened
    assert "access-token" not in flattened


def test_config_status_reports_missing_alibaba_parts(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "ppio_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_app_secret", "")
    monkeypatch.setattr(settings, "alibaba_access_token", "")

    status = get_config_status()

    assert status["seller_sprite"]["configured"] is False
    assert status["vision"]["configured"] is False
    assert status["alibaba_open"]["configured"] is False
    assert status["alibaba_open"]["has_app_key"] is True
    assert status["alibaba_open"]["has_app_secret"] is False
    assert status["alibaba_open"]["has_access_token"] is False


def test_browser_readiness_is_independent_of_mjjl_api_key(monkeypatch):
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "sellersprite_browser_enabled", True)
    monkeypatch.setattr(settings, "sellersprite_browser_locator_profile_path", "/host/profile.json")
    monkeypatch.setattr(settings, "sellersprite_browser_download_dir", "/container/downloads")
    monkeypatch.setattr(settings, "sellersprite_browser_host_download_dir", "C:/Downloads")
    monkeypatch.setattr(settings, "sellersprite_browser_page_timeout_seconds", 45)
    monkeypatch.setattr(settings, "sellersprite_browser_export_timeout_seconds", 120)
    monkeypatch.setattr(settings, "sellersprite_browser_min_interval_seconds", 5)
    monkeypatch.setattr(settings, "sellersprite_browser_max_retries", 1)
    monkeypatch.setattr(config_status_module, "check_seller_sprite_browser", lambda: {
        "key": "seller_sprite_browser",
        "label": "SellerSprite browser ready",
        "detail": "Chrome CDP, locator profile, and download directory verified",
        "level": "ok",
    })

    status = get_config_status()

    browser = status["seller_sprite_browser"]
    assert browser == {
        "enabled": True,
        "status": "ready",
        "readiness_label": "SellerSprite browser ready",
        "readiness_detail": "Chrome CDP, locator profile, and download directory verified",
        "locator_profile_configured": True,
        "download_dir_configured": True,
        "host_download_dir_configured": True,
        "page_timeout_seconds": 45,
        "export_timeout_seconds": 120,
        "min_interval_seconds": 5,
        "max_retries": 1,
    }
    assert "/host/profile.json" not in str(browser)
    assert "/container/downloads" not in str(browser)
    assert "C:/Downloads" not in str(browser)


def test_browser_configuration_helper_is_available_for_volume_backed_local_settings():
    assert callable(getattr(config_status_module, "configure_sellersprite_browser", None))


def test_browser_configuration_persists_only_project_local_safe_state(monkeypatch, tmp_path):
    profile = tmp_path / "data" / "live-locators.json"
    profile.parent.mkdir()
    profile.write_text(json.dumps({
        "panel_open": "css=#panel-open", "ready": "css=#panel",
        "login_required": "css=#login", "permission_required": "css=#permission",
        "captcha": "css=#captcha", "reverse_keywords": "css=#reverse",
        "asin_input": "name=asin", "submit": "css=#submit",
        "results_ready": "css=#results", "export_menu": "css=#menu",
        "export": "css=#export",
    }), encoding="utf-8")
    monkeypatch.setattr(config_status_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_status_module, "check_seller_sprite_browser", lambda: {
        "key": "seller_sprite_browser",
        "label": "SellerSprite browser ready",
        "detail": "Chrome CDP, locator profile, and download directory verified",
        "level": "ok",
    })

    result = config_status_module.configure_sellersprite_browser(
        locator_profile_path="/app/data/live-locators.json",
        download_dir="/app/data/imports/sellersprite",
        host_download_dir="C:/Users/dell/Downloads",
        enabled=True,
    )

    stored = json.loads((tmp_path / "data" / "sellersprite_browser_config.json").read_text(encoding="utf-8"))
    assert stored == {
        "download_dir": "/app/data/imports/sellersprite",
        "enabled": True,
        "host_download_dir": "configured",
        "locator_profile_path": "/app/data/live-locators.json",
    }
    assert result["status"] == "ready"
    assert "C:/Users/dell/Downloads" not in str(result)


def test_browser_configuration_saves_enabled_state_before_locator_profile_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(config_status_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_status_module, "check_seller_sprite_browser", lambda: {
        "key": "seller_sprite_browser",
        "label": "SellerSprite browser locator profile unavailable",
        "detail": "Configure a valid locator profile",
        "level": "warning",
    })

    result = config_status_module.configure_sellersprite_browser(
        locator_profile_path="/app/data/sellersprite_live_locators.json",
        download_dir="/app/data/imports/sellersprite",
        host_download_dir="Chrome-managed",
        enabled=True,
    )

    stored = json.loads((tmp_path / "data" / "sellersprite_browser_config.json").read_text(encoding="utf-8"))
    assert stored["enabled"] is True
    assert result["status"] == "unavailable"


def test_browser_configuration_rejects_paths_escaping_the_data_volume(monkeypatch, tmp_path):
    monkeypatch.setattr(config_status_module, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="below /app/data/"):
        config_status_module.configure_sellersprite_browser(
            locator_profile_path="/app/data/../outside.json",
            download_dir="/app/data/imports/sellersprite",
            host_download_dir="Chrome-managed",
            enabled=True,
        )


def test_configure_seller_sprite_writes_env_without_returning_secret(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("MJJL_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr("agent.config_status.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "mjjl_api_key", "")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")

    result = configure_seller_sprite("secret-value", "https://api.example/v1")

    assert result["configured"] is True
    assert result["key_length"] == 12
    assert "secret-value" not in str(result)
    assert "MJJL_API_KEY=secret-value" in env_path.read_text(encoding="utf-8")
    assert settings.mjjl_api_key == "secret-value"
    assert settings.mjjl_api_base == "https://api.example/v1"


def test_configure_vision_model_writes_env_without_returning_secret(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("PPIO_MODEL=old-model\n", encoding="utf-8")
    monkeypatch.setattr("agent.config_status.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "ppio_api_key", "")
    monkeypatch.setattr(settings, "ppio_api_base", "https://api.ppio.com/openai")
    monkeypatch.setattr(settings, "ppio_model", "old-model")

    result = configure_vision_model("vision-secret", "qwen/qwen2.5-vl-72b-instruct", "https://vision.example/v1")

    text = env_path.read_text(encoding="utf-8")
    assert result["configured"] is True
    assert result["provider"] == "ppio"
    assert result["model"] == "qwen/qwen2.5-vl-72b-instruct"
    assert result["base_url"] == "https://vision.example/v1"
    assert "vision-secret" not in str(result)
    assert "PPIO_API_KEY=vision-secret" in text
    assert "PPIO_MODEL=qwen/qwen2.5-vl-72b-instruct" in text
    assert settings.ppio_model == "qwen/qwen2.5-vl-72b-instruct"


def test_configure_alibaba_supplier_search_writes_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("ALIBABA_SUPPLIER_SEARCH_METHOD=old.method\n", encoding="utf-8")
    monkeypatch.setattr("agent.config_status.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_app_secret", "app-secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")

    result = configure_alibaba_supplier_search(
        "com.alibaba.custom",
        "alibaba.custom.supplier.search",
        "keyword",
        "com.alibaba.alt|alibaba.alt.search|keywords",
    )

    text = env_path.read_text(encoding="utf-8")
    assert result["configured"] is True
    assert result["namespace"] == "com.alibaba.custom"
    assert result["method"] == "alibaba.custom.supplier.search"
    assert result["keyword_param"] == "keyword"
    assert result["candidates"] == "com.alibaba.alt|alibaba.alt.search|keywords"
    assert "ALIBABA_SUPPLIER_SEARCH_NAMESPACE=com.alibaba.custom" in text
    assert "ALIBABA_SUPPLIER_SEARCH_METHOD=alibaba.custom.supplier.search" in text
    assert "ALIBABA_SUPPLIER_SEARCH_KEYWORD_PARAM=keyword" in text
    assert "ALIBABA_SUPPLIER_SEARCH_CANDIDATES=com.alibaba.alt|alibaba.alt.search|keywords" in text
    assert "app-secret" not in str(result)
    assert "access-token" not in str(result)


def test_check_seller_sprite_asin_returns_sanitized_summary(monkeypatch):
    class FakeDetail:
        asin = "B0TEST1234"
        title = "Test Product"
        brand = "Acme"
        price = 19.99
        list_price = None
        rating = 4.5
        review_count = 321
        bsr = 1200
        bsr_category_name = "Home & Kitchen"
        category_path = "Home & Kitchen:Bedding"

        def __bool__(self):
            return True

    class FakeClient:
        api_key = "secret-value"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def asin_detail(self, marketplace, asin):
            assert marketplace == "US"
            assert asin == "B0TEST1234"
            return FakeDetail()

        def competitor_lookup(self, *args, **kwargs):
            raise AssertionError("competitor fallback should not run after ASIN detail evidence")

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    saved = []
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: saved.append(result) or {
        "has_market_evidence": True,
        "asin": result["asin"],
        "key_length": result["key_length"],
    })

    result = check_seller_sprite_asin("b0test1234", "us")

    assert result["has_market_evidence"] is True
    assert result["evidence_source"] == "asin_detail"
    assert result["api_checks"][0]["name"] == "asin_detail"
    assert result["api_checks"][0]["evidence"] is True
    assert result["key_length"] == len("secret-value")
    assert result["review_count"] == 321
    assert result["last_check"]["has_market_evidence"] is True
    assert saved[0]["asin"] == "B0TEST1234"
    assert "secret-value" not in str(result)


def test_check_seller_sprite_asin_falls_back_to_competitor_lookup(monkeypatch):
    class FakeClient:
        api_key = "secret-value"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def asin_detail(self, marketplace, asin):
            raise RuntimeError("未授权")

        def competitor_lookup(self, marketplace, asins, size):
            assert marketplace == "US"
            assert asins == ["B0TEST1234"]
            assert size == 10
            return {
                "code": "OK",
                "data": {
                    "items": [{
                        "asin": "B0TEST1234",
                        "title": "Fallback Product",
                        "brand": "Acme",
                        "price": 21.5,
                        "rating": 4.2,
                        "ratings": 99,
                        "bsr": 4321,
                        "units": 777,
                    }]
                },
            }

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: {
        "has_market_evidence": result["has_market_evidence"],
        "asin": result["asin"],
        "key_length": result["key_length"],
        "evidence_source": result["evidence_source"],
        "error": result["error"],
    })

    result = check_seller_sprite_asin("B0TEST1234", "US")

    assert result["has_market_evidence"] is True
    assert result["evidence_source"] == "competitor_lookup"
    assert result["error"] is None
    assert result["est_monthly_sales"] == 777
    assert result["review_count"] == 99
    assert result["api_checks"][0]["name"] == "asin_detail"
    assert result["api_checks"][0]["ok"] is False
    assert result["api_checks"][1]["name"] == "competitor_lookup"
    assert result["api_checks"][1]["evidence"] is True
    assert result["key_length"] == len("secret-value")
    assert result["last_check"]["has_market_evidence"] is True
    assert "secret-value" not in str(result)


def test_check_seller_sprite_asin_returns_sanitized_error(monkeypatch):
    class FakeClient:
        api_key = "secret-value"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def asin_detail(self, marketplace, asin):
            raise RuntimeError("未授权")

        def competitor_lookup(self, marketplace, asins, size):
            raise RuntimeError("竞品未授权")

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: {
        "has_market_evidence": False,
        "asin": result["asin"],
        "key_length": result["key_length"],
        "error": result["error"],
    })

    result = check_seller_sprite_asin("B0TEST1234", "US")

    assert result["has_market_evidence"] is False
    assert "asin_detail: 未授权" in result["error"]
    assert "competitor_lookup: 竞品未授权" in result["error"]
    assert result["key_length"] == len("secret-value")
    assert "未授权" in result["last_check"]["error"]
    assert "secret-value" not in str(result)


def test_check_seller_sprite_capabilities_allows_visits_without_permission(monkeypatch):
    class FakeDetail:
        asin = "B0TEST1234"
        title = "Test Product"
        brand = "Acme"
        price = 19.99
        list_price = None
        rating = 4.5
        review_count = 321
        bsr = 1200
        bsr_category_name = "Home & Kitchen"

        def __bool__(self):
            return True

    class FakePrediction:
        est_monthly_sales = 1200

        def __bool__(self):
            return True

    class FakeClient:
        api_key = "secret-value"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_visits(self):
            return {"code": "ERROR_AUTH_ERROR", "message": "没有该接口访问次数查询权限"}

        def asin_detail(self, marketplace, asin):
            assert marketplace == "US"
            assert asin == "B0TEST1234"
            return FakeDetail()

        def competitor_lookup(self, marketplace, asins, size):
            return {"code": "OK", "data": {"items": []}}

        def bsr_prediction(self, marketplace, bsr, category_id):
            assert bsr == 2
            assert category_id == "11260432011"
            return FakePrediction()

        def keyword_research_trends(self, keyword, marketplace):
            return {"code": "OK", "data": {"items": [{"keyword": keyword, "searches": 100}]}}

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: {
        "has_market_evidence": result["has_market_evidence"],
        "authorized_api_count": result["authorized_api_count"],
        "authorized_data_api_count": result["authorized_data_api_count"],
        "error": result["error"],
    })

    result = check_seller_sprite_capabilities("b0test1234", "us", "water bottle")

    assert result["has_market_evidence"] is True
    assert result["evidence_source"] == "asin_detail"
    assert result["authorized_api_count"] == 3
    assert result["authorized_data_api_count"] == 3
    assert result["error"] is None
    assert result["api_checks"][0]["name"] == "visits"
    assert result["api_checks"][0]["ok"] is False
    assert result["api_checks"][1]["name"] == "asin_detail"
    assert result["api_checks"][1]["ok"] is True
    assert "secret-value" not in str(result)


def test_check_seller_sprite_capabilities_reports_no_authorized_data_api(monkeypatch):
    class FakeClient:
        api_key = "secret-value"
        base_url = "https://api.sellersprite.com"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_visits(self):
            raise RuntimeError("visits denied")

        def asin_detail(self, marketplace, asin):
            raise RuntimeError("asin denied")

        def competitor_lookup(self, marketplace, asins, size):
            raise RuntimeError("competitor denied")

        def bsr_prediction(self, marketplace, bsr, category_id):
            raise RuntimeError("bsr denied")

        def keyword_research_trends(self, keyword, marketplace):
            raise RuntimeError("keyword denied")

    monkeypatch.setattr("analyzers.maijiajingling.MaijiajinglingClient", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_seller_sprite_diagnostic", lambda result: {
        "has_market_evidence": result["has_market_evidence"],
        "authorized_api_count": result["authorized_api_count"],
        "authorized_data_api_count": result["authorized_data_api_count"],
        "error": result["error"],
    })

    result = check_seller_sprite_capabilities("B0TEST1234", "US", "water bottle")

    assert result["has_market_evidence"] is False
    assert result["authorized_api_count"] == 0
    assert result["authorized_data_api_count"] == 0
    assert "asin_detail: asin denied" in result["error"]
    assert "secret-value" not in str(result)


def test_check_alibaba_pifatuan_returns_sanitized_supplier_summary(monkeypatch):
    class FakeSupplier:
        alibaba_offer_id = "123456789"
        supplier_name = "Ningbo Factory"
        title_cn = "304不锈钢保温杯"
        base_price_cny = 22.0
        moq = 20
        monthly_sales = 1200
        repeat_buyer_rate = 0.38
        is_factory = True
        raw_data = {"source": "alibaba_pifatuan"}

    class FakeClient:
        app_key = "app-secret"
        app_secret = "secret-value"
        access_token = "token-value"
        gateway = "https://gw.open.1688.com/openapi"
        namespace = "com.alibaba.custom"
        method = "alibaba.custom.supplier.search"
        keyword_param = "keyword"
        candidates = ""

        def configured(self):
            return True

        def search(self, keywords, top_k):
            assert keywords == ["水杯"]
            assert top_k == 2
            return [FakeSupplier()]

    monkeypatch.setattr("matchers.alibaba_pifatuan.AlibabaPifatuanSearch", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_alibaba_open_diagnostic", lambda result: {
        "has_supplier_evidence": True,
        "keyword": result["keyword"],
        "count": result["count"],
    })

    result = check_alibaba_pifatuan("水杯", 2)

    assert result["configured"] is True
    assert result["namespace"] == "com.alibaba.custom"
    assert result["method"] == "alibaba.custom.supplier.search"
    assert result["keyword_param"] == "keyword"
    assert result["count"] == 1
    assert result["suppliers"][0]["offer_id"] == "123456789"
    assert result["suppliers"][0]["monthly_sales"] == 1200
    assert result["last_check"]["has_supplier_evidence"] is True
    assert "secret-value" not in str(result)
    assert "token-value" not in str(result)


def test_check_alibaba_pifatuan_missing_config_returns_error(monkeypatch):
    class FakeClient:
        gateway = ""
        namespace = "com.alibaba.pifatuan"
        method = "alibaba.pifatuan.product.list"
        keyword_param = "keywords"

        def configured(self):
            return False

        def search(self, keywords, top_k):
            raise AssertionError("search should not run without config")

    monkeypatch.setattr("matchers.alibaba_pifatuan.AlibabaPifatuanSearch", lambda: FakeClient())
    monkeypatch.setattr("agent.config_status.save_alibaba_open_diagnostic", lambda result: {
        "has_supplier_evidence": False,
        "keyword": result["keyword"],
        "count": result["count"],
        "error": result["error"],
    })

    result = check_alibaba_pifatuan("水杯", 3)

    assert result["configured"] is False
    assert result["count"] == 0
    assert "ALIBABA_APP_KEY" in result["error"]
    assert result["last_check"]["error"] == result["error"]

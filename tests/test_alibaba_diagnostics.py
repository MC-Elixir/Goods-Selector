from __future__ import annotations

from agent import alibaba_diagnostics
from config.settings import settings


def test_alibaba_open_diagnostic_round_trip_matches_current_config(monkeypatch, tmp_path):
    path = tmp_path / "alibaba_open_diagnostic.json"
    monkeypatch.setattr(alibaba_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.pifatuan")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.pifatuan.product.list")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keywords")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "")

    saved = alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 1,
        "error": None,
        "suppliers": [{
            "offer_id": "123",
            "supplier": "Factory",
            "title": "保温杯",
            "monthly_sales": 1200,
            "source": "alibaba_pifatuan",
        }],
    })

    loaded = alibaba_diagnostics.load_alibaba_open_diagnostic()

    assert loaded["has_supplier_evidence"] is True
    assert loaded["keyword"] == "水杯"
    assert loaded["count"] == 1
    assert loaded["namespace"] == "com.alibaba.pifatuan"
    assert loaded["method"] == "alibaba.pifatuan.product.list"
    assert loaded["candidates"] == ""
    assert loaded["suppliers"][0]["offer_id"] == "123"
    assert saved["checked_at"]
    text = path.read_text(encoding="utf-8")
    assert "app-key" not in text
    assert "access-token" not in text


def test_alibaba_open_diagnostic_ignored_when_token_shape_changes(monkeypatch, tmp_path):
    path = tmp_path / "alibaba_open_diagnostic.json"
    monkeypatch.setattr(alibaba_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_access_token", "old-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.pifatuan")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.pifatuan.product.list")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keywords")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "")
    alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 1,
        "error": None,
    })

    monkeypatch.setattr(settings, "alibaba_access_token", "different-token")

    assert alibaba_diagnostics.load_alibaba_open_diagnostic() == {}


def test_alibaba_open_diagnostic_ignored_when_search_api_changes(monkeypatch, tmp_path):
    path = tmp_path / "alibaba_open_diagnostic.json"
    monkeypatch.setattr(alibaba_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.pifatuan")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.pifatuan.product.list")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keywords")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "")
    alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 1,
        "error": None,
    })

    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.custom.supplier.search")

    assert alibaba_diagnostics.load_alibaba_open_diagnostic() == {}


def test_alibaba_open_diagnostic_ignored_when_candidates_change(monkeypatch, tmp_path):
    path = tmp_path / "alibaba_open_diagnostic.json"
    monkeypatch.setattr(alibaba_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.pifatuan")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.pifatuan.product.list")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keywords")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "com.a|m|keyword")
    alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 1,
        "error": None,
        "attempts": [{"namespace": "com.a", "method": "m", "keyword_param": "keyword", "ok": True, "count": 1}],
    })

    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "com.b|m|keyword")

    assert alibaba_diagnostics.load_alibaba_open_diagnostic() == {}


def test_alibaba_open_supplier_guard_requires_successful_diagnostic(monkeypatch, tmp_path):
    path = tmp_path / "alibaba_open_diagnostic.json"
    monkeypatch.setattr(alibaba_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "alibaba_app_key", "app-key")
    monkeypatch.setattr(settings, "alibaba_app_secret", "app-secret")
    monkeypatch.setattr(settings, "alibaba_access_token", "access-token")
    monkeypatch.setattr(settings, "alibaba_api_gateway", "https://gw.open.1688.com/openapi/")
    monkeypatch.setattr(settings, "alibaba_supplier_search_namespace", "com.alibaba.pifatuan")
    monkeypatch.setattr(settings, "alibaba_supplier_search_method", "alibaba.pifatuan.product.list")
    monkeypatch.setattr(settings, "alibaba_supplier_search_keyword_param", "keywords")
    monkeypatch.setattr(settings, "alibaba_supplier_search_candidates", "")

    ready, reason = alibaba_diagnostics.alibaba_open_supplier_guard()
    assert ready is False
    assert "has not passed" in reason

    alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 0,
        "error": "未授权",
    })
    ready, reason = alibaba_diagnostics.alibaba_open_supplier_guard()
    assert ready is False
    assert "未授权" in reason

    alibaba_diagnostics.save_alibaba_open_diagnostic({
        "gateway": "https://gw.open.1688.com/openapi",
        "keyword": "水杯",
        "count": 2,
        "error": None,
    })
    ready, reason = alibaba_diagnostics.alibaba_open_supplier_guard()
    assert ready is True
    assert reason == ""

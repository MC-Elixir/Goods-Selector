from __future__ import annotations

from agent import seller_sprite_diagnostics
from config.settings import settings


def test_seller_sprite_diagnostic_round_trip_matches_current_key(monkeypatch, tmp_path):
    path = tmp_path / "seller_sprite_diagnostic.json"
    monkeypatch.setattr(seller_sprite_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "mjjl_api_key", "secret-value")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")

    saved = seller_sprite_diagnostics.save_seller_sprite_diagnostic({
        "base_url": "https://api.sellersprite.com",
        "key_length": len("secret-value"),
        "asin": "B0TEST1234",
        "marketplace": "US",
        "has_market_evidence": True,
        "error": None,
        "bsr": 1200,
        "review_count": 321,
    })

    loaded = seller_sprite_diagnostics.load_seller_sprite_diagnostic()

    assert loaded["asin"] == "B0TEST1234"
    assert loaded["has_market_evidence"] is True
    assert loaded["key_length"] == len("secret-value")
    assert saved["checked_at"]
    assert "secret-value" not in path.read_text(encoding="utf-8")


def test_seller_sprite_diagnostic_ignored_when_key_shape_changes(monkeypatch, tmp_path):
    path = tmp_path / "seller_sprite_diagnostic.json"
    monkeypatch.setattr(seller_sprite_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "mjjl_api_key", "old-secret")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")
    seller_sprite_diagnostics.save_seller_sprite_diagnostic({
        "base_url": "https://api.sellersprite.com",
        "key_length": len("old-secret"),
        "asin": "B0TEST1234",
        "marketplace": "US",
        "has_market_evidence": False,
        "error": "未授权",
    })

    monkeypatch.setattr(settings, "mjjl_api_key", "different-secret")

    assert seller_sprite_diagnostics.load_seller_sprite_diagnostic() == {}


def test_seller_sprite_market_data_guard_requires_successful_diagnostic(monkeypatch, tmp_path):
    path = tmp_path / "seller_sprite_diagnostic.json"
    monkeypatch.setattr(seller_sprite_diagnostics, "_DIAGNOSTIC_FILE", path)
    monkeypatch.setattr(settings, "mjjl_api_key", "secret-value")
    monkeypatch.setattr(settings, "mjjl_api_base", "https://api.sellersprite.com/v1")
    monkeypatch.setattr(
        "agent.preflight.check_seller_sprite_browser",
        lambda: {"level": "warning", "detail": "browser unavailable"},
    )

    ready, reason = seller_sprite_diagnostics.seller_sprite_market_data_guard()
    assert ready is False
    assert "has not passed" in reason

    seller_sprite_diagnostics.save_seller_sprite_diagnostic({
        "base_url": "https://api.sellersprite.com",
        "key_length": len("secret-value"),
        "asin": "B0TEST1234",
        "marketplace": "US",
        "has_market_evidence": False,
        "error": "未授权",
    })
    ready, reason = seller_sprite_diagnostics.seller_sprite_market_data_guard()
    assert ready is False
    assert "未授权" in reason

    seller_sprite_diagnostics.save_seller_sprite_diagnostic({
        "base_url": "https://api.sellersprite.com",
        "key_length": len("secret-value"),
        "asin": "B0TEST1234",
        "marketplace": "US",
        "has_market_evidence": True,
        "error": None,
    })
    ready, reason = seller_sprite_diagnostics.seller_sprite_market_data_guard()
    assert ready is True
    assert reason == ""


def test_market_data_guard_prefers_ready_browser_over_invalid_retained_api_key(
    monkeypatch,
):
    monkeypatch.setattr(
        "agent.preflight.check_seller_sprite_browser",
        lambda: {
            "key": "seller_sprite_browser",
            "label": "SellerSprite browser ready",
            "detail": "Chrome CDP ready",
            "level": "ok",
        },
    )
    monkeypatch.setattr(seller_sprite_diagnostics.settings, "mjjl_api_key", "retained-invalid-key")

    ready, reason = seller_sprite_diagnostics.seller_sprite_market_data_guard()

    assert ready is True
    assert reason == ""

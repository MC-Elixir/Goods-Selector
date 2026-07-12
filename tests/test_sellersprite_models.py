import importlib
import json

import pytest

from agent.sellersprite_models import (
    SellerSpriteContext,
    SellerSpriteLocatorProfile,
    SellerSpriteResult,
)
from agent.sellersprite_policy import validate_sellersprite_asin
from config.settings import Settings


settings_module = importlib.import_module("config.settings")


def _documented_locators() -> dict[str, str]:
    return {
        "ready": "#panel",
        "login_required": "text=Log in",
        "permission_required": "[data-state='permission-required']",
        "captcha": "iframe[name='captcha']",
        "reverse_keywords": "role=tab[name='Reverse Keywords']",
        "asin_input": "input[name='asin']",
        "submit": "role=button[name='Search']",
        "results_ready": "[data-state='results-ready']",
        "export": "role=button[name='Export']",
    }


def test_context_generates_distinct_call_and_run_ids():
    context = SellerSpriteContext.create("b00q7oan50")

    assert context.asin == "B00Q7OAN50"
    assert len(context.sourcing_run_id) == 36
    assert len(context.call_id) == 36
    assert context.call_id != context.sourcing_run_id
    assert context.observed_at.endswith("+00:00")


def test_needs_human_result_preserves_context_and_error_code():
    context = SellerSpriteContext.create("B00Q7OAN50")

    result = SellerSpriteResult.needs_human(context, "CAPTCHA")

    assert result.status == "NEEDS_HUMAN"
    assert result.context is context
    assert result.data == {}
    assert result.error_code == "CAPTCHA"


def test_profile_rejects_coordinate_and_missing_required_locator(tmp_path):
    missing_path = tmp_path / "missing.json"
    missing_path.write_text('{"ready": "#panel"}', encoding="utf-8")

    with pytest.raises(ValueError, match="locator"):
        SellerSpriteLocatorProfile.from_json(missing_path)

    coordinate_path = tmp_path / "coordinate.json"
    locators = _documented_locators()
    locators["export"] = "742,381"
    coordinate_path.write_text(json.dumps(locators), encoding="utf-8")

    with pytest.raises(ValueError, match="locator"):
        SellerSpriteLocatorProfile.from_json(coordinate_path)


def test_profile_loads_all_documented_locators(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_documented_locators()), encoding="utf-8")

    profile = SellerSpriteLocatorProfile.from_json(path)

    assert profile.ready == "#panel"
    assert profile.export == "role=button[name='Export']"


def test_asin_policy_normalizes_amazon_identifier():
    assert validate_sellersprite_asin(" b00q7oan50 ") == "B00Q7OAN50"


def test_asin_policy_rejects_non_amazon_identifier():
    with pytest.raises(ValueError, match="ASIN"):
        validate_sellersprite_asin("not-an-asin")


def test_sellersprite_browser_settings_default_to_disabled_and_create_import_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module, "DATA_DIR", tmp_path)

    settings = Settings(_env_file=None)

    assert settings.sellersprite_browser_enabled is False
    assert settings.sellersprite_browser_locator_profile_path == ""
    assert settings.sellersprite_browser_download_dir == ""
    assert settings.sellersprite_browser_host_download_dir == ""
    assert settings.sellersprite_browser_page_timeout_seconds == 45
    assert settings.sellersprite_browser_export_timeout_seconds == 120
    assert settings.sellersprite_browser_min_interval_seconds == 5
    assert settings.sellersprite_browser_max_retries == 1
    assert settings.sellersprite_import_dir == tmp_path / "imports" / "sellersprite"
    assert settings.sellersprite_import_dir.is_dir()

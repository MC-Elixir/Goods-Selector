import importlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent.sellersprite_models import (
    SellerSpriteContext,
    SellerSpriteLocatorProfile,
    SellerSpriteResult,
)
from agent.sellersprite_policy import (
    normalize_sellersprite_error_code,
    validate_sellersprite_asin,
)
from config.settings import Settings


settings_module = importlib.import_module("config.settings")


def _documented_locators() -> dict[str, str]:
    return {
        "ready": "css=#panel",
        "login_required": "text=Log in",
        "permission_required": "css=[data-state='permission-required']",
        "captcha": "iframe=name=captcha",
        "reverse_keywords": "role=tab[name='Reverse Keywords']",
        "asin_input": "name=asin",
        "submit": "role=button[name='Search']",
        "results_ready": "css=[data-state='results-ready']",
        "export": "role=button[name='Export']",
    }


def test_context_generates_distinct_call_and_run_ids():
    context = SellerSpriteContext.create("b00q7oan50")

    assert context.asin == "B00Q7OAN50"
    assert len(context.sourcing_run_id) == 36
    assert len(context.call_id) == 36
    assert context.call_id != context.sourcing_run_id
    assert UUID(context.sourcing_run_id).version == 4
    assert UUID(context.call_id).version == 4
    assert context.observed_at.endswith("+00:00")


def test_context_canonicalizes_supplied_uuid_sourcing_run_id():
    context = SellerSpriteContext.create(
        "B00Q7OAN50",
        "{C0FFEE00-0000-4000-8000-000000000001}",
    )

    assert context.sourcing_run_id == "c0ffee00-0000-4000-8000-000000000001"


def test_context_rejects_non_uuid_sourcing_run_id():
    with pytest.raises(ValueError, match="sourcing_run_id"):
        SellerSpriteContext.create("B00Q7OAN50", "run-id\\napi_key=not-for-logs")


def test_needs_human_result_preserves_context_and_error_code():
    context = SellerSpriteContext.create("B00Q7OAN50")

    result = SellerSpriteResult.needs_human(context, "CAPTCHA")

    assert result.status == "NEEDS_HUMAN"
    assert result.context is context
    assert result.data == {}
    assert result.error_code == "CAPTCHA"


@pytest.mark.parametrize(
    "error_code",
    [
        "EXTENSION_UNAVAILABLE",
        "SELLERSPRITE_LOGIN_REQUIRED",
        "SELLERSPRITE_PERMISSION_REQUIRED",
        "CAPTCHA",
        "ASIN_MISMATCH",
        "EXPORT_FAILED",
        "DOWNLOAD_TIMEOUT",
        "INVALID_EXPORT",
        "NEEDS_HUMAN",
        "CANCELLED",
        "AMBIGUOUS_DOWNLOAD",
        "INTERNAL",
    ],
)
def test_error_code_policy_allowlists_documented_codes(error_code):
    assert normalize_sellersprite_error_code(error_code.lower()) == error_code


@pytest.mark.parametrize(
    "untrusted_error_code",
    [
        "unknown",
        "CAPTCHA\\napi_key=not-for-logs",
        "CAPTCHA\\x00token=not-for-logs",
    ],
)
def test_needs_human_maps_untrusted_error_codes_to_internal(untrusted_error_code):
    context = SellerSpriteContext.create("B00Q7OAN50")

    result = SellerSpriteResult.needs_human(context, untrusted_error_code)

    assert result.error_code == "INTERNAL"


def test_profile_rejects_missing_required_locator(tmp_path):
    missing_path = tmp_path / "missing.json"
    missing_path.write_text('{"ready": "css=#panel"}', encoding="utf-8")

    with pytest.raises(ValueError, match="locator"):
        SellerSpriteLocatorProfile.from_json(missing_path)


@pytest.mark.parametrize(
    "invalid_locator",
    [
        "742,381",
        "click(742,381)",
        "x=742,y=381",
        "xpath=//button",
        "css=",
    ],
)
def test_profile_rejects_coordinate_and_unsupported_locator_syntax(tmp_path, invalid_locator):
    path = tmp_path / "profile.json"
    locators = _documented_locators()
    locators["export"] = invalid_locator
    path.write_text(json.dumps(locators), encoding="utf-8")

    with pytest.raises(ValueError, match="locator"):
        SellerSpriteLocatorProfile.from_json(path)


@pytest.mark.parametrize(
    "locator",
    [
        "css=#panel",
        "text=Panel ready",
        "role=button[name='Open']",
        "id=panel",
        "name=panel",
        "iframe=name=extension",
        "shadow=#host >> button",
    ],
)
def test_profile_accepts_documented_locator_prefixes(tmp_path, locator):
    path = tmp_path / "profile.json"
    locators = _documented_locators()
    locators["ready"] = locator
    path.write_text(json.dumps(locators), encoding="utf-8")

    profile = SellerSpriteLocatorProfile.from_json(path)

    assert profile.ready == locator


def test_profile_loads_all_documented_locators(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_documented_locators()), encoding="utf-8")

    profile = SellerSpriteLocatorProfile.from_json(path)

    assert profile.ready == "css=#panel"
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


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("SELLERSPRITE_BROWSER_PAGE_TIMEOUT_SECONDS", "0"),
        ("SELLERSPRITE_BROWSER_PAGE_TIMEOUT_SECONDS", "121"),
        ("SELLERSPRITE_BROWSER_EXPORT_TIMEOUT_SECONDS", "0"),
        ("SELLERSPRITE_BROWSER_EXPORT_TIMEOUT_SECONDS", "301"),
        ("SELLERSPRITE_BROWSER_MIN_INTERVAL_SECONDS", "0"),
        ("SELLERSPRITE_BROWSER_MIN_INTERVAL_SECONDS", "61"),
        ("SELLERSPRITE_BROWSER_MAX_RETRIES", "-1"),
        ("SELLERSPRITE_BROWSER_MAX_RETRIES", "2"),
    ],
)
def test_sellersprite_browser_settings_reject_out_of_range_environment_overrides(
    monkeypatch,
    environment_name,
    value,
):
    monkeypatch.setenv(environment_name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

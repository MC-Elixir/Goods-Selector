from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import traceback

import pytest

from matchers.product_understanding import (
    ProductUnderstandingError,
    product_image_urls,
    understand_amazon_product,
)
from matchers.vision_analyzer import VisionAnalyzer
from matchers import vision_analyzer as vision_analyzer_module


class FakeAnalyzer:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def analyze_product(self, payload):
        self.requests.append(payload)
        return self.response


def _product():
    return SimpleNamespace(
        asin="B000TEST",
        title="Acme replacement filter four pack",
        brand="Acme",
        main_image_url="https://img/1.jpg",
        raw_data={
            "bullet_points": ["Replacement filter, pack of 4"],
            "description": "Fits countertop water machine",
            "attributes": {"number_of_items": 4},
            "secondary_images": [
                "https://img/2.jpg",
                "https://img/1.jpg",
                "invalid-image",
                "https://img/3.jpg",
                "https://img/4.jpg",
                "https://img/5.jpg",
            ],
        },
    )


def _response():
    return {
        "asin": "B000TEST",
        "original_title_en": "Acme replacement filter four pack",
        "translated_title_cn": "净水器替换滤芯四件装",
        "generic_product_name": "water filter",
        "supply_chain_name_cn": "净水器替换滤芯",
        "category": "water filtration",
        "subcategory": "replacement filters",
        "function": ["过滤饮用水"],
        "material": ["活性炭"],
        "components": ["滤芯"],
        "package_quantity": 4,
        "dimensions_visible": [],
        "target_user": ["净水器用户"],
        "use_case": ["台式净水器滤芯更换"],
        "replaceable_part_or_full_product": "replacement",
        "distinguishing_features": ["四件装"],
        "likely_supplier_keywords_cn": ["净水器替换滤芯", "活性炭滤芯"],
        "excluded_brand_tokens": ["Acme"],
        "uncertainty": ["未提供可见尺寸"],
        "model_provider": "fake",
        "model_name": "fake-v1",
        "prompt_version": "amazon-understanding-v1",
    }


def test_understanding_uses_all_text_and_at_most_five_deduplicated_images():
    product = _product()
    analyzer = FakeAnalyzer(_response())

    result = understand_amazon_product(product, analyzer)

    request = analyzer.requests[0]
    assert request == {
        "asin": "B000TEST",
        "title": "Acme replacement filter four pack",
        "brand": "Acme",
        "bullet_points": ["Replacement filter, pack of 4"],
        "description": "Fits countertop water machine",
        "attributes": {"number_of_items": 4},
        "image_urls": [
            "https://img/1.jpg",
            "https://img/2.jpg",
            "https://img/3.jpg",
            "https://img/4.jpg",
            "https://img/5.jpg",
        ],
    }
    assert result.replaceable_part_or_full_product == "replacement"
    assert result.package_quantity == 4
    assert result.uncertainty == ["未提供可见尺寸"]


def test_brand_is_retained_only_as_an_excluded_token_not_supplier_query_copy():
    result = understand_amazon_product(_product(), FakeAnalyzer(_response()))

    assert "Acme" in result.excluded_brand_tokens
    assert all("acme" not in keyword.lower() for keyword in result.likely_supplier_keywords_cn)


def test_invalid_model_json_is_not_silently_coerced():
    analyzer = FakeAnalyzer({"generic_product_name": "filter"})

    with pytest.raises(ProductUnderstandingError, match="schema_validation"):
        understand_amazon_product(_product(), analyzer)


@pytest.mark.parametrize("missing_field", ["function", "package_quantity", "uncertainty"])
def test_every_semantic_field_must_be_explicit_even_when_schema_has_a_default(missing_field):
    response = _response()
    response.pop(missing_field)

    with pytest.raises(ProductUnderstandingError) as exc_info:
        understand_amazon_product(_product(), FakeAnalyzer(response))

    assert exc_info.value.code == "schema_validation"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("package_quantity", "4"), ("function", "filters water")],
)
def test_schema_validation_is_strict_and_does_not_coerce_types(field, invalid_value):
    response = _response()
    response[field] = invalid_value

    with pytest.raises(ProductUnderstandingError) as exc_info:
        understand_amazon_product(_product(), FakeAnalyzer(response))

    assert exc_info.value.code == "schema_validation"


def test_extra_model_field_is_rejected():
    response = _response()
    response["unreviewed_claim"] = True

    with pytest.raises(ProductUnderstandingError) as exc_info:
        understand_amazon_product(_product(), FakeAnalyzer(response))

    assert exc_info.value.code == "schema_validation"


def test_product_image_urls_handles_non_mapping_raw_data():
    product = SimpleNamespace(main_image_url="https://img/main.jpg", raw_data=None)
    assert product_image_urls(product) == ["https://img/main.jpg"]


def test_product_image_urls_rejects_malformed_http_like_values():
    product = SimpleNamespace(
        main_image_url="httpjunk",
        raw_data={
            "secondary_images": [
                "http://",
                "https:///missing-host.jpg",
                "ftp://img/file.jpg",
                "https://img/valid.jpg",
            ]
        },
    )
    assert product_image_urls(product) == ["https://img/valid.jpg"]


def test_brand_cleaning_uses_full_brand_words_and_model_excluded_aliases_case_insensitively():
    product = _product()
    product.brand = "Acme Home"
    response = _response()
    response.update({
        "generic_product_name": "ACME countertop water filter",
        "supply_chain_name_cn": "Acme Home 净水器 ACMECO 滤芯",
        "likely_supplier_keywords_cn": [
            "acme home replacement filter",
            "Acme 滤芯",
            "ACMECO carbon filter",
            "活性炭滤芯",
        ],
        "excluded_brand_tokens": ["AcmeCo"],
    })

    result = understand_amazon_product(product, FakeAnalyzer(response))

    assert result.excluded_brand_tokens == ["AcmeCo", "Acme Home"]
    supplier_copy = " ".join([
        result.generic_product_name,
        result.supply_chain_name_cn,
        *result.likely_supplier_keywords_cn,
    ]).casefold()
    assert "acme" not in supplier_copy
    assert "home" not in supplier_copy
    assert "acmeco" not in supplier_copy
    assert result.likely_supplier_keywords_cn == ["活性炭滤芯"]


def test_short_latin_brand_tokens_do_not_damage_words_that_merely_contain_them():
    product = _product()
    product.brand = "US Home GE"
    response = _response()
    response.update({
        "generic_product_name": "industrial household geometry filter",
        "supply_chain_name_cn": "US Home GE filter supplier",
        "likely_supplier_keywords_cn": ["industrial filter", "US filter"],
    })

    result = understand_amazon_product(product, FakeAnalyzer(response))

    assert result.generic_product_name == "industrial household geometry filter"
    assert result.supply_chain_name_cn == "filter supplier"
    assert result.likely_supplier_keywords_cn == ["industrial filter"]


@patch("matchers.vision_analyzer._HAS_OPENAI", True)
@patch("matchers.vision_analyzer._openai")
@patch("matchers.vision_analyzer._download_image")
def test_analyze_product_sends_every_image_and_records_actual_backend(
    download_image, mock_openai
):
    download_image.side_effect = [b"first-image", b"second-image"]
    response = _response()
    response["model_provider"] = "wrong"
    response["model_name"] = "wrong"
    response["prompt_version"] = "wrong"
    choice = MagicMock()
    choice.message.content = __import__("json").dumps(response)
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])
    mock_openai.OpenAI.return_value = client
    analyzer = VisionAnalyzer(provider="ppio", api_key="test", model="vision-v1")
    analyzer._cache = None

    result = analyzer.analyze_product({
        "asin": "B000TEST",
        "title": "Acme filter",
        "brand": "Acme",
        "bullet_points": [],
        "description": None,
        "attributes": {},
        "image_urls": ["https://img/1.jpg", "https://img/2.jpg"],
    })

    content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert len([block for block in content if block["type"] == "image_url"]) == 2
    assert result["model_provider"] == "ppio"
    assert result["model_name"] == "vision-v1"
    assert result["prompt_version"] == "amazon-understanding-v1"


@patch("matchers.vision_analyzer._download_image")
def test_product_cache_key_changes_for_text_images_provider_model_and_prompt(download_image):
    download_image.side_effect = lambda url: url.encode()
    analyzer = object.__new__(VisionAnalyzer)
    analyzer._provider = "ppio"
    analyzer._model = "model-a"
    payload = {
        "title": "Filter",
        "brand": "Acme",
        "bullet_points": [],
        "description": None,
        "attributes": {},
        "image_urls": ["https://img/1.jpg", "https://img/2.jpg"],
    }

    key = analyzer._product_cache_key(payload, [b"one", b"two"])
    assert key != analyzer._product_cache_key({**payload, "title": "Other"}, [b"one", b"two"])
    assert key != analyzer._product_cache_key(payload, [b"one", b"changed"])
    analyzer._model = "model-b"
    assert key != analyzer._product_cache_key(payload, [b"one", b"two"])
    analyzer._model = "model-a"
    analyzer._provider = "anthropic"
    assert key != analyzer._product_cache_key(payload, [b"one", b"two"])


def test_product_cache_key_changes_when_prompt_content_changes_without_version_change(monkeypatch):
    analyzer = object.__new__(VisionAnalyzer)
    analyzer._provider = "ppio"
    analyzer._model = "model-a"
    payload = {"title": "Filter", "image_urls": []}
    original_key = analyzer._product_cache_key(payload, [])

    monkeypatch.setattr(
        vision_analyzer_module,
        "_PRODUCT_UNDERSTANDING_PROMPT",
        vision_analyzer_module._PRODUCT_UNDERSTANDING_PROMPT + "\nnew instruction",
    )

    assert original_key != analyzer._product_cache_key(payload, [])


@pytest.mark.parametrize(
    ("analyzer", "expected_code"),
    [
        (FakeAnalyzer(RuntimeError("provider secret sk-test")), "provider_failure"),
    ],
)
def test_safe_error_codes_do_not_leak_exception_details(analyzer, expected_code):
    def raise_error(_payload):
        raise analyzer.response

    analyzer.analyze_product = raise_error
    with pytest.raises(ProductUnderstandingError) as exc_info:
        understand_amazon_product(_product(), analyzer)
    assert exc_info.value.code == expected_code
    assert str(exc_info.value) == expected_code
    assert "secret" not in str(exc_info.value)
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "sk-test" not in rendered


@patch("matchers.vision_analyzer._download_image", side_effect=RuntimeError("signed URL secret"))
def test_image_download_failure_has_stable_safe_code(_download):
    analyzer = object.__new__(VisionAnalyzer)
    analyzer._cache = None
    analyzer._provider = "ppio"
    analyzer._model = "model-a"

    with pytest.raises(Exception) as exc_info:
        analyzer.analyze_product({"image_urls": ["https://img/1.jpg"]})

    assert exc_info.value.code == "image_download_failure"
    assert str(exc_info.value) == "image_download_failure"


def test_json_parse_failure_has_stable_safe_code():
    analyzer = object.__new__(VisionAnalyzer)
    analyzer._cache = None
    analyzer._provider = "ppio"
    analyzer._model = "model-a"
    analyzer._client = MagicMock()
    analyzer._client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not-json secret"))]
    )

    with pytest.raises(Exception) as exc_info:
        analyzer.analyze_product({"image_urls": []})

    assert exc_info.value.code == "json_parse_failure"
    assert str(exc_info.value) == "json_parse_failure"


def test_provider_failure_has_stable_safe_code():
    analyzer = object.__new__(VisionAnalyzer)
    analyzer._cache = None
    analyzer._provider = "ppio"
    analyzer._model = "model-a"
    analyzer._client = MagicMock()
    analyzer._client.chat.completions.create.side_effect = RuntimeError("api key sk-secret")

    with pytest.raises(Exception) as exc_info:
        analyzer.analyze_product({"image_urls": []})

    assert exc_info.value.code == "provider_failure"
    assert str(exc_info.value) == "provider_failure"

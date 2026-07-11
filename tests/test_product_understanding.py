from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from matchers.product_understanding import (
    ProductUnderstandingError,
    product_image_urls,
    understand_amazon_product,
)
from matchers.vision_analyzer import VisionAnalyzer


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


def test_product_image_urls_handles_non_mapping_raw_data():
    product = SimpleNamespace(main_image_url="https://img/main.jpg", raw_data=None)
    assert product_image_urls(product) == ["https://img/main.jpg"]


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

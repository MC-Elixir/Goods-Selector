from types import SimpleNamespace

import pytest

from matchers.alibaba_pailitao import SupplierDTO
from matchers.verifier import LLMVisualVerifier, VisionVerificationError
from schemas.sourcing import VisionMatchResult


class FakeVisionClient:
    provider = "injected-provider"
    model = "injected-model"

    def __init__(self):
        self.requests = []
        self.response = {
            "same_product_type": True,
            "same_core_function": True,
            "same_accessory_full_product_relation": True,
            "same_structure": True,
            "same_material": True,
            "same_package_quantity": True,
            "major_visual_differences": [],
            "potential_mismatch": [],
            "confidence": 0.91,
            "evidence": ["两侧均为四只装替换滤芯"],
            "provider": "untrusted",
            "model": "untrusted",
            "prompt_version": "untrusted",
        }

    def verify(self, payload):
        self.requests.append(payload)
        return self.response


def _objects():
    product = SimpleNamespace(
        main_image_url="https://amazon/1.jpg",
        raw_data={
            "secondary_images": ["https://amazon/2.jpg", "https://amazon/1.jpg"],
            "understanding": {"package_quantity": 4, "function": ["filter water"]},
        },
    )
    supplier = SupplierDTO(
        alibaba_offer_id="123",
        offer_image_url="https://1688/1.jpg",
        raw_data={
            "detail": {
                "detail_images": ["https://1688/d1.jpg"],
                "sku_images": ["https://1688/s1.jpg"],
                "package_quantity": 4,
            }
        },
    )
    client = FakeVisionClient()
    verifier = LLMVisualVerifier(
        api_key="test", api_base="https://example.invalid", model="configured-model",
        provider_client=client,
    )
    return verifier, client, product, supplier


def test_schema_is_strict_and_forbids_extra_fields():
    payload = dict(FakeVisionClient().response)
    payload.update(provider="p", model="m", prompt_version="v")
    with pytest.raises(Exception):
        VisionMatchResult.model_validate({**payload, "same_product_type": 1}, strict=True)
    with pytest.raises(Exception):
        VisionMatchResult.model_validate({**payload, "unexpected": True}, strict=True)


def test_dual_image_request_contains_both_image_sets_and_attributes():
    verifier, client, product, supplier = _objects()
    result = verifier.verify_pair(product, supplier)
    request = client.requests[0]
    assert request["amazon_images"] == [product.main_image_url, "https://amazon/2.jpg"]
    assert request["supplier_images"] == [supplier.offer_image_url, "https://1688/d1.jpg", "https://1688/s1.jpg"]
    assert request["amazon_attributes"]["package_quantity"] == 4
    assert request["supplier_attributes"]["package_quantity"] == 4
    assert (result.provider, result.model, result.prompt_version) == (
        "injected-provider", "injected-model", "supplier-visual-match-v1",
    )
    assert result.model_dump()["is_match"] is True
    assert result.model_dump()["classification_confidence"] == 0.91


@pytest.mark.parametrize("response", [
    {"same_product_type": "probably"},
    {"same_product_type": True},
    {**FakeVisionClient().response, "same_core_function": None},
])
def test_invalid_task_b_json_is_rejected_without_raw_response(response):
    verifier, client, product, supplier = _objects()
    client.response = response
    with pytest.raises(VisionVerificationError, match="^schema_validation$") as exc:
        verifier.verify_pair(product, supplier)
    assert "probably" not in str(exc.value)


@pytest.mark.parametrize("field", [
    "same_product_type", "same_core_function", "same_package_quantity",
    "same_accessory_full_product_relation",
])
def test_decisive_negative_cannot_be_overridden_by_confidence(field):
    verifier, client, product, supplier = _objects()
    client.response[field] = False
    client.response["confidence"] = 1.0
    result = verifier.verify_pair(product, supplier)
    assert result.is_match is False


def test_accessory_full_product_relation_key_is_required():
    verifier, client, product, supplier = _objects()
    client.response.pop("same_accessory_full_product_relation")
    with pytest.raises(VisionVerificationError, match="^schema_validation$"):
        verifier.verify_pair(product, supplier)


def test_cache_identity_includes_failed_slot_identity_and_final_prompt():
    verifier, _, _, _ = _objects()
    payload = {"amazon_attributes": {}, "supplier_attributes": {}}
    images = {"amazon": [b"same"], "supplier": [b"same"]}
    slots_a = {
        "amazon": [{"slot": 0, "status": "ok", "content_sha256": "x"}],
        "supplier": [{"slot": 0, "status": "failed", "url_sha256": "a"}],
    }
    slots_b = {
        "amazon": [{"slot": 0, "status": "ok", "content_sha256": "x"}],
        "supplier": [{"slot": 1, "status": "failed", "url_sha256": "a"}],
    }
    slots_c = {
        "amazon": slots_a["amazon"],
        "supplier": [*slots_a["supplier"], {"slot": 1, "status": "failed", "url_sha256": "b"}],
    }
    key = verifier._vision_cache_key(payload, images, slots_a, "final prompt A")
    assert key == verifier._vision_cache_key(payload, images, slots_a, "final prompt A")
    assert key != verifier._vision_cache_key(payload, images, slots_b, "final prompt A")
    assert key != verifier._vision_cache_key(payload, images, slots_c, "final prompt A")
    assert key != verifier._vision_cache_key(payload, images, slots_a, "final prompt B")


def test_provider_image_blocks_preserve_png_and_webp_media_types():
    verifier, _, _, _ = _objects()
    png = verifier._openai_task_image_block(b"\x89PNG\r\n", "image/png")
    webp = verifier._anthropic_task_image_block(b"RIFF0000WEBP", "image/webp")
    assert png["image_url"]["url"].startswith("data:image/png;base64,")
    assert webp["source"]["media_type"] == "image/webp"


def test_unsupported_image_bytes_are_not_accepted_as_jpeg():
    verifier, _, _, _ = _objects()
    assert verifier._task_image_media_type(b"<html>not an image</html>") is None

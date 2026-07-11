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


@pytest.mark.parametrize("field", ["same_product_type", "same_core_function", "same_package_quantity"])
def test_decisive_negative_cannot_be_overridden_by_confidence(field):
    verifier, client, product, supplier = _objects()
    client.response[field] = False
    client.response["confidence"] = 1.0
    result = verifier.verify_pair(product, supplier)
    assert result.is_match is False

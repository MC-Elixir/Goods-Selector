"""
视觉分析器 + 1688 文字搜索的单元测试。
所有外部 API 调用均通过 mock 隔离，无需真实 key。
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from matchers import vision_analyzer as vision_analyzer_module
from matchers.vision_analyzer import (
    ProductAnalysis,
    VisionAnalyzer,
    _parse_json_response,
    _detect_media_type,
)
from matchers.alibaba_text_search import _parse_search_response, _item_to_dto
from matchers.alibaba_pailitao import SupplierDTO
from matchers.verifier import LLMVisualVerifier


@pytest.fixture(autouse=True)
def _disable_vision_cache(monkeypatch):
    monkeypatch.setattr(vision_analyzer_module.settings, "enable_api_cache", False)


# ============================================================
# _parse_json_response
# ============================================================
class TestParseJsonResponse:
    def test_plain_json(self):
        payload = json.dumps({
            "category_zh": "折叠桌",
            "keywords_zh": ["铝合金折叠桌", "折叠野餐桌", "户外折叠桌", "便携桌"],
            "title_zh": "铝合金折叠野餐桌",
            "material": "铝合金",
            "color": "银色",
            "key_features": ["轻便", "折叠"],
            "has_dangerous_attr": False,
            "description_en": "Lightweight aluminum folding table.",
        })
        result = _parse_json_response(payload)
        assert result.category_zh == "折叠桌"
        assert len(result.keywords_zh) == 4
        assert result.has_dangerous_attr is False

    def test_markdown_code_block(self):
        payload = "```json\n{\"category_zh\":\"瑜伽垫\",\"keywords_zh\":[\"瑜伽垫\",\"运动垫\",\"健身垫\",\"防滑垫\"],\"title_zh\":\"瑜伽垫\",\"has_dangerous_attr\":false,\"description_en\":\"Yoga mat.\"}\n```"
        result = _parse_json_response(payload)
        assert result.category_zh == "瑜伽垫"

    def test_missing_optional_fields_use_defaults(self):
        payload = json.dumps({
            "category_zh": "手机支架",
            "keywords_zh": ["手机支架", "桌面支架"],
            "title_zh": "手机支架",
            "has_dangerous_attr": False,
            "description_en": "Phone stand.",
        })
        result = _parse_json_response(payload)
        assert result.material is None
        assert result.color is None
        assert result.key_features == []

    def test_dangerous_attr_true(self):
        payload = json.dumps({
            "category_zh": "移动电源",
            "keywords_zh": ["移动电源", "充电宝", "大容量充电宝", "便携充电"],
            "title_zh": "移动电源",
            "has_dangerous_attr": True,
            "description_en": "Power bank.",
        })
        result = _parse_json_response(payload)
        assert result.has_dangerous_attr is True

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            _parse_json_response("这不是 JSON 内容")


# ============================================================
# _detect_media_type
# ============================================================
class TestDetectMediaType:
    def test_jpeg(self):
        assert _detect_media_type(b"\xff\xd8\xff" + b"\x00" * 10) == "image/jpeg"

    def test_png(self):
        assert _detect_media_type(b"\x89PNG" + b"\x00" * 10) == "image/png"

    def test_webp(self):
        assert _detect_media_type(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"

    def test_unknown_defaults_to_jpeg(self):
        assert _detect_media_type(b"\x00\x00\x00\x00") == "image/jpeg"


# ============================================================
# _parse_search_response（1688 API 解析）
# ============================================================
_MOCK_OFFER = {
    "offerId": "123456789",
    "subject": "铝合金折叠桌 户外便携轻量野餐桌",
    "saleInfo": {
        "minOrderQuantity": 50,
        "priceRangeList": [
            {"startQuantity": 1, "price": 45.0},
            {"startQuantity": 50, "price": 38.0},
            {"startQuantity": 200, "price": 32.0},
        ],
    },
    "supplierInfo": {
        "supplierName": "广州某某贸易有限公司",
        "supplierUrl": "https://shop.1688.com/xxx",
        "isFactory": True,
    },
    "productInfo": {"mainPictUrl": "https://img.1688.com/xxx.jpg"},
    "tradeInfo": {"monthlyOrderNum": 350, "repeatPurchaseRate": 0.42},
}


class TestParseSearchResponse:
    def test_normal_response(self):
        raw = {"result": {"offerList": [_MOCK_OFFER]}}
        dtos = _parse_search_response(raw)
        assert len(dtos) == 1
        dto = dtos[0]
        assert dto.alibaba_offer_id == "123456789"
        assert dto.moq == 50
        assert dto.base_price_cny == 38.0   # 第二档（中位）
        assert dto.monthly_sales == 350
        assert dto.repeat_buyer_rate == pytest.approx(0.42)
        assert dto.is_factory is True

    def test_empty_offer_list(self):
        assert _parse_search_response({"result": {"offerList": []}}) == []

    def test_missing_result_key(self):
        assert _parse_search_response({}) == []

    def test_offer_url_constructed(self):
        dtos = _parse_search_response({"result": {"offerList": [_MOCK_OFFER]}})
        assert "123456789" in dtos[0].offer_url

    def test_delivery_days_none_by_default(self):
        dtos = _parse_search_response({"result": {"offerList": [_MOCK_OFFER]}})
        assert dtos[0].delivery_days is None

    def test_malformed_offer_skipped(self):
        raw = {"result": {"offerList": [_MOCK_OFFER, None]}}
        # None 会触发解析异常，应被跳过而不是崩溃
        dtos = _parse_search_response(raw)
        assert len(dtos) == 1


# ============================================================
# VisionAnalyzer（mock API 客户端，不依赖真实 Key）
# ============================================================
_PAYLOAD = json.dumps({
    "category_zh": "折叠桌",
    "keywords_zh": ["铝合金折叠桌", "折叠野餐桌", "户外折叠桌", "便携桌"],
    "title_zh": "铝合金折叠桌",
    "has_dangerous_attr": False,
    "description_en": "Folding table.",
})


class TestVisionAnalyzerPPIO:
    """用 mock OpenAI 客户端测试 PPIO 后端。"""

    def _mock_openai_client(self):
        choice = MagicMock()
        choice.message.content = _PAYLOAD
        resp = MagicMock()
        resp.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = resp
        return client

    @patch("matchers.vision_analyzer._HAS_OPENAI", True)
    @patch("matchers.vision_analyzer._openai")
    def test_ppio_analyze_returns_product_analysis(self, mock_openai):
        mock_openai.OpenAI.return_value = self._mock_openai_client()
        analyzer = VisionAnalyzer(provider="ppio", api_key="ppio-test-key")
        result = analyzer.analyze(image_bytes=b"\xff\xd8\xff" + b"\x00" * 100)

        assert isinstance(result, ProductAnalysis)
        assert result.category_zh == "折叠桌"
        assert len(result.keywords_zh) >= 4
        assert result.has_dangerous_attr is False

    @patch("matchers.vision_analyzer._HAS_OPENAI", True)
    @patch("matchers.vision_analyzer._openai")
    def test_ppio_uses_correct_model(self, mock_openai):
        mock_client = self._mock_openai_client()
        mock_openai.OpenAI.return_value = mock_client
        VisionAnalyzer(
            provider="ppio",
            api_key="ppio-test-key",
            model="qwen/qwen2.5-vl-72b-instruct",
        ).analyze(image_bytes=b"\xff\xd8\xff" + b"\x00" * 100)

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "qwen/qwen2.5-vl-72b-instruct"

    @patch("matchers.vision_analyzer._HAS_OPENAI", True)
    @patch("matchers.vision_analyzer._openai")
    def test_ppio_image_sent_as_data_url(self, mock_openai):
        mock_client = self._mock_openai_client()
        mock_openai.OpenAI.return_value = mock_client
        VisionAnalyzer(
            provider="ppio", api_key="ppio-test-key"
        ).analyze(image_bytes=b"\xff\xd8\xff" + b"\x00" * 100)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        content = messages[0]["content"]
        img_block = next(b for b in content if b["type"] == "image_url")
        assert img_block["image_url"]["url"].startswith("data:image/jpeg;base64,")


class TestVisionAnalyzerAnthropic:
    """用 mock Anthropic 客户端测试 Anthropic 后端。"""

    def _mock_anthropic_client(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=_PAYLOAD)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        return mock_client

    @patch("matchers.vision_analyzer._HAS_ANTHROPIC", True)
    @patch("matchers.vision_analyzer._anthropic")
    def test_anthropic_analyze_returns_product_analysis(self, mock_anthropic):
        mock_anthropic.Anthropic.return_value = self._mock_anthropic_client()
        analyzer = VisionAnalyzer(provider="anthropic", api_key="sk-ant-test")
        result = analyzer.analyze(image_bytes=b"\xff\xd8\xff" + b"\x00" * 100)

        assert isinstance(result, ProductAnalysis)
        assert result.category_zh == "折叠桌"


class TestVisionAnalyzerAutoDetect:
    """测试 auto provider 选择逻辑。"""

    @patch("matchers.vision_analyzer.settings")
    def test_auto_selects_ppio_when_key_set(self, mock_settings):
        mock_settings.vision_provider = "ppio"
        mock_settings.ppio_api_key = "ppio-key"
        mock_settings.ppio_api_base = "https://api.ppinfra.com/v3/openai"
        mock_settings.ppio_model = "qwen/qwen2.5-vl-72b-instruct"
        mock_settings.enable_api_cache = False

        with patch("matchers.vision_analyzer._HAS_OPENAI", True), \
             patch("matchers.vision_analyzer._openai") as mock_openai:
            choice = MagicMock()
            choice.message.content = _PAYLOAD
            resp = MagicMock()
            resp.choices = [choice]
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = resp
            mock_openai.OpenAI.return_value = mock_client

            analyzer = VisionAnalyzer(provider="auto")
            assert analyzer._provider == "ppio"


def test_high_confidence_negative_is_rejected(monkeypatch):
    product = SimpleNamespace(main_image_url="https://amazon/image.jpg")
    supplier = SupplierDTO(
        alibaba_offer_id="negative",
        supplier_name="整机供应商",
        offer_image_url="https://1688/image.jpg",
        match_quality_score=0.8,
    )
    verifier = LLMVisualVerifier(
        api_key="test",
        api_base="https://example.invalid",
        model="test",
    )
    monkeypatch.setattr(
        verifier,
        "_compare_images",
        lambda *_: {
            "is_match": False,
            "confidence": 0.99,
            "reason": "整机与替换滤芯",
            "differences": ["功能不同"],
        },
    )

    result = verifier.verify([supplier], product, threshold=0.3)

    assert result == []
    assert supplier.match_quality_score == 0.0
    assert supplier.raw_data["visual_match"]["decision"] == "reject"

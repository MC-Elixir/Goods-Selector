"""1688 pifatuan open-platform matcher tests."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote

import pytest

from matchers.alibaba_pifatuan import (
    AlibabaPifatuanSearch,
    _parse_candidate_apis,
    _parse_pifatuan_response,
)


def test_parse_pifatuan_response_maps_supplier_fields():
    raw = {
        "success": True,
        "result": {
            "productList": [
                {
                    "productId": 123456789,
                    "subject": "304不锈钢保温杯 700ml",
                    "productInfo": {"mainPictUrl": "https://img.example/a.jpg"},
                    "saleInfo": {
                        "minOrderQuantity": "20",
                        "priceRangeList": [
                            {"startQuantity": 1, "price": "25.5"},
                            {"startQuantity": 50, "price": "22.0"},
                        ],
                    },
                    "supplierInfo": {
                        "supplierName": "宁波源头工厂",
                        "isFactory": True,
                    },
                    "tradeInfo": {
                        "monthlyOrderNum": "1200",
                        "repeatPurchaseRate": "0.38",
                    },
                    "detailInfo": {
                        "attributes": [
                            {"attributeName": "包装尺寸", "value": "8x8x26cm"},
                            {"attributeName": "发货期", "value": "7天"},
                            {"attributeName": "专利", "value": "外观专利"},
                        ]
                    },
                }
            ]
        },
    }

    suppliers = _parse_pifatuan_response(raw)

    assert len(suppliers) == 1
    supplier = suppliers[0]
    assert supplier.alibaba_offer_id == "123456789"
    assert supplier.title_cn == "304不锈钢保温杯 700ml"
    assert supplier.offer_url.endswith("/123456789.html")
    assert supplier.offer_image_url == "https://img.example/a.jpg"
    assert supplier.base_price_cny == 22.0
    assert supplier.moq == 20
    assert supplier.monthly_sales == 1200
    assert supplier.repeat_buyer_rate == 0.38
    assert supplier.is_factory is True
    assert supplier.delivery_days == 7
    assert supplier.product_dimensions_cm == "8.0x8.0x26.0cm"
    assert "patent_claim" in supplier.raw_data["risk_flags"]
    assert supplier.raw_data["source"] == "alibaba_pifatuan"


def test_build_payload_uses_param2_signature_shape(monkeypatch):
    client = AlibabaPifatuanSearch(
        app_key="app",
        app_secret="secret",
        access_token="token",
        gateway="https://gw.open.1688.com/openapi/",
    )

    payload = client._build_payload({"pageSize": 3, "pageNum": 1, "keywords": "水杯"})
    parsed = parse_qs(payload)
    param2 = json.loads(unquote(parsed["param2"][0]))

    assert parsed["access_token"] == ["token"]
    assert param2["keywords"] == "水杯"
    assert param2["pageSize"] == 3
    assert "_aop_signature" in param2


def test_search_posts_to_pifatuan_endpoint(monkeypatch):
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "result": {
                    "productList": [
                        {
                            "offerId": "111",
                            "title": "水杯",
                            "supplierInfo": {"supplierName": "Factory"},
                        }
                    ]
                },
            }

    def fake_post(url, data, headers, timeout):
        posts.append((url, data, headers, timeout))
        return FakeResponse()

    monkeypatch.setattr("matchers.alibaba_pifatuan.requests.post", fake_post)
    client = AlibabaPifatuanSearch(
        app_key="app",
        app_secret="secret",
        access_token="token",
        gateway="https://gw.open.1688.com/openapi/",
    )
    monkeypatch.setattr(client, "_cache", None)

    suppliers = client.search(["水杯"], top_k=3)

    assert suppliers[0].alibaba_offer_id == "111"
    assert "/param2/1/com.alibaba.pifatuan/alibaba.pifatuan.product.list/app" in posts[0][0]
    assert posts[0][2]["Content-Type"] == "application/x-www-form-urlencoded"


def test_search_uses_configured_openapi_method(monkeypatch):
    posts = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "result": {"productList": [{"offerId": "222", "title": "水杯"}]}}

    def fake_post(url, data, headers, timeout):
        posts.append((url, data))
        return FakeResponse()

    monkeypatch.setattr("matchers.alibaba_pifatuan.requests.post", fake_post)
    client = AlibabaPifatuanSearch(
        app_key="app",
        app_secret="secret",
        access_token="token",
        gateway="https://gw.open.1688.com/openapi/",
        namespace="com.alibaba.custom",
        method="alibaba.custom.supplier.search",
        keyword_param="keyword",
    )
    monkeypatch.setattr(client, "_cache", None)

    suppliers = client.search(["水杯"], top_k=1)
    parsed = parse_qs(posts[0][1])
    param2 = json.loads(unquote(parsed["param2"][0]))

    assert suppliers[0].alibaba_offer_id == "222"
    assert "/param2/1/com.alibaba.custom/alibaba.custom.supplier.search/app" in posts[0][0]
    assert param2["keyword"] == "水杯"
    assert "keywords" not in param2


def test_parse_candidate_apis_supports_pipe_and_slash_formats():
    apis = _parse_candidate_apis(
        "com.alibaba.one|alibaba.one.search|keyword\n"
        "com.alibaba.two/alibaba.two.search:keywords"
    )

    assert [(a.namespace, a.method, a.keyword_param) for a in apis] == [
        ("com.alibaba.one", "alibaba.one.search", "keyword"),
        ("com.alibaba.two", "alibaba.two.search", "keywords"),
    ]


def test_search_tries_fallback_candidate_after_unsupported_api(monkeypatch):
    posts = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.reason = "Bad Request" if status_code >= 400 else "OK"
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    def fake_post(url, data, headers, timeout):
        posts.append((url, data))
        if "alibaba.pifatuan.product.list" in url:
            return FakeResponse(400, {"errorCode": "gw.APIUnsupported", "errorMessage": "API unsupported"})
        return FakeResponse(200, {"success": True, "result": {"productList": [{"offerId": "333", "title": "水杯"}]}})

    monkeypatch.setattr("matchers.alibaba_pifatuan.requests.post", fake_post)
    monkeypatch.setattr(
        "matchers.alibaba_pifatuan.settings.alibaba_supplier_search_candidates",
        "com.alibaba.custom|alibaba.custom.supplier.search|keyword",
    )
    client = AlibabaPifatuanSearch(
        app_key="app",
        app_secret="secret",
        access_token="token",
        gateway="https://gw.open.1688.com/openapi/",
    )
    monkeypatch.setattr(client, "_cache", None)

    suppliers = client.search(["水杯"], top_k=1)
    fallback_payload = json.loads(unquote(parse_qs(posts[-1][1])["param2"][0]))

    assert suppliers[0].alibaba_offer_id == "333"
    assert len(posts) >= 2
    assert "alibaba.custom.supplier.search" in posts[-1][0]
    assert client.method == "alibaba.custom.supplier.search"
    assert client.last_attempts[0]["ok"] is False
    assert client.last_attempts[1]["ok"] is True
    assert fallback_payload["keyword"] == "水杯"


def test_search_reports_open_platform_error_body(monkeypatch):
    class FakeResponse:
        status_code = 400
        reason = "Bad Request"
        text = '{"errorCode":"invalid-permission","errorMessage":"API not authorized"}'

        def json(self):
            return {"errorCode": "invalid-permission", "errorMessage": "API not authorized"}

    def fake_post(url, data, headers, timeout):
        return FakeResponse()

    monkeypatch.setattr("matchers.alibaba_pifatuan.requests.post", fake_post)
    client = AlibabaPifatuanSearch(
        app_key="app",
        app_secret="secret",
        access_token="token",
        gateway="https://gw.open.1688.com/openapi/",
    )
    monkeypatch.setattr(client, "_cache", None)

    with pytest.raises(RuntimeError, match="invalid-permission.*API not authorized"):
        client.search(["水杯"], top_k=1)


def test_search_requires_full_open_platform_config():
    client = AlibabaPifatuanSearch(app_key="app", app_secret="secret", access_token="")

    with pytest.raises(RuntimeError, match="not configured"):
        client.search(["水杯"])

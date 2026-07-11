"""卖家精灵市场分析编排单测。"""
from __future__ import annotations

from types import SimpleNamespace

from analyzers.maijiajingling import (
    AsinDetailDTO,
    BsrPredictionDTO,
    MaijiajinglingClient,
    MarketAnalysisDTO,
    MarketDataError,
    _extract_keyword_metrics,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(SimpleNamespace(method="GET", path=path, params=params))
        return _FakeResponse(self.payload)

    def request(self, method, path, **kwargs):
        self.calls.append(SimpleNamespace(method=method, path=path, params=kwargs.get("params")))
        return _FakeResponse(self.payload)


class _FakeMJJLClient(MaijiajinglingClient):
    def __init__(self):
        super().__init__(api_key="test-key", base_url="https://api.sellersprite.com")
        self.keyword_payload = None
        self.fail_keyword_research = False

    def asin_detail(self, marketplace: str, asin: str) -> AsinDetailDTO:
        return AsinDetailDTO(
            asin=asin,
            marketplace=marketplace,
            brand="Generic",
            title="Silicone Kitchen Mat",
            price=24.99,
            bsr=1200,
            bsr_category_id="123",
            bsr_category_name="Kitchen Mats",
            category_name="Kitchen Mats",
            raw={"asin": asin},
        )

    def bsr_prediction(self, marketplace: str, bsr: int, category_id: str) -> BsrPredictionDTO:
        return BsrPredictionDTO(
            marketplace=marketplace,
            bsr=bsr,
            category_id=category_id,
            est_daily_sales=18,
            est_monthly_sales=540,
        )

    def competitor_lookup(self, **kwargs) -> dict:
        return {
            "code": "OK",
            "data": {
                "items": [
                    {"price": 24.99, "reviewCount": 100, "totalRevenue": 1000},
                    {"price": 19.99, "reviewCount": 50, "totalRevenue": 500},
                ]
            },
        }

    def keyword_research(self, keyword: str, marketplace: str = "US", **kwargs) -> dict:
        if self.fail_keyword_research:
            raise RuntimeError("keyword research unavailable")
        self.keyword_payload = {"keyword": keyword, "marketplace": marketplace}
        return {
            "code": "OK",
            "data": {
                "items": [
                    {
                        "keyword": keyword,
                        "searchVolume": 4200,
                        "purchase": 280,
                        "purchaseRate": 6.67,
                        "keywordDifficulty": 0.35,
                        "opportunityScore": 0.12,
                        "searchesTrend": [100, 120, 140],
                    }
                ]
            },
        }

    def keyword_research_trends(self, keyword: str, marketplace: str = "US") -> dict:
        return {
            "code": "OK",
            "data": [
                {
                    "time": "2026年06月",
                    "keywrod": keyword,
                    "search": 6500,
                    "purchase": 520,
                    "purchaseRate": 8.0,
                },
                {
                    "time": "2026年05月",
                    "keywrod": keyword,
                    "search": 6200,
                    "purchase": 490,
                    "purchaseRate": 7.9,
                },
            ],
        }


def test_extract_keyword_metrics_handles_common_field_names():
    metrics = _extract_keyword_metrics(
        {
            "data": {
                "items": [
                    {
                        "keywordText": "silicone mat",
                        "monthlySearches": "3,500",
                        "difficulty": "22%",
                        "purchaseRate": "8%",
                    }
                ]
            }
        }
    )

    assert metrics["main_keyword"] == "silicone mat"
    assert metrics["search_volume_monthly"] == 3500
    assert metrics["keyword_difficulty"] == 0.22
    assert metrics["purchase_rate"] == 0.08
    assert metrics["opportunity_score"] is not None


def test_asin_detail_parses_current_official_bsr_fields():
    client = MaijiajinglingClient(api_key="test-key", base_url="https://api.sellersprite.com")
    client._client = _RecordingHttpClient({
        "code": "OK",
        "data": {
            "asin": "B0TEST1234",
            "badge": {"bestSeller": "Y", "ebc": "Y"},
            "brand": "Generic",
            "bsrId": "home-garden",
            "bsrLabel": "Home & Kitchen",
            "bsrRank": 1006,
            "imageUrl": "https://example.com/image.jpg",
            "nodeId": "1063280",
            "nodeIdPath": "1055398:1063252:1063280",
            "nodeLabelPath": "Home & Kitchen:Bedding",
            "price": 21.99,
            "rating": 4.5,
            "reviews": 321,
            "title": "Test Product",
            "features": ["Soft", "Machine washable"],
            "fulfillment": "FBA",
            "parent": "B0PARENT",
            "variations": 3,
        },
    })

    detail = client.asin_detail("US", "B0TEST1234")

    assert detail.bsr == 1006
    assert detail.bsr_category_id == "1055398"
    assert detail.bsr_category_name == "Home & Kitchen"
    assert detail.category_id == "1063280"
    assert detail.category_path == "Home & Kitchen:Bedding"
    assert detail.main_image == "https://example.com/image.jpg"
    assert detail.review_count == 321
    assert detail.bullet_points == ["Soft", "Machine washable"]
    assert detail.fulfilled_by_amazon is True
    assert detail.parent_asin == "B0PARENT"
    assert detail.variation_count == 3


def test_category_lookup_uses_current_product_node_endpoint():
    client = MaijiajinglingClient(api_key="test-key", base_url="https://api.sellersprite.com")
    fake_http = _RecordingHttpClient({"code": "OK", "data": {"items": []}})
    client._client = fake_http

    client.category_lookup("US", keyword="Books", parent_id="2619525011:3741271")

    assert fake_http.calls[0].method == "GET"
    assert fake_http.calls[0].path == "/v1/product/node"
    assert fake_http.calls[0].params == {
        "marketplace": "US",
        "keyword": "Books",
        "nodeIdPath": "2619525011:3741271",
    }


def test_analyze_market_populates_sales_competition_and_keyword_metrics():
    client = _FakeMJJLClient()

    dto = client.analyze_market("B0TEST1234", "US", keyword="kitchen mat")

    assert dto.asin == "B0TEST1234"
    assert dto.est_daily_sales == 18
    assert dto.est_monthly_sales == 540
    assert dto.competing_listings == 2
    assert dto.avg_price_top10 == 22.49
    assert dto.main_keyword == "kitchen mat"
    assert dto.search_volume_monthly == 4200
    assert dto.monthly_purchases == 280
    assert dto.purchase_rate == 6.67
    assert dto.keyword_difficulty == 0.35
    assert dto.opportunity_score == 0.12
    assert client.keyword_payload == {"keyword": "kitchen mat", "marketplace": "US"}
    assert set(dto.raw_data) == {"bsr_prediction", "competitor_lookup", "keyword_research", "asin_detail"}


def test_analyze_market_falls_back_to_keyword_trends():
    client = _FakeMJJLClient()
    client.fail_keyword_research = True

    dto = client.analyze_market("B0TEST1234", "US", keyword="kitchen mat")

    assert dto.main_keyword == "kitchen mat"
    assert dto.search_volume_monthly == 6500
    assert dto.monthly_purchases == 520
    assert dto.purchase_rate == 8.0
    assert "keyword_research_trends" in dto.raw_data


def test_analyze_market_continues_when_asin_detail_unavailable():
    class FallbackClient(_FakeMJJLClient):
        def asin_detail(self, marketplace: str, asin: str) -> AsinDetailDTO:
            raise RuntimeError("ASIN detail unauthorized")

        def competitor_lookup(self, **kwargs) -> dict:
            return {
                "code": "OK",
                "data": {
                    "items": [
                        {
                            "asin": "B0TEST1234",
                            "title": "Fallback Product",
                            "brand": "Acme",
                            "price": "22.50",
                            "rating": "4.4",
                            "ratings": "88",
                            "bsrRank": "3456",
                            "units": "660",
                            "revenue": "14850",
                        }
                    ]
                },
            }

    client = FallbackClient()

    dto = client.analyze_market("B0TEST1234", "US", keyword="fallback keyword")

    assert dto.asin == "B0TEST1234"
    assert dto.title == "Fallback Product"
    assert dto.brand == "Acme"
    assert dto.price == 22.5
    assert dto.rating == 4.4
    assert dto.review_count == 88
    assert dto.bsr == 3456
    assert dto.est_monthly_sales == 660
    assert dto.est_daily_sales == 22
    assert dto.competing_listings == 1
    assert dto.main_keyword == "fallback keyword"
    assert "asin_detail_error" in dto.raw_data
    assert "competitor_lookup" in dto.raw_data


def test_invalid_key_is_failed_evidence_not_empty_market(monkeypatch):
    client = MaijiajinglingClient(api_key="invalid")
    monkeypatch.setattr(
        client, "analyze_market",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MarketDataError("AUTH_REQUIRED", "invalid key")
        ),
    )
    result = client.analyze_market_evidence(
        "B000TEST", marketplace="US", keyword="water filter"
    )
    assert result.status == "failed"
    assert result.error_code == "AUTH_REQUIRED"
    assert result.data is None


def test_partial_market_result_lists_missing_fields(monkeypatch):
    client = MaijiajinglingClient(api_key="test")
    monkeypatch.setattr(
        client, "analyze_market",
        lambda *args, **kwargs: MarketAnalysisDTO(
            asin="B000TEST", est_monthly_sales=500
        ),
    )
    result = client.analyze_market_evidence(
        "B000TEST", marketplace="US", keyword="water filter"
    )
    assert result.status == "partial"
    assert "competing_listings" in result.missing_fields
    assert "search_volume_monthly" in result.missing_fields


def test_market_http_failures_have_stable_safe_error_codes():
    assert MarketDataError.from_exception(__import__("httpx").TimeoutException("late")).error_code == "TIMEOUT"
    for status, code in ((401, "AUTH_REQUIRED"), (403, "AUTH_REQUIRED"), (429, "RATE_LIMITED")):
        request = __import__("httpx").Request("GET", "https://api.sellersprite.com/v1/test")
        response = __import__("httpx").Response(status, request=request)
        error = MarketDataError.from_exception(__import__("httpx").HTTPStatusError("failed", request=request, response=response))
        assert error.error_code == code
        assert "secret" not in error.diagnostic.lower()


def test_request_diagnostics_are_hashed_and_do_not_store_api_key():
    client = MaijiajinglingClient(api_key="top-secret", base_url="https://api.sellersprite.com")
    client._client = _RecordingHttpClient({"code": "OK", "data": {"value": 1}})

    body, diagnostic = client._request("GET", "/v1/test")

    assert body["data"] == {"value": 1}
    assert diagnostic["endpoint"] == "/v1/test"
    assert len(diagnostic["response_hash"]) == 64
    assert "top-secret" not in str(diagnostic)
    assert __import__("datetime").datetime.fromisoformat(
        diagnostic["response_timestamp"]
    ).utcoffset() is not None

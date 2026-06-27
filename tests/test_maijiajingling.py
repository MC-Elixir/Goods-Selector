"""卖家精灵市场分析编排单测。"""
from __future__ import annotations

from analyzers.maijiajingling import (
    AsinDetailDTO,
    BsrPredictionDTO,
    MaijiajinglingClient,
    _extract_keyword_metrics,
)


class _FakeMJJLClient(MaijiajinglingClient):
    def __init__(self):
        super().__init__(api_key="test-key", base_url="https://api.sellersprite.com")
        self.keyword_payload = None

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
        self.keyword_payload = {"keyword": keyword, "marketplace": marketplace}
        return {
            "code": "OK",
            "data": {
                "items": [
                    {
                        "keyword": keyword,
                        "searchVolume": 4200,
                        "keywordDifficulty": 0.35,
                        "opportunityScore": 0.12,
                        "searchesTrend": [100, 120, 140],
                    }
                ]
            },
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
    assert metrics["opportunity_score"] is not None


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
    assert dto.keyword_difficulty == 0.35
    assert dto.opportunity_score == 0.12
    assert client.keyword_payload == {"keyword": "kitchen mat", "marketplace": "US"}
    assert set(dto.raw_data) == {"bsr_prediction", "competitor_lookup", "keyword_research", "asin_detail"}

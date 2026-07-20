from analyzers.sellersprite_browser_market import market_from_reverse_keyword_result


def test_reverse_keyword_evidence_maps_only_supported_market_fields():
    market = market_from_reverse_keyword_result(
        asin="B00Q7OAN50",
        marketplace="US",
        result_data={
            "manifest_id": "00000000-0000-0000-0000-000000000001",
            "file_sha256": "a" * 64,
            "row_count": 1109,
            "keyword_rows": [
                {
                    "keyword": "small keyword",
                    "search_volume": 100,
                    "purchase_volume": 8,
                    "purchase_rate": 0.08,
                    "competing_products": 900,
                },
                {
                    "keyword": "main keyword",
                    "search_volume": 900,
                    "purchase_volume": 45,
                    "purchase_rate": 0.05,
                    "competing_products": 1200,
                },
            ],
        },
    )

    assert market.main_keyword == "main keyword"
    assert market.search_volume_monthly == 900
    assert market.monthly_purchases == 45
    assert market.purchase_rate == 0.05
    assert market.competing_listings == 1200
    assert market.est_monthly_sales is None
    assert market.keyword_difficulty is None
    assert market.opportunity_score is None
    assert market.raw_data["source_ref"] == f"sha256:{'a' * 64}"
    assert [row["keyword"] for row in market.raw_data["keyword_candidates"]] == [
        "small keyword",
        "main keyword",
    ]


def test_reverse_keyword_evidence_preserves_unknowns_instead_of_zeroes():
    market = market_from_reverse_keyword_result(
        asin="B00Q7OAN50",
        marketplace="US",
        result_data={"row_count": 0, "keyword_rows": []},
    )

    assert market.main_keyword is None
    assert market.search_volume_monthly is None
    assert market.monthly_purchases is None
    assert market.purchase_rate is None
    assert market.competing_listings is None
    assert market.raw_data["selected_keyword_row"] is None


def test_reverse_keyword_evidence_rejects_invalid_numeric_metrics():
    market = market_from_reverse_keyword_result(
        asin="B00Q7OAN50",
        marketplace="US",
        result_data={
            "keyword_rows": [{
                "keyword": "unsafe",
                "search_volume": float("nan"),
                "purchase_volume": -1,
                "purchase_rate": True,
                "competing_products": "100",
            }]
        },
    )

    assert market.main_keyword == "unsafe"
    assert market.search_volume_monthly is None
    assert market.monthly_purchases is None
    assert market.purchase_rate is None
    assert market.competing_listings is None

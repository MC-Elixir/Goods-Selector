from types import SimpleNamespace

from agent import history


def test_hide_result_removes_only_the_library_record(tmp_path, monkeypatch):
    export = tmp_path / "candidates_hidden.json"
    export.write_text('[{"product":{"asin":"BHIDDEN","title":"hidden item"},"suppliers":[]}]', encoding="utf-8")
    hidden_path = tmp_path / "hidden.json"
    monkeypatch.setattr(history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(history, "_HIDDEN_FILE", hidden_path)
    monkeypatch.setattr(history, "_load_saved", lambda: {})
    monkeypatch.setattr(history, "load_supplier_reviews", lambda: {})

    result = history.hide_result("hidden:BHIDDEN")

    assert result["hidden"] is True
    assert history.list_results(run_id="hidden")["count"] == 0
    assert export.exists()
    assert "BHIDDEN" in export.read_text(encoding="utf-8")


def test_list_results_includes_review_specs_and_supplier_candidates(tmp_path, monkeypatch):
    export = tmp_path / "candidates_review.json"
    export.write_text(
        """
        [
          {
            "product": {
              "asin": "BTEST123",
              "marketplace": "US",
              "title": "24 oz stainless steel water bottle with straw",
              "brand": "Acme",
              "category": "Sports & Outdoors",
              "price": 24.99,
              "main_image_url": "https://example.com/a.jpg"
            },
            "profit": {
              "selling_price": 24.99,
              "purchase_cost": 3.2,
              "profit_margin": 0.42,
              "net_profit": 6.2
            },
            "score": {
              "total_score": 82.5,
              "profit_score": 0.8,
              "demand_score": 0.7,
              "competition_score": 0.6,
              "passed_hard_filter": true,
              "rejection_reasons": []
            },
            "market": {
              "bsr": 1200,
              "est_monthly_sales": 540,
              "main_keyword": "water bottle",
              "search_volume_monthly": 4200,
              "monthly_purchases": 280,
              "purchase_rate": 6.67
            },
            "suppliers": [
              {
                "alibaba_offer_id": "123456789",
                "supplier_name": "Ningbo Bottle Factory",
                "offer_url": "https://detail.1688.com/offer/123456789.html",
                "offer_image_url": "https://example.com/b.jpg",
                "base_price_cny": 22.5,
                "moq": 100,
                "monthly_sales": 1200,
                "repeat_buyer_rate": 0.31,
                "is_factory": true,
                "title_cn": "304不锈钢 700ml 带吸管保温杯",
                "match_quality_score": 0.88,
                "image_similarity": 0.91,
                "match_verification_method": "heuristic",
                "raw_data": {
                  "source": "alibaba_pifatuan",
                  "supplier_quality_score": 0.82,
                  "supplier_business_score": 0.91,
                  "supplier_candidate_score": 0.87,
                  "supplier_rank_score": 0.89,
                  "supplier_profit_margin": 0.42,
                  "supplier_net_profit": 6.2,
                  "supplier_purchase_cost": 3.2,
                  "supplier_profit_score": 1.0,
                  "visual_match": {
                    "score": 0.91,
                    "source": "image_similarity"
                  },
                  "target_spec": {
                    "category": "保温杯",
                    "material": "不锈钢",
                    "capacity_ml": 709.8,
                    "pack_count": 2,
                    "features": ["吸管"]
                  },
                  "spec_match": {
                    "score": 0.86,
                    "matched": ["material", "capacity", "features"],
                    "missing": ["dimensions"],
                    "conflicts": []
                  }
                }
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(history, "_load_saved", lambda: {})
    monkeypatch.setattr(history, "load_supplier_reviews", lambda: {
        "review:BTEST123:123456789": {"status": "accepted", "note": ""}
    })

    data = history.list_results(run_id="review")

    assert data["count"] == 1
    item = data["items"][0]
    assert item["review_status"] == "needs_specs"
    assert item["review_summary"] == {
        "matched_count": 3,
        "missing_count": 1,
        "conflict_count": 0,
        "needs_manual_check": True,
        "top_issues": ["dimensions"],
    }
    assert item["amazon_url"] == "https://www.amazon.com/dp/BTEST123"
    assert item["decision_brief"]["action"] == "manual_verify"
    assert item["decision_brief"]["confidence"] == "medium"
    assert {"code": "market_data_rich", "value": {"est_monthly_sales": 540}} in item["decision_brief"]["positives"]
    assert {"code": "supplier_evidence", "value": "alibaba_pifatuan"} in item["decision_brief"]["positives"]
    assert {"code": "spec_match", "value": 0.86} in item["decision_brief"]["positives"]
    assert {"code": "missing:dimensions", "value": None} in item["decision_brief"]["risks"]
    assert "verify_specs" in item["decision_brief"]["next_steps"]
    assert item["product_spec"]["material"] == "不锈钢"
    assert item["product_spec"]["capacity_ml"] == 709.8
    assert item["product_spec"]["features"] == ["吸管"]
    assert item["top_supplier_spec"]["material"] == "不锈钢"
    assert item["profit_breakdown"]["purchase_cost"] == 3.2
    assert item["profit_breakdown"]["profit_margin"] == 0.42
    assert item["score_breakdown"]["profit_score"] == 0.8
    assert item["score_breakdown"]["total_score"] == 82.5
    assert item["rejection_reasons"] == []
    assert item["market"]["est_monthly_sales"] == 540
    assert item["market"]["search_volume_monthly"] == 4200
    assert item["market"]["main_keyword"] == "water bottle"
    assert item["visual_similarity"] == 0.91
    assert item["visual_match"]["score"] == 0.91
    assert item["supplier_candidates"][0]["rank"] == 1
    assert item["supplier_candidates"][0]["review_key"] == "review:BTEST123:123456789"
    assert item["supplier_candidates"][0]["review_status"] == "accepted"
    assert item["supplier_review_summary"]["accepted"] == 1
    assert item["supplier_candidates"][0]["visual_similarity"] == 0.91
    assert item["supplier_candidates"][0]["supplier_quality_score"] == 0.82
    assert item["supplier_candidates"][0]["supplier_business_score"] == 0.91
    assert item["supplier_candidates"][0]["candidate_score"] == 0.87
    assert item["supplier_candidates"][0]["rank_score"] == 0.89
    assert item["supplier_candidates"][0]["profit_margin"] == 0.42
    assert item["supplier_candidates"][0]["net_profit"] == 6.2
    assert item["supplier_candidates"][0]["purchase_cost_usd"] == 3.2
    assert item["supplier_candidates"][0]["profit_score"] == 1.0
    assert item["supplier_candidates"][0]["sourcing_source"] == "alibaba_pifatuan"
    assert item["supplier_candidates"][0]["visual_match"]["source"] == "image_similarity"
    assert item["supplier_candidates"][0]["spec_match"]["score"] == 0.86
    assert item["supplier_candidates"][0]["supplier_spec"]["capacity_ml"] == 700.0
    comparison = {row["match_key"]: row for row in item["spec_comparison"]}
    assert comparison["material"]["status"] == "matched"
    assert comparison["capacity"]["target"] == 709.8
    assert comparison["capacity"]["supplier"] == 700.0
    assert comparison["dimensions"]["status"] == "missing"


def test_list_results_marks_conflict_for_manual_review(tmp_path, monkeypatch):
    export = tmp_path / "candidates_conflict.json"
    export.write_text(
        """
        [
          {
            "product": {"asin": "BCONFLICT", "title": "2 pack cotton pillow"},
            "score": {"total_score": 44, "passed_hard_filter": false},
            "suppliers": [
              {
                "alibaba_offer_id": "987654321",
                "supplier_name": "Supplier",
                "title_cn": "单个记忆棉枕头",
                "raw_data": {
                  "spec_match": {
                    "score": 0.41,
                    "matched": ["category"],
                    "missing": [],
                    "conflicts": ["material", "pack_count"]
                  }
                }
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(history, "_load_saved", lambda: {})
    monkeypatch.setattr(history, "load_supplier_reviews", lambda: {})

    item = history.list_results(run_id="conflict")["items"][0]

    assert item["review_status"] == "conflict"
    assert item["review_summary"]["needs_manual_check"] is True
    assert item["review_summary"]["top_issues"] == ["material", "pack_count"]
    assert item["decision_brief"]["action"] == "manual_verify"
    assert {"code": "conflict:material", "value": None} in item["decision_brief"]["risks"]
    assert {"code": "conflict:pack_count", "value": None} in item["decision_brief"]["risks"]


def test_list_accepted_supplier_shortlist_exports_only_accepted(tmp_path, monkeypatch):
    export = tmp_path / "candidates_reviewed.json"
    export.write_text(
        """
        [
          {
            "product": {"asin": "BKEEP", "title": "steel bottle", "price": 29.99},
            "profit": {"profit_margin": 0.42, "net_profit": 6.2},
            "score": {"total_score": 82.5},
            "suppliers": [
              {
                "alibaba_offer_id": "111",
                "supplier_name": "Accepted Factory",
                "title_cn": "304不锈钢保温杯",
                "offer_url": "https://detail.1688.com/offer/111.html",
                "base_price_cny": 20,
                "moq": 10,
                "monthly_sales": 1200,
                "repeat_buyer_rate": 0.31,
                "is_factory": true,
                "match_quality_score": 0.88,
                "image_similarity": 0.91,
                "raw_data": {
                  "source": "alibaba_pifatuan",
                  "supplier_quality_score": 0.82,
                  "supplier_business_score": 0.91,
                  "supplier_candidate_score": 0.87,
                  "spec_match": {
                    "score": 0.86,
                    "missing": ["dimensions"],
                    "conflicts": []
                  }
                }
              },
              {
                "alibaba_offer_id": "222",
                "supplier_name": "Pending Factory",
                "title_cn": "待审核",
                "base_price_cny": 18
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(history, "load_supplier_reviews", lambda: {
        "reviewed:BKEEP:111": {"status": "accepted", "note": "sample ok", "reviewed_at": "2026-07-01T00:00:00Z"},
        "reviewed:BKEEP:222": {"status": "rejected", "note": "", "reviewed_at": "2026-07-01T00:00:00Z"},
    })

    data = history.list_accepted_supplier_shortlist(run_id="reviewed")

    assert data["count"] == 1
    item = data["items"][0]
    assert item["asin"] == "BKEEP"
    assert item["supplier"] == "Accepted Factory"
    assert item["offer_url"].endswith("/111.html")
    assert item["match_quality"] == 0.88
    assert item["visual_similarity"] == 0.91
    assert item["candidate_score"] == 0.87
    assert item["sourcing_source"] == "alibaba_pifatuan"
    assert item["supplier_quality_score"] == 0.82
    assert item["supplier_business_score"] == 0.91
    assert item["monthly_sales"] == 1200
    assert item["repeat_buyer_rate"] == 0.31
    assert item["is_factory"] is True
    assert item["spec_missing"] == "dimensions"
    assert item["note"] == "sample ok"


def test_audit_export_reports_sourcing_quality(tmp_path):
    export = tmp_path / "candidates_audit.json"
    export.write_text(
        """
        [
          {
            "product": {"asin": "BREADY", "title": "24 oz stainless bottle"},
            "profit": {"profit_margin": 0.38},
            "score": {"total_score": 86, "passed_hard_filter": true},
            "market": {
              "est_monthly_sales": 540,
              "main_keyword": "water bottle"
            },
            "suppliers": [
              {
                "alibaba_offer_id": "111111111",
                "supplier_name": "Factory A",
                "base_price_cny": 20,
                "match_quality_score": 0.91,
                "raw_data": {
                  "spec_match": {
                    "score": 0.88,
                    "matched": ["material", "capacity"],
                    "missing": [],
                    "conflicts": []
                  }
                }
              }
            ]
          },
          {
            "product": {"asin": "BCONFLICT", "title": "2 pack pillow"},
            "profit": {"profit_margin": 0.18},
            "score": {"total_score": 42, "passed_hard_filter": false},
            "suppliers": [
              {
                "alibaba_offer_id": "222222222",
                "supplier_name": "Factory B",
                "base_price_cny": 99999,
                "match_quality_score": 0.43,
                "raw_data": {
                  "spec_match": {
                    "score": 0.44,
                    "matched": ["category"],
                    "missing": ["dimensions"],
                    "conflicts": ["pack_count"]
                  }
                }
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )

    audit = history.audit_export(export)

    assert audit["candidate_count"] == 2
    assert audit["real_supplier_count"] == 2
    assert audit["supplier_evidence_count"] == 2
    assert audit["supplier_evidence_rate"] == 1.0
    assert audit["supplier_evidence_ready"] is True
    assert audit["supplier_source_counts"] == {"unknown": 2}
    assert audit["review_ready_count"] == 1
    assert audit["review_manual_count"] == 1
    assert audit["review_conflict_count"] == 1
    assert audit["review_ready_rate"] == 0.5
    assert audit["market_data_count"] == 1
    assert audit["market_data_rate"] == 0.5
    assert audit["market_data_ready"] is False
    assert audit["market_data_rich_count"] == 1
    assert audit["market_data_rich_rate"] == 0.5
    assert audit["market_data_rich_ready"] is False
    assert audit["avg_spec_match_score"] == 0.66
    assert audit["avg_match_quality_score"] == 0.67
    assert audit["total_spec_issues"] == 2
    assert audit["sourcing_quality"] == "conflict_review"
    assert audit["suspicious_price_count"] == 1


def test_list_export_runs_includes_compact_quality_metrics(tmp_path, monkeypatch):
    export = tmp_path / "candidates_runquality.json"
    export.write_text(
        """
        [
          {
            "product": {"asin": "BREADY"},
            "score": {"total_score": 90, "passed_hard_filter": true},
            "suppliers": [
              {
                "alibaba_offer_id": "333333333",
                "supplier_name": "Factory C",
                "raw_data": {
                  "spec_match": {
                    "score": 0.9,
                    "matched": ["category"],
                    "missing": [],
                    "conflicts": []
                  }
                }
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(history, "settings", SimpleNamespace(export_dir=tmp_path))

    runs = history.list_export_runs()

    assert runs[0]["id"] == "runquality"
    assert runs[0]["sourcing_quality"] == "ready"
    assert runs[0]["review_ready_count"] == 1
    assert runs[0]["review_manual_count"] == 0
    assert runs[0]["supplier_evidence_count"] == 1
    assert runs[0]["supplier_evidence_rate"] == 1.0
    assert runs[0]["market_data_rich_count"] == 0
    assert runs[0]["market_data_rich_rate"] == 0.0
    assert runs[0]["avg_spec_match_score"] == 0.9

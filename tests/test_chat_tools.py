from types import SimpleNamespace
from contextlib import contextmanager

import agent.chat_tools as chat_tools
from config.settings import settings
from db.models import MarketAnalysis, Product, ProfitSnapshot, Score, Supplier


def test_chat_tools_reads_candidate_detail_from_exports(tmp_path, monkeypatch):
    export = tmp_path / "candidates_chat.json"
    export.write_text(
        """
        [
          {
            "product": {
              "asin": "BCHAT12345",
              "marketplace": "US",
              "title": "Insulated water bottle",
              "price": 25.99
            },
            "profit": {
              "profit_margin": 0.31,
              "net_profit": 5.2,
              "purchase_cost": 3.1
            },
            "score": {
              "total_score": 76.5,
              "passed_hard_filter": true,
              "rejection_reasons": []
            },
            "market": {
              "est_monthly_sales": 900,
              "search_volume_monthly": 5200
            },
            "suppliers": [
              {
                "alibaba_offer_id": "1234567890",
                "supplier_name": "Bottle Factory",
                "base_price_cny": 22.5,
                "moq": 100,
                "match_quality_score": 0.84,
                "raw_data": {"source": "alibaba_playwright"}
              }
            ]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(chat_tools.history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(chat_tools.history, "_load_saved", lambda: {})
    monkeypatch.setattr(chat_tools.history, "load_supplier_reviews", lambda: {})

    detail = chat_tools.get_candidate_detail("BCHAT12345", run_id="chat")

    assert detail["asin"] == "BCHAT12345"
    assert detail["margin"] == 0.31
    assert detail["score"] == 76.5
    assert detail["supplier"] == "Bottle Factory"


def test_chat_answer_returns_data_insufficient_without_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_tools.history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(chat_tools.history, "_load_saved", lambda: {})
    monkeypatch.setattr(chat_tools.history, "load_supplier_reviews", lambda: {})

    response = chat_tools.answer_chat("请推荐一个产品", run_id="missing")

    assert "数据不足" in response["answer"]
    assert "结论：需要人工复核" in response["answer"]
    assert response["used_tools"]


def test_chat_answer_uses_minimax_after_tool_context(monkeypatch):
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="结论：暂缓\n依据：来自工具数据"))]
            )

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    def fake_openai(**kwargs):
        calls["client_kwargs"] = kwargs
        return FakeClient()

    monkeypatch.setattr(settings, "ppio_api_key", "ppio-key")
    monkeypatch.setattr(settings, "ppio_api_base", "https://api.ppio.com/openai")
    monkeypatch.setattr(settings, "ppio_text_model", "minimax/minimax-m3")
    monkeypatch.setattr(chat_tools._openai, "OpenAI", fake_openai)
    monkeypatch.setattr(chat_tools, "get_candidate_detail", lambda asin, run_id=None: {
        "asin": asin,
        "title": "Water bottle",
        "supplier": "Bottle Factory",
        "margin": 0.31,
        "score": 76,
        "passed": True,
        "market": {"search_volume_monthly": 5200},
        "product_spec": {"dimensions_cm": "8x8x26cm", "risk_flags": []},
    })

    response = chat_tools.answer_chat("分析 B0LLM0001", selected_asin="B0LLM0001", use_llm=True)

    assert response["answer"].startswith("结论：暂缓")
    assert response["model"] == "minimax/minimax-m3"
    assert response["used_tools"] == ["get_candidate_detail", "llm:minimax/minimax-m3"]
    assert calls["client_kwargs"]["timeout"] == 30.0
    assert calls["model"] == "minimax/minimax-m3"
    prompt = calls["messages"][0]["content"]
    assert "B0LLM0001" in prompt
    assert "Water bottle" in prompt


def test_chat_answer_does_not_call_llm_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_tools.history, "settings", SimpleNamespace(export_dir=tmp_path))
    monkeypatch.setattr(chat_tools.history, "_load_saved", lambda: {})
    monkeypatch.setattr(chat_tools.history, "load_supplier_reviews", lambda: {})
    monkeypatch.setattr(settings, "ppio_api_key", "ppio-key")

    def fail_openai(**kwargs):
        raise AssertionError("LLM must not be called without tool data")

    monkeypatch.setattr(chat_tools._openai, "OpenAI", fail_openai)

    response = chat_tools.answer_chat("随便推荐", run_id="missing", use_llm=True)

    assert "数据不足" in response["answer"]
    assert "llm" not in " ".join(response["used_tools"])


def test_chat_tools_fallback_to_db_candidate_detail(monkeypatch):
    product = Product(
        id=1,
        asin="BDBCHAT123",
        marketplace="US",
        category="Home & Kitchen",
        title="Desk lamp",
        brand="Generic",
        price=29.99,
        length_cm=20,
        width_cm=12,
        height_cm=8,
    )
    supplier = SimpleNamespace(
        id=2,
        product_id=1,
        alibaba_offer_id="offer-1",
        supplier_name="Lamp Factory",
        offer_url="https://detail.1688.com/offer/1.html",
        base_price_cny=18.5,
        moq=50,
        product_dimensions_cm="20x12x8cm",
        material="铝合金",
        match_quality_score=0.82,
    )
    profit = ProfitSnapshot(
        product_id=1,
        supplier_id=2,
        selling_price=29.99,
        purchase_cost=2.6,
        total_cost=18.0,
        net_profit=6.2,
        profit_margin=0.27,
    )
    score = Score(
        product_id=1,
        profit_score=0.8,
        demand_score=0.6,
        competition_score=0.55,
        supply_score=0.7,
        logistics_score=0.75,
        risk_score=0.45,
        total_score=72.0,
        passed_hard_filter=False,
        rejection_reasons=["patent_claim"],
    )
    market = MarketAnalysis(
        product_id=1,
        main_keyword="desk lamp",
        search_volume_monthly=4000,
        competing_listings=900,
        top10_revenue_share=0.52,
    )

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def order_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    class Session:
        def query(self, model):
            rows = {
                Product: [product],
                Supplier: [supplier],
                ProfitSnapshot: [profit],
                Score: [score],
                MarketAnalysis: [market],
            }.get(model, [])
            return Query(rows)

    @contextmanager
    def fake_scope():
        yield Session()

    monkeypatch.setattr(chat_tools.history, "list_results", lambda **kwargs: {"items": []})
    monkeypatch.setattr(chat_tools, "session_scope", fake_scope)

    detail = chat_tools.get_candidate_detail("BDBCHAT123")

    assert detail["asin"] == "BDBCHAT123"
    assert detail["supplier"] == "Lamp Factory"
    assert detail["margin"] == 0.27
    assert detail["score"] == 72.0
    assert detail["market"]["search_volume_monthly"] == 4000
    assert "patent_claim" in detail["rejection_reasons"]


def test_chat_answer_explains_rejected_or_paused_candidate(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_candidate_detail", lambda asin, run_id=None: {
        "asin": asin,
        "title": "Desk lamp",
        "supplier": "Lamp Factory",
        "offer_url": "https://detail.1688.com/offer/1.html",
        "margin": 0.18,
        "net_profit": 3.2,
        "score": 62,
        "passed": False,
        "moq": 600,
        "rejection_reasons": ["margin_too_low", "moq_exceeded", "patent_claim"],
        "market": {"search_volume_monthly": 4000, "competing_listings": 900},
        "product_spec": {"dimensions_cm": "20x12x8cm", "risk_flags": ["patent_claim"]},
    })

    response = chat_tools.answer_chat("为什么淘汰 BWHYDROP1", selected_asin="BWHYDROP1")

    assert "结论：淘汰" in response["answer"]
    assert "决策解释：" in response["answer"]
    assert "为什么淘汰" in response["answer"]
    assert "margin_too_low" in response["answer"]


def test_chat_answer_compares_multiple_asins(monkeypatch):
    monkeypatch.setattr(chat_tools, "compare_candidates", lambda asins, run_id=None: [
        {
            "asin": "B0COMP0001",
            "title": "Desk lamp A",
            "supplier": "Factory A",
            "offer_url": "https://detail.1688.com/offer/a.html",
            "margin": 0.31,
            "net_profit": 6.1,
            "score": 78,
            "passed": True,
            "moq": 50,
            "market": {"search_volume_monthly": 5000, "competing_listings": 800},
            "product_spec": {"dimensions_cm": "20x12x8cm", "risk_flags": []},
        },
        {
            "asin": "B0COMP0002",
            "title": "Desk lamp B",
            "supplier": "",
            "margin": 0.18,
            "net_profit": 2.1,
            "score": 61,
            "passed": False,
            "moq": None,
            "rejection_reasons": ["supplier_missing"],
            "market": {"search_volume_monthly": 4500, "competing_listings": 1600},
            "product_spec": {"risk_flags": ["patent_claim"]},
        },
    ])

    response = chat_tools.answer_chat("比较 B0COMP0001 和 B0COMP0002")

    assert "compare_candidates" in response["used_tools"]
    assert "候选对比：" in response["answer"]
    assert "B0COMP0001" in response["answer"]
    assert "B0COMP0002" in response["answer"]
    assert "优先看 B0COMP0001" in response["answer"]


def test_generate_decision_report_marks_pause_when_evidence_is_incomplete(monkeypatch):
    monkeypatch.setattr(chat_tools, "get_candidate_detail", lambda asin, run_id=None: {
        "asin": asin,
        "title": "Water bottle",
        "supplier": "Bottle Factory",
        "offer_url": "https://detail.1688.com/offer/1.html",
        "margin": 0.24,
        "net_profit": 4.8,
        "score": 69,
        "passed": True,
        "moq": 100,
        "market": {"search_volume_monthly": 5200, "competing_listings": 1200},
        "product_spec": {"dimensions_cm": "8x8x26cm", "risk_flags": ["checked_clear"]},
    })

    report = chat_tools.generate_decision_report("B0PAUSE001")

    assert report["conclusion"] == "暂缓"
    assert "为什么暂缓" in report["report"]
    assert "利润" in report["report"]
    assert "风险" in report["report"]

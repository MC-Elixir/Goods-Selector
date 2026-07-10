from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.models import Base, Product, ProfitSnapshot, RunLog, Score, Supplier
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.orchestrator import PipelineTimeout, run_pipeline


def _temp_session_scope(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runtime_controls.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    @contextmanager
    def temp_session_scope():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return temp_session_scope


def test_run_pipeline_emits_per_asin_heartbeat(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    products = [
        ProductDTO(asin="B0HEART001", marketplace="US", title="Heartbeat one", price=25.0),
        ProductDTO(asin="B0HEART002", marketplace="US", title="Heartbeat two", price=26.0),
    ]
    events: list[dict] = []

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: products)
    monkeypatch.setattr(
        "matchers.match_suppliers",
        lambda product: [SupplierDTO(alibaba_offer_id=f"offer-{product.asin}", base_price_cny=20.0)],
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, supplier: SimpleNamespace(
            selling_price=product.price,
            purchase_cost=3.0,
            shipping_cost=1.0,
            fba_fee=2.0,
            commission=3.0,
            ad_cost=1.0,
            return_loss=0.5,
            exchange_loss=0.2,
            other_costs=0.0,
            total_cost=10.7,
            net_profit=14.3,
            profit_margin=0.4,
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(
            profit_score=0.8,
            demand_score=0.7,
            competition_score=0.6,
            supply_score=0.8,
            logistics_score=0.7,
            risk_score=0.9,
            total_score=78.0,
            passed_hard_filter=True,
            rejection_reasons=[],
        ),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: records)

    run_pipeline(
        "Sports & Outdoors",
        limit=2,
        marketplace="US",
        export=False,
        progress_callback=events.append,
    )

    match_events = [event for event in events if event.get("stage") == "match" and event.get("asin")]
    assert [(event["asin"], event["index"], event["total"]) for event in match_events] == [
        ("B0HEART001", 1, 2),
        ("B0HEART002", 2, 2),
    ]


def test_run_pipeline_stage_timeout_fails_run_log(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    product = ProductDTO(asin="B0TIMEOUT1", marketplace="US", title="Slow match", price=25.0)

    def slow_match(product):
        raise TimeoutError("match supplier timed out after 0.01s")

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("matchers.match_suppliers", slow_match)

    with pytest.raises(PipelineTimeout):
        run_pipeline(
            "Sports & Outdoors",
            limit=1,
            marketplace="US",
            export=False,
            stage_timeouts={"match": 0.01},
        )

    with temp_session_scope() as session:
        run = session.query(RunLog).one()
        assert run.status == "failed"
        assert "match" in (run.error_message or "")
        assert run.products_crawled == 1


def test_run_pipeline_passes_cancel_check_to_matcher_when_supported(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    product = ProductDTO(asin="B0CANCEL1", marketplace="US", title="Cancelable match", price=25.0)
    received_cancel_check = []

    def fake_match(product, *, cancel_check=None):
        received_cancel_check.append(cancel_check)
        assert cancel_check is not None
        assert cancel_check() is False
        return [SupplierDTO(alibaba_offer_id="offer-cancel", base_price_cny=20.0)]

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("matchers.match_suppliers", fake_match)
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, supplier: SimpleNamespace(
            selling_price=product.price,
            purchase_cost=3.0,
            shipping_cost=1.0,
            fba_fee=2.0,
            commission=3.0,
            ad_cost=1.0,
            return_loss=0.5,
            exchange_loss=0.2,
            other_costs=0.0,
            total_cost=10.7,
            net_profit=14.3,
            profit_margin=0.4,
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(
            profit_score=0.8,
            demand_score=0.7,
            competition_score=0.6,
            supply_score=0.8,
            logistics_score=0.7,
            risk_score=0.9,
            total_score=78.0,
            passed_hard_filter=True,
            rejection_reasons=[],
        ),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: records)

    run_pipeline(
        "Sports & Outdoors",
        limit=1,
        marketplace="US",
        export=False,
        cancel_check=lambda: False,
    )

    assert received_cancel_check and received_cancel_check[0] is not None


def test_run_pipeline_persists_products_and_suppliers_during_run(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    product = ProductDTO(
        asin="B0PERSIST1",
        marketplace="US",
        title="Persisted product",
        category="Sports & Outdoors",
        price=25.0,
        bsr_rank=12,
        raw_data={"source_rank": 1},
    )
    supplier = SupplierDTO(
        alibaba_offer_id="1688persist1",
        supplier_name="Persist Factory",
        offer_url="https://detail.1688.com/offer/1688persist1.html",
        base_price_cny=18.0,
        moq=50,
        raw_data={"source": "unit-test"},
    )

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("matchers.match_suppliers", lambda product: [supplier])
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, supplier: SimpleNamespace(
            selling_price=25.0,
            purchase_cost=3.0,
            shipping_cost=1.0,
            fba_fee=2.0,
            commission=3.0,
            ad_cost=1.0,
            return_loss=0.5,
            exchange_loss=0.2,
            other_costs=0.0,
            total_cost=10.7,
            net_profit=14.3,
            profit_margin=0.4,
        ),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(
            profit_score=0.8,
            demand_score=0.7,
            competition_score=0.6,
            supply_score=0.8,
            logistics_score=0.7,
            risk_score=0.9,
            total_score=78.0,
            passed_hard_filter=True,
            rejection_reasons=[],
        ),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: records)

    run_pipeline("Sports & Outdoors", limit=1, marketplace="US", export=False)

    with temp_session_scope() as session:
        saved_product = session.query(Product).filter_by(asin="B0PERSIST1", marketplace="US").one()
        saved_supplier = session.query(Supplier).filter_by(product_id=saved_product.id).one()
        saved_profit = session.query(ProfitSnapshot).filter_by(product_id=saved_product.id).one()
        saved_score = session.query(Score).filter_by(product_id=saved_product.id).one()
        assert saved_product.title == "Persisted product"
        assert saved_product.raw_data["source_rank"] == 1
        assert saved_supplier.alibaba_offer_id == "1688persist1"
        assert saved_supplier.base_price_cny == 18.0
        assert saved_profit.net_profit == 14.3
        assert saved_score.total_score == 78.0

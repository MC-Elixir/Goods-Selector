from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.models import Base, RunLog
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.orchestrator import run_pipeline


def test_run_pipeline_caps_seller_sprite_browser_market_calls(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pipeline.db'}",
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

    products = [
        ProductDTO(
            asin=f"ASIN{i}",
            marketplace="US",
            title=f"Test product {i}",
            price=20.0,
        )
        for i in range(5)
    ]
    supplier = SupplierDTO(
        alibaba_offer_id="offer-1",
        base_price_cny=30.0,
        monthly_sales=100,
    )
    market_calls: list[tuple[str, str]] = []

    class FakeBrowserDependencies:
        browser_enabled = True
        profile = object()
        session_factory = object()

        def __init__(self, **_kwargs):
            pass

    def fake_browser_export(asin, *, sourcing_run_id=None, dependencies=None):
        market_calls.append((asin, "US"))
        return SimpleNamespace(
            status="SUCCESS",
            error_code=None,
            data={
                "row_count": 1,
                "file_sha256": "a" * 64,
                "manifest_id": f"manifest-{asin}",
                "keyword_rows": [{"keyword": "test", "search_volume": 100}],
            },
        )

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 2)
    monkeypatch.setattr(
        "crawlers.amazon_bsr.crawl_best_sellers",
        lambda category, limit, marketplace: products,
    )
    monkeypatch.setattr("matchers.match_suppliers", lambda product: [supplier])
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, best_supplier: SimpleNamespace(net_profit=10.0, profit_margin=0.4),
    )
    monkeypatch.setattr(
        "agent.sellersprite_service.SellerSpriteDependencies",
        FakeBrowserDependencies,
    )
    monkeypatch.setattr(
        "agent.sellersprite_service.run_reverse_keyword_export",
        fake_browser_export,
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(total_score=80.0, passed_hard_filter=True),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: records)

    run_id = run_pipeline("Home & Kitchen", limit=5, marketplace="US", export=False)

    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.api_calls["sellersprite_browser_exports"] == 2
        assert run.api_calls["mjjl_skipped_cap"] == 3

    assert market_calls == [("ASIN0", "US"), ("ASIN1", "US")]


def test_run_pipeline_zero_market_cap_does_not_create_seller_sprite_client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pipeline_zero.db'}",
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

    products = [
        ProductDTO(asin="ASIN0", marketplace="US", title="Test product 0", price=20.0),
        ProductDTO(asin="ASIN1", marketplace="US", title="Test product 1", price=20.0),
    ]
    supplier = SupplierDTO(alibaba_offer_id="offer-1", base_price_cny=30.0)

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr(
        "crawlers.amazon_bsr.crawl_best_sellers",
        lambda category, limit, marketplace: products,
    )
    monkeypatch.setattr("matchers.match_suppliers", lambda product: [supplier])
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, best_supplier: SimpleNamespace(net_profit=10.0, profit_margin=0.4),
    )
    monkeypatch.setattr(
        "analyzers.maijiajingling.MaijiajinglingClient",
        lambda: (_ for _ in ()).throw(AssertionError("SellerSprite client should not be created")),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(total_score=80.0, passed_hard_filter=True),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: records)

    run_id = run_pipeline("Home & Kitchen", limit=2, marketplace="US", export=False)

    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.api_calls.get("mjjl", 0) == 0
        assert run.api_calls["mjjl_skipped_cap"] == 2

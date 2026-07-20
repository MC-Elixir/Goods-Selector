from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from crawlers.amazon_bsr import ProductDTO
from crawlers.amazon_search import AmazonSearchFailure, SearchPageDiagnostic
from config.settings import settings
from db.models import Base, ExecutionNode, RunLog
from pipeline.orchestrator import run_pipeline


def test_keyword_source_mode_uses_search_crawler_not_category_crawler(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'source_mode.db'}",
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
            asin="B000000123",
            marketplace="US",
            title="Water bottle",
            price=24.99,
            raw_data={
                "source_mode": "keyword",
                "source_keyword": "水杯",
                "keyword_normalized": "water bottle",
                "source_rank": 1,
            },
        )
    ]
    calls: list[tuple[str, str, int]] = []

    def fail_category(*args, **kwargs):
        raise AssertionError("category crawler must not run for keyword mode")

    def fake_search(keyword, marketplace="US", limit=10):
        calls.append((keyword, marketplace, limit))
        return products

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", fail_category)
    monkeypatch.setattr("crawlers.amazon_search.search_amazon_products", fake_search)
    monkeypatch.setattr("matchers.match_suppliers", lambda product: [])
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: [])

    run_id = run_pipeline(
        category="Home & Kitchen",
        keyword="水杯",
        source_mode="keyword",
        limit=10,
        marketplace="US",
        export=False,
    )

    assert calls == [("水杯", "US", 10)]
    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.category is None
        assert run.marketplace == "US"
        assert run.api_calls["source_mode"] == "keyword"
        assert run.api_calls["source_query"] == "水杯"
        assert run.api_calls["keyword_normalized"] == "water bottle"


def test_category_source_mode_keeps_existing_bsr_crawler(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'category_mode.db'}",
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

    products = [ProductDTO(asin="B000000999", marketplace="US", title="Toy", price=19.99)]
    calls: list[tuple[str, int, str]] = []

    def fake_category(category, limit, marketplace):
        calls.append((category, limit, marketplace))
        return products

    def fail_search(*args, **kwargs):
        raise AssertionError("keyword crawler must not run for category mode")

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", fake_category)
    monkeypatch.setattr("crawlers.amazon_search.search_amazon_products", fail_search)
    monkeypatch.setattr("matchers.match_suppliers", lambda product: [])
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n: [])

    run_id = run_pipeline(
        category="Home & Kitchen",
        source_mode="category",
        limit=5,
        marketplace="US",
        export=False,
    )

    assert calls == [("Home & Kitchen", 5, "US")]
    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.category == "Home & Kitchen"
        assert run.api_calls["source_mode"] == "category"
        assert run.api_calls["source_query"] == "Home & Kitchen"


def test_keyword_captcha_becomes_human_required_with_sanitized_diagnostics(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostic.db'}", future=True)
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

    diagnostic = SearchPageDiagnostic(
        kind="captcha",
        action="Refresh Amazon cookies and retry after completing the robot check.",
        page_title="Robot Check",
        result_cards=0,
        product_links=0,
        url="https://www.amazon.com/s?k=patio+umbrella",
    )
    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(
        "crawlers.amazon_search.search_amazon_products",
        lambda *args, **kwargs: (_ for _ in ()).throw(AmazonSearchFailure("patio umbrella", diagnostic)),
    )

    run_id = run_pipeline(
        category="",
        keyword="patio umbrella",
        source_mode="keyword",
        limit=10,
        marketplace="US",
        export=False,
    )

    with temp_session_scope() as session:
        run = session.query(RunLog).one()
        assert run.id == run_id
        assert run.status == "human_required"
        assert run.api_calls["amazon_search"]["kind"] == "captcha"
        assert "html" not in run.api_calls["amazon_search"]
        node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_type="run", stage="source_discovery"
        ).one()
        assert node.status == "human_required"
        assert node.human_action_required["error_code"] == "HUMAN_ACTION_REQUIRED"

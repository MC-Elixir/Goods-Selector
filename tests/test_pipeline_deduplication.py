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


def _temp_session_scope(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dedupe.db'}",
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


def test_run_pipeline_deduplicates_source_products_by_asin(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    products = [
        ProductDTO(asin="B0DUP00001", marketplace="US", title="Duplicate later", price=22.0, bsr_rank=12),
        ProductDTO(asin="B0DUP00001", marketplace="US", title="Duplicate first", price=21.0, bsr_rank=5),
        ProductDTO(asin="B0UNIQUE01", marketplace="US", title="Unique", price=25.0, bsr_rank=9),
    ]
    matched_asins: list[str] = []

    def fake_match(product):
        matched_asins.append(product.asin)
        return [SupplierDTO(alibaba_offer_id=f"78048561758{len(matched_asins)}", base_price_cny=20.0)]

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: products)
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", lambda product, **_kwargs: fake_match(product))
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, supplier: SimpleNamespace(net_profit=10.0, profit_margin=0.4),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(total_score=80.0, passed_hard_filter=True),
    )

    run_id = run_pipeline("Sports & Outdoors", limit=3, marketplace="US", export=False)

    assert matched_asins == ["B0DUP00001", "B0UNIQUE01"]
    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.products_crawled == 2
        assert run.api_calls["amazon_source_raw"] == 3
        assert run.api_calls["amazon_duplicates_removed"] == 1


def test_run_pipeline_deduplicates_suppliers_by_offer_id(monkeypatch, tmp_path):
    temp_session_scope = _temp_session_scope(tmp_path)
    product = ProductDTO(asin="B0SUPDUP01", marketplace="US", title="Outdoor bottle", price=24.0)
    captured_records = []

    def fake_match(product):
        return [
            SupplierDTO(
                alibaba_offer_id="780485617589",
                supplier_name="Lower match",
                base_price_cny=20.0,
                match_quality_score=0.2,
            ),
            SupplierDTO(
                alibaba_offer_id="780485617589",
                supplier_name="Better match",
                base_price_cny=20.0,
                match_quality_score=0.9,
            ),
            SupplierDTO(
                alibaba_offer_id="780485617590",
                supplier_name="Other offer",
                base_price_cny=20.0,
                match_quality_score=0.7,
            ),
        ]

    def fake_rank(records, top_n=None):
        captured_records[:] = records
        return records

    monkeypatch.setattr("pipeline.orchestrator.session_scope", temp_session_scope)
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", lambda product, **_kwargs: fake_match(product))
    monkeypatch.setattr(
        "pipeline.orchestrator.predict_profit",
        lambda product, supplier: SimpleNamespace(net_profit=10.0, profit_margin=0.4),
    )
    monkeypatch.setattr(
        "pipeline.orchestrator.score_product",
        lambda **kwargs: SimpleNamespace(total_score=80.0, passed_hard_filter=True),
    )
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", fake_rank)

    run_id = run_pipeline("Sports & Outdoors", limit=1, marketplace="US", export=False)

    assert run_id
    assert [s.alibaba_offer_id for s in captured_records[0].suppliers] == [
        "780485617589",
        "780485617590",
    ]
    assert captured_records[0].suppliers[0].supplier_name == "Better match"
    with temp_session_scope() as session:
        run = session.get(RunLog, run_id)
        assert run.api_calls["supplier_duplicates_removed"] == 1

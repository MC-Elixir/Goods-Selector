from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import settings
from crawlers.amazon_bsr import ProductDTO
from db.migrate import install_sqlite_foreign_keys
from db.models import (
    Base,
    ExecutionNode,
    ProfitSnapshot,
    RunLog,
    Score,
    Supplier,
)
from execution.repository import ExecutionRepository
from matchers.alibaba_pailitao import SupplierDTO
from pipeline.orchestrator import resume_pipeline, run_pipeline


def _memory_session_scope():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    install_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    @contextmanager
    def session_scope():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return Session, session_scope


def _profit(product, _supplier):
    return SimpleNamespace(
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
        net_profit=float(product.price) - 10.7,
        profit_margin=0.4,
    )


def _score(**_kwargs):
    return SimpleNamespace(
        profit_score=0.8,
        demand_score=0.7,
        competition_score=0.6,
        supply_score=0.8,
        logistics_score=0.7,
        risk_score=0.9,
        total_score=78.0,
        passed_hard_filter=True,
        rejection_reasons=[],
    )


def test_three_asin_resume_retries_only_failed_match(monkeypatch):
    Session, session_scope = _memory_session_scope()
    products = [
        ProductDTO(asin="ASIN-A", marketplace="US", title="Product A", price=25.0),
        ProductDTO(asin="ASIN-B", marketplace="US", title="Product B", price=26.0),
        ProductDTO(asin="ASIN-C", marketplace="US", title="Product C", price=27.0),
    ]
    match_calls: list[str] = []
    fail_b = {"enabled": True}

    def fake_match(product, *, market_keywords=None, cancel_check=None):
        assert cancel_check is None or cancel_check() is False
        assert settings.alibaba_allow_mock_suppliers is False
        assert market_keywords == []
        match_calls.append(product.asin)
        if product.asin == "ASIN-B" and fail_b["enabled"]:
            raise RuntimeError("injected B match failure")
        return [SupplierDTO(
            alibaba_offer_id={"ASIN-A": "1001", "ASIN-B": "1002", "ASIN-C": "1003"}[product.asin],
            supplier_name=f"Factory {product.asin}",
            base_price_cny=20.0,
            moq=20,
            raw_data={"source": "unit-test"},
        )]

    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: products)
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", fake_match)
    monkeypatch.setattr("pipeline.orchestrator.predict_profit", _profit)
    monkeypatch.setattr("pipeline.orchestrator.score_product", _score)
    monkeypatch.setattr(
        "pipeline.orchestrator.rank_candidates",
        lambda records, top_n=None: [record for record in records if record.score is not None],
    )
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

    run_id = run_pipeline(
        category="Home & Kitchen",
        limit=3,
        marketplace="US",
        export=False,
    )
    assert match_calls == ["ASIN-A", "ASIN-B", "ASIN-C"]

    with Session() as session:
        run = session.get(RunLog, run_id)
        assert run.status == "failed"
        match_nodes = session.query(ExecutionNode).filter_by(run_id=run_id, stage="match").all()
        assert {node.scope_key: node.status for node in match_nodes} == {
            "ASIN-A": "succeeded",
            "ASIN-B": "failed",
            "ASIN-C": "succeeded",
        }
        b_node_id = next(node.id for node in match_nodes if node.scope_key == "ASIN-B")
        assert session.query(ProfitSnapshot).count() == 2
        assert session.query(Score).count() == 2

    repo = ExecutionRepository(session_context=session_scope)
    repo.retry_node(b_node_id, reason="injected dependency recovered", actor_ref="test")
    fail_b["enabled"] = False
    settings.alibaba_allow_mock_suppliers = True
    assert resume_pipeline(run_id) == run_id
    assert settings.alibaba_allow_mock_suppliers is True

    assert match_calls == ["ASIN-A", "ASIN-B", "ASIN-C", "ASIN-B"]
    assert Counter(match_calls) == Counter({"ASIN-B": 2, "ASIN-A": 1, "ASIN-C": 1})
    with Session() as session:
        run = session.get(RunLog, run_id)
        assert run.status == "success"
        assert session.query(Supplier).count() == 3
        assert session.query(ProfitSnapshot).count() == 3
        assert session.query(Score).count() == 3
        match_nodes = session.query(ExecutionNode).filter_by(run_id=run_id, stage="match").all()
        assert {node.scope_key: node.attempt_count for node in match_nodes} == {
            "ASIN-A": 1,
            "ASIN-B": 2,
            "ASIN-C": 1,
        }
        filter_node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_type="run", stage="filter"
        ).one()
        assert filter_node.attempt_count == 2
        export_node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_type="run", stage="export"
        ).one()
        assert export_node.status == "skipped"
        assert export_node.generation == 2


def test_retry_wait_is_a_stage_barrier_until_retry_succeeds(monkeypatch):
    Session, session_scope = _memory_session_scope()
    product = ProductDTO(
        asin="ASIN-RETRY", marketplace="US", title="Retry Product", price=25.0
    )
    calls = {"match": 0}

    def match(_product, **_kwargs):
        calls["match"] += 1
        if calls["match"] == 1:
            raise ConnectionError("temporary supplier endpoint failure")
        return [SupplierDTO(
            alibaba_offer_id="retry-offer", supplier_name="Retry Factory",
            base_price_cny=20, moq=20, raw_data={"source": "unit-test"},
        )]

    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", match)
    monkeypatch.setattr("pipeline.orchestrator.predict_profit", _profit)
    monkeypatch.setattr("pipeline.orchestrator.score_product", _score)
    monkeypatch.setattr(
        "pipeline.orchestrator.rank_candidates",
        lambda records, top_n=None: [record for record in records if record.score is not None],
    )
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

    run_id = run_pipeline("Home & Kitchen", limit=1, export=False)

    with Session() as session:
        run = session.get(RunLog, run_id)
        assert run.status == "retry_wait"
        nodes = session.query(ExecutionNode).filter_by(run_id=run_id).all()
        assert {node.stage for node in nodes} == {
            "source_discovery", "ingest", "market", "match"
        }
        assert next(node for node in nodes if node.stage == "market").status == "skipped"
        assert next(node for node in nodes if node.stage == "match").status == "retry_wait"

    with Session.begin() as session:
        match_node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_key="ASIN-RETRY", stage="match"
        ).one()
        match_node.next_retry_at = datetime.utcnow() - timedelta(seconds=1)

    assert resume_pipeline(run_id) == run_id
    assert calls == {"match": 2}
    with Session() as session:
        assert session.get(RunLog, run_id).status == "success"
        stages = {
            node.stage: node.status
            for node in session.query(ExecutionNode).filter_by(run_id=run_id)
        }
        assert stages["match"] == "succeeded"
        assert stages["profit"] == "succeeded"
        assert stages["market"] == "skipped"
        assert stages["score"] == "succeeded"
        assert stages["filter"] == "succeeded"
        assert stages["export"] == "skipped"


def test_match_success_with_empty_supplier_is_not_fake_failure(monkeypatch):
    Session, session_scope = _memory_session_scope()
    product = ProductDTO(asin="ASIN-EMPTY", marketplace="US", title="No supplier", price=20.0)
    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", lambda _product, **_kwargs: [])
    monkeypatch.setattr("pipeline.orchestrator.rank_candidates", lambda records, top_n=None: [])
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)

    run_id = run_pipeline("Home & Kitchen", limit=1, export=False)
    with Session() as session:
        nodes = {
            node.stage: node for node in session.query(ExecutionNode).filter_by(
                run_id=run_id, scope_key="ASIN-EMPTY"
            )
        }
        assert nodes["match"].status == "succeeded"
        assert nodes["match"].output_snapshot["suppliers"] == []
        assert nodes["profit"].status == "skipped"
        assert nodes["profit"].error_code == "NOT_APPLICABLE"
        assert nodes["score"].status == "skipped"
        assert session.get(RunLog, run_id).status == "success"


def test_missing_committed_score_row_invalidates_only_score_and_aggregates(monkeypatch):
    Session, session_scope = _memory_session_scope()
    product = ProductDTO(
        asin="ASIN-VALIDATE", marketplace="US", title="Validation Product", price=30.0,
        weight_kg=0.5, length_cm=10, width_cm=10, height_cm=10,
    )
    calls = {"match": 0, "profit": 0, "score": 0}

    def match(_product, **_kwargs):
        calls["match"] += 1
        return [SupplierDTO(
            alibaba_offer_id="validate-offer", supplier_name="Factory",
            base_price_cny=20, moq=20, raw_data={"source": "unit-test"},
        )]

    def profit(*args, **kwargs):
        calls["profit"] += 1
        return _profit(*args, **kwargs)

    def score(*args, **kwargs):
        calls["score"] += 1
        return _score(*args, **kwargs)

    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", match)
    monkeypatch.setattr("pipeline.orchestrator.predict_profit", profit)
    monkeypatch.setattr("pipeline.orchestrator.score_product", score)
    monkeypatch.setattr(
        "pipeline.orchestrator.rank_candidates",
        lambda records, top_n=None: [record for record in records if record.score is not None],
    )
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

    run_id = run_pipeline("Home & Kitchen", limit=1, export=False)
    with Session.begin() as session:
        session.query(Score).filter(Score.result_key.is_not(None)).delete()

    resume_pipeline(run_id)

    assert calls == {"match": 1, "profit": 1, "score": 2}
    with Session() as session:
        score_node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_key="ASIN-VALIDATE", stage="score"
        ).one()
        filter_node = session.query(ExecutionNode).filter_by(
            run_id=run_id, scope_type="run", stage="filter"
        ).one()
        assert score_node.generation == 2
        assert score_node.attempt_count == 2
        assert filter_node.attempt_count == 2
        assert session.query(Score).count() == 1


def test_force_rerun_generation_invalidates_downstream_even_when_output_is_identical(monkeypatch):
    Session, session_scope = _memory_session_scope()
    product = ProductDTO(
        asin="ASIN-FORCE", marketplace="US", title="Force Product", price=30.0,
        weight_kg=0.5, length_cm=10, width_cm=10, height_cm=10,
    )
    calls = {"match": 0, "profit": 0, "score": 0}

    def match(_product, **_kwargs):
        calls["match"] += 1
        return [SupplierDTO(
            alibaba_offer_id="same-offer", supplier_name="Same Factory",
            base_price_cny=20, moq=20, raw_data={"source": "unit-test"},
        )]

    def profit(*args, **kwargs):
        calls["profit"] += 1
        return _profit(*args, **kwargs)

    def score(*args, **kwargs):
        calls["score"] += 1
        return _score(*args, **kwargs)

    monkeypatch.setattr("pipeline.orchestrator.session_scope", session_scope)
    monkeypatch.setattr("crawlers.amazon_bsr.crawl_best_sellers", lambda *args: [product])
    monkeypatch.setattr("pipeline.recoverable._formal_match_suppliers", match)
    monkeypatch.setattr("pipeline.orchestrator.predict_profit", profit)
    monkeypatch.setattr("pipeline.orchestrator.score_product", score)
    monkeypatch.setattr(
        "pipeline.orchestrator.rank_candidates",
        lambda records, top_n=None: [record for record in records if record.score is not None],
    )
    monkeypatch.setattr(settings, "mjjl_max_products_per_run", 0)
    monkeypatch.setattr(settings, "alibaba_allow_mock_suppliers", False)

    run_id = run_pipeline("Home & Kitchen", limit=1, export=False)
    repo = ExecutionRepository(session_context=session_scope)
    match_node = repo.find_node(
        run_id, scope_type="asin", scope_key="ASIN-FORCE", stage="match"
    )
    repo.force_rerun(
        match_node["id"],
        reason="operator requested fresh supplier evidence",
        expected_resume_token=match_node["resume_token"],
    )
    resume_pipeline(run_id)

    assert calls == {"match": 2, "profit": 2, "score": 2}
    with Session() as session:
        generations = {
            node.stage: node.generation
            for node in session.query(ExecutionNode).filter_by(
                run_id=run_id, scope_key="ASIN-FORCE"
            )
        }
        assert generations["match"] == 2
        assert generations["profit"] == 2
        assert generations["score"] == 2
        assert session.query(ProfitSnapshot).count() == 2
        assert session.query(Score).count() == 2

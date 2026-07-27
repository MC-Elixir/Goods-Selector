from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, RunLog
from execution.models import ErrorDisposition
from execution.repository import ExecutionRepository
from pipeline import orchestrator


def _store(monkeypatch):
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    @contextmanager
    def session_scope():
        with Session.begin() as session:
            yield session

    monkeypatch.setattr(orchestrator, "session_scope", session_scope)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    return ExecutionRepository(session_context=session_scope), run_id


def test_public_retry_and_attempt_query_keep_same_run(monkeypatch):
    repo, run_id = _store(monkeypatch)
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B0COMMAND1", stage="match"
    )
    claim = repo.claim(node_id, worker_id="worker-a")
    repo.fail(
        claim,
        disposition=ErrorDisposition.PERMANENT,
        error_code="INJECTED",
        error_detail="failure",
    )

    node = orchestrator.retry_node(run_id, "B0COMMAND1", "match", reason="dependency fixed")
    assert node["run_id"] == run_id
    assert node["status"] == "pending"
    assert orchestrator.execution_nodes(run_id)[0]["id"] == node_id
    attempts = orchestrator.execution_attempts(run_id, node_id)
    assert [(item["attempt_no"], item["status"]) for item in attempts] == [(1, "failed")]


def test_public_force_rerun_requires_reason_and_increments_generation(monkeypatch):
    repo, run_id = _store(monkeypatch)
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B0COMMAND2", stage="score"
    )
    claim = repo.claim(node_id, worker_id="worker-a")
    repo.succeed(claim, output_snapshot={"score": 80})

    with pytest.raises(ValueError, match="reason"):
        orchestrator.force_rerun_node(run_id, "B0COMMAND2", "score", "")
    node = orchestrator.force_rerun_node(
        run_id, "B0COMMAND2", "score", "reviewed scoring inputs changed"
    )
    assert node["run_id"] == run_id
    assert node["status"] == "pending"
    assert node["generation"] == 2

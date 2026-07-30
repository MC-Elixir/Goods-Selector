from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.migrate import install_sqlite_foreign_keys
from db.models import (
    Base,
    ExecutionAttempt,
    ExecutionNode,
    ExecutionOperation,
    Product,
    ProfitSnapshot,
    RunLog,
    Supplier,
)
from execution.models import (
    ALLOWED_TRANSITIONS,
    ErrorDisposition,
    LeaseLost,
    NodeStatus,
    validate_transition,
)
from execution.repository import ExecutionRepository, fingerprint, json_snapshot


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    install_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    clock = [datetime(2026, 7, 15, 1, 0, 0)]
    repo = ExecutionRepository(Session, now=lambda: clock[0])
    return repo, Session, run_id, clock


def test_state_machine_rejects_illegal_transitions():
    validate_transition("pending", "running")
    validate_transition("running", "succeeded")
    validate_transition("retry_wait", "pending")
    validate_transition("human_required", "pending")
    with pytest.raises(ValueError, match="succeeded -> running"):
        validate_transition("succeeded", "running")
    with pytest.raises(ValueError, match="pending -> succeeded"):
        validate_transition("pending", "succeeded")


def test_state_machine_exhaustively_accepts_only_declared_transitions():
    for before in NodeStatus:
        for after in NodeStatus:
            if after in ALLOWED_TRANSITIONS[before]:
                validate_transition(before, after)
            else:
                with pytest.raises(ValueError):
                    validate_transition(before, after)


def test_claim_success_and_succeeded_default_skip(repository):
    repo, _Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id,
        scope_type="asin",
        scope_key="B000TEST001",
        stage="match",
        input_snapshot={"schema_version": "1", "price": None, "count": 0},
        timeout_seconds=30,
    )
    initial_resume_token = repo.get_node(node_id)["resume_token"]
    assert initial_resume_token
    claim = repo.claim(node_id, worker_id="worker-a", lease_seconds=10)
    assert claim is not None
    assert claim.attempt_no == 1
    assert repo.claim(node_id, worker_id="worker-b") is None

    repo.succeed(claim, output_snapshot={"suppliers": [], "measured_zero": 0, "unknown": None})
    node = repo.get_node(node_id)
    assert node["status"] == "succeeded"
    assert node["attempt_count"] == 1
    assert node["output_snapshot"]["unknown"] is None
    assert node["output_snapshot"]["measured_zero"] == 0
    assert repo.claim(node_id, worker_id="worker-b") is None


def test_retry_wait_promotes_only_when_due(repository):
    repo, _Session, run_id, clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000TEST002", stage="match"
    )
    claim = repo.claim(node_id, worker_id="worker-a")
    assert claim is not None
    status = repo.fail(
        claim,
        disposition=ErrorDisposition.RETRYABLE,
        error_code="TEMPORARY",
        error_detail="temporary failure",
        max_attempts=3,
        backoff_seconds=10,
    )
    assert status == "retry_wait"
    assert repo.promote_due_retries(run_id=run_id) == 0
    clock[0] += timedelta(seconds=10)
    assert repo.promote_due_retries(run_id=run_id) == 1
    second = repo.claim(node_id, worker_id="worker-b")
    assert second is not None
    assert second.attempt_no == 2


def test_human_resume_and_force_rerun_keep_audit_history(repository):
    repo, Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000TEST003", stage="match"
    )
    first = repo.claim(node_id, worker_id="worker-a")
    repo.fail(
        first,
        disposition=ErrorDisposition.HUMAN_REQUIRED,
        error_code="CAPTCHA",
        error_detail="captcha requires a human",
        human_action={"instructions": "complete captcha in Chrome"},
    )
    assert repo.get_node(node_id)["status"] == "human_required"
    human_token = repo.get_node(node_id)["resume_token"]
    repo.resume_human(
        node_id,
        reason="captcha completed",
        actor_ref="local-user",
        expected_resume_token=human_token,
    )
    resumed_token = repo.get_node(node_id)["resume_token"]
    with pytest.raises(LeaseLost, match="resume token changed"):
        repo.resume_human(
            node_id,
            reason="stale browser tab",
            actor_ref="stale-user",
            expected_resume_token=human_token,
        )
    second = repo.claim(node_id, worker_id="worker-b")
    repo.succeed(second, output_snapshot={"suppliers": []})

    repo.force_rerun(node_id, reason="reviewed supplier locators changed", actor_ref="local-user")
    node = repo.get_node(node_id)
    assert node["status"] == "pending"
    assert node["generation"] == 2
    assert node["resume_token"] != resumed_token
    assert len(repo.list_attempts(node_id)) == 2
    with Session() as session:
        operations = session.scalars(
            select(ExecutionOperation).where(ExecutionOperation.node_id == node_id).order_by(
                ExecutionOperation.id
            )
        ).all()
    assert [operation.operation for operation in operations] == ["resume", "force_rerun"]


def test_stale_worker_is_recovered_and_fenced(repository):
    repo, _Session, run_id, clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000TEST004", stage="match"
    )
    old_claim = repo.claim(node_id, worker_id="worker-old", lease_seconds=5)
    clock[0] += timedelta(seconds=6)
    assert repo.recover_stale(run_id=run_id, max_attempts=3) == 1
    assert repo.get_node(node_id)["status"] == "retry_wait"
    assert repo.promote_due_retries(run_id=run_id) == 1
    new_claim = repo.claim(node_id, worker_id="worker-new")
    assert new_claim is not None

    with pytest.raises(LeaseLost):
        repo.succeed(old_claim, output_snapshot={"late": True})
    repo.succeed(new_claim, output_snapshot={"late": False})
    attempts = repo.list_attempts(node_id)
    assert [attempt["finish_reason"] for attempt in attempts] == ["stale", "completed"]


def test_input_fingerprint_change_invalidates_success(repository):
    repo, _Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id,
        scope_type="asin",
        scope_key="B000TEST005",
        stage="score",
        input_snapshot={"upstream": "v1"},
    )
    claim = repo.claim(node_id, worker_id="worker-a")
    repo.succeed(claim, output_snapshot={"score": 80})
    same_id = repo.ensure_node(
        run_id=run_id,
        scope_type="asin",
        scope_key="B000TEST005",
        stage="score",
        input_snapshot={"upstream": "v2"},
    )
    assert same_id == node_id
    node = repo.get_node(node_id)
    assert node["status"] == "pending"
    assert node["generation"] == 2
    assert node["output_snapshot"] is None


def test_invalid_committed_result_is_audited_and_reexecuted(repository):
    repo, Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000TESTVAL", stage="profit",
        input_snapshot={"schema_version": "1", "input": "same"},
    )
    claim = repo.claim(node_id, worker_id="worker-a")
    repo.succeed(claim, output_snapshot={"profit": 1})

    repo.invalidate_succeeded(node_id, reason="result_key row missing")
    node = repo.get_node(node_id)
    assert node["status"] == "pending"
    assert node["generation"] == 2
    assert node["error_code"] == "RESULT_VALIDATION_FAILED"
    with Session() as session:
        operation = session.query(ExecutionOperation).filter_by(
            node_id=node_id, operation="result_invalidated"
        ).one()
        assert operation.reason == "result_key row missing"


def test_cancel_requested_is_preserved_while_a_node_is_running(repository):
    repo, Session, run_id, _clock = repository
    running_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000RUNNING", stage="match"
    )
    pending_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000PENDING", stage="match"
    )
    claim = repo.claim(running_id, worker_id="worker-a")
    assert claim is not None
    repo.cancel_run(run_id, reason="operator cancel", actor_ref="test")

    assert repo.get_node(pending_id)["status"] == "cancelled"
    assert repo.update_run_status(run_id) == "cancel_requested"
    with Session() as session:
        assert session.get(RunLog, run_id).status == "cancel_requested"


def test_required_export_must_exist_and_succeed_before_run_success(repository):
    repo, _Session, run_id, _clock = repository
    filter_id = repo.ensure_node(
        run_id=run_id, scope_type="run", scope_key="run", stage="filter"
    )
    filter_claim = repo.claim(filter_id, worker_id="worker-a")
    repo.succeed(filter_claim, output_snapshot={"schema_version": "1", "records": []})

    assert repo.aggregate_run_status(run_id, export_required=True) == "retry_wait"
    assert repo.aggregate_run_status(run_id, export_required=False) == "success"

    export_id = repo.ensure_node(
        run_id=run_id, scope_type="run", scope_key="run", stage="export"
    )
    repo.mark_skipped(export_id, reason="injected missing export")
    assert repo.aggregate_run_status(run_id, export_required=True) == "failed"


def test_force_rerun_fences_an_older_generation(repository):
    repo, _Session, run_id, clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000FORCE1", stage="score"
    )
    old = repo.claim(node_id, worker_id="worker-old", lease_seconds=1)
    clock[0] += timedelta(seconds=2)
    repo.recover_stale(run_id=run_id, max_attempts=3)
    repo.promote_due_retries(run_id=run_id)
    recovered = repo.claim(node_id, worker_id="worker-recovered")
    repo.succeed(recovered, output_snapshot={"score": 70})
    repo.force_rerun(node_id, reason="weights changed", actor_ref="test")

    with pytest.raises(LeaseLost):
        repo.succeed(old, output_snapshot={"score": 99})
    assert repo.get_node(node_id)["generation"] == 2


def test_result_key_unique_index_is_idempotency_backstop(repository):
    _repo, Session, _run_id, _clock = repository
    with Session.begin() as session:
        product = Product(asin="B000UNIQUE", marketplace="US", title="Unique")
        session.add(product)
        session.flush()
        supplier = Supplier(product_id=product.id, alibaba_offer_id="offer-unique")
        session.add(supplier)
        session.flush()
        product_id, supplier_id = product.id, supplier.id
        session.add(ProfitSnapshot(
            product_id=product_id, supplier_id=supplier_id,
            selling_price=10, result_key="same",
        ))
    with pytest.raises(IntegrityError):
        with Session.begin() as session:
            session.add(ProfitSnapshot(
                product_id=product_id, supplier_id=supplier_id,
                selling_price=20, result_key="same",
            ))


def test_concurrent_claim_allows_exactly_one_winner(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'claim-race.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    repo = ExecutionRepository(Session)
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000RACE01", stage="match"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(
            lambda worker: repo.claim(node_id, worker_id=worker),
            ["worker-a", "worker-b"],
        ))
    assert sum(claim is not None for claim in claims) == 1
    assert repo.get_node(node_id)["attempt_count"] == 1


def test_node_identity_and_attempt_number_unique_constraints(repository):
    repo, Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000UNIQUE2", stage="match"
    )
    with pytest.raises(IntegrityError):
        with Session.begin() as session:
            session.add(ExecutionNode(
                run_id=run_id,
                scope_type="asin",
                scope_key="B000UNIQUE2",
                stage="match",
                status="pending",
            ))

    claim = repo.claim(node_id, worker_id="worker-a")
    with pytest.raises(IntegrityError):
        with Session.begin() as session:
            session.add(ExecutionAttempt(
                node_id=node_id,
                attempt_no=claim.attempt_no,
                generation=claim.generation,
                status="running",
                lease_token="duplicate-attempt",
            ))


def test_business_result_and_success_state_share_transaction(repository):
    repo, Session, run_id, _clock = repository
    node_id = repo.ensure_node(
        run_id=run_id, scope_type="asin", scope_key="B000TEST006", stage="profit"
    )
    claim = repo.claim(node_id, worker_id="worker-a")

    def injected_failure(session, _node):
        # This write must roll back together with the node state.
        session.add(ProfitSnapshot(
            product_id=999,
            supplier_id=999,
            selling_price=10.0,
            result_key="rollback-test",
        ))
        session.flush()

    with pytest.raises(Exception):
        repo.succeed(claim, output_snapshot={"profit": 1}, result_writer=injected_failure)
    node = repo.get_node(node_id)
    assert node["status"] == "running"
    with Session() as session:
        assert session.scalar(
            select(ProfitSnapshot.id).where(ProfitSnapshot.result_key == "rollback-test")
        ) is None


def test_snapshot_serializer_preserves_null_and_real_zero():
    value = json_snapshot({"unknown": None, "measured": 0, "flag": False})
    assert value == {"unknown": None, "measured": 0, "flag": False}
    assert fingerprint(value) == fingerprint({"flag": False, "measured": 0, "unknown": None})

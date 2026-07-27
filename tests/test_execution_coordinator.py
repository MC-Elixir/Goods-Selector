from __future__ import annotations

from datetime import datetime, timedelta
from time import sleep

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, RunLog
from execution.coordinator import RecoverableRunCoordinator
from execution.models import HumanActionRequired
from execution.policies import RetryPolicy
from execution.repository import ExecutionRepository


def _coordinator(*, cancel_check=None):
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    repo = ExecutionRepository(Session, now=lambda: datetime(2026, 7, 15, 12, 0, 0))
    return RecoverableRunCoordinator(
        run_id=run_id,
        repository=repo,
        cancel_check=cancel_check,
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0),
    ), repo, run_id


def test_human_action_is_durable_and_resumable():
    coordinator, repo, run_id = _coordinator()

    result = coordinator.run_node(
        scope_type="asin", scope_key="B0HUMAN001", stage="match",
        input_snapshot={"schema_version": "1", "query": "bottle"},
        handler=lambda _ctx: (_ for _ in ()).throw(HumanActionRequired(
            "CAPTCHA", "complete the slider", instructions="Use visible Chrome"
        )),
    )

    assert result.status == "human_required"
    node = repo.list_nodes(run_id)[0]
    assert node["human_action_required"]["error_code"] == "CAPTCHA"
    repo.resume_human(node["id"], reason="slider completed", actor_ref="test")
    assert repo.get_node(node["id"])["status"] == "pending"


def test_late_cancellation_is_not_recorded_as_permanent_failure():
    cancelled = {"value": False}
    coordinator, repo, run_id = _coordinator(cancel_check=lambda: cancelled["value"])

    def handler(_ctx):
        cancelled["value"] = True
        return {"schema_version": "1", "ignored": True}

    result = coordinator.run_node(
        scope_type="asin", scope_key="B0CANCEL01", stage="score",
        input_snapshot={"schema_version": "1", "score": 1}, handler=handler,
    )

    assert result.status == "cancelled"
    assert repo.list_nodes(run_id)[0]["error_code"] == "CANCELLED"


def test_retryable_error_enters_bounded_retry_wait():
    coordinator, repo, run_id = _coordinator()
    result = coordinator.run_node(
        scope_type="asin", scope_key="B0RETRY001", stage="market",
        input_snapshot={"schema_version": "1", "asin": "B0RETRY001"},
        handler=lambda _ctx: (_ for _ in ()).throw(ConnectionError("temporary outage")),
    )

    assert result.status == "retry_wait"
    node = repo.list_nodes(run_id)[0]
    assert node["attempt_count"] == 1
    assert node["next_retry_at"] is not None


def test_external_auth_error_is_normalized_to_human_required():
    coordinator, repo, run_id = _coordinator()

    class BrowserBlocked(RuntimeError):
        error_code = "AUTH_REQUIRED"
        instructions = "Log in to 1688 in visible Chrome"
        evidence_refs = ["screenshot:login"]

    result = coordinator.run_node(
        scope_type="asin", scope_key="B0AUTH0001", stage="match",
        input_snapshot={"schema_version": "1"},
        handler=lambda _ctx: (_ for _ in ()).throw(BrowserBlocked("login redirected")),
    )
    assert result.status == "human_required"
    action = repo.list_nodes(run_id)[0]["human_action_required"]
    assert action["error_code"] == "AUTH_REQUIRED"
    assert action["instructions"] == "Log in to 1688 in visible Chrome"
    assert action["evidence_refs"] == ["screenshot:login"]


def test_timeout_retries_are_bounded_and_end_timed_out():
    coordinator, repo, run_id = _coordinator()

    def timeout(_ctx):
        raise TimeoutError("browser deadline")

    statuses = []
    for _ in range(3):
        statuses.append(coordinator.run_node(
            scope_type="asin", scope_key="B0TIME0001", stage="match",
            input_snapshot={"schema_version": "1"}, handler=timeout,
        ).status)
    assert statuses == ["retry_wait", "retry_wait", "timed_out"]
    attempts = repo.list_attempts(repo.list_nodes(run_id)[0]["id"])
    assert [attempt["finish_reason"] for attempt in attempts] == [
        "timed_out", "timed_out", "timed_out"
    ]


def test_heartbeat_write_failure_does_not_replace_handler_result(monkeypatch):
    coordinator, repo, run_id = _coordinator()
    coordinator.lease_seconds = 0.3
    calls = {"count": 0}

    def failed_heartbeat(*_args, **_kwargs):
        calls["count"] += 1
        raise OSError("injected heartbeat write failure")

    monkeypatch.setattr(repo, "heartbeat", failed_heartbeat)
    result = coordinator.run_node(
        scope_type="asin", scope_key="B0HEART001", stage="market",
        input_snapshot={"schema_version": "1"},
        handler=lambda _ctx: (sleep(0.15) or {"schema_version": "1", "market": None}),
    )
    assert calls["count"] >= 1
    assert result.status == "succeeded"
    assert repo.list_nodes(run_id)[0]["status"] == "succeeded"


def test_crash_after_handler_before_commit_is_recovered_as_stale():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    clock = [datetime(2026, 7, 15, 12, 0, 0)]
    repo = ExecutionRepository(Session, now=lambda: clock[0])
    coordinator = RecoverableRunCoordinator(
        run_id=run_id, repository=repo, lease_seconds=1,
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0),
    )

    def crash_writer(_output):
        def writer(_session, _node):
            raise KeyboardInterrupt("injected process crash before commit")
        return writer

    try:
        coordinator.run_node(
            scope_type="asin", scope_key="B0CRASH001", stage="match",
            input_snapshot={"schema_version": "1"},
            handler=lambda _ctx: {
                "schema_version": "1", "suppliers": [{"id": "returned"}]
            },
            result_writer_factory=crash_writer,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("injected crash did not escape coordinator")

    node = repo.list_nodes(run_id)[0]
    assert node["status"] == "running"
    assert node["output_snapshot"] is None
    clock[0] += timedelta(seconds=2)
    assert repo.recover_stale(run_id=run_id, max_attempts=3) == 1
    assert repo.get_node(node["id"])["status"] == "retry_wait"


def test_succeeded_node_is_not_reused_when_result_validation_fails():
    coordinator, repo, run_id = _coordinator()
    calls = {"count": 0}

    def handler(_ctx):
        calls["count"] += 1
        return {"schema_version": "1", "value": calls["count"]}

    first = coordinator.run_node(
        scope_type="asin", scope_key="B0VALID001", stage="profit",
        input_snapshot={"schema_version": "1"}, handler=handler,
    )
    second = coordinator.run_node(
        scope_type="asin", scope_key="B0VALID001", stage="profit",
        input_snapshot={"schema_version": "1"}, handler=handler,
        success_validator=lambda _node: False,
    )

    assert first.status == second.status == "succeeded"
    assert calls["count"] == 2
    node = repo.list_nodes(run_id)[0]
    assert node["generation"] == 2
    assert node["attempt_count"] == 2


def test_crash_before_handler_call_leaves_recoverable_lease():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session.begin() as session:
        run = RunLog(category="Home & Kitchen", marketplace="US", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
    clock = [datetime(2026, 7, 15, 12, 0, 0)]
    repo = ExecutionRepository(Session, now=lambda: clock[0])
    coordinator = RecoverableRunCoordinator(
        run_id=run_id, repository=repo, lease_seconds=1,
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0),
    )

    try:
        coordinator.run_node(
            scope_type="asin", scope_key="B0PRECALL1", stage="match",
            input_snapshot={"schema_version": "1"},
            handler=lambda _ctx: (_ for _ in ()).throw(
                KeyboardInterrupt("crash before external call")
            ),
        )
    except KeyboardInterrupt:
        pass
    clock[0] += timedelta(seconds=2)
    assert repo.recover_stale(run_id=run_id, max_attempts=3) == 1
    assert repo.list_nodes(run_id)[0]["status"] == "retry_wait"


def test_restart_after_upstream_success_does_not_repeat_upstream():
    coordinator, repo, run_id = _coordinator()
    calls = {"upstream": 0, "downstream": 0}

    def upstream(_ctx):
        calls["upstream"] += 1
        return {"schema_version": "1", "value": "ready"}

    coordinator.run_node(
        scope_type="asin", scope_key="B0BARRIER1", stage="match",
        input_snapshot={"schema_version": "1"}, handler=upstream,
    )
    restarted = RecoverableRunCoordinator(run_id=run_id, repository=repo)
    cached = restarted.run_node(
        scope_type="asin", scope_key="B0BARRIER1", stage="match",
        input_snapshot={"schema_version": "1"}, handler=upstream,
    )
    restarted.run_node(
        scope_type="asin", scope_key="B0BARRIER1", stage="profit",
        input_snapshot={
            "schema_version": "1",
            "upstream": cached.output_snapshot,
        },
        handler=lambda _ctx: (
            calls.__setitem__("downstream", calls["downstream"] + 1)
            or {"schema_version": "1", "profit": None}
        ),
    )
    assert calls == {"upstream": 1, "downstream": 1}


def test_snapshots_require_explicit_schema_version():
    coordinator, repo, run_id = _coordinator()
    try:
        coordinator.run_node(
            scope_type="asin", scope_key="B0SCHEMA01", stage="match",
            input_snapshot={"query": "missing version"},
            handler=lambda _ctx: {"schema_version": "1"},
        )
    except ValueError as exc:
        assert "input snapshot requires schema_version" in str(exc)
    else:
        raise AssertionError("missing input schema version was accepted")
    assert repo.list_nodes(run_id) == []

    result = coordinator.run_node(
        scope_type="asin", scope_key="B0SCHEMA02", stage="match",
        input_snapshot={"schema_version": "1"},
        handler=lambda _ctx: {"value": "missing output version"},
    )
    assert result.status == "failed"
    assert result.error_code == "VALUEERROR"

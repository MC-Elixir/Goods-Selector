"""AgentRuntime job behavior tests."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent.runner import AgentRuntime
from agent.state import AgentJob, AgentRunConfig
from db.models import Base, RunLog


@pytest.fixture(autouse=True)
def _skip_runtime_result_summary(monkeypatch):
    monkeypatch.setattr(
        "agent.runner.summarize_run_result",
        lambda **kwargs: {"status": "skipped", "provider": "test"},
    )


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached before timeout")


def _runtime(tmp_path) -> AgentRuntime:
    return AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")


def _full_research_payload(tmp_path):
    research_xlsx = tmp_path / "market_research.xlsx"
    research_json = tmp_path / "market_research.json"
    research_xlsx.write_bytes(b"xlsx")
    research_json.write_text("{}", encoding="utf-8")
    return {
        "status": "SUCCESS",
        "run_id": "research-run-1",
        "keyword": "patio umbrella",
        "items": [{
            "seller": "Focused Seller",
            "representative_asin": "B000000321",
            "representative_title": "Patio Umbrella",
            "brand": "Shade Co",
            "price": 49.99,
            "rating": 4.4,
            "review_count": 180,
            "monthly_sales": 420,
            "monthly_revenue": 20995.8,
            "fit_score": 88.0,
            "fit_category": "focused",
            "fit_reasons": ["少而精", "月销稳定"],
        }],
        "excluded_items": [],
        "exports": {"xlsx": str(research_xlsx), "json": str(research_json)},
    }


def test_runtime_startup_marks_interrupted_runs_as_failed(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}", future=True)
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

    with temp_session_scope() as session:
        session.add(RunLog(marketplace="US", started_at=datetime.utcnow(), status="running"))

    monkeypatch.setattr("agent.runner.session_scope", temp_session_scope)
    AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")

    with temp_session_scope() as session:
        run = session.query(RunLog).one()
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.error_message == "Interrupted by WebUI server restart"


def test_runtime_startup_preserves_recoverable_run_before_first_node(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'early-recovery.db'}", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, future=True)

    @contextmanager
    def temp_session_scope():
        with session_local.begin() as session:
            yield session

    with temp_session_scope() as session:
        session.add(RunLog(
            marketplace="US",
            started_at=datetime.utcnow(),
            status="running",
            api_calls={"recoverable_config": {
                "category": "Home & Kitchen",
                "source_mode": "category",
                "marketplace": "US",
                "limit": 1,
            }},
        ))

    monkeypatch.setattr("agent.runner.session_scope", temp_session_scope)
    AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")

    with temp_session_scope() as session:
        run = session.query(RunLog).one()
        assert run.status == "retry_wait"
        assert run.finished_at is None
        assert run.error_message is None


def test_runtime_queues_jobs_and_runs_only_one_at_a_time(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    first_started = threading.Event()
    release_first = threading.Event()
    calls: list[str] = []

    def fake_run_job(job_id: str) -> None:
        calls.append(job_id)
        with runtime._lock:
            runtime._jobs[job_id].status = "running"
        if len(calls) == 1:
            first_started.set()
            release_first.wait(timeout=2)
        with runtime._lock:
            runtime._jobs[job_id].status = "success"

    monkeypatch.setattr(runtime, "_run_job", fake_run_job)

    first = runtime.start_run(AgentRunConfig(category="Home & Kitchen", limit=1))
    second = runtime.start_run(AgentRunConfig(category="Toys & Games", limit=1))

    _wait_until(first_started.is_set)

    assert runtime.get_job(first.id)["status"] == "running"
    assert runtime.get_job(second.id)["status"] == "queued"
    assert calls == [first.id]

    release_first.set()
    _wait_until(lambda: runtime.get_job(second.id)["status"] == "success")

    assert calls == [first.id, second.id]


def test_runtime_can_cancel_queued_job(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    first_started = threading.Event()
    release_first = threading.Event()

    def fake_run_job(job_id: str) -> None:
        with runtime._lock:
            runtime._jobs[job_id].status = "running"
        first_started.set()
        release_first.wait(timeout=2)
        with runtime._lock:
            runtime._jobs[job_id].status = "success"

    monkeypatch.setattr(runtime, "_run_job", fake_run_job)

    runtime.start_run(AgentRunConfig(category="Home & Kitchen", limit=1))
    queued = runtime.start_run(AgentRunConfig(category="Toys & Games", limit=1))
    _wait_until(first_started.is_set)

    cancelled = runtime.cancel_job(queued.id)

    assert cancelled["status"] == "cancelled"
    assert cancelled["message"] == "Cancelled before start"

    release_first.set()
    time.sleep(0.05)

    assert runtime.get_job(queued.id)["status"] == "cancelled"


def test_runtime_passes_progress_and_cancel_hooks_to_pipeline(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")
    started = threading.Event()
    saw_cancel = threading.Event()

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {"candidate_count": 0})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    def fake_pipeline(**kwargs):
        progress_callback = kwargs["progress_callback"]
        cancel_check = kwargs["cancel_check"]
        progress_callback({
            "stage": "match",
            "asin": "B0HOOK0001",
            "index": 1,
            "total": 2,
            "message": "Matching B0HOOK0001 (1/2)",
        })
        started.set()
        _wait_until(cancel_check)
        saw_cancel.set()
        return 901

    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", fake_pipeline)

    job = runtime.start_run(AgentRunConfig(category="Sports & Outdoors", limit=2))
    _wait_until(started.is_set)
    heartbeat = runtime.get_job(job.id)
    assert heartbeat["message"] == "Matching B0HOOK0001 (1/2)"
    assert heartbeat["events"][-1]["event"] == "match"

    runtime.cancel_job(job.id)
    _wait_until(lambda: runtime.get_job(job.id)["status"] == "cancelled")

    assert saw_cancel.is_set()
    assert runtime.get_job(job.id)["message"] == "Cancelled after pipeline"


def test_runtime_keeps_cancellation_message_during_late_progress(monkeypatch, tmp_path):
    runtime = AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")
    job = AgentJob(config=AgentRunConfig(category="Home & Kitchen", limit=1))
    job.status = "running"
    runtime._jobs[job.id] = job

    runtime.cancel_job(job.id)
    runtime._handle_pipeline_progress(job.id, {
        "stage": "match",
        "message": "Matching suppliers for B0LATE0001 (1/10)",
        "asin": "B0LATE0001",
        "index": 1,
        "total": 10,
    })

    data = runtime.get_job(job.id)
    assert data["status"] == "cancel_requested"
    assert data["message"] == "Cancellation requested"
    assert data["events"][-1]["event"] == "match"


def test_full_research_compatibility_mode_starts_with_amazon_pipeline(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text('[{"asin": "B000000321"}]', encoding="utf-8")
    captured = {}

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("agent.runner._run_market_research", lambda config: (_ for _ in ()).throw(AssertionError("must not create seed products")))
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr(
        "agent.runner.audit_export",
        lambda path: {"candidate_count": 1, "supplier_evidence_ready": True},
    )
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return 913

    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", fake_pipeline)
    runtime = _runtime(tmp_path)
    job = runtime.start_run(AgentRunConfig(
        category="Home & Kitchen",
        limit=5,
        workflow_mode="full_research",
        research_keyword="patio umbrella",
        require_supplier_evidence=True,
    ))

    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")
    result = runtime.get_job(job.id)

    assert "seed_products" not in captured
    assert captured["category"] == "Home & Kitchen"
    assert captured["export_review_on_empty"] is True
    assert result["research"] == {}
    assert not any(event["event"] == "market_research_complete" for event in result["events"])


def test_full_research_no_longer_runs_competitor_export_gate(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr(
        "agent.runner._run_market_research",
        lambda config: {"status": "CAPTCHA", "keyword": config.research_keyword},
    )
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: calls.append(kwargs) or 914)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})
    runtime = _runtime(tmp_path)
    job = runtime.start_run(AgentRunConfig(
        category="Home & Kitchen",
        limit=5,
        workflow_mode="full_research",
        research_keyword="patio umbrella",
    ))

    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")
    assert len(calls) == 1
    assert "seed_products" not in calls[0]


def test_runtime_records_progress_to_persistent_run_events(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")
    recorded = []

    monkeypatch.setattr("agent.runner.record_run_event", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {"candidate_count": 0})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    def fake_pipeline(**kwargs):
        kwargs["progress_callback"]({
            "run_id": 777,
            "stage": "match",
            "asin": "B0EVENT777",
            "index": 1,
            "total": 1,
            "message": "Matching B0EVENT777 (1/1)",
        })
        return 777

    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", fake_pipeline)

    job = runtime.start_run(AgentRunConfig(category="Sports & Outdoors", limit=1))
    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")

    match_event = next(item for item in recorded if item["event"] == "match")
    assert match_event["run_id"] == 777
    assert match_event["job_id"] == job.id
    assert match_event["stage"] == "match"
    assert match_event["asin"] == "B0EVENT777"


def test_runtime_retries_failed_job_with_same_config(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    calls: list[str] = []

    def fake_run_job(job_id: str) -> None:
        calls.append(job_id)
        with runtime._lock:
            job = runtime._jobs[job_id]
            if len(calls) == 1:
                job.status = "failed"
                job.error = "boom"
            else:
                job.status = "success"

    monkeypatch.setattr(runtime, "_run_job", fake_run_job)

    failed = runtime.start_run(AgentRunConfig(category="Home & Kitchen", source_mode="category", limit=7))
    _wait_until(lambda: runtime.get_job(failed.id)["status"] == "failed")

    retried = runtime.retry_job(failed.id)
    _wait_until(lambda: runtime.get_job(retried.id)["status"] == "success")

    assert retried.id != failed.id
    assert retried.config == failed.config
    assert retried.retry_of == failed.id
    assert retried.attempt == 2
    assert calls == [failed.id, retried.id]


def test_runtime_records_job_event_log(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = _runtime(tmp_path)

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 777)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {"candidate_count": 0})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    job = runtime.start_run(AgentRunConfig(category="Home & Kitchen", limit=1))
    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")

    data = runtime.get_job(job.id)
    event_types = [event["event"] for event in data["events"]]

    assert event_types[0] == "queued"
    assert "running" in event_types
    assert event_types[-1] == "success"
    assert all(event.get("at") for event in data["events"])


def test_runtime_attaches_result_summary_after_success(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = AgentRuntime(job_store_path=tmp_path / "agent_jobs.json")

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 778)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {"candidate_count": 2})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})
    monkeypatch.setattr(
        "agent.runner.summarize_run_result",
        lambda **kwargs: {
            "status": "success",
            "provider": "ppio",
            "model": "minimax/minimax-m3",
            "summary": "结论：暂缓。依据：候选不足，需要补数据。",
        },
    )

    job = runtime.start_run(AgentRunConfig(category="Home & Kitchen", limit=1))
    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")

    data = runtime.get_job(job.id)
    assert data["result_summary"]["model"] == "minimax/minimax-m3"
    assert "结论：暂缓" in data["result_summary"]["summary"]


def test_runtime_persists_job_history_to_disk(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    store = tmp_path / "agent_jobs.json"

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 888)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {"candidate_count": 0})
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    runtime = AgentRuntime(job_store_path=store)
    job = runtime.start_run(AgentRunConfig(category="Home & Kitchen", limit=1))
    _wait_until(lambda: runtime.get_job(job.id)["status"] == "success")

    restored = AgentRuntime(job_store_path=store)
    restored_job = restored.get_job(job.id)

    assert restored_job["status"] == "success"
    assert restored_job["run_log_id"] == 888
    assert restored_job["events"][0]["event"] == "queued"
    assert restored_job["events"][-1]["event"] == "success"


def test_runtime_marks_running_jobs_interrupted_on_restore(tmp_path):
    store = tmp_path / "agent_jobs.json"
    running = AgentJob(config=AgentRunConfig(category="Home & Kitchen", limit=1))
    running.status = "running"
    running.message = "Running sourcing pipeline"
    running.events.append({"event": "running", "message": "Running sourcing pipeline", "at": "2026-07-08T00:00:00+00:00"})

    runtime = AgentRuntime(job_store_path=store)
    with runtime._lock:
        runtime._jobs[running.id] = running
        runtime._persist_jobs_locked()

    restored = AgentRuntime(job_store_path=store)
    data = restored.get_job(running.id)

    assert data["status"] == "failed"
    assert data["message"] == "Interrupted by server restart"
    assert data["events"][-1]["event"] == "interrupted"


def test_runtime_requeues_persisted_retry_wait_job_after_restart(monkeypatch, tmp_path):
    store = tmp_path / "agent_jobs.json"
    monkeypatch.setattr(AgentRuntime, "_recover_interrupted_runs", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_ensure_worker_locked", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_restored_job_status", lambda self, job: "queued")

    waiting = AgentJob(config=AgentRunConfig(category="Home & Kitchen", limit=1))
    waiting.status = "retry_wait"
    waiting.run_log_id = 321
    runtime = AgentRuntime(job_store_path=store)
    with runtime._lock:
        runtime._jobs[waiting.id] = waiting
        runtime._persist_jobs_locked()

    restored = AgentRuntime(job_store_path=store)
    data = restored.get_job(waiting.id)
    assert data["status"] == "queued"
    assert data["run_log_id"] == 321
    assert data["events"][-1]["event"] == "resume_queued"
    assert waiting.id in restored._queue


def test_runtime_reconstructs_missing_job_from_sqlite_truth(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sqlite-truth.db'}", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, future=True)

    @contextmanager
    def temp_session_scope():
        with session_local.begin() as session:
            yield session

    with temp_session_scope() as session:
        run = RunLog(
            category="Home & Kitchen",
            marketplace="US",
            status="retry_wait",
            api_calls={
                "recoverable_config": {
                    "category": "Home & Kitchen",
                    "source_mode": "category",
                    "keyword": "",
                    "marketplace": "US",
                    "limit": 3,
                    "allow_mock_suppliers": False,
                }
            },
        )
        session.add(run)
        session.flush()
        run_id = run.id

    monkeypatch.setattr("agent.runner.session_scope", temp_session_scope)
    monkeypatch.setattr(AgentRuntime, "_recover_interrupted_runs", lambda self: None)
    monkeypatch.setattr(AgentRuntime, "_ensure_worker_locked", lambda self: None)
    runtime = AgentRuntime(job_store_path=tmp_path / "missing-agent-jobs.json")
    assert runtime.list_jobs() == []

    runtime._restore_missing_sqlite_jobs()
    jobs = runtime.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == f"recovered-run-{run_id}"
    assert jobs[0]["run_log_id"] == run_id
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["config"]["no_mock"] is True


def test_runtime_fails_job_when_required_market_data_missing(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = _runtime(tmp_path)

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.seller_sprite_market_data_guard", lambda: (True, ""))
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 321)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {
        "candidate_count": 1,
        "market_data_count": 0,
        "market_data_rate": 0.0,
        "market_data_ready": False,
        "market_data_rich_ready": False,
    })
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    job = AgentJob(config=AgentRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_market_data=True,
    ))
    runtime._jobs[job.id] = job
    runtime._run_job(job.id)
    data = runtime.get_job(job.id)

    assert data["status"] == "failed"
    assert data["message"] == "Market data missing"
    assert data["error"] == "SellerSprite rich market data required but missing from export"
    assert data["run_log_id"] == 321
    assert data["audit"]["market_data_rich_ready"] is False


def test_runtime_fails_before_pipeline_when_required_market_data_unavailable(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    called = []

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr(
        "agent.runner.seller_sprite_market_data_guard",
        lambda: (False, "SellerSprite ASIN check failed: 未授权"),
    )
    monkeypatch.setattr("agent.runner.init_db", lambda: called.append("init_db"))
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: called.append("pipeline"))

    job = AgentJob(config=AgentRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_market_data=True,
    ))
    runtime._jobs[job.id] = job
    runtime._run_job(job.id)
    data = runtime.get_job(job.id)

    assert data["status"] == "failed"
    assert data["message"] == "Run failed"
    assert data["error"] == "SellerSprite ASIN check failed: 未授权"
    assert called == []


def test_runtime_fails_job_when_required_supplier_evidence_missing(monkeypatch, tmp_path):
    export = tmp_path / "candidates_live.json"
    export.write_text("[]", encoding="utf-8")
    runtime = _runtime(tmp_path)

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 654)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {"json": export})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: {
        "candidate_count": 1,
        "supplier_evidence_count": 0,
        "supplier_evidence_rate": 0.0,
        "supplier_evidence_ready": False,
        "real_supplier_count": 0,
        "supplier_source_counts": {"none": 1},
    })
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    job = AgentJob(config=AgentRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_supplier_evidence=True,
    ))
    runtime._jobs[job.id] = job
    runtime._run_job(job.id)
    data = runtime.get_job(job.id)

    assert data["status"] == "failed"
    assert data["message"] == "Supplier evidence missing"
    assert data["error"] == "Real supplier match evidence required but missing from export"
    assert data["run_log_id"] == 654
    assert data["audit"]["supplier_evidence"] == {
        "count": 0,
        "rate": 0.0,
        "ready": False,
        "real_supplier_count": 0,
        "source_counts": {"none": 1},
        "avg_spec_match_score": None,
        "avg_match_quality_score": None,
    }


def test_runtime_reports_no_candidates_before_supplier_evidence_guard(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)

    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 655)
    monkeypatch.setattr("agent.runner.latest_export_after", lambda started: {})
    monkeypatch.setattr("agent.runner.audit_export", lambda path: (_ for _ in ()).throw(AssertionError("no export")))
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 1, "total": 1})

    job = AgentJob(config=AgentRunConfig(
        category="Pet Supplies",
        limit=10,
        require_supplier_evidence=True,
    ))
    runtime._jobs[job.id] = job
    runtime._run_job(job.id)
    data = runtime.get_job(job.id)

    assert data["status"] == "failed"
    assert data["message"] == "No candidates passed filters"
    assert data["error"] == "No candidates passed hard filters; no export was generated"
    assert data["run_log_id"] == 655


def test_runtime_keeps_zero_passed_status_when_review_export_exists(
    monkeypatch, tmp_path
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.models import Base, RunLog

    export = tmp_path / "review.json"
    export.write_text('[{"asin": "B0REVIEW001"}]', encoding="utf-8")
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    with session_local() as session:
        session.add(RunLog(id=656, status="success", candidates_after_filter=0))
        session.commit()

    @contextmanager
    def temp_session_scope():
        session = session_local()
        try:
            yield session
        finally:
            session.close()

    runtime = _runtime(tmp_path)
    monkeypatch.setattr("agent.runner.session_scope", temp_session_scope)
    monkeypatch.setattr("agent.runner.run_preflight", lambda: {"ready": True, "checks": []})
    monkeypatch.setattr("agent.runner.seller_sprite_market_data_guard", lambda: (True, ""))
    monkeypatch.setattr("agent.runner.init_db", lambda: None)
    monkeypatch.setattr("pipeline.orchestrator.run_pipeline", lambda **kwargs: 656)
    monkeypatch.setattr(
        "agent.runner._exports_for_run",
        lambda run_id, started: {"json": export, "xlsx": tmp_path / "review.xlsx"},
    )
    monkeypatch.setattr(
        "agent.runner.audit_export",
        lambda path: {
            "candidate_count": 1,
            "supplier_evidence_ready": True,
            "market_data_rich_ready": True,
        },
    )
    monkeypatch.setattr("agent.runner.manual_queue_summary", lambda: {"open": 0, "total": 0})

    job = AgentJob(config=AgentRunConfig(
        category="Home & Kitchen",
        limit=1,
        require_supplier_evidence=True,
        require_market_data=True,
    ))
    runtime._jobs[job.id] = job
    runtime._run_job(job.id)
    data = runtime.get_job(job.id)

    assert data["status"] == "review_required"
    assert data["message"] == "Review report generated"
    assert data["error"] == "No candidates passed hard filters; a review report was generated"
    assert data["exports"]["json"] == str(export)


def test_runtime_migrates_review_export_failure_to_review_required(
    monkeypatch, tmp_path
):
    store = tmp_path / "agent_jobs.json"
    store.write_text(json.dumps({
        "jobs": [{
            "config": {"category": "Home & Kitchen"},
            "id": "legacyreview1",
            "status": "failed",
            "created_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "message": "No candidates passed filters",
            "error": "No candidates passed hard filters; a review report was generated",
            "exports": {"json": "/app/data/exports/review.json"},
        }],
        "queue": [],
    }), encoding="utf-8")
    monkeypatch.setattr("agent.runner.AgentRuntime._recover_interrupted_runs", lambda self: None)

    restored = AgentRuntime(job_store_path=store).get_job("legacyreview1")

    assert restored["status"] == "review_required"
    assert restored["message"] == "Review report generated"

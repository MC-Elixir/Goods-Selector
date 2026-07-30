"""Agent runtime: environment + tools + prompt policy + execution loop."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent.history import audit_export, latest_export_after
from agent.manual_queue import manual_queue_summary
from agent.preflight import run_preflight
from agent.result_summarizer import summarize_run_result
from agent.run_events import record_run_event
from agent.seller_sprite_diagnostics import seller_sprite_market_data_guard
from agent.state import AgentJob, AgentRunConfig
from config.settings import settings
from db.init_db import init_db
from db.models import ArtifactManifest, ExecutionNode, RunLog
from db.session import session_scope
from execution.repository import ExecutionRepository

AGENT_SYSTEM_PROMPT = """\
You are Amazon Selector Agent.

Goal:
Run product sourcing jobs end-to-end and return trustworthy product candidates.

Decision policy:
- Prefer real Amazon and real 1688 data over mock data.
- In no-mock mode, never allow mock suppliers into formal results.
- Run preflight before launching a job.
- If 1688 is blocked by login, popup, or captcha, stop and ask for human action.
- When 1688 is blocked during sourcing, preserve the ASIN in the manual
  sourcing queue so it can be verified by a human later.
- After each run, audit exported results for mock suppliers, suspicious prices,
  margins, and candidate counts before presenting them.

Loop:
Observe environment state -> choose tool -> run tool -> update state -> repeat
until the job succeeds, fails with a clear reason, or needs human intervention.
"""

_RESEARCH_HUMAN_STATUSES = frozenset({
    "EXTENSION_UNAVAILABLE",
    "SELLERSPRITE_LOGIN_REQUIRED",
    "SELLERSPRITE_PERMISSION_REQUIRED",
    "SELLERSPRITE_QUOTA_EXCEEDED",
    "CAPTCHA",
    "NEEDS_HUMAN",
})


class AgentRuntime:
    def __init__(self, job_store_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._jobs: dict[str, AgentJob] = {}
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None
        self._restore_from_sqlite = job_store_path is None
        self._job_store_path = Path(job_store_path) if job_store_path else settings.log_dir / "agent_jobs.json"
        self._recover_interrupted_runs()
        self._load_jobs()
        if self._restore_from_sqlite:
            self._restore_missing_sqlite_jobs()

    def preflight(self) -> dict[str, Any]:
        return run_preflight()

    def start_run(self, config: AgentRunConfig) -> AgentJob:
        job = AgentJob(config=config)
        return self._enqueue_job(job)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status == "queued":
                try:
                    self._queue.remove(job_id)
                except ValueError:
                    pass
                job.status = "cancelled"
                job.cancel_requested = True
                job.finished_at = datetime.now(UTC)
                job.message = "Cancelled before start"
                self._add_event_locked(job, "cancelled", job.message)
                self._refresh_queue_positions_locked()
                self._persist_jobs_locked()
            elif job.status == "running":
                job.status = "cancel_requested"
                job.cancel_requested = True
                job.message = "Cancellation requested"
                self._add_event_locked(job, "cancel_requested", job.message)
                self._persist_jobs_locked()
            elif job.status == "cancel_requested":
                pass
            else:
                raise ValueError(f"cannot cancel job in status {job.status}")
            self._condition.notify_all()
            payload = job.to_dict()
        if job.run_log_id and job.cancel_requested:
            try:
                repository = ExecutionRepository(session_context=session_scope)
                repository.cancel_run(
                    int(job.run_log_id), reason="cancel requested from AgentRuntime", actor_ref=job.id
                )
                repository.update_run_status(int(job.run_log_id))
            except Exception:
                pass
        return payload

    def retry_job(self, job_id: str) -> AgentJob:
        with self._lock:
            original = self._jobs.get(job_id)
            if not original:
                raise KeyError(job_id)
            research_gate = original.status == "human_required" and not original.run_log_id
            if original.status not in {"failed", "cancelled"} and not research_gate:
                raise ValueError(f"cannot retry job in status {original.status}")
            job = AgentJob(
                config=replace(original.config),
                retry_of=original.id,
                attempt=int(original.attempt or 1) + 1,
                run_log_id=original.run_log_id,
                research=dict(original.research),
            )
            if research_gate:
                # Browser state changed outside the process. Re-run the market
                # export instead of reusing the human-action result.
                job.research = {}
        if original.run_log_id and self._prepare_recoverable_retry(int(original.run_log_id), job.id):
            return self._enqueue_job(job)
        job.run_log_id = None
        return self._enqueue_job(job)

    def execution_nodes(self, run_id: int) -> list[dict[str, Any]]:
        return ExecutionRepository(session_context=session_scope).list_nodes(int(run_id))

    def execution_attempts(self, run_id: int, node_id: int) -> list[dict[str, Any]]:
        repository = ExecutionRepository(session_context=session_scope)
        node = repository.get_node(int(node_id))
        if not node or int(node["run_id"]) != int(run_id):
            raise KeyError(node_id)
        return repository.list_attempts(int(node_id))

    def operate_node(
        self,
        job_id: str,
        node_id: int,
        action: str,
        *,
        reason: str,
        resume_token: str,
    ) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if not job.run_log_id:
                raise ValueError("job has no recoverable run")
            if job.status in {"queued", "running", "cancel_requested"}:
                raise ValueError(f"cannot resume node while job is {job.status}")
            run_id = int(job.run_log_id)
        repo = ExecutionRepository(session_context=session_scope)
        node = repo.get_node(int(node_id))
        if not node or int(node["run_id"]) != run_id:
            raise KeyError(node_id)
        if action == "resume":
            repo.resume_human(
                int(node_id), reason=reason, actor_ref=job_id,
                expected_resume_token=resume_token,
            )
        elif action == "retry":
            repo.retry_node(
                int(node_id), reason=reason, actor_ref=job_id,
                expected_resume_token=resume_token,
            )
        elif action == "force-rerun":
            repo.force_rerun(
                int(node_id), reason=reason, actor_ref=job_id,
                expected_resume_token=resume_token,
            )
        else:
            raise ValueError(f"unsupported node action: {action}")
        with self._lock:
            job.status = "queued"
            job.cancel_requested = False
            job.finished_at = None
            job.error = None
            job.message = f"Queued to {action} {node['scope_key']}:{node['stage']}"
            self._add_event_locked(job, action.replace("-", "_"), job.message,
                                   run_id=run_id, node_id=int(node_id),
                                   asin=node["scope_key"] if node["scope_type"] == "asin" else None,
                                   stage=node["stage"])
            if job.id not in self._queue:
                self._queue.append(job.id)
            self._refresh_queue_positions_locked()
            self._ensure_worker_locked()
            self._persist_jobs_locked()
            self._condition.notify_all()
            return {"job": job.to_dict(), "node": repo.get_node(int(node_id))}

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh_queue_positions_locked()
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._refresh_queue_positions_locked()
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _enqueue_job(self, job: AgentJob) -> AgentJob:
        with self._lock:
            self._add_event_locked(job, "queued", job.message)
            self._jobs[job.id] = job
            self._queue.append(job.id)
            self._refresh_queue_positions_locked()
            self._ensure_worker_locked()
            self._persist_jobs_locked()
            self._condition.notify_all()
            return job

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._queue:
                    self._worker = None
                    return
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if not job or job.status == "cancelled" or job.cancel_requested:
                    self._refresh_queue_positions_locked()
                    continue
                self._refresh_queue_positions_locked()
            self._run_job(job_id)

    def _refresh_queue_positions_locked(self) -> None:
        positions = {job_id: index + 1 for index, job_id in enumerate(self._queue)}
        for job_id, job in self._jobs.items():
            job.queue_position = positions.get(job_id) if job.status == "queued" else None

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                job.message = "Cancelled before start"
                self._add_event_locked(job, "cancelled", job.message)
                return
            job.status = "running"
            job.started_at = datetime.now(UTC)
            job.message = "Running preflight"
            self._add_event_locked(job, "running", job.message)
            self._persist_jobs_locked()

        try:
            preflight = run_preflight()
            if not preflight["ready"]:
                raise RuntimeError(_preflight_error(preflight))
            if job.config.require_market_data:
                ready, reason = seller_sprite_market_data_guard()
                if not ready:
                    raise RuntimeError(reason)
            if self._is_cancel_requested(job_id):
                self._mark_cancelled(job_id, "Cancelled before pipeline")
                return

            init_db()

            started = time.time()
            seed_products: list[dict[str, Any]] | None = None
            if job.config.workflow_mode == "full_research" and not job.run_log_id:
                seed_products = self._prepare_full_research(job_id)
                if seed_products is None:
                    return
                if self._is_cancel_requested(job_id):
                    self._mark_cancelled(job_id, "Cancelled after market research")
                    return

            with self._lock:
                job.message = "Running sourcing pipeline"
                self._add_event_locked(job, "pipeline", job.message)
                self._persist_jobs_locked()

            # settings is a process-wide singleton. The web agent runs one job at a time
            # in normal use, so temporarily applying mode flags is sufficient here.
            previous_mock = settings.alibaba_allow_mock_suppliers
            previous_llm = settings.enable_llm_verification
            settings.alibaba_allow_mock_suppliers = _runtime_allow_mock_suppliers(job.config)
            if job.config.llm_verification is not None:
                settings.enable_llm_verification = bool(job.config.llm_verification)
            try:
                if job.run_log_id:
                    from pipeline.orchestrator import resume_pipeline
                    run_log_id = resume_pipeline(
                        int(job.run_log_id),
                        progress_callback=lambda event: self._handle_pipeline_progress(job_id, event),
                        cancel_check=lambda: self._is_cancel_requested(job_id),
                    )
                else:
                    from pipeline.orchestrator import run_pipeline
                    run_log_id = run_pipeline(
                        category=job.config.category,
                        source_mode=job.config.source_mode,
                        keyword=job.config.keyword,
                        limit=job.config.limit,
                        marketplace=job.config.marketplace,
                        progress_callback=lambda event: self._handle_pipeline_progress(job_id, event),
                        cancel_check=lambda: self._is_cancel_requested(job_id),
                        **(
                            {
                                "seed_products": seed_products,
                                # A controlled full-research trial must still deliver
                                # auditable supplier/rejection evidence when every
                                # product is stopped by a hard filter.
                                "export_review_on_empty": True,
                            }
                            if seed_products is not None
                            else {}
                        ),
                    )
            finally:
                settings.alibaba_allow_mock_suppliers = previous_mock
                settings.enable_llm_verification = previous_llm

            if self._is_cancel_requested(job_id):
                self._mark_cancelled(job_id, "Cancelled after pipeline")
                return

            with self._lock:
                job.run_log_id = run_log_id
                self._persist_jobs_locked()
            exports = _exports_for_run(run_log_id, started)
            audit = audit_export(exports["json"]) if exports.get("json") else {}
            audit["manual_queue"] = manual_queue_summary()
            audit["supplier_evidence"] = _supplier_evidence_summary(audit)
            result_summary = summarize_run_result(
                run_log_id=run_log_id,
                config=job.config.__dict__,
                exports={k: str(v) for k, v in exports.items() if v},
                audit=audit,
            )

            run_status, run_error = _run_status(run_log_id)
            retry_delay: float | None = None
            with self._lock:
                job.run_log_id = run_log_id
                job.finished_at = datetime.now(UTC)
                job.exports = {k: str(v) for k, v in exports.items() if v}
                job.audit = audit
                job.result_summary = result_summary
                if run_status == "human_required":
                    job.status = "human_required"
                    job.message = "Human action required"
                    job.error = run_error or "Complete the required browser action, then resume the node"
                    self._add_event_locked(job, "human_required", job.message)
                elif run_status == "retry_wait":
                    job.status = "retry_wait"
                    job.message = "Run waiting for retry"
                    job.error = run_error
                    self._add_event_locked(job, "retry_wait", job.message)
                    retry_delay = _retry_delay(run_log_id)
                elif run_status == "running":
                    job.status = "retry_wait"
                    job.message = "Run still has a leased execution node"
                    job.error = run_error or "Waiting for the current lease owner or stale recovery"
                    self._add_event_locked(job, "retry_wait", job.message)
                    retry_delay = _lease_delay(run_log_id)
                elif run_status == "cancel_requested":
                    job.status = "cancel_requested"
                    job.message = "Cancellation waiting for running nodes"
                    job.error = run_error
                    self._add_event_locked(job, "cancel_requested", job.message)
                elif run_status == "failed":
                    job.status = "failed"
                    job.message = "Run has failed execution nodes"
                    job.error = run_error or "One or more execution nodes failed"
                    self._add_event_locked(job, "failed", job.message)
                elif run_status == "cancelled":
                    job.status = "cancelled"
                    job.message = "Run cancelled"
                    job.error = run_error
                    self._add_event_locked(job, "cancelled", job.message)
                elif _no_candidates_passed(exports, audit, run_id=run_log_id) and (
                    job.config.require_supplier_evidence or job.config.require_market_data
                ):
                    if job.exports:
                        job.status = "review_required"
                        job.message = "Review report generated"
                        job.error = "No candidates passed hard filters; a review report was generated"
                        self._add_event_locked(job, "review_required", job.message)
                    else:
                        job.status = "failed"
                        job.message = "No candidates passed filters"
                        job.error = "No candidates passed hard filters; no export was generated"
                        self._add_event_locked(job, "failed", job.message)
                elif job.config.require_supplier_evidence and not audit.get("supplier_evidence_ready"):
                    job.status = "failed"
                    job.message = "Supplier evidence missing"
                    job.error = "Real supplier match evidence required but missing from export"
                    self._add_event_locked(job, "failed", job.message)
                elif job.config.require_market_data and not audit.get("market_data_rich_ready"):
                    job.status = "failed"
                    job.message = "Market data missing"
                    job.error = "SellerSprite rich market data required but missing from export"
                    self._add_event_locked(job, "failed", job.message)
                else:
                    job.status = "success"
                    job.message = "Run complete"
                    self._add_event_locked(job, "success", job.message)
                self._persist_jobs_locked()
            if retry_delay is not None:
                self._schedule_retry(job_id, retry_delay)
        except Exception as exc:
            with self._lock:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.message = "Run cancelled"
                    job.error = str(exc)
                    self._add_event_locked(job, "cancelled", job.message)
                else:
                    job.status = "failed"
                    job.message = "Run failed"
                    job.error = str(exc)
                    self._add_event_locked(job, "failed", job.message)
                job.finished_at = datetime.now(UTC)
                self._persist_jobs_locked()

    def _prepare_full_research(self, job_id: str) -> list[dict[str, Any]] | None:
        with self._lock:
            job = self._jobs[job_id]
            cached = job.research if job.research.get("status") == "SUCCESS" else None
            if cached is None:
                job.message = "Exporting and scoring SellerSprite market data"
                self._add_event_locked(job, "market_research", job.message)
                self._persist_jobs_locked()

        payload = cached or _run_market_research(job.config)
        safe_payload = _research_job_payload(payload)
        status = str(safe_payload.get("status") or "INTERNAL").upper()
        with self._lock:
            job = self._jobs[job_id]
            job.research = safe_payload
            if status != "SUCCESS":
                job.finished_at = datetime.now(UTC)
                job.error = _research_status_message(status)
                if status in _RESEARCH_HUMAN_STATUSES:
                    job.status = "human_required"
                    job.message = "Browser action required for market research"
                    self._add_event_locked(
                        job, "human_required", job.message, stage="market_research",
                        error_code=status,
                    )
                else:
                    job.status = "failed"
                    job.message = "Market research failed"
                    self._add_event_locked(
                        job, "failed", job.message, stage="market_research",
                        error_code=status,
                    )
                self._persist_jobs_locked()
                return None

        seed_products = _research_seed_products(safe_payload, job.config)
        if not seed_products:
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
                job.message = "No eligible market candidates"
                job.error = (
                    "市场研究报告已生成，但没有符合规则且带有效 ASIN 的候选；"
                    "请调整 Amazon 列表或研究范围后重试。"
                )
                self._add_event_locked(job, "failed", job.message, stage="market_research")
                self._persist_jobs_locked()
            return None

        with self._lock:
            job = self._jobs[job_id]
            job.message = f"Market research complete; {len(seed_products)} candidates selected"
            self._add_event_locked(
                job,
                "market_research_complete",
                job.message,
                candidate_count=len(seed_products),
                research_run_id=safe_payload.get("run_id"),
            )
            self._persist_jobs_locked()
        return seed_products

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancel_requested)

    def _mark_cancelled(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "cancelled"
            job.finished_at = datetime.now(UTC)
            job.message = message
            self._add_event_locked(job, "cancelled", message)
            self._persist_jobs_locked()

    def _handle_pipeline_progress(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in {"running", "cancel_requested"}:
                return
            message = str(event.get("message") or event.get("stage") or "Pipeline progress")
            event_name = str(event.get("stage") or "progress")
            event_payload = {k: v for k, v in event.items() if k not in {"stage", "message"}}
            if job.status != "cancel_requested":
                job.message = message
            if event.get("run_id") not in (None, ""):
                try:
                    job.run_log_id = int(event["run_id"])
                except (TypeError, ValueError):
                    pass
            self._add_event_locked(job, event_name, message, **event_payload)
            self._persist_jobs_locked()

    def _add_event_locked(self, job: AgentJob, event: str, message: str = "", **extra: Any) -> None:
        payload = {
            "event": event,
            "message": message,
            "at": datetime.now(UTC).isoformat(),
        }
        for key, value in extra.items():
            if key not in payload:
                payload[key] = value
        job.events.append(payload)
        self._record_persistent_event(job, payload)

    def _record_persistent_event(self, job: AgentJob, payload: dict[str, Any]) -> None:
        try:
            record_run_event(
                event=str(payload.get("event") or "event"),
                message=str(payload.get("message") or ""),
                run_id=payload.get("run_id") or job.run_log_id,
                job_id=job.id,
                stage=payload.get("stage") or payload.get("event"),
                asin=payload.get("asin"),
                index=payload.get("index"),
                total=payload.get("total"),
                payload={k: v for k, v in payload.items() if k not in {"event", "message"}},
            )
        except Exception:
            return

    def _persist_jobs_locked(self) -> None:
        self._refresh_queue_positions_locked()
        payload = {
            "jobs": [job.to_dict() for job in sorted(self._jobs.values(), key=lambda j: j.created_at)],
            "queue": list(self._queue),
        }
        try:
            self._job_store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._job_store_path.with_suffix(self._job_store_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._job_store_path)
        except OSError:
            # Job persistence is operational telemetry; the in-memory queue must
            # keep working even if a host-mounted log directory has bad perms.
            return

    def _load_jobs(self) -> None:
        if not self._job_store_path.exists():
            return
        try:
            payload = json.loads(self._job_store_path.read_text(encoding="utf-8"))
        except Exception:
            return
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(raw_jobs, list):
            return
        for raw in raw_jobs:
            try:
                job = _job_from_dict(raw)
            except Exception:
                continue
            if (
                job.status == "failed"
                and job.exports
                and job.error
                == "No candidates passed hard filters; a review report was generated"
            ):
                # Compatibility migration for controlled-trial jobs completed
                # before review_required became a first-class outcome.
                job.status = "review_required"
                job.message = "Review report generated"
            if job.status in {"running", "cancel_requested", "retry_wait"}:
                recovered_status = self._restored_job_status(job)
                if recovered_status == "queued":
                    job.status = "queued"
                    job.finished_at = None
                    job.cancel_requested = False
                    job.message = "Queued to resume after server restart"
                    job.error = None
                    self._add_event_locked(job, "resume_queued", job.message)
                else:
                    job.status = recovered_status
                    job.finished_at = datetime.now(UTC)
                    if recovered_status == "success":
                        job.message = "Run complete"
                        job.error = None
                        self._add_event_locked(job, "recovered_complete", job.message)
                    elif recovered_status == "cancelled":
                        job.message = "Run cancelled"
                        job.error = None
                        self._add_event_locked(job, "cancelled", job.message)
                    elif recovered_status == "human_required":
                        job.message = "Human action required"
                        job.error = "Complete the required action and resume the node"
                        self._add_event_locked(job, "human_required", job.message)
                    elif recovered_status == "cancel_requested":
                        job.message = "Cancellation waiting for running nodes"
                        job.error = None
                        self._add_event_locked(job, "cancel_requested", job.message)
                    else:
                        job.message = "Interrupted by server restart"
                        job.error = "WebUI process stopped while job was running"
                        self._add_event_locked(job, "interrupted", job.message)
            self._jobs[job.id] = job
            if job.status == "cancel_requested" and job.run_log_id:
                self._schedule_cancel_recovery(
                    job.id,
                    int(job.run_log_id),
                    _lease_delay(int(job.run_log_id)),
                )
        queue = payload.get("queue") if isinstance(payload, dict) else []
        self._queue = deque(
            job_id for job_id in queue
            if job_id in self._jobs and self._jobs[job_id].status == "queued"
        )
        for job_id, job in self._jobs.items():
            if job.status == "queued" and job_id not in self._queue:
                self._queue.append(job_id)
        self._refresh_queue_positions_locked()
        if self._jobs:
            self._persist_jobs_locked()
        if self._queue:
            self._ensure_worker_locked()

    def _recover_interrupted_runs(self) -> None:
        """Recover leased nodes; only legacy open runs are forced to failed."""
        try:
            repository = ExecutionRepository(session_context=session_scope)
            repository.recover_stale(max_attempts=3, backoff_seconds=0)
            repository.promote_due_retries()
            with session_scope() as session:
                run_ids = [
                    run.id for run in session.query(RunLog).filter(
                        RunLog.status.in_(["running", "cancel_requested", "retry_wait"])
                    ).all()
                ]
            for run_id in run_ids:
                nodes = repository.list_nodes(run_id)
                if nodes:
                    repository.update_run_status(run_id)
                    continue
                with session_scope() as session:
                    run = session.get(RunLog, run_id)
                    if run is not None:
                        recoverable = (
                            isinstance(run.api_calls, dict)
                            and isinstance(run.api_calls.get("recoverable_config"), dict)
                        )
                        if recoverable:
                            run.status = "retry_wait"
                            run.finished_at = None
                            run.error_message = None
                        else:
                            run.status = "failed"
                            run.finished_at = datetime.now(UTC)
                            run.error_message = "Interrupted by WebUI server restart"
        except Exception:
            # The database might not have been initialized yet. The Docker
            # entrypoint initializes it before serving, and a later startup can retry.
            return

    def _restore_missing_sqlite_jobs(self) -> None:
        """Rebuild active UI jobs from SQLite when JSON telemetry is absent."""
        try:
            with session_scope() as session:
                runs = session.query(RunLog).filter(
                    RunLog.status.in_([
                        "running", "retry_wait", "human_required", "cancel_requested"
                    ])
                ).order_by(RunLog.id.asc()).all()
                snapshots = [
                    {
                        "id": run.id,
                        "status": run.status,
                        "config": dict((run.api_calls or {}).get("recoverable_config") or {}),
                        "error": run.error_message,
                    }
                    for run in runs
                    if isinstance(run.api_calls, dict)
                    and isinstance((run.api_calls or {}).get("recoverable_config"), dict)
                ]
        except Exception:
            return
        with self._lock:
            known_run_ids = {
                int(job.run_log_id) for job in self._jobs.values() if job.run_log_id
            }
            for snapshot in snapshots:
                run_id = int(snapshot["id"])
                if run_id in known_run_ids:
                    continue
                config = snapshot["config"]
                job = AgentJob(
                    id=f"recovered-run-{run_id}",
                    run_log_id=run_id,
                    config=AgentRunConfig(
                        category=str(config.get("category") or ""),
                        source_mode=str(config.get("source_mode") or "category"),
                        keyword=str(config.get("keyword") or ""),
                        marketplace=str(config.get("marketplace") or "US"),
                        limit=int(config.get("limit") or 100),
                        no_mock=not bool(config.get("allow_mock_suppliers", False)),
                        workflow_mode=(
                            "full_research" if config.get("seed_products") else "standard"
                        ),
                    ),
                )
                if snapshot["status"] == "human_required":
                    job.status = "human_required"
                    job.message = "Human action required"
                    job.error = snapshot["error"]
                elif snapshot["status"] == "cancel_requested":
                    job.status = "cancel_requested"
                    job.cancel_requested = True
                    job.message = "Cancellation waiting for running nodes"
                else:
                    job.status = "queued"
                    job.message = "Recovered from SQLite execution state"
                    self._queue.append(job.id)
                self._add_event_locked(job, "sqlite_recovered", job.message, run_id=run_id)
                self._jobs[job.id] = job
                if job.status == "cancel_requested":
                    self._schedule_cancel_recovery(
                        job.id, run_id, _lease_delay(run_id)
                    )
            self._refresh_queue_positions_locked()
            if snapshots:
                self._persist_jobs_locked()
            if self._queue:
                self._ensure_worker_locked()

    def _restored_job_status(self, job: AgentJob) -> str:
        if not job.run_log_id:
            return "failed"
        status, _error = _run_status(int(job.run_log_id))
        if status in {"running", "retry_wait"}:
            return "queued"
        if status in {"human_required", "failed", "cancelled", "success", "cancel_requested"}:
            return status
        return "failed"

    def _prepare_recoverable_retry(self, run_id: int, actor_ref: str) -> bool:
        repository = ExecutionRepository(session_context=session_scope)
        nodes = repository.list_nodes(run_id)
        if not nodes:
            return False
        changed = False
        for node in nodes:
            if node["status"] in {"failed", "timed_out"}:
                repository.retry_node(
                    int(node["id"]), reason="whole-run retry requested", actor_ref=actor_ref,
                    expected_resume_token=node.get("resume_token"),
                )
                changed = True
            elif node["status"] == "cancelled":
                repository.force_rerun(
                    int(node["id"]), reason="whole-run retry after cancellation", actor_ref=actor_ref,
                    expected_resume_token=node.get("resume_token"),
                )
                changed = True
        return changed

    def _schedule_retry(self, job_id: str, delay_seconds: float) -> None:
        def requeue() -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job.status != "retry_wait":
                    return
                job.status = "queued"
                job.finished_at = None
                job.message = "Retry backoff elapsed; queued to resume"
                self._add_event_locked(job, "retry_queued", job.message)
                if job_id not in self._queue:
                    self._queue.append(job_id)
                self._refresh_queue_positions_locked()
                self._ensure_worker_locked()
                self._persist_jobs_locked()
                self._condition.notify_all()

        timer = threading.Timer(max(float(delay_seconds), 0.05), requeue)
        timer.daemon = True
        timer.start()

    def _schedule_cancel_recovery(
        self,
        job_id: str,
        run_id: int,
        delay_seconds: float,
    ) -> None:
        def recover() -> None:
            repository = ExecutionRepository(session_context=session_scope)
            try:
                repository.recover_stale(run_id=run_id, max_attempts=1, backoff_seconds=0)
                repository.cancel_run(
                    run_id,
                    reason="complete cancellation after interrupted worker lease",
                    actor_ref=job_id,
                )
                status = repository.update_run_status(run_id)
            except Exception:
                status = "cancel_requested"
            if status == "cancel_requested":
                self._schedule_cancel_recovery(job_id, run_id, _lease_delay(run_id))
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job.status != "cancel_requested":
                    return
                job.status = "cancelled"
                job.finished_at = datetime.now(UTC)
                job.message = "Run cancelled"
                job.error = None
                self._add_event_locked(job, "cancelled", job.message)
                self._persist_jobs_locked()

        timer = threading.Timer(max(float(delay_seconds), 0.05), recover)
        timer.daemon = True
        timer.start()


def _preflight_error(preflight: dict[str, Any]) -> str:
    blocking = [c for c in preflight.get("checks", []) if c.get("level") == "error"]
    if not blocking:
        return "Preflight failed"
    return "; ".join(f"{c['label']}: {c['detail']}" for c in blocking)


def _run_market_research(config: AgentRunConfig) -> dict[str, Any]:
    """Run the real browser export used by the controlled full-workflow job."""
    from agent.seller_research_service import run_competitor_export
    from db.session import engine as db_engine

    label = (
        config.research_keyword
        or config.research_niche_label
        or config.keyword
        or config.category
    ).strip()
    return run_competitor_export(
        label,
        niche_label=(config.research_niche_label or label).strip(),
        marketplace=config.marketplace,
        category=config.research_category,
        engine=db_engine,
        generate_ai_reasons=bool(config.generate_ai_reasons),
        export=True,
    )


def _research_job_payload(payload: object) -> dict[str, Any]:
    """Keep only report, score and source evidence needed by the job/UI."""
    if not isinstance(payload, dict):
        return {"status": "INTERNAL"}
    safe: dict[str, Any] = {}
    for key in (
        "status",
        "keyword",
        "niche_label",
        "marketplace",
        "category",
        "ruleset_version",
        "quality_summary",
        "source",
        "items",
        "excluded_items",
        "ai_reasons",
        "run_id",
        "exports",
        "message",
    ):
        value = payload.get(key)
        if value is not None:
            safe[key] = value
    safe["status"] = str(safe.get("status") or "INTERNAL").upper()
    return safe


def _research_seed_products(
    payload: dict[str, Any],
    config: AgentRunConfig,
) -> list[dict[str, Any]]:
    """Convert ranked eligible seller representatives into pipeline products."""
    from agent.sellersprite_policy import ASIN_RE

    seeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    for item in rows:
        if not isinstance(item, dict):
            continue
        asin = str(item.get("representative_asin") or "").strip().upper()
        if not ASIN_RE.fullmatch(asin) or asin in seen:
            continue
        seen.add(asin)
        raw_evidence = {
            "source_mode": "seller_research",
            "source_query": (
                config.research_keyword
                or config.research_niche_label
                or config.keyword
                or config.category
            ),
            "research_run_id": payload.get("run_id"),
            "research_fit_score": item.get("fit_score"),
            "research_fit_category": item.get("fit_category"),
            "research_fit_reasons": item.get("fit_reasons") or [],
            "research_monthly_sales": item.get("monthly_sales"),
            "research_monthly_revenue": item.get("monthly_revenue"),
            "research_seller": item.get("seller"),
        }
        seeds.append({
            "asin": asin,
            "marketplace": config.marketplace,
            "title": str(item.get("representative_title") or asin),
            "category": config.category or None,
            "brand": item.get("brand"),
            "price": item.get("price"),
            "rating": item.get("rating"),
            "review_count": item.get("review_count"),
            "listing_url": f"https://www.amazon.com/dp/{asin}",
            "raw_data": raw_evidence,
        })
        if len(seeds) >= int(config.limit):
            break
    return seeds


def _research_status_message(status: str) -> str:
    messages = {
        "EXTENSION_UNAVAILABLE": "卖家精灵插件未就绪，请确认 9222 Chrome、扩展和 Amazon 列表页后重试。",
        "SELLERSPRITE_LOGIN_REQUIRED": "卖家精灵需要登录，请在 9222 Chrome 完成登录后重试。",
        "SELLERSPRITE_PERMISSION_REQUIRED": "卖家精灵扩展需要页面权限，请在 Chrome 中授权后重试。",
        "SELLERSPRITE_QUOTA_EXCEEDED": "卖家精灵账号额度不足，请处理账号额度后重试。",
        "CAPTCHA": "浏览器出现验证码，请在 9222 Chrome 完成人工验证后重试。",
        "NEEDS_HUMAN": "市场研究需要浏览器人工处理，完成后重试。",
        "EXPORT_FAILED": "卖家精灵导出失败，请确认当前 Amazon 列表已加载数据后重试。",
        "DOWNLOAD_TIMEOUT": "等待卖家精灵下载超时，请检查浏览器下载目录后重试。",
        "INVALID_EXPORT": "卖家精灵导出文件无效，请刷新 Amazon 列表后重试。",
    }
    return messages.get(status, f"市场研究未完成（{status}），请检查浏览器状态后重试。")


def _supplier_evidence_summary(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "count": audit.get("supplier_evidence_count", 0),
        "rate": audit.get("supplier_evidence_rate", 0.0),
        "ready": bool(audit.get("supplier_evidence_ready")),
        "real_supplier_count": audit.get("real_supplier_count", 0),
        "source_counts": audit.get("supplier_source_counts", {}),
        "avg_spec_match_score": audit.get("avg_spec_match_score"),
        "avg_match_quality_score": audit.get("avg_match_quality_score"),
    }


def _no_candidates_passed(
    exports: dict[str, Any],
    audit: dict[str, Any],
    *,
    run_id: int | None = None,
) -> bool:
    # Review-on-empty exports contain rejected records by design. The durable
    # run count remains the authority for whether anything actually passed.
    if run_id is not None:
        try:
            with session_scope() as session:
                row = session.get(RunLog, int(run_id))
                if row is not None:
                    return int(row.candidates_after_filter or 0) == 0
        except Exception:
            # Keep compatibility with partially initialized/debug runtimes.
            pass
    if "candidate_count" in audit:
        try:
            return int(audit.get("candidate_count") or 0) == 0
        except (TypeError, ValueError):
            return False
    return not bool(exports.get("json"))


def _runtime_allow_mock_suppliers(config: AgentRunConfig) -> bool:
    dev_flag = str(os.getenv("DEV_ALLOW_MOCK_SUPPLIERS") or "").strip().lower() in {"1", "true", "yes", "on"}
    return bool(dev_flag and not config.no_mock)


def _exports_for_run(run_id: int, started: float) -> dict[str, Path]:
    """Return only the newest fully committed artifact set for this run."""
    try:
        with session_scope() as session:
            latest = (
                session.query(ArtifactManifest)
                .filter_by(run_id=int(run_id), status="committed")
                .order_by(ArtifactManifest.id.desc())
                .first()
            )
            if latest is None:
                return latest_export_after(started)
            rows = (
                session.query(ArtifactManifest)
                .filter_by(
                    run_id=int(run_id),
                    artifact_set_id=latest.artifact_set_id,
                    status="committed",
                )
                .order_by(ArtifactManifest.id.asc())
                .all()
            )
            exports: dict[str, Path] = {}
            for row in rows:
                path = Path(row.final_path)
                if row.logical_name in {"excel", "json"}:
                    exports[row.logical_name.replace("excel", "xlsx")] = path
                elif row.artifact_type == "markdown":
                    exports.setdefault("markdown", path)
            return exports
    except Exception:
        # Legacy and mocked runs have no artifact manifests.
        return latest_export_after(started)


def _run_status(run_id: int) -> tuple[str, str | None]:
    """Read durable run state; mocked/legacy runs without a row remain compatible."""
    try:
        with session_scope() as session:
            run = session.get(RunLog, int(run_id))
            if run is None:
                return "success", None
            error = run.error_message
            if not error and run.status in {"failed", "human_required", "retry_wait"}:
                node = (
                    session.query(ExecutionNode)
                    .filter(
                        ExecutionNode.run_id == int(run_id),
                        ExecutionNode.status.in_(["failed", "timed_out", "human_required", "retry_wait"]),
                    )
                    .order_by(ExecutionNode.id.asc())
                    .first()
                )
                if node is not None:
                    error = node.error_detail or node.error_code
            return str(run.status or "success"), error
    except Exception:
        return "success", None


def _retry_delay(run_id: int) -> float:
    try:
        with session_scope() as session:
            dates = [
                row[0]
                for row in session.query(ExecutionNode.next_retry_at).filter_by(
                    run_id=int(run_id), status="retry_wait"
                ).all()
                if row[0] is not None
            ]
        if not dates:
            return 0.05
        now = datetime.now(UTC).replace(tzinfo=None)
        return max(min(dates) - now, timedelta()).total_seconds()
    except Exception:
        return 1.0


def _lease_delay(run_id: int) -> float:
    try:
        with session_scope() as session:
            dates = [
                row[0]
                for row in session.query(ExecutionNode.lease_expires_at).filter_by(
                    run_id=int(run_id), status="running"
                ).all()
                if row[0] is not None
            ]
        if not dates:
            return 0.05
        now = datetime.now(UTC).replace(tzinfo=None)
        return max(min(dates) - now, timedelta()).total_seconds() + 0.05
    except Exception:
        return 1.0


def _job_from_dict(raw: dict[str, Any]) -> AgentJob:
    config_raw = raw.get("config") or {}
    config = AgentRunConfig(
        category=str(config_raw.get("category") or ""),
        source_mode=config_raw.get("source_mode") or "category",
        keyword=str(config_raw.get("keyword") or ""),
        marketplace=str(config_raw.get("marketplace") or "US"),
        limit=int(config_raw.get("limit") or 10),
        no_mock=bool(config_raw.get("no_mock", True)),
        llm_verification=config_raw.get("llm_verification"),
        require_market_data=bool(config_raw.get("require_market_data", False)),
        require_supplier_evidence=bool(config_raw.get("require_supplier_evidence", False)),
        workflow_mode=config_raw.get("workflow_mode") or "standard",
        research_keyword=str(config_raw.get("research_keyword") or ""),
        research_niche_label=str(config_raw.get("research_niche_label") or ""),
        research_category=config_raw.get("research_category"),
        generate_ai_reasons=bool(config_raw.get("generate_ai_reasons", False)),
    )
    job = AgentJob(
        config=config,
        id=str(raw.get("id") or ""),
        status=raw.get("status") or "queued",
        created_at=_parse_dt(raw.get("created_at")) or datetime.now(UTC),
        started_at=_parse_dt(raw.get("started_at")),
        finished_at=_parse_dt(raw.get("finished_at")),
        run_log_id=raw.get("run_log_id"),
        message=str(raw.get("message") or ""),
        error=raw.get("error"),
        exports=raw.get("exports") if isinstance(raw.get("exports"), dict) else {},
        research=raw.get("research") if isinstance(raw.get("research"), dict) else {},
        audit=raw.get("audit") if isinstance(raw.get("audit"), dict) else {},
        result_summary=raw.get("result_summary") if isinstance(raw.get("result_summary"), dict) else {},
        queue_position=raw.get("queue_position"),
        cancel_requested=bool(raw.get("cancel_requested", False)),
        retry_of=raw.get("retry_of"),
        attempt=int(raw.get("attempt") or 1),
        events=raw.get("events") if isinstance(raw.get("events"), list) else [],
    )
    if not job.id:
        raise ValueError("job id missing")
    return job


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

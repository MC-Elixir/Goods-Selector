"""Agent runtime: environment + tools + prompt policy + execution loop."""
from __future__ import annotations

import threading
import time
import os
import json
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import settings
from db.init_db import init_db
from db.models import RunLog
from db.session import session_scope
from agent.history import audit_export, latest_export_after
from agent.manual_queue import manual_queue_summary
from agent.preflight import run_preflight
from agent.result_summarizer import summarize_run_result
from agent.run_events import record_run_event
from agent.seller_sprite_diagnostics import seller_sprite_market_data_guard
from agent.state import AgentJob, AgentRunConfig


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


class AgentRuntime:
    def __init__(self, job_store_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._jobs: dict[str, AgentJob] = {}
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None
        self._job_store_path = Path(job_store_path) if job_store_path else settings.log_dir / "agent_jobs.json"
        self._recover_interrupted_runs()
        self._load_jobs()

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
            return job.to_dict()

    def retry_job(self, job_id: str) -> AgentJob:
        with self._lock:
            original = self._jobs.get(job_id)
            if not original:
                raise KeyError(job_id)
            if original.status not in {"failed", "cancelled"}:
                raise ValueError(f"cannot retry job in status {original.status}")
            job = AgentJob(
                config=replace(original.config),
                retry_of=original.id,
                attempt=int(original.attempt or 1) + 1,
            )
        return self._enqueue_job(job)

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
                from pipeline.orchestrator import run_pipeline

                run_log_id = run_pipeline(
                    category=job.config.category,
                    source_mode=job.config.source_mode,
                    keyword=job.config.keyword,
                    limit=job.config.limit,
                    marketplace=job.config.marketplace,
                    progress_callback=lambda event: self._handle_pipeline_progress(job_id, event),
                    cancel_check=lambda: self._is_cancel_requested(job_id),
                )
            finally:
                settings.alibaba_allow_mock_suppliers = previous_mock
                settings.enable_llm_verification = previous_llm

            if self._is_cancel_requested(job_id):
                self._mark_cancelled(job_id, "Cancelled after pipeline")
                return

            exports = latest_export_after(started)
            audit = audit_export(exports["json"]) if exports.get("json") else {}
            audit["manual_queue"] = manual_queue_summary()
            audit["supplier_evidence"] = _supplier_evidence_summary(audit)
            result_summary = summarize_run_result(
                run_log_id=run_log_id,
                config=job.config.__dict__,
                exports={k: str(v) for k, v in exports.items() if v},
                audit=audit,
            )

            with self._lock:
                job.run_log_id = run_log_id
                job.finished_at = datetime.now(UTC)
                job.exports = {k: str(v) for k, v in exports.items() if v}
                job.audit = audit
                job.result_summary = result_summary
                if _no_candidates_passed(exports, audit) and (
                    job.config.require_supplier_evidence or job.config.require_market_data
                ):
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
            if job.status in {"running", "cancel_requested"}:
                job.status = "failed"
                job.finished_at = datetime.now(UTC)
                job.message = "Interrupted by server restart"
                job.error = "WebUI process stopped while job was running"
                self._add_event_locked(job, "interrupted", job.message)
            self._jobs[job.id] = job
        queue = payload.get("queue") if isinstance(payload, dict) else []
        self._queue = deque(
            job_id for job_id in queue
            if job_id in self._jobs and self._jobs[job_id].status == "queued"
        )
        self._refresh_queue_positions_locked()
        if self._jobs:
            self._persist_jobs_locked()
        if self._queue:
            self._ensure_worker_locked()

    def _recover_interrupted_runs(self) -> None:
        """Close runs left open when this single-process WebUI was restarted."""
        try:
            with session_scope() as session:
                runs = session.query(RunLog).filter(RunLog.status == "running").all()
                for run in runs:
                    run.status = "failed"
                    run.finished_at = datetime.now(UTC)
                    run.error_message = "Interrupted by WebUI server restart"
        except Exception:
            # The database might not have been initialized yet. The Docker
            # entrypoint initializes it before serving, and a later startup can retry.
            return


def _preflight_error(preflight: dict[str, Any]) -> str:
    blocking = [c for c in preflight.get("checks", []) if c.get("level") == "error"]
    if not blocking:
        return "Preflight failed"
    return "; ".join(f"{c['label']}: {c['detail']}" for c in blocking)


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


def _no_candidates_passed(exports: dict[str, Any], audit: dict[str, Any]) -> bool:
    if "candidate_count" in audit:
        try:
            return int(audit.get("candidate_count") or 0) == 0
        except (TypeError, ValueError):
            return False
    return not bool(exports.get("json"))


def _runtime_allow_mock_suppliers(config: AgentRunConfig) -> bool:
    dev_flag = str(os.getenv("DEV_ALLOW_MOCK_SUPPLIERS") or "").strip().lower() in {"1", "true", "yes", "on"}
    return bool(dev_flag and not config.no_mock)


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

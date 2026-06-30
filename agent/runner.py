"""Agent runtime: environment + tools + prompt policy + execution loop."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from config.settings import settings
from db.init_db import init_db
from agent.history import audit_export, latest_export_after
from agent.preflight import run_preflight
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
- After each run, audit exported results for mock suppliers, suspicious prices,
  margins, and candidate counts before presenting them.

Loop:
Observe environment state -> choose tool -> run tool -> update state -> repeat
until the job succeeds, fails with a clear reason, or needs human intervention.
"""


class AgentRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, AgentJob] = {}

    def preflight(self) -> dict[str, Any]:
        return run_preflight()

    def start_run(self, config: AgentRunConfig) -> AgentJob:
        job = AgentJob(config=config)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run_job, args=(job.id,), daemon=True)
        thread.start()
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in jobs]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = datetime.utcnow()
            job.message = "Running preflight"

        try:
            preflight = run_preflight()
            if not preflight["ready"]:
                raise RuntimeError(_preflight_error(preflight))

            init_db()

            started = time.time()
            with self._lock:
                job.message = "Running sourcing pipeline"

            # settings is a process-wide singleton. The web agent runs one job at a time
            # in normal use, so temporarily applying mode flags is sufficient here.
            previous_mock = settings.alibaba_allow_mock_suppliers
            previous_llm = settings.enable_llm_verification
            settings.alibaba_allow_mock_suppliers = not job.config.no_mock
            if job.config.llm_verification is not None:
                settings.enable_llm_verification = bool(job.config.llm_verification)
            try:
                from pipeline.orchestrator import run_pipeline

                run_log_id = run_pipeline(
                    category=job.config.category,
                    limit=job.config.limit,
                    marketplace=job.config.marketplace,
                )
            finally:
                settings.alibaba_allow_mock_suppliers = previous_mock
                settings.enable_llm_verification = previous_llm

            exports = latest_export_after(started)
            audit = audit_export(exports["json"]) if exports.get("json") else {}

            with self._lock:
                job.run_log_id = run_log_id
                job.status = "success"
                job.finished_at = datetime.utcnow()
                job.message = "Run complete"
                job.exports = {k: str(v) for k, v in exports.items() if v}
                job.audit = audit
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                job.message = "Run failed"
                job.error = str(exc)


def _preflight_error(preflight: dict[str, Any]) -> str:
    blocking = [c for c in preflight.get("checks", []) if c.get("level") == "error"]
    if not blocking:
        return "Preflight failed"
    return "; ".join(f"{c['label']}: {c['detail']}" for c in blocking)

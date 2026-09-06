"""Controlled small sourcing run used for live end-to-end validation."""
from __future__ import annotations

import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from agent.history import audit_export, latest_export_after
from agent.manual_queue import manual_queue_summary
from agent.preflight import run_preflight
from agent.seller_sprite_diagnostics import seller_sprite_market_data_guard
from config.settings import settings
from db.init_db import init_db
from db.models import RunLog
from db.session import session_scope


@dataclass
class SmokeRunConfig:
    category: str
    marketplace: str = "US"
    limit: int = 3
    top_n: int = 5
    no_mock: bool = True
    llm_verification: bool = False
    require_preflight: bool = True
    require_market_data: bool = False
    require_supplier_evidence: bool = False
    timeout_seconds: int = 180


def run_smoke(config: SmokeRunConfig) -> dict[str, Any]:
    """Run a constrained live pipeline and return an audit-ready summary."""
    started = time.time()
    preflight = run_preflight()
    if config.require_preflight and not preflight["ready"]:
        return {
            "status": "preflight_failed",
            "config": asdict(config),
            "preflight": preflight,
            "manual_queue": manual_queue_summary(),
            "duration_seconds": round(time.time() - started, 2),
        }
    if config.require_market_data:
        ready, reason = seller_sprite_market_data_guard()
        if not ready:
            return {
                "status": "market_data_unavailable",
                "config": asdict(config),
                "error": reason,
                "preflight": preflight,
                "manual_queue": manual_queue_summary(),
                "duration_seconds": round(time.time() - started, 2),
            }

    init_db()
    previous_mock = settings.alibaba_allow_mock_suppliers
    previous_llm = settings.enable_llm_verification
    settings.alibaba_allow_mock_suppliers = not config.no_mock
    settings.enable_llm_verification = config.llm_verification
    try:
        try:
            from pipeline.orchestrator import run_pipeline

            with _timeout_after(config.timeout_seconds):
                run_log_id = run_pipeline(
                    category=config.category,
                    limit=config.limit,
                    marketplace=config.marketplace,
                    top_n=config.top_n,
                    export=True,
                    export_review_on_empty=True,
                )
        except SmokeRunTimeout as exc:
            return _failure_summary("timeout", config, preflight, started, str(exc))
        except Exception as exc:
            return _failure_summary("failed", config, preflight, started, str(exc))
    finally:
        settings.alibaba_allow_mock_suppliers = previous_mock
        settings.enable_llm_verification = previous_llm

    exports = latest_export_after(started)
    audit = audit_export(exports["json"]) if exports.get("json") else {}
    audit["manual_queue"] = manual_queue_summary()
    audit["market_data"] = _market_data_summary(audit)
    audit["supplier_evidence"] = _supplier_evidence_summary(audit)
    if config.require_supplier_evidence and not audit["supplier_evidence"]["ready"]:
        return {
            "status": "supplier_evidence_missing",
            "config": asdict(config),
            "run_log_id": run_log_id,
            "run_log": _run_log_summary(run_log_id),
            "exports": {k: str(v) for k, v in exports.items() if v},
            "audit": audit,
            "preflight": preflight,
            "duration_seconds": round(time.time() - started, 2),
        }
    if config.require_market_data and not audit["market_data"]["rich_ready"]:
        return {
            "status": "market_data_missing",
            "config": asdict(config),
            "run_log_id": run_log_id,
            "run_log": _run_log_summary(run_log_id),
            "exports": {k: str(v) for k, v in exports.items() if v},
            "audit": audit,
            "preflight": preflight,
            "duration_seconds": round(time.time() - started, 2),
        }
    return {
        "status": "success",
        "config": asdict(config),
        "run_log_id": run_log_id,
        "run_log": _run_log_summary(run_log_id),
        "exports": {k: str(v) for k, v in exports.items() if v},
        "audit": audit,
        "preflight": preflight,
        "duration_seconds": round(time.time() - started, 2),
    }


class SmokeRunTimeout(TimeoutError):
    pass


@contextmanager
def _timeout_after(seconds: int):
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handle_timeout(signum, frame):  # noqa: ARG001
        raise SmokeRunTimeout(f"smoke run exceeded {seconds}s")

    previous = signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _failure_summary(
    status: str,
    config: SmokeRunConfig,
    preflight: dict[str, Any],
    started: float,
    error: str,
) -> dict[str, Any]:
    exports = latest_export_after(started)
    audit = audit_export(exports["json"]) if exports.get("json") else {}
    audit["manual_queue"] = manual_queue_summary()
    audit["market_data"] = _market_data_summary(audit)
    audit["supplier_evidence"] = _supplier_evidence_summary(audit)
    return {
        "status": status,
        "config": asdict(config),
        "error": error,
        "exports": {k: str(v) for k, v in exports.items() if v},
        "audit": audit,
        "preflight": preflight,
        "duration_seconds": round(time.time() - started, 2),
    }


def _run_log_summary(run_log_id: int | None) -> dict[str, Any]:
    if not run_log_id:
        return {}
    try:
        with session_scope() as session:
            run = session.get(RunLog, run_log_id)
            if not run:
                return {}
            return {
                "status": run.status,
                "products_crawled": run.products_crawled,
                "suppliers_matched": run.suppliers_matched,
                "profits_calculated": run.profits_calculated,
                "candidates_after_filter": run.candidates_after_filter,
                "api_calls": run.api_calls or {},
                "error_message": run.error_message,
            }
    except Exception:
        return {}


def _market_data_summary(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "count": audit.get("market_data_count", 0),
        "rate": audit.get("market_data_rate", 0.0),
        "ready": bool(audit.get("market_data_ready")),
        "rich_count": audit.get("market_data_rich_count", 0),
        "rich_rate": audit.get("market_data_rich_rate", 0.0),
        "rich_ready": bool(audit.get("market_data_rich_ready")),
    }


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

"""Small local feedback store for controlled client trials."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import settings

_LOCK = threading.RLock()
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_BLOCKED_STAGES = {
    "none",
    "preflight",
    "market_research",
    "sourcing",
    "report",
}
_SOURCE_MODES = {"category", "keyword"}
_TERMINAL_STATUSES = {
    "success",
    "failed",
    "cancelled",
    "human_required",
    "review_required",
}
_INSTALLER_READINESS = {
    "minimum_sample_size": 3,
    "minimum_source_mode_count": 2,
    "minimum_delivery_rate": 2 / 3,
    "minimum_average_ease": 4.0,
    "minimum_average_usefulness": 4.0,
    "minimum_would_use_again_rate": 2 / 3,
    "minimum_no_blocker_rate": 2 / 3,
}


def feedback_store_path() -> Path:
    return settings.export_dir.parent / "trial_feedback.json"


def save_trial_feedback(
    payload: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    item = _validated_feedback(payload)
    target = path or feedback_store_path()
    now = datetime.now(UTC).isoformat()

    with _LOCK:
        rows = _read_rows(target)
        existing = next(
            (row for row in rows if row.get("job_id") == item["job_id"]),
            None,
        )
        if existing:
            item["id"] = existing.get("id") or uuid.uuid4().hex
            item["created_at"] = existing.get("created_at") or now
            item["updated_at"] = now
            rows = [
                item if row.get("job_id") == item["job_id"] else row
                for row in rows
            ]
        else:
            item["id"] = uuid.uuid4().hex
            item["created_at"] = now
            item["updated_at"] = now
            rows.append(item)
        _write_rows(target, rows)
    return item


def list_trial_feedback(
    *,
    job_id: str | None = None,
    limit: int = 100,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    target = path or feedback_store_path()
    safe_limit = max(1, min(int(limit), 500))
    with _LOCK:
        rows = _read_rows(target)
    if job_id:
        rows = [row for row in rows if row.get("job_id") == job_id]
    return list(reversed(rows[-safe_limit:]))


def summarize_trial_feedback(
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return a transparent go/no-go scorecard for the installer phase."""
    rows = list_trial_feedback(limit=500, path=path)
    sample_size = len(rows)
    average_ease = _average(rows, "ease")
    average_usefulness = _average(rows, "result_usefulness")
    source_modes = sorted({
        str(row.get("source_mode"))
        for row in rows
        if row.get("source_mode") in _SOURCE_MODES
    })
    delivery_rate = _rate(
        rows,
        lambda row: (
            row.get("workflow_completed") is True
            and row.get("deliverables_ready") is True
        ),
    )
    would_use_again_rate = _rate(
        rows, lambda row: row.get("would_use_again") is True
    )
    no_blocker_rate = _rate(
        rows, lambda row: row.get("blocked_stage") == "none"
    )
    blocker_counts = {
        stage: sum(1 for row in rows if row.get("blocked_stage") == stage)
        for stage in sorted(_BLOCKED_STAGES)
    }
    nonzero_blockers = {
        stage: count
        for stage, count in blocker_counts.items()
        if stage != "none" and count > 0
    }
    top_blocker = (
        max(nonzero_blockers, key=lambda stage: (nonzero_blockers[stage], stage))
        if nonzero_blockers
        else None
    )

    criteria = [
        _criterion(
            "sample_size",
            sample_size,
            _INSTALLER_READINESS["minimum_sample_size"],
        ),
        _criterion(
            "source_mode_count",
            len(source_modes),
            _INSTALLER_READINESS["minimum_source_mode_count"],
        ),
        _criterion(
            "delivery_rate",
            delivery_rate,
            _INSTALLER_READINESS["minimum_delivery_rate"],
        ),
        _criterion(
            "average_ease",
            average_ease,
            _INSTALLER_READINESS["minimum_average_ease"],
        ),
        _criterion(
            "average_usefulness",
            average_usefulness,
            _INSTALLER_READINESS["minimum_average_usefulness"],
        ),
        _criterion(
            "would_use_again_rate",
            would_use_again_rate,
            _INSTALLER_READINESS["minimum_would_use_again_rate"],
        ),
        _criterion(
            "no_blocker_rate",
            no_blocker_rate,
            _INSTALLER_READINESS["minimum_no_blocker_rate"],
        ),
    ]
    ready = bool(sample_size) and all(item["passed"] for item in criteria)
    if sample_size == 0:
        status = "no_data"
    elif sample_size < _INSTALLER_READINESS["minimum_sample_size"]:
        status = "collecting"
    elif ready:
        status = "ready_for_installer"
    else:
        status = "needs_improvement"

    return {
        "status": status,
        "ready_for_installer": ready,
        "sample_size": sample_size,
        "minimum_sample_size": _INSTALLER_READINESS["minimum_sample_size"],
        "remaining_trials": max(
            0, _INSTALLER_READINESS["minimum_sample_size"] - sample_size
        ),
        "metrics": {
            "source_mode_count": len(source_modes),
            "source_modes": source_modes,
            "delivery_rate": delivery_rate,
            "average_ease": average_ease,
            "average_usefulness": average_usefulness,
            "would_use_again_rate": would_use_again_rate,
            "no_blocker_rate": no_blocker_rate,
        },
        "criteria": criteria,
        "blocker_counts": blocker_counts,
        "top_blocker": top_blocker,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def _validated_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("feedback body must be an object")
    job_id = str(payload.get("job_id") or "").strip()
    if not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id is invalid")
    ease = _rating(payload.get("ease"), "ease")
    usefulness = _rating(payload.get("result_usefulness"), "result_usefulness")
    would_use_again = payload.get("would_use_again")
    if not isinstance(would_use_again, bool):
        raise ValueError("would_use_again must be a boolean")
    blocked_stage = str(payload.get("blocked_stage") or "none").strip()
    if blocked_stage not in _BLOCKED_STAGES:
        raise ValueError("blocked_stage is invalid")
    job_status = str(payload.get("job_status") or "").strip()
    if job_status and job_status not in _TERMINAL_STATUSES:
        raise ValueError("job_status is invalid")
    source_mode = str(payload.get("source_mode") or "").strip()
    if source_mode not in _SOURCE_MODES:
        raise ValueError("source_mode is invalid")
    workflow_completed = payload.get("workflow_completed")
    if not isinstance(workflow_completed, bool):
        raise ValueError("workflow_completed must be a boolean")
    deliverables_ready = payload.get("deliverables_ready")
    if not isinstance(deliverables_ready, bool):
        raise ValueError("deliverables_ready must be a boolean")
    comment = str(payload.get("comment") or "").strip()
    if len(comment) > 500:
        raise ValueError("comment must be at most 500 characters")
    return {
        "job_id": job_id,
        "job_status": job_status or None,
        "source_mode": source_mode,
        "workflow_completed": workflow_completed,
        "deliverables_ready": deliverables_ready,
        "ease": ease,
        "result_usefulness": usefulness,
        "would_use_again": would_use_again,
        "blocked_stage": blocked_stage,
        "comment": comment,
    }


def _rating(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer from 1 to 5")
    try:
        rating = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer from 1 to 5") from exc
    if rating < 1 or rating > 5:
        raise ValueError(f"{field} must be an integer from 1 to 5")
    return rating


def _average(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [
        float(row[field])
        for row in rows
        if isinstance(row.get(field), (int, float))
        and not isinstance(row.get(field), bool)
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _rate(
    rows: list[dict[str, Any]],
    predicate,
) -> float | None:
    if not rows:
        return None
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 3)


def _criterion(key: str, actual: float | int | None, target: float | int) -> dict:
    return {
        "key": key,
        "actual": actual,
        "target": round(float(target), 3),
        "operator": ">=",
        "passed": actual is not None and float(actual) + 1e-9 >= float(target),
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)

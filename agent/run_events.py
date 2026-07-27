"""Persistent Agent loop event timeline."""
from __future__ import annotations

from typing import Any

from db.models import RunEvent
from db.session import session_scope


def record_run_event(
    *,
    event: str,
    message: str = "",
    run_id: int | None = None,
    job_id: str | None = None,
    stage: str | None = None,
    asin: str | None = None,
    index: int | None = None,
    total: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    with session_scope() as session:
        session.add(RunEvent(
            run_id=run_id,
            job_id=job_id,
            event=event,
            stage=stage,
            asin=asin,
            message=message,
            index=index,
            total=total,
            payload=payload or {},
        ))


def list_run_events(
    *,
    run_id: int | str | None = None,
    job_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = session.query(RunEvent)
        if run_id not in (None, ""):
            query = query.filter(RunEvent.run_id == int(run_id))
        if job_id:
            query = query.filter(RunEvent.job_id == job_id)
        rows = query.order_by(RunEvent.created_at.asc(), RunEvent.id.asc()).limit(limit).all()
        return [_event_to_dict(row) for row in rows]


def _event_to_dict(row: RunEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "job_id": row.job_id,
        "event": row.event,
        "stage": row.stage,
        "asin": row.asin,
        "message": row.message,
        "index": row.index,
        "total": row.total,
        "payload": row.payload or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

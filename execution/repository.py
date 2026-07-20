"""Transactional repository for recoverable execution state."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Any, Callable, Iterator
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from db.models import (
    ExecutionAttempt,
    ExecutionNode,
    ExecutionOperation,
    RunLog,
)
from execution.models import (
    Claim,
    ErrorDisposition,
    LeaseLost,
    NodeStatus,
    validate_transition,
)


ResultWriter = Callable[[Session, ExecutionNode], None]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def json_snapshot(value: Any) -> Any:
    """Validate and normalize a snapshot before it reaches a JSON column."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=_json_default, sort_keys=True))


def fingerprint(value: Any) -> str:
    normalized = json.dumps(
        json_snapshot(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(normalized.encode("utf-8")).hexdigest()


class ExecutionRepository:
    def __init__(
        self,
        session_factory=None,
        *,
        session_context=None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        if session_factory is None and session_context is None:
            from db.session import SessionLocal
            session_factory = SessionLocal
        self._session_factory = session_factory
        self._session_context = session_context
        self._now = now

    @contextmanager
    def _session(self) -> Iterator[Session]:
        if self._session_context is not None:
            with self._session_context() as session:
                yield session
            return
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def ensure_node(
        self,
        *,
        run_id: int,
        scope_type: str,
        scope_key: str,
        stage: str,
        input_snapshot: dict[str, Any] | None = None,
        input_fingerprint: str | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        if scope_type not in {"run", "asin"}:
            raise ValueError("scope_type must be run or asin")
        normalized = json_snapshot(input_snapshot)
        calculated = input_fingerprint or (
            fingerprint({
                "stage": stage,
                "handler_schema_version": (
                    normalized.get("schema_version") if isinstance(normalized, dict) else None
                ),
                "input": normalized,
            })
            if normalized is not None else None
        )
        with self._session() as session:
            node = session.query(ExecutionNode).filter_by(
                run_id=run_id,
                scope_type=scope_type,
                scope_key=scope_key,
                stage=stage,
            ).one_or_none()
            if node is None:
                node = ExecutionNode(
                    run_id=run_id,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    stage=stage,
                    status=NodeStatus.PENDING.value,
                    input_snapshot=normalized,
                    input_fingerprint=calculated,
                    timeout_seconds=timeout_seconds,
                    resume_token=uuid4().hex,
                )
                session.add(node)
                session.flush()
                return node.id
            if node.status == NodeStatus.RUNNING.value:
                if calculated is not None and calculated != node.input_fingerprint:
                    raise ValueError("cannot replace input for a running node")
                return node.id
            if (
                node.status in {NodeStatus.SUCCEEDED.value, NodeStatus.SKIPPED.value}
                and calculated is not None
                and calculated != node.input_fingerprint
            ):
                self._invalidate_for_input_change(session, node, normalized, calculated)
            elif node.status != NodeStatus.SUCCEEDED.value:
                node.input_snapshot = normalized
                node.input_fingerprint = calculated
                node.timeout_seconds = timeout_seconds
                node.updated_at = self._now()
            return node.id

    def _invalidate_for_input_change(
        self,
        session: Session,
        node: ExecutionNode,
        input_snapshot: dict[str, Any] | None,
        input_fingerprint: str,
    ) -> None:
        before = node.status
        node.status = NodeStatus.PENDING.value
        node.generation += 1
        node.input_snapshot = input_snapshot
        node.input_fingerprint = input_fingerprint
        node.output_snapshot = None
        node.output_fingerprint = None
        node.error_code = None
        node.error_detail = None
        node.finished_at = None
        node.resume_token = uuid4().hex
        node.updated_at = self._now()
        self._operation(
            session,
            node,
            "input_invalidated",
            before,
            node.status,
            reason="upstream input fingerprint changed",
        )

    def claim(
        self,
        node_id: int,
        *,
        worker_id: str,
        lease_seconds: float = 60.0,
    ) -> Claim | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._now()
        lease_token = uuid4().hex
        with self._session() as session:
            node = session.get(ExecutionNode, node_id)
            if node is None:
                raise KeyError(node_id)
            if node.status != NodeStatus.PENDING.value:
                return None
            current_count = node.attempt_count
            result = session.execute(
                update(ExecutionNode)
                .where(
                    ExecutionNode.id == node_id,
                    ExecutionNode.status == NodeStatus.PENDING.value,
                    ExecutionNode.attempt_count == current_count,
                )
                .values(
                    status=NodeStatus.RUNNING.value,
                    attempt_count=current_count + 1,
                    worker_id=worker_id,
                    lease_token=lease_token,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    next_retry_at=None,
                    error_code=None,
                    error_detail=None,
                    human_action_required=None,
                    started_at=now,
                    finished_at=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
            attempt = ExecutionAttempt(
                node_id=node_id,
                attempt_no=current_count + 1,
                generation=node.generation,
                status=NodeStatus.RUNNING.value,
                worker_id=worker_id,
                lease_token=lease_token,
                input_fingerprint=node.input_fingerprint,
                input_snapshot=node.input_snapshot,
                started_at=now,
                heartbeat_at=now,
            )
            session.add(attempt)
            session.flush()
            deadline = (
                now + timedelta(seconds=float(node.timeout_seconds))
                if node.timeout_seconds
                else None
            )
            return Claim(
                node_id=node.id,
                run_id=node.run_id,
                scope_type=node.scope_type,
                scope_key=node.scope_key,
                stage=node.stage,
                attempt_id=attempt.id,
                attempt_no=current_count + 1,
                generation=node.generation,
                lease_token=lease_token,
                worker_id=worker_id,
                deadline=deadline,
                input_fingerprint=node.input_fingerprint,
                input_snapshot=node.input_snapshot,
            )

    def heartbeat(self, claim: Claim, *, lease_seconds: float = 60.0) -> None:
        now = self._now()
        with self._session() as session:
            node = self._locked_node(session, claim)
            node.heartbeat_at = now
            node.lease_expires_at = now + timedelta(seconds=lease_seconds)
            node.updated_at = now
            attempt = self._running_attempt(session, claim)
            attempt.heartbeat_at = now

    def succeed(
        self,
        claim: Claim,
        *,
        output_snapshot: dict[str, Any] | list[Any] | None,
        output_fingerprint: str | None = None,
        evidence_refs: list[str] | None = None,
        result_writer: ResultWriter | None = None,
    ) -> None:
        normalized = json_snapshot(output_snapshot)
        calculated = output_fingerprint or fingerprint(normalized)
        now = self._now()
        with self._session() as session:
            node = self._locked_node(session, claim)
            attempt = self._running_attempt(session, claim)
            if result_writer:
                result_writer(session, node)
            validate_transition(node.status, NodeStatus.SUCCEEDED)
            node.status = NodeStatus.SUCCEEDED.value
            node.output_snapshot = normalized
            node.output_fingerprint = calculated
            node.evidence_refs = json_snapshot(evidence_refs or [])
            node.worker_id = None
            node.lease_token = None
            node.heartbeat_at = now
            node.lease_expires_at = None
            node.next_retry_at = None
            node.error_code = None
            node.error_detail = None
            node.human_action_required = None
            node.finished_at = now
            node.updated_at = now
            attempt.status = NodeStatus.SUCCEEDED.value
            attempt.output_snapshot = normalized
            attempt.output_fingerprint = calculated
            attempt.finished_at = now
            attempt.finish_reason = "completed"

    def fail(
        self,
        claim: Claim,
        *,
        disposition: ErrorDisposition,
        error_code: str,
        error_detail: str,
        max_attempts: int = 3,
        backoff_seconds: float = 0.0,
        human_action: dict[str, Any] | None = None,
    ) -> str:
        now = self._now()
        with self._session() as session:
            node = self._locked_node(session, claim)
            attempt = self._running_attempt(session, claim)
            if disposition == ErrorDisposition.RETRYABLE and node.attempt_count < max_attempts:
                target = NodeStatus.RETRY_WAIT
                next_retry = now + timedelta(seconds=max(backoff_seconds, 0.0))
            elif disposition == ErrorDisposition.HUMAN_REQUIRED:
                target = NodeStatus.HUMAN_REQUIRED
                next_retry = None
            elif disposition == ErrorDisposition.CANCELLED:
                target = NodeStatus.CANCELLED
                next_retry = None
            elif disposition == ErrorDisposition.TIMED_OUT and node.attempt_count < max_attempts:
                target = NodeStatus.RETRY_WAIT
                next_retry = now + timedelta(seconds=max(backoff_seconds, 0.0))
            elif disposition == ErrorDisposition.TIMED_OUT:
                target = NodeStatus.TIMED_OUT
                next_retry = None
            else:
                target = NodeStatus.FAILED
                next_retry = None
            validate_transition(node.status, target)
            node.status = target.value
            node.worker_id = None
            node.lease_token = None
            node.lease_expires_at = None
            node.next_retry_at = next_retry
            node.error_code = error_code
            node.error_detail = error_detail[:8000]
            node.human_action_required = json_snapshot(human_action)
            node.finished_at = now if target not in {NodeStatus.RETRY_WAIT} else None
            node.updated_at = now
            attempt.status = target.value
            attempt.error_code = error_code
            attempt.error_detail = error_detail[:8000]
            attempt.finished_at = now
            attempt.finish_reason = disposition.value
            return target.value

    def promote_due_retries(self, *, run_id: int | None = None) -> int:
        now = self._now()
        with self._session() as session:
            query = session.query(ExecutionNode).filter(
                ExecutionNode.status == NodeStatus.RETRY_WAIT.value,
                or_(ExecutionNode.next_retry_at.is_(None), ExecutionNode.next_retry_at <= now),
            )
            if run_id is not None:
                query = query.filter(ExecutionNode.run_id == run_id)
            nodes = query.all()
            for node in nodes:
                validate_transition(node.status, NodeStatus.PENDING)
                node.status = NodeStatus.PENDING.value
                node.next_retry_at = None
                node.updated_at = now
            return len(nodes)

    def recover_stale(
        self,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.0,
        run_id: int | None = None,
    ) -> int:
        now = self._now()
        recovered = 0
        with self._session() as session:
            query = session.query(ExecutionNode).filter(
                ExecutionNode.status == NodeStatus.RUNNING.value,
                ExecutionNode.lease_expires_at.is_not(None),
                ExecutionNode.lease_expires_at < now,
            )
            if run_id is not None:
                query = query.filter(ExecutionNode.run_id == run_id)
            for node in query.all():
                old_token = node.lease_token
                old_worker = node.worker_id
                old_expiry = node.lease_expires_at
                if old_token is None or old_expiry is None:
                    continue
                attempt = session.query(ExecutionAttempt).filter_by(
                    node_id=node.id,
                    lease_token=old_token,
                    status=NodeStatus.RUNNING.value,
                ).one_or_none()
                before = node.status
                target = (
                    NodeStatus.RETRY_WAIT.value
                    if node.attempt_count < max_attempts else NodeStatus.FAILED.value
                )
                next_retry = (
                    now + timedelta(seconds=max(backoff_seconds, 0.0))
                    if target == NodeStatus.RETRY_WAIT.value else None
                )
                result = session.execute(
                    update(ExecutionNode)
                    .where(
                        ExecutionNode.id == node.id,
                        ExecutionNode.status == NodeStatus.RUNNING.value,
                        ExecutionNode.lease_token == old_token,
                        ExecutionNode.worker_id == old_worker,
                        ExecutionNode.lease_expires_at == old_expiry,
                        ExecutionNode.lease_expires_at < now,
                    )
                    .values(
                        status=target,
                        next_retry_at=next_retry,
                        finished_at=now if target == NodeStatus.FAILED.value else None,
                        error_code="WORKER_LOST",
                        error_detail="execution lease expired before completion",
                        worker_id=None,
                        lease_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    continue
                if attempt is not None:
                    attempt.status = "stale"
                    attempt.error_code = "WORKER_LOST"
                    attempt.error_detail = "execution lease expired before completion"
                    attempt.finished_at = now
                    attempt.finish_reason = "stale"
                self._operation(
                    session,
                    node,
                    "stale_recovery",
                    before,
                    target,
                    reason="execution lease expired before completion",
                )
                recovered += 1
        return recovered

    def invalidate_succeeded(self, node_id: int, *, reason: str) -> None:
        """Re-run a succeeded node whose committed side effect no longer validates."""
        if not reason.strip():
            raise ValueError("invalidation reason is required")
        now = self._now()
        with self._session() as session:
            node = session.get(ExecutionNode, node_id)
            if node is None:
                raise KeyError(node_id)
            if node.status != NodeStatus.SUCCEEDED.value:
                raise ValueError(f"cannot invalidate node in status {node.status}")
            before = node.status
            node.status = NodeStatus.PENDING.value
            node.generation += 1
            node.output_snapshot = None
            node.output_fingerprint = None
            node.evidence_refs = None
            node.error_code = "RESULT_VALIDATION_FAILED"
            node.error_detail = reason
            node.finished_at = None
            node.resume_token = uuid4().hex
            node.updated_at = now
            self._operation(
                session,
                node,
                "result_invalidated",
                before,
                node.status,
                reason=reason,
            )

    def resume_human(
        self,
        node_id: int,
        *,
        reason: str,
        actor_ref: str | None = None,
        expected_resume_token: str | None = None,
    ) -> None:
        if not reason.strip():
            raise ValueError("resume reason is required")
        self._reset_to_pending(
            node_id,
            allowed={NodeStatus.HUMAN_REQUIRED},
            operation="resume",
            reason=reason,
            actor_ref=actor_ref,
            increment_generation=False,
            expected_resume_token=expected_resume_token,
        )

    def retry_node(
        self,
        node_id: int,
        *,
        reason: str,
        actor_ref: str | None = None,
        expected_resume_token: str | None = None,
    ) -> None:
        if not reason.strip():
            raise ValueError("retry reason is required")
        self._reset_to_pending(
            node_id,
            allowed={NodeStatus.FAILED, NodeStatus.TIMED_OUT},
            operation="retry",
            reason=reason,
            actor_ref=actor_ref,
            increment_generation=False,
            expected_resume_token=expected_resume_token,
        )

    def force_rerun(
        self,
        node_id: int,
        *,
        reason: str,
        actor_ref: str | None = None,
        expected_resume_token: str | None = None,
    ) -> None:
        if not reason.strip():
            raise ValueError("force rerun reason is required")
        self._reset_to_pending(
            node_id,
            allowed={NodeStatus.SUCCEEDED, NodeStatus.SKIPPED, NodeStatus.CANCELLED},
            operation="force_rerun",
            reason=reason,
            actor_ref=actor_ref,
            increment_generation=True,
            expected_resume_token=expected_resume_token,
        )

    def _reset_to_pending(
        self,
        node_id: int,
        *,
        allowed: set[NodeStatus],
        operation: str,
        reason: str,
        actor_ref: str | None,
        increment_generation: bool,
        expected_resume_token: str | None,
    ) -> None:
        now = self._now()
        with self._session() as session:
            node = session.get(ExecutionNode, node_id)
            if node is None:
                raise KeyError(node_id)
            if (
                expected_resume_token is not None
                and node.resume_token != expected_resume_token
            ):
                raise LeaseLost(f"resume token changed for node {node_id}")
            before = NodeStatus(node.status)
            if before not in allowed:
                raise ValueError(f"cannot {operation} node in status {before.value}")
            if not increment_generation:
                validate_transition(before, NodeStatus.PENDING)
            node.status = NodeStatus.PENDING.value
            if increment_generation:
                node.generation += 1
            node.worker_id = None
            node.lease_token = None
            node.lease_expires_at = None
            node.next_retry_at = None
            node.output_snapshot = None
            node.output_fingerprint = None
            node.error_code = None
            node.error_detail = None
            node.human_action_required = None
            node.resume_token = uuid4().hex
            node.finished_at = None
            node.updated_at = now
            self._operation(
                session,
                node,
                operation,
                before.value,
                node.status,
                reason=reason,
                actor_type="user",
                actor_ref=actor_ref,
            )

    def mark_skipped(self, node_id: int, *, reason: str) -> None:
        with self._session() as session:
            node = session.get(ExecutionNode, node_id)
            if node is None:
                raise KeyError(node_id)
            validate_transition(node.status, NodeStatus.SKIPPED)
            node.status = NodeStatus.SKIPPED.value
            node.error_code = "NOT_APPLICABLE"
            node.error_detail = reason
            node.finished_at = self._now()
            node.updated_at = node.finished_at

    def cancel_run(self, run_id: int, *, reason: str, actor_ref: str | None = None) -> int:
        if not reason.strip():
            raise ValueError("cancel reason is required")
        now = self._now()
        changed = 0
        with self._session() as session:
            run = session.get(RunLog, run_id)
            if run is None:
                raise KeyError(run_id)
            run.status = "cancel_requested"
            for node in session.query(ExecutionNode).filter(
                ExecutionNode.run_id == run_id,
                ExecutionNode.status.in_([
                    NodeStatus.PENDING.value,
                    NodeStatus.RETRY_WAIT.value,
                    NodeStatus.HUMAN_REQUIRED.value,
                    NodeStatus.FAILED.value,
                    NodeStatus.TIMED_OUT.value,
                ]),
            ).all():
                before = node.status
                node.status = NodeStatus.CANCELLED.value
                node.finished_at = now
                node.next_retry_at = None
                node.updated_at = now
                self._operation(
                    session,
                    node,
                    "cancel",
                    before,
                    node.status,
                    reason=reason,
                    actor_type="user",
                    actor_ref=actor_ref,
                )
                changed += 1
        return changed

    def list_nodes(self, run_id: int) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.query(ExecutionNode).filter_by(run_id=run_id).order_by(
                ExecutionNode.id.asc()
            ).all()
            return [self._node_dict(row) for row in rows]

    def list_attempts(self, node_id: int) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.query(ExecutionAttempt).filter_by(node_id=node_id).order_by(
                ExecutionAttempt.attempt_no.asc()
            ).all()
            return [self._attempt_dict(row) for row in rows]

    def find_node(
        self,
        run_id: int,
        *,
        scope_type: str,
        scope_key: str,
        stage: str,
    ) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.query(ExecutionNode).filter_by(
                run_id=int(run_id),
                scope_type=scope_type,
                scope_key=scope_key,
                stage=stage,
            ).one_or_none()
            return self._node_dict(row) if row else None

    def get_node(self, node_id: int) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.get(ExecutionNode, node_id)
            return self._node_dict(row) if row else None

    def aggregate_run_status(self, run_id: int, *, export_required: bool = True) -> str:
        nodes = self.list_nodes(run_id)
        statuses = {node["status"] for node in nodes}
        if NodeStatus.RUNNING.value in statuses:
            with self._session() as session:
                run = session.get(RunLog, int(run_id))
                return "cancel_requested" if run and run.status == "cancel_requested" else "running"
        if NodeStatus.HUMAN_REQUIRED.value in statuses:
            return "human_required"
        if NodeStatus.RETRY_WAIT.value in statuses or NodeStatus.PENDING.value in statuses:
            return "retry_wait"
        if NodeStatus.FAILED.value in statuses or NodeStatus.TIMED_OUT.value in statuses:
            return "failed"
        if NodeStatus.CANCELLED.value in statuses:
            return "cancelled"
        if export_required and nodes:
            export_nodes = [node for node in nodes if node["stage"] == "export"]
            if not export_nodes:
                # A crash can happen after filter commits but before the export
                # node is created. Keep the original Run resumable instead of
                # reporting a false success.
                return "retry_wait"
            if export_nodes[-1]["status"] != NodeStatus.SUCCEEDED.value:
                return "failed"
        if statuses and statuses <= {NodeStatus.SUCCEEDED.value, NodeStatus.SKIPPED.value}:
            return "success"
        return "success" if nodes else "failed"

    def update_run_status(self, run_id: int, *, export_required: bool = True) -> str:
        status = self.aggregate_run_status(run_id, export_required=export_required)
        with self._session() as session:
            run = session.get(RunLog, run_id)
            if run is None:
                raise KeyError(run_id)
            run.status = status
            if status in {"success", "failed", "cancelled"}:
                run.finished_at = self._now()
            else:
                run.finished_at = None
        return status

    def _locked_node(self, session: Session, claim: Claim) -> ExecutionNode:
        node = session.get(ExecutionNode, claim.node_id)
        if (
            node is None
            or node.status != NodeStatus.RUNNING.value
            or node.generation != claim.generation
            or node.lease_token != claim.lease_token
            or node.worker_id != claim.worker_id
            or node.lease_expires_at is None
            or node.lease_expires_at < self._now()
        ):
            raise LeaseLost(f"execution lease lost for node {claim.node_id}")
        return node

    def _running_attempt(self, session: Session, claim: Claim) -> ExecutionAttempt:
        attempt = session.get(ExecutionAttempt, claim.attempt_id)
        if (
            attempt is None
            or attempt.node_id != claim.node_id
            or attempt.generation != claim.generation
            or attempt.lease_token != claim.lease_token
            or attempt.status != NodeStatus.RUNNING.value
        ):
            raise LeaseLost(f"execution attempt lease lost for node {claim.node_id}")
        return attempt

    def _operation(
        self,
        session: Session,
        node: ExecutionNode,
        operation: str,
        before_status: str,
        after_status: str,
        *,
        reason: str | None = None,
        actor_type: str = "system",
        actor_ref: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        session.add(ExecutionOperation(
            run_id=node.run_id,
            node_id=node.id,
            operation=operation,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason=reason,
            before_status=before_status,
            after_status=after_status,
            payload=json_snapshot(payload),
        ))

    @staticmethod
    def _node_dict(row: ExecutionNode) -> dict[str, Any]:
        return {
            column.name: getattr(row, column.name)
            for column in ExecutionNode.__table__.columns
        }

    @staticmethod
    def _attempt_dict(row: ExecutionAttempt) -> dict[str, Any]:
        return {
            column.name: getattr(row, column.name)
            for column in ExecutionAttempt.__table__.columns
        }

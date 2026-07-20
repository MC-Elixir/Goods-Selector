"""Deterministic node executor shared by pipeline stage barriers."""
from __future__ import annotations

from dataclasses import dataclass
from socket import gethostname
from threading import Event, Thread
from typing import Any, Callable
from uuid import uuid4

from agent.cancellation import CancellationRequested
from execution.models import Claim, LeaseLost, NodeStatus, StageContext
from execution.policies import RetryPolicy, classify_error
from execution.repository import ExecutionRepository


StageHandler = Callable[[StageContext], Any]
ResultWriterFactory = Callable[[Any], Callable]
ProgressCallback = Callable[[dict[str, Any]], None]
SuccessValidator = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class NodeResult:
    node_id: int
    status: str
    output_snapshot: Any
    executed: bool
    error_code: str | None = None
    error_detail: str | None = None
    exception: Exception | None = None


class RecoverableRunCoordinator:
    def __init__(
        self,
        *,
        run_id: int,
        repository: ExecutionRepository,
        progress_callback: ProgressCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
        worker_id: str | None = None,
        lease_seconds: float = 90.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.run_id = run_id
        self.repository = repository
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.worker_id = worker_id or f"{gethostname()}:{uuid4().hex[:12]}"
        self.lease_seconds = lease_seconds
        self.retry_policy = retry_policy or RetryPolicy()

    def recover_stale(self) -> int:
        return self.repository.recover_stale(
            run_id=self.run_id,
            max_attempts=self.retry_policy.max_attempts,
            backoff_seconds=self.retry_policy.initial_backoff_seconds,
        )

    def run_node(
        self,
        *,
        scope_type: str,
        scope_key: str,
        stage: str,
        input_snapshot: dict[str, Any] | None,
        handler: StageHandler,
        timeout_seconds: float | None = None,
        result_writer_factory: ResultWriterFactory | None = None,
        success_validator: SuccessValidator | None = None,
        evidence_refs: list[str] | None = None,
        progress_payload: dict[str, Any] | None = None,
    ) -> NodeResult:
        self._validate_snapshot(input_snapshot, label="input")
        node_id = self.repository.ensure_node(
            run_id=self.run_id,
            scope_type=scope_type,
            scope_key=scope_key,
            stage=stage,
            input_snapshot=input_snapshot,
            timeout_seconds=timeout_seconds,
        )
        node = self.repository.get_node(node_id)
        if node is None:
            raise RuntimeError(f"execution node disappeared: {node_id}")
        if node["status"] == NodeStatus.SUCCEEDED.value and success_validator is not None:
            try:
                valid = bool(success_validator(node))
            except Exception:
                valid = False
            if not valid:
                self.repository.invalidate_succeeded(
                    node_id,
                    reason=f"{stage} committed result failed validation",
                )
                node = self.repository.get_node(node_id)
        if node["status"] in {NodeStatus.SUCCEEDED.value, NodeStatus.SKIPPED.value}:
            return NodeResult(node_id, node["status"], node["output_snapshot"], False)
        if node["status"] == NodeStatus.RETRY_WAIT.value:
            self.repository.promote_due_retries(run_id=self.run_id)
            node = self.repository.get_node(node_id)
        if node["status"] != NodeStatus.PENDING.value:
            return NodeResult(
                node_id,
                node["status"],
                node["output_snapshot"],
                False,
                node["error_code"],
                node["error_detail"],
            )
        claim = self.repository.claim(
            node_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            current = self.repository.get_node(node_id)
            return NodeResult(
                node_id,
                current["status"],
                current["output_snapshot"],
                False,
                current["error_code"],
                current["error_detail"],
            )
        self._progress(claim, "running", **(progress_payload or {}))
        failure: Exception | None = None
        heartbeat_stop = Event()
        heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            args=(claim, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            if self.cancel_check and self.cancel_check():
                raise CancellationRequested(f"{stage} cancelled before execution")
            context = StageContext(
                node_id=claim.node_id,
                attempt_id=claim.attempt_id,
                run_id=self.run_id,
                asin=scope_key if scope_type == "asin" else None,
                attempt_no=claim.attempt_no,
                generation=claim.generation,
                lease_token=claim.lease_token,
                worker_id=claim.worker_id,
                deadline=claim.deadline,
                cancel_check=self.cancel_check,
                heartbeat=lambda: self.repository.heartbeat(
                    claim, lease_seconds=self.lease_seconds
                ),
                input_snapshot=claim.input_snapshot,
            )
            context.raise_if_deadline_exceeded()
            output = handler(context)
            self._validate_snapshot(output, label="output")
            context.raise_if_cancelled()
            context.raise_if_deadline_exceeded()
            result_writer = result_writer_factory(output) if result_writer_factory else None
            self.repository.succeed(
                claim,
                output_snapshot=output,
                evidence_refs=evidence_refs,
                result_writer=result_writer,
            )
        except LeaseLost as exc:
            # Another worker recovered this attempt. Fencing deliberately
            # prevents this stale worker from changing either node or result.
            failure = exc
            self.repository.recover_stale(
                run_id=self.run_id,
                max_attempts=self.retry_policy.max_attempts,
                backoff_seconds=self.retry_policy.initial_backoff_seconds,
            )
        except Exception as exc:
            failure = exc
            classified = classify_error(exc)
            target = self.repository.fail(
                claim,
                disposition=classified.disposition,
                error_code=classified.error_code,
                error_detail=classified.detail,
                max_attempts=self.retry_policy.max_attempts,
                backoff_seconds=self.retry_policy.backoff_seconds(claim.attempt_no),
                human_action=classified.human_action,
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)
        current = self.repository.get_node(node_id)
        return NodeResult(
            node_id,
            current["status"],
            current["output_snapshot"],
            True,
            current["error_code"],
            current["error_detail"],
            failure,
        )

    def _heartbeat_loop(self, claim: Claim, stop: Event) -> None:
        interval = max(min(self.lease_seconds / 3.0, 30.0), 0.1)
        while not stop.wait(interval):
            try:
                self.repository.heartbeat(claim, lease_seconds=self.lease_seconds)
            except LeaseLost:
                return
            except Exception:
                # A transient telemetry write must not replace the handler's
                # real outcome; expiry recovery still provides the safety net.
                continue

    def skip_node(
        self,
        *,
        scope_type: str,
        scope_key: str,
        stage: str,
        input_snapshot: dict[str, Any] | None,
        reason: str,
    ) -> NodeResult:
        self._validate_snapshot(input_snapshot, label="input")
        node_id = self.repository.ensure_node(
            run_id=self.run_id,
            scope_type=scope_type,
            scope_key=scope_key,
            stage=stage,
            input_snapshot=input_snapshot,
        )
        node = self.repository.get_node(node_id)
        if node["status"] == NodeStatus.PENDING.value:
            self.repository.mark_skipped(node_id, reason=reason)
            node = self.repository.get_node(node_id)
        return NodeResult(
            node_id,
            node["status"],
            node["output_snapshot"],
            False,
            node["error_code"],
            node["error_detail"],
        )

    @staticmethod
    def _validate_snapshot(snapshot: Any, *, label: str) -> None:
        if not isinstance(snapshot, dict):
            raise ValueError(f"execution {label} snapshot must be a JSON object")
        version = snapshot.get("schema_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"execution {label} snapshot requires schema_version")

    def _progress(self, claim: Claim, status: str, **extra: Any) -> None:
        if not self.progress_callback:
            return
        self.progress_callback({
            "run_id": self.run_id,
            "stage": claim.stage,
            "asin": claim.scope_key if claim.scope_type == "asin" else None,
            "status": status,
            "attempt": claim.attempt_no,
            "generation": claim.generation,
            "message": f"{claim.stage} {status}",
            **extra,
        })

"""Shared agent state and serialization helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4


JobStatus = Literal[
    "queued", "running", "success", "failed", "retry_wait",
    "human_required", "cancel_requested", "cancelled",
]
SourceMode = Literal["category", "keyword"]


@dataclass
class AgentRunConfig:
    category: str
    source_mode: SourceMode = "category"
    keyword: str = ""
    marketplace: str = "US"
    limit: int = 10
    no_mock: bool = True
    llm_verification: bool | None = None
    require_market_data: bool = False
    require_supplier_evidence: bool = False


@dataclass
class AgentJob:
    config: AgentRunConfig
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    status: JobStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    run_log_id: int | None = None
    message: str = "Queued"
    error: str | None = None
    exports: dict[str, str] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    queue_position: int | None = None
    cancel_requested: bool = False
    retry_of: str | None = None
    attempt: int = 1
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["started_at"] = self.started_at.isoformat() if self.started_at else None
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data

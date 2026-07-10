from __future__ import annotations

from typing import Any

from schemas.sourcing import EvidenceStatus, FieldEvidence


def evidence(**kwargs: Any) -> FieldEvidence[Any]:
    return FieldEvidence[Any](**kwargs)


def critical_evidence_gaps(
    fields: dict[str, FieldEvidence[Any]], required: set[str]
) -> list[str]:
    gaps: list[str] = []
    disallowed = {
        EvidenceStatus.MISSING, EvidenceStatus.MOCK, EvidenceStatus.CONFLICTING,
        EvidenceStatus.INFERRED, EvidenceStatus.STALE,
    }
    for name in sorted(required):
        item = fields.get(name)
        if item is None:
            gaps.append(f"{name}:missing")
            continue
        status = item.effective_status()
        if item.value is None or status in disallowed:
            gaps.append(f"{name}:{status.value}")
    return gaps

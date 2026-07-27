from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from schemas.sourcing import EvidenceStatus, FieldEvidence


def evidence(**kwargs: Any) -> FieldEvidence[Any]:
    return FieldEvidence[Any](**kwargs)


def trusted_evidence_value(candidate: Any, *, max_age: timedelta = timedelta(days=30),
                           min_confidence: float = 0.5) -> Any | None:
    """Return a value only when its provenance is decision-grade.

    This deliberately rejects legacy raw values: presence is not provenance.
    """
    if isinstance(candidate, FieldEvidence):
        record = candidate.model_dump()
        record["status"] = candidate.effective_status().value
    elif isinstance(candidate, dict) and "status" in candidate and "value" in candidate:
        record = dict(candidate)
    else:
        return None
    status = str(getattr(record.get("status"), "value", record.get("status", ""))).casefold()
    if status not in {EvidenceStatus.EXTRACTED.value, EvidenceStatus.VERIFIED.value}:
        return None
    if record.get("value") is None or not record.get("source_type"):
        return None
    if not (record.get("source_ref") or record.get("artifact_hash")):
        return None
    confidence = record.get("confidence")
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or confidence < min_confidence):
        return None
    observed = record.get("observed_at")
    if isinstance(observed, str):
        try:
            observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(observed, datetime) or observed.utcoffset() is None:
        return None
    now = datetime.now(timezone.utc)
    if observed > now + timedelta(minutes=5) or observed < now - max_age:
        return None
    expires = record.get("expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            return None
    if expires is not None and (not isinstance(expires, datetime) or expires.utcoffset() is None or expires <= now):
        return None
    return record["value"]


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
        elif trusted_evidence_value(item) is None:
            gaps.append(f"{name}:untrusted")
    return gaps

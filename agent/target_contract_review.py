"""Human review queue for the pinned target-category benchmark cases."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, PROJECT_ROOT

_QUEUE_FILE = (
    PROJECT_ROOT
    / "benchmarks"
    / "fixtures"
    / "target_category_human_review_queue.json"
)
_REVIEWS_FILE = DATA_DIR / "target_category_human_reviews.json"
_LOCK = threading.RLock()
_ACTIONS = {"accept", "reject", "no_match"}


def list_target_contract_reviews() -> dict[str, Any]:
    """Return the immutable queue enriched with stored evidence and decisions."""
    dataset = _read_json_object(_QUEUE_FILE)
    decisions = _read_reviews()
    cases = [
        _review_case(case, decisions.get(str(case.get("case_id"))) or {})
        for case in dataset.get("cases") or []
        if isinstance(case, dict)
    ]
    return {
        "schema_version": "1.0",
        "dataset_id": dataset.get("dataset_id"),
        "ground_truth_type": dataset.get("ground_truth_type"),
        "case_count": len(cases),
        "reviewed_case_count": sum(case["reviewed"] for case in cases),
        "cases": cases,
    }


def save_target_contract_review(
    case_id: str,
    action: str,
    *,
    offer_id: str | None = None,
    note: str | None = None,
    reviewer_id: str = "local-webui",
) -> dict[str, Any]:
    """Persist one explicit candidate or case-level review decision atomically."""
    case_id = str(case_id or "").strip()
    action = str(action or "").strip()
    offer_id = str(offer_id or "").strip() or None
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of {', '.join(sorted(_ACTIONS))}")

    dataset = _read_json_object(_QUEUE_FILE)
    cases = {
        str(case.get("case_id")): case
        for case in dataset.get("cases") or []
        if isinstance(case, dict) and case.get("case_id")
    }
    case = cases.get(case_id)
    if case is None:
        raise KeyError(case_id)
    candidate_ids = [str(value) for value in case.get("candidate_offer_ids") or []]
    candidate_id_set = set(candidate_ids)
    if action in {"accept", "reject"}:
        if not offer_id:
            raise ValueError("offer_id is required for accept or reject")
        if offer_id not in candidate_id_set:
            raise ValueError("offer_id is not a candidate for this case")
    elif offer_id:
        raise ValueError("offer_id is not allowed for no_match")

    with _LOCK:
        reviews = _read_reviews(strict=True)
        stored = reviews.get(case_id)
        decision = dict(stored) if isinstance(stored, dict) else {}
        candidate_decisions = {
            str(key): value
            for key, value in (decision.get("candidate_decisions") or {}).items()
            if str(key) in candidate_id_set and value in {"accepted", "rejected"}
        }
        if action == "no_match":
            decision["no_match"] = True
            candidate_decisions = {
                candidate_id: "rejected" for candidate_id in candidate_ids
            }
        else:
            candidate_decisions[offer_id] = (
                "accepted" if action == "accept" else "rejected"
            )
            decision["no_match"] = None
        decision.update(
            {
                "candidate_decisions": candidate_decisions,
                "review_notes": str(note or "").strip(),
                "reviewer_id": str(reviewer_id or "local-webui").strip(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        reviews[case_id] = decision
        _atomic_write_json(
            _REVIEWS_FILE,
            {
                "schema_version": "1.0",
                "dataset_id": dataset.get("dataset_id"),
                "cases": reviews,
            },
        )
    return _review_case(case, decision)


def reviewed_target_contract_dataset() -> dict[str, Any]:
    """Build evaluator labels from complete, explicit human reviews only."""
    queue = list_target_contract_reviews()
    return {
        "schema_version": queue["schema_version"],
        "dataset_id": queue["dataset_id"],
        "ground_truth_type": queue["ground_truth_type"],
        "cases": [
            {
                key: value
                for key, value in case.items()
                if key not in {"amazon_evidence", "candidates", "artifact"}
            }
            for case in queue["cases"]
        ],
    }


def _review_case(case: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    candidate_ids = [str(value) for value in case.get("candidate_offer_ids") or []]
    candidate_titles = list(case.get("candidate_titles") or [])
    raw_decisions = decision.get("candidate_decisions") or {}
    candidate_decisions = {
        offer_id: raw_decisions.get(offer_id, "pending") for offer_id in candidate_ids
    }
    no_match = decision.get("no_match") is True
    accepted = [
        offer_id
        for offer_id, status in candidate_decisions.items()
        if status == "accepted"
    ]
    all_candidate_decisions = bool(candidate_ids) and all(
        status in {"accepted", "rejected"} for status in candidate_decisions.values()
    )
    reviewed = no_match or (all_candidate_decisions and bool(accepted))
    evidence = _load_artifact_evidence(case)
    stored_candidates = evidence.get("candidates") or {}
    candidates = []
    for index, offer_id in enumerate(candidate_ids):
        stored = stored_candidates.get(offer_id)
        candidates.append(
            {
                "offer_id": offer_id,
                "title": (
                    _candidate_title(stored)
                    or (candidate_titles[index] if index < len(candidate_titles) else "")
                ),
                "decision": candidate_decisions[offer_id],
                "offer_url": _candidate_value(stored, "offer_url")
                or f"https://detail.1688.com/offer/{offer_id}.html",
                "image_url": _candidate_value(stored, "offer_image_url"),
                "stored_evidence": stored,
            }
        )
    payload = dict(case)
    payload.update(
        {
            "reviewed": reviewed,
            "correct_offer_ids": [] if no_match else accepted,
            "no_match": True if no_match else (False if reviewed else None),
            "recommendation_label": (
                "reject" if no_match else ("recommend" if reviewed else None)
            ),
            "review_notes": str(decision.get("review_notes") or ""),
            "reviewer": {
                "reviewer_id": decision.get("reviewer_id"),
                "reviewed_at": decision.get("updated_at") if reviewed else None,
            },
            "artifact": evidence["artifact"],
            "amazon_evidence": evidence.get("amazon"),
            "candidates": candidates,
        }
    )
    return payload


def _load_artifact_evidence(case: dict[str, Any]) -> dict[str, Any]:
    relative = Path(str(case.get("artifact_path") or ""))
    resolved = (PROJECT_ROOT / relative).resolve()
    root = PROJECT_ROOT.resolve()
    artifact = {
        "path": relative.as_posix(),
        "expected_sha256": str(case.get("artifact_sha256") or ""),
        "available": False,
        "sha256_verified": False,
        "error": None,
    }
    if resolved != root and root not in resolved.parents:
        artifact["error"] = "artifact path escapes the project root"
        return {"artifact": artifact, "amazon": None, "candidates": {}}
    if not resolved.is_file():
        artifact["error"] = "pinned artifact is not available locally"
        return {"artifact": artifact, "amazon": None, "candidates": {}}

    raw = resolved.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    artifact.update({"available": True, "actual_sha256": actual_sha256})
    if actual_sha256 != artifact["expected_sha256"]:
        artifact["error"] = "pinned artifact checksum mismatch"
        return {"artifact": artifact, "amazon": None, "candidates": {}}
    artifact["sha256_verified"] = True
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        artifact["error"] = "pinned artifact is not valid JSON"
        return {"artifact": artifact, "amazon": None, "candidates": {}}

    record = _find_case_record(payload, str(case.get("asin") or ""))
    if record is None:
        artifact["error"] = "ASIN was not found in the pinned artifact"
        return {"artifact": artifact, "amazon": None, "candidates": {}}
    product = record.get("product") if isinstance(record.get("product"), dict) else {}
    suppliers = record.get("suppliers") if isinstance(record.get("suppliers"), list) else []
    by_id = {
        offer_id: supplier
        for supplier in suppliers
        if isinstance(supplier, dict)
        and (offer_id := _candidate_offer_id(supplier)) is not None
    }
    return {
        "artifact": artifact,
        "amazon": product or {
            "asin": case.get("asin"),
            "title": case.get("amazon_title"),
        },
        "candidates": by_id,
    }


def _find_case_record(payload: Any, asin: str) -> dict[str, Any] | None:
    rows = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        rows = payload.get("items") or payload.get("records") or payload.get("cases") or []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        product = row.get("product") if isinstance(row.get("product"), dict) else {}
        if str(product.get("asin") or row.get("asin") or "") == asin:
            return row
    return None


def _candidate_offer_id(candidate: dict[str, Any]) -> str | None:
    raw = candidate.get("raw_data") if isinstance(candidate.get("raw_data"), dict) else {}
    value = candidate.get("alibaba_offer_id") or candidate.get("offer_id") or raw.get("offer_id")
    return str(value) if value is not None else None


def _candidate_title(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    raw = candidate.get("raw_data") if isinstance(candidate.get("raw_data"), dict) else {}
    return str(candidate.get("title_cn") or candidate.get("title") or raw.get("title_cn") or "")


def _candidate_value(candidate: dict[str, Any] | None, key: str) -> Any:
    return candidate.get(key) if isinstance(candidate, dict) else None


def _read_reviews(*, strict: bool = False) -> dict[str, dict[str, Any]]:
    if not _REVIEWS_FILE.is_file():
        return {}
    try:
        payload = _read_json_object(_REVIEWS_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if strict:
            raise ValueError(
                "review decision file is unreadable; refusing to overwrite it"
            ) from exc
        return {}
    cases = payload.get("cases")
    return cases if isinstance(cases, dict) else {}


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass

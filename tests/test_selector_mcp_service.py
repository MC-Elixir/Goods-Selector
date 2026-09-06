from __future__ import annotations

import asyncio

import pytest

from selector_mcp.service import SelectorService
from selector_mcp.store import IdempotencyStore


class FakeClient:
    def __init__(self) -> None:
        self.ready = True
        self.start_calls = []
        self.saved_calls = []
        self.resume_calls = []
        self.job = {
            "id": "job_123456",
            "status": "success",
            "config": {"source_mode": "category", "category": "Home & Kitchen", "no_mock": True},
            "run_log_id": 8,
            "exports": {
                "json": "/app/data/exports/candidates_run-1.json",
                "xlsx": "/app/data/exports/candidates_run-1.xlsx",
            },
            "research": {"exports": {"xlsx": "/app/data/exports/research_run-1.xlsx"}},
            "error": "Authorization: Bearer never-show-this",
        }
        self.rows = [
            {"key": "run-1:B000000001", "asin": "B000000001", "title": "A", "score": 70, "margin": .2, "supplier_candidates": [{"secret": True}]},
            {"key": "run-1:B000000002", "asin": "B000000002", "title": "B", "score": 90, "margin": .1},
        ]

    async def preflight(self):
        return {
            "ready": self.ready,
            "summary": "ready" if self.ready else "blocked",
            "blocking_count": 0 if self.ready else 1,
            "warning_count": 0,
            "checks": [],
        }

    async def start_job(self, body):
        self.start_calls.append(body)
        return {"job": {**self.job, "status": "queued"}}

    async def get_job(self, job_id):
        assert job_id == "job_123456"
        return dict(self.job)

    async def results(self, export_id):
        assert export_id == "run-1"
        return {"items": list(self.rows)}

    async def save(self, key, saved):
        self.saved_calls.append((key, saved))
        return {"key": key, "saved": saved}

    async def nodes(self, run_id):
        assert run_id == 8
        return {"nodes": [{
            "id": 12, "status": "human_required", "stage": "supplier_match",
            "scope_type": "asin", "scope_key": "B000000001", "human_action_required": True,
            "resume_token": "internal-only", "error_detail": "captcha",
        }]}

    async def resume_node(self, job_id, node_id, *, resume_token, reason):
        self.resume_calls.append((job_id, node_id, resume_token, reason))
        return {"job": {**self.job, "status": "queued"}, "node": {"id": node_id, "resume_token": "internal-only"}}

    async def job_action(self, job_id, action):
        return {"job": {**self.job, "status": "queued"}}


@pytest.fixture
def service(tmp_path):
    client = FakeClient()
    return SelectorService(client, IdempotencyStore(tmp_path / "requests.json")), client


def run(coro):
    return asyncio.run(coro)


def test_start_requires_confirmation_and_preflight(service):
    subject, client = service
    with pytest.raises(ValueError, match="confirm=true"):
        run(subject.start_sourcing("request-0001", "category", category="Home & Kitchen"))

    client.ready = False
    result = run(subject.start_sourcing(
        "request-0001", "category", category="Home & Kitchen", confirm=True
    ))
    assert result["started"] is False
    assert client.start_calls == []


def test_start_is_persistently_idempotent_and_forces_no_mock(service):
    subject, client = service
    first = run(subject.start_sourcing(
        "request-0001", "category", category="Home & Kitchen", confirm=True
    ))
    second = run(subject.start_sourcing(
        "request-0001", "category", category="Home & Kitchen", confirm=True
    ))
    assert first["started"] is True
    assert second["idempotent_replay"] is True
    assert len(client.start_calls) == 1
    assert client.start_calls[0]["no_mock"] is True
    assert client.start_calls[0]["marketplace"] == "US"


def test_candidates_are_bounded_sorted_and_remove_raw_supplier_data(service):
    subject, _ = service
    result = run(subject.get_top_candidates("job_123456", limit=10, sort_by="score"))
    assert [row["asin"] for row in result["candidates"]] == ["B000000002", "B000000001"]
    assert "supplier_candidates" not in str(result)
    assert "never-show-this" not in str(result["job"])


def test_report_uses_public_links_and_no_container_paths(service):
    subject, _ = service
    result = run(subject.get_report("job_123456"))
    assert {item["type"] for item in result["reports"]} == {"sourcing_xlsx"}
    assert all(item["url"].startswith("http://127.0.0.1:8765/api/exports/") for item in result["reports"])
    assert "/app/" not in str(result)


def test_resume_uses_token_internally_but_never_returns_it(service):
    subject, client = service
    result = run(subject.resume_job("job_123456", confirm=True))
    assert client.resume_calls[0][2] == "internal-only"
    assert "internal-only" not in str(result)
    assert "resume_token" not in str(result)


def test_corrupt_idempotency_store_fails_closed(tmp_path):
    path = tmp_path / "requests.json"
    path.write_text("not-json", encoding="utf-8")
    subject = SelectorService(FakeClient(), IdempotencyStore(path))

    with pytest.raises(RuntimeError, match="避免重复启动"):
        run(subject.start_sourcing(
            "request-0001", "category", category="Home & Kitchen", confirm=True
        ))

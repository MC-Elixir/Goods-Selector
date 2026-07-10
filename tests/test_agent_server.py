"""Agent WebUI server helper tests."""
from __future__ import annotations

from http import HTTPStatus

import pytest

from agent.server import (
    _handle_browser_agent_request,
    _config_from_body,
    _handle_job_action,
    _market_data_guard_error,
    reviewed_supplier_csv_fields,
)


def test_config_from_body_includes_market_data_requirement():
    config = _config_from_body({
        "category": "Home & Kitchen",
        "marketplace": "US",
        "limit": 1,
        "no_mock": True,
        "llm_verification": False,
        "require_market_data": True,
        "require_supplier_evidence": True,
    })

    assert config.require_market_data is True
    assert config.require_supplier_evidence is True


def test_keyword_config_rejects_unmapped_chinese_for_amazon_us():
    with pytest.raises(ValueError, match="requires an English query"):
        _config_from_body({
            "source_mode": "keyword",
            "keyword": "户外大伞",
            "marketplace": "US",
            "limit": 10,
        })


def test_market_data_guard_is_skipped_when_not_required(monkeypatch):
    def fail_if_called():
        raise AssertionError("guard should not be called")

    monkeypatch.setattr("agent.server.seller_sprite_market_data_guard", fail_if_called)
    config = _config_from_body({
        "category": "Home & Kitchen",
        "marketplace": "US",
        "limit": 1,
        "require_market_data": False,
    })

    assert _market_data_guard_error(config) is None


def test_market_data_guard_returns_reason_when_required(monkeypatch):
    monkeypatch.setattr(
        "agent.server.seller_sprite_market_data_guard",
        lambda: (False, "SellerSprite ASIN check failed: unauthorized"),
    )
    config = _config_from_body({
        "category": "Home & Kitchen",
        "marketplace": "US",
        "limit": 1,
        "require_market_data": True,
    })

    assert _market_data_guard_error(config) == "SellerSprite ASIN check failed: unauthorized"


def test_reviewed_supplier_csv_fields_include_candidate_scores():
    fields = reviewed_supplier_csv_fields()

    assert "candidate_score" in fields
    assert "supplier_quality_score" in fields
    assert "supplier_business_score" in fields
    assert "sourcing_source" in fields
    assert fields.index("candidate_score") > fields.index("visual_similarity")


def test_handle_job_action_cancel_routes_to_runtime():
    calls = []

    class Runtime:
        def cancel_job(self, job_id):
            calls.append(("cancel", job_id))
            return {"id": job_id, "status": "cancelled"}

    status, payload = _handle_job_action("/api/jobs/job-1/cancel", Runtime())

    assert status == HTTPStatus.OK
    assert payload == {"job": {"id": "job-1", "status": "cancelled"}}
    assert calls == [("cancel", "job-1")]


def test_handle_job_action_retry_routes_to_runtime():
    calls = []

    class Runtime:
        def retry_job(self, job_id):
            calls.append(("retry", job_id))

            class Job:
                def to_dict(self):
                    return {"id": "job-2", "retry_of": job_id, "status": "queued"}

            return Job()

    status, payload = _handle_job_action("/api/jobs/job-1/retry", Runtime())

    assert status == HTTPStatus.ACCEPTED
    assert payload == {"job": {"id": "job-2", "retry_of": "job-1", "status": "queued"}}
    assert calls == [("retry", "job-1")]


def test_handle_job_action_rejects_unknown_action():
    class Runtime:
        pass

    status, payload = _handle_job_action("/api/jobs/job-1/delete", Runtime())

    assert status == HTTPStatus.NOT_FOUND
    assert payload == {"error": "not found"}


def test_handle_browser_agent_request_routes_task(monkeypatch):
    calls = []

    def fake_run(task_type, **kwargs):
        calls.append((task_type, kwargs))
        return {"ok": True, "status": "success", "task_type": task_type}

    monkeypatch.setattr("agent.server.run_browser_task", fake_run)

    status, payload = _handle_browser_agent_request({
        "task_type": "cookie_check",
        "url": "https://s.1688.com/selloffer/offer_search.htm",
    })

    assert status == HTTPStatus.OK
    assert payload == {"ok": True, "status": "success", "task_type": "cookie_check"}
    assert calls == [("cookie_check", {
        "url": "https://s.1688.com/selloffer/offer_search.htm",
        "offer_url": "",
        "asin": "",
        "keyword": "",
    })]

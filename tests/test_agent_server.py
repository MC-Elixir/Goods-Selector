"""Agent WebUI server helper tests."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from http import HTTPStatus
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agent import server
from agent.sellersprite_models import SellerSpriteContext, SellerSpriteResult
from agent.server import (
    AgentRequestHandler,
    _handle_browser_agent_request,
    _config_from_body,
    _full_research_config_from_body,
    _handle_execution_attempt_query,
    _json_default,
    _handle_job_action,
    _market_data_guard_error,
    _save_trial_feedback_for_job,
    reviewed_supplier_csv_fields,
)


@pytest.fixture
def server_client():
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), AgentRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    class Client:
        def get_json(self, path: str) -> tuple[int, dict]:
            request = Request(f"http://127.0.0.1:{httpd.server_port}{path}", method="GET")
            try:
                with urlopen(request, timeout=2) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        def post_json(self, path: str, payload: object) -> tuple[int, dict]:
            request = Request(
                f"http://127.0.0.1:{httpd.server_port}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=2) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        yield Client()
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def test_sellersprite_reverse_keyword_endpoint_rejects_invalid_asin(server_client):
    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", {"asin": "bad"}
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert "ASIN" in payload["error"]


def test_sellersprite_import_history_endpoint_returns_sanitized_rows(monkeypatch, server_client):
    monkeypatch.setattr(server, "list_sellersprite_imports", lambda *_args, **_kwargs: [{
        "id": "9d8d4859-53ef-4f93-9354-e8b7508490f0", "asin": "B00Q7OAN50",
        "artifact_type": "xlsx", "file_sha256": "a" * 64, "observed_at": "2026-07-14T00:00:00+00:00",
        "imported_at": "2026-07-14T00:01:00+00:00", "row_count": 1109, "status": "imported", "error_code": None,
    }])

    status, payload = server_client.get_json("/api/sellersprite/imports?limit=999")

    assert status == HTTPStatus.OK
    assert payload["items"][0]["row_count"] == 1109
    assert "source_file" not in str(payload)


def test_sellersprite_browser_config_endpoint_requires_boolean_and_returns_safe_status(monkeypatch, server_client):
    calls = []
    monkeypatch.setattr(server, "configure_sellersprite_browser", lambda **kwargs: calls.append(kwargs) or {
        "enabled": True, "status": "ready", "locator_profile_configured": True,
        "download_dir_configured": True, "host_download_dir_configured": True,
    })

    status, payload = server_client.post_json("/api/sellersprite/browser-config", {
        "locator_profile_path": "/app/data/live-locators.json",
        "download_dir": "/app/data/imports/sellersprite",
        "host_download_dir": "C:/Users/dell/Downloads",
        "enabled": True,
    })

    assert status == HTTPStatus.OK
    assert payload["status"] == "ready"
    assert calls == [{
        "locator_profile_path": "/app/data/live-locators.json",
        "download_dir": "/app/data/imports/sellersprite",
        "host_download_dir": "C:/Users/dell/Downloads",
        "enabled": True,
    }]
    assert "C:/Users/dell/Downloads" not in str(payload)

    invalid_status, invalid_payload = server_client.post_json("/api/sellersprite/browser-config", {"enabled": "true"})
    assert invalid_status == HTTPStatus.BAD_REQUEST
    assert invalid_payload == {"error": "enabled must be a boolean"}


@pytest.mark.parametrize("asin", [1234567890, True, ["B00Q7OAN50"], {"asin": "B00Q7OAN50"}])
def test_sellersprite_reverse_keyword_endpoint_rejects_non_string_asin(server_client, asin):
    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", {"asin": asin}
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert "ASIN" in payload["error"]


def test_sellersprite_reverse_keyword_endpoint_rejects_non_object_json(server_client):
    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", ["B00Q7OAN50"]
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert payload == {"error": "JSON body must be an object"}


def test_sellersprite_reverse_keyword_endpoint_rejects_invalid_sourcing_run_id(
    monkeypatch, server_client
):
    calls = []
    monkeypatch.setattr(server, "run_reverse_keyword_export", lambda **kwargs: calls.append(kwargs))

    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords",
        {"asin": "B00Q7OAN50", "sourcing_run_id": "not-a-uuid"},
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert payload == {"error": "sourcing_run_id must be a UUID"}
    assert calls == []


def test_sellersprite_reverse_keyword_endpoint_returns_business_failure(monkeypatch, server_client):
    context = SellerSpriteContext.create("B00Q7OAN50")
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return SellerSpriteResult.needs_human(context, "CAPTCHA")

    monkeypatch.setattr(server, "run_reverse_keyword_export", fake_run)

    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", {"asin": "B00Q7OAN50"}
    )

    assert status == HTTPStatus.OK
    assert payload["status"] == "NEEDS_HUMAN"
    assert payload["error_code"] == "CAPTCHA"
    assert payload["context"]["asin"] == "B00Q7OAN50"
    assert calls == [{"asin": "B00Q7OAN50", "sourcing_run_id": None}]


def test_sellersprite_reverse_keyword_endpoint_only_returns_safe_result_fields(
    monkeypatch, server_client
):
    context = SellerSpriteContext.create("B00Q7OAN50")
    manifest_id = str(uuid.uuid4())
    result = SellerSpriteResult(
        status="SUCCESS",
        context=context,
        data={
            "row_count": 21,
            "file_sha256": "c" * 64,
            "keyword_rows": [
                {
                    "keyword": f"insulated bottle {index}",
                    "search_volume": index,
                    "raw_payload": {"cookie": "secret"},
                    "untrusted_metric": "not-public",
                }
                for index in range(21)
            ],
            "manifest_id": manifest_id,
            "download_path": "/secret/download.csv",
            "cookies": "session=secret",
            "cdp_url": "ws://secret-host/devtools/browser/abc",
        },
    )
    monkeypatch.setattr(server, "run_reverse_keyword_export", lambda **_: result)

    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", {"asin": "B00Q7OAN50"}
    )

    assert status == HTTPStatus.OK
    assert payload["data"]["row_count"] == 21
    assert payload["data"]["file_sha256"] == "c" * 64
    assert payload["data"]["manifest_id"] == manifest_id
    assert len(payload["data"]["keyword_rows"]) == 20
    assert payload["data"]["keyword_rows"][0] == {
        "keyword": "insulated bottle 0",
        "search_volume": 0,
    }
    assert all(
        set(row) <= {"keyword", "search_volume"}
        for row in payload["data"]["keyword_rows"]
    )
    assert "secret" not in str(payload)


@pytest.mark.parametrize(
    "manifest_id",
    [None, "not-a-uuid", "01234567-89AB-4DEF-8123-456789ABCDEF"],
    ids=["missing", "invalid", "non-canonical"],
)
def test_sellersprite_reverse_keyword_endpoint_never_claims_success_without_canonical_manifest_id(
    monkeypatch, server_client, manifest_id
):
    context = SellerSpriteContext.create("B00Q7OAN50")
    data = {
        "row_count": 1,
        "file_sha256": "c" * 64,
        "keyword_rows": [{"keyword": "insulated bottle", "search_volume": 10}],
    }
    if manifest_id is not None:
        data["manifest_id"] = manifest_id
    monkeypatch.setattr(
        server,
        "run_reverse_keyword_export",
        lambda **_: SellerSpriteResult(status="SUCCESS", context=context, data=data),
    )

    status, payload = server_client.post_json(
        "/api/sellersprite/reverse-keywords", {"asin": "B00Q7OAN50"}
    )

    assert status == HTTPStatus.OK
    assert payload["status"] == "INTERNAL"
    assert payload["error_code"] == "INTERNAL"
    assert payload["data"] == {}


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


def test_full_research_config_enforces_real_bounded_workflow():
    config = _full_research_config_from_body({
        "source_mode": "keyword",
        "keyword": "patio umbrella",
        "marketplace": "US",
        "limit": 8,
        "generate_ai_reasons": True,
    })

    assert config.workflow_mode == "full_research"
    assert config.research_keyword == "patio umbrella"
    assert config.research_niche_label == "patio umbrella"
    assert config.no_mock is True
    assert config.require_supplier_evidence is True
    assert config.generate_ai_reasons is True


def test_full_research_endpoint_starts_one_agent_job(monkeypatch, server_client):
    from agent.state import AgentJob

    calls = []

    def fake_start(config):
        calls.append(config)
        return AgentJob(config=config, id="trialjob0001")

    monkeypatch.setattr(AgentRequestHandler.runtime, "start_run", fake_start)
    status, payload = server_client.post_json("/api/trial/full-research", {
        "source_mode": "category",
        "category": "Home & Kitchen",
        "marketplace": "US",
        "limit": 5,
    })

    assert status == HTTPStatus.ACCEPTED
    assert payload["job"]["id"] == "trialjob0001"
    assert payload["job"]["config"]["workflow_mode"] == "full_research"
    assert len(calls) == 1


def test_trial_feedback_endpoint_validates_and_saves(monkeypatch, server_client):
    calls = []

    def fake_save(payload):
        calls.append(payload)
        return {"id": "feedback-1", **payload}

    monkeypatch.setattr(server, "save_trial_feedback", fake_save)
    monkeypatch.setattr(
        AgentRequestHandler.runtime,
        "get_job",
        lambda job_id: {
            "id": job_id,
            "status": "review_required",
            "config": {
                "workflow_mode": "full_research",
                "source_mode": "keyword",
            },
            "research": {
                "exports": {
                    "xlsx": "/app/data/exports/market.xlsx",
                    "json": "/app/data/exports/market.json",
                }
            },
            "exports": {
                "xlsx": "/app/data/exports/result.xlsx",
                "json": "/app/data/exports/result.json",
            },
        },
    )
    status, payload = server_client.post_json("/api/trial/feedback", {
        "job_id": "trialjob0001",
        "job_status": "running",
        "ease": 4,
        "result_usefulness": 5,
        "would_use_again": True,
        "blocked_stage": "sourcing",
        "comment": "淘汰原因很清楚",
    })

    assert status == HTTPStatus.CREATED
    assert payload["feedback"]["id"] == "feedback-1"
    assert calls[0]["result_usefulness"] == 5
    assert calls[0]["job_status"] == "review_required"
    assert calls[0]["source_mode"] == "keyword"
    assert calls[0]["workflow_completed"] is True
    assert calls[0]["deliverables_ready"] is True


def test_trial_feedback_get_can_filter_by_job(monkeypatch, server_client):
    calls = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        return [{"job_id": kwargs["job_id"], "ease": 4}]

    monkeypatch.setattr(server, "list_trial_feedback", fake_list)
    status, payload = server_client.get_json(
        "/api/trial/feedback?job_id=trialjob0001&limit=10"
    )

    assert status == HTTPStatus.OK
    assert payload["items"][0]["job_id"] == "trialjob0001"
    assert calls == [{"job_id": "trialjob0001", "limit": 10}]


def test_trial_feedback_summary_endpoint(monkeypatch, server_client):
    monkeypatch.setattr(
        server,
        "summarize_trial_feedback",
        lambda: {
            "status": "collecting",
            "sample_size": 1,
            "ready_for_installer": False,
        },
    )

    status, payload = server_client.get_json("/api/trial/feedback/summary")

    assert status == HTTPStatus.OK
    assert payload["status"] == "collecting"
    assert payload["sample_size"] == 1


def test_trial_feedback_rejects_unfinished_job(monkeypatch):
    class Runtime:
        def get_job(self, job_id):
            return {
                "id": job_id,
                "status": "running",
                "config": {
                    "workflow_mode": "full_research",
                    "source_mode": "keyword",
                },
            }

    monkeypatch.setattr(
        server,
        "save_trial_feedback",
        lambda payload: (_ for _ in ()).throw(
            AssertionError("unfinished feedback must not be stored")
        ),
    )

    with pytest.raises(ValueError, match="only accepted after"):
        _save_trial_feedback_for_job(Runtime(), {
            "job_id": "trialjob0001",
            "ease": 5,
            "result_usefulness": 5,
            "would_use_again": True,
            "blocked_stage": "none",
        })


def test_trial_feedback_rejects_standard_agent_job():
    class Runtime:
        def get_job(self, job_id):
            return {
                "id": job_id,
                "status": "success",
                "config": {
                    "workflow_mode": "standard",
                    "source_mode": "category",
                },
            }

    with pytest.raises(ValueError, match="full research trial"):
        _save_trial_feedback_for_job(Runtime(), {
            "job_id": "trialjob0001",
            "ease": 5,
            "result_usefulness": 5,
            "would_use_again": True,
            "blocked_stage": "none",
        })


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


def test_target_contract_review_endpoints_route_to_review_store(
    monkeypatch, server_client
):
    monkeypatch.setattr(
        server,
        "list_target_contract_reviews",
        lambda: {"case_count": 3, "reviewed_case_count": 0, "cases": []},
    )
    calls = []
    monkeypatch.setattr(
        server,
        "save_target_contract_review",
        lambda case_id, action, **kwargs: calls.append(
            (case_id, action, kwargs)
        )
        or {"case_id": case_id, "reviewed": False},
    )

    status, payload = server_client.get_json("/api/target-contract/reviews")
    assert status == HTTPStatus.OK
    assert payload["case_count"] == 3

    status, payload = server_client.post_json(
        "/api/target-contract/reviews",
        {
            "case_id": "case-1",
            "action": "reject",
            "offer_id": "101",
            "note": "wrong size",
        },
    )
    assert status == HTTPStatus.OK
    assert payload["case"]["case_id"] == "case-1"
    assert calls == [
        (
            "case-1",
            "reject",
            {"offer_id": "101", "note": "wrong size"},
        )
    ]


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


def test_handle_node_action_requires_reason_and_routes_to_runtime():
    calls = []

    class Runtime:
        def operate_node(self, job_id, node_id, action, *, reason, resume_token):
            calls.append((job_id, node_id, action, reason, resume_token))
            return {"job": {"id": job_id, "status": "queued"}, "node": {"id": node_id}}

    path = "/api/jobs/job-1/nodes/42/retry"
    with pytest.raises(ValueError, match="reason is required"):
        _handle_job_action(path, Runtime(), {})
    with pytest.raises(ValueError, match="resume_token is required"):
        _handle_job_action(path, Runtime(), {"reason": "credentials restored"})

    status, payload = _handle_job_action(path, Runtime(), {
        "reason": "credentials restored",
        "resume_token": "token-v1",
    })
    assert status == HTTPStatus.ACCEPTED
    assert payload["node"]["id"] == 42
    assert calls == [("job-1", 42, "retry", "credentials restored", "token-v1")]


def test_handle_node_action_rejects_unknown_operation():
    status, payload = _handle_job_action(
        "/api/jobs/job-1/nodes/42/delete", object(), {"reason": "no"}
    )
    assert status == HTTPStatus.NOT_FOUND
    assert payload == {"error": "not found"}


def test_execution_attempt_query_is_scoped_to_run_and_node():
    class Runtime:
        def execution_attempts(self, run_id, node_id):
            if (run_id, node_id) != (7, 42):
                raise KeyError(node_id)
            return [{"attempt_no": 1, "status": "failed"}]

    status, payload = _handle_execution_attempt_query(Runtime(), 7, 42)
    assert status == HTTPStatus.OK
    assert payload == {
        "run_id": 7,
        "node_id": 42,
        "attempts": [{"attempt_no": 1, "status": "failed"}],
    }
    status, payload = _handle_execution_attempt_query(Runtime(), 8, 42)
    assert status == HTTPStatus.NOT_FOUND
    assert payload == {"error": "not found"}


def test_execution_api_datetime_payloads_are_json_serializable():
    encoded = json.dumps(
        {"heartbeat_at": datetime(2026, 7, 15, 12, 30, 0)},
        default=_json_default,
    )
    assert '"heartbeat_at": "2026-07-15T12:30:00"' in encoded


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

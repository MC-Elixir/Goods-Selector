from pathlib import Path

from agent.server import _resume_human_job


def test_operator_page_has_login_preflight_and_resume_controls():
    html = Path("webui/operator.html").read_text(encoding="utf-8")
    script = Path("webui/operator.js").read_text(encoding="utf-8")
    assert "人工处理台" in html
    assert "/api/browser-setup/status" in script
    assert "/api/preflight" in script
    assert "/api/operator/jobs/" in script
    assert "resume_token" not in script


def test_operator_resume_keeps_internal_token_out_of_response():
    class Runtime:
        def get_job(self, job_id):
            return {"id": job_id, "status": "human_required", "run_log_id": 7}

        def execution_nodes(self, run_id):
            assert run_id == 7
            return [{"id": 9, "human_action_required": True, "resume_token": "secret-token", "stage": "supplier_match"}]

        def operate_node(self, job_id, node_id, action, *, reason, resume_token):
            assert (job_id, node_id, action, resume_token) == ("job_123456", 9, "resume", "secret-token")
            return {"job": {"id": job_id, "status": "queued"}, "node": {"id": 9, "stage": "supplier_match", "resume_token": "secret-token"}}

    result = _resume_human_job(Runtime(), "job_123456", reason="done")
    assert result["resumed"] is True
    assert "secret-token" not in str(result)
    assert "resume_token" not in str(result)

from __future__ import annotations

import asyncio

import httpx
import pytest

from selector_mcp.server import StaticTokenVerifier, create_mcp_server


EXPECTED_TOOLS = {
    "selector_check_environment", "selector_list_categories", "selector_list_jobs",
    "selector_get_job", "selector_wait_for_job", "selector_start_sourcing",
    "selector_get_top_candidates", "selector_get_candidate", "selector_compare_candidates",
    "selector_explain_rejection", "selector_save_candidate", "selector_get_report",
    "selector_list_human_actions", "selector_browser_status", "selector_begin_login",
    "selector_finish_login", "selector_resume_job", "selector_cancel_job", "selector_retry_job",
}


def test_mcp_exposes_only_the_business_tool_allowlist(tmp_path):
    server = create_mcp_server(token="x" * 32, store_path=tmp_path / "requests.json")
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS
    assert not any(word in name for name in names for word in ("shell", "file", "http", "browser_script"))
    by_name = {tool.name: tool for tool in tools}
    assert by_name["selector_get_job"].annotations.readOnlyHint is True
    assert by_name["selector_start_sourcing"].annotations.readOnlyHint is False
    assert by_name["selector_start_sourcing"].annotations.idempotentHint is True


def test_static_bearer_token_verification_uses_exact_match():
    verifier = StaticTokenVerifier("correct-token-value-that-is-long")
    assert asyncio.run(verifier.verify_token("wrong-token-value-that-is-long")) is None
    accepted = asyncio.run(verifier.verify_token("correct-token-value-that-is-long"))
    assert accepted is not None
    assert accepted.scopes == ["selector:use"]


def test_mcp_refuses_to_start_with_a_weak_token(tmp_path):
    with pytest.raises(RuntimeError, match="至少 24"):
        create_mcp_server(token="short", store_path=tmp_path / "requests.json")


def test_streamable_http_requires_bearer_token_and_accepts_valid_token(tmp_path):
    token = "a" * 32
    server = create_mcp_server(token=token, store_path=tmp_path / "requests.json")

    async def exercise():
        app = server.streamable_http_app()
        request = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        common = {"Accept": "application/json, text/event-stream"}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8766",
            ) as client:
                missing = await client.post("/mcp", headers=common, json=request)
                invalid = await client.post(
                    "/mcp", headers={**common, "Authorization": "Bearer wrong"}, json=request
                )
                accepted = await client.post(
                    "/mcp", headers={**common, "Authorization": f"Bearer {token}"}, json=request
                )
        return missing, invalid, accepted

    missing, invalid, accepted = asyncio.run(exercise())
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["result"]["serverInfo"]["name"] == "amazon-selector"

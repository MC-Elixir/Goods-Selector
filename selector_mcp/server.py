"""Authenticated Streamable HTTP MCP server for a single client deployment."""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from selector_mcp.client import SelectorApiClient
from selector_mcp.service import SelectorService
from selector_mcp.store import IdempotencyStore


class StaticTokenVerifier:
    def __init__(self, token: str) -> None:
        self.token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self.token):
            return None
        return AccessToken(
            token=token,
            client_id="amazon-selector-client",
            scopes=["selector:use"],
            subject="single-client",
        )


def _required_token(value: str | None = None) -> str:
    token = str(value if value is not None else os.getenv("SELECTOR_MCP_TOKEN") or "").strip()
    if len(token) < 24:
        raise RuntimeError("SELECTOR_MCP_TOKEN 必须配置为至少 24 个字符的随机密钥。")
    return token


def create_mcp_server(
    *,
    token: str | None = None,
    api_base_url: str | None = None,
    public_base_url: str | None = None,
    store_path: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> FastMCP:
    secret = _required_token(token)
    advertised_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    service = SelectorService(
        SelectorApiClient(api_base_url or os.getenv("SELECTOR_API_BASE_URL") or "http://127.0.0.1:8765"),
        IdempotencyStore(store_path or os.getenv("SELECTOR_IDEMPOTENCY_PATH") or "data/mcp_idempotency.json"),
        public_base_url=public_base_url or os.getenv("SELECTOR_PUBLIC_BASE_URL") or "http://127.0.0.1:8765",
    )
    mcp = FastMCP(
        "amazon-selector",
        instructions=(
            "受控 Amazon US 选品工具。开始任务前先检查环境；所有写操作必须先取得用户明确确认；"
            "遇到登录或验证码时引导用户打开 operator_url，处理完成后再恢复任务。"
        ),
        token_verifier=StaticTokenVerifier(secret),
        auth=AuthSettings(
            issuer_url=f"http://{advertised_host}:{port}",
            resource_server_url=f"http://{advertised_host}:{port}",
            required_scopes=["selector:use"],
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    idempotent_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    browser_write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
    browser_replace = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
    destructive_write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

    mcp.tool(name="selector_check_environment", annotations=read)(service.check_environment)
    mcp.tool(name="selector_list_categories", annotations=read)(service.list_categories)
    mcp.tool(name="selector_list_jobs", annotations=read)(service.list_jobs)
    mcp.tool(name="selector_get_job", annotations=read)(service.get_job)
    mcp.tool(name="selector_wait_for_job", annotations=read)(service.wait_for_job)
    mcp.tool(name="selector_start_sourcing", annotations=idempotent_write)(service.start_sourcing)
    mcp.tool(name="selector_get_top_candidates", annotations=read)(service.get_top_candidates)
    mcp.tool(name="selector_get_candidate", annotations=read)(service.get_candidate)
    mcp.tool(name="selector_compare_candidates", annotations=read)(service.compare_candidates)
    mcp.tool(name="selector_explain_rejection", annotations=read)(service.explain_rejection)
    mcp.tool(name="selector_save_candidate", annotations=idempotent_write)(service.save_candidate)
    mcp.tool(name="selector_get_report", annotations=read)(service.get_report)
    mcp.tool(name="selector_list_human_actions", annotations=read)(service.list_human_actions)
    mcp.tool(name="selector_browser_status", annotations=read)(service.browser_status)
    mcp.tool(name="selector_begin_login", annotations=browser_write)(service.begin_login)
    mcp.tool(name="selector_finish_login", annotations=browser_replace)(service.finish_login)
    mcp.tool(name="selector_resume_job", annotations=write)(service.resume_job)
    mcp.tool(name="selector_cancel_job", annotations=destructive_write)(service.cancel_job)
    mcp.tool(name="selector_retry_job", annotations=write)(service.retry_job)
    return mcp


def run_server(host: str = "127.0.0.1", port: int = 8766) -> None:
    create_mcp_server(host=host, port=port).run(transport="streamable-http")

"""Small, allow-listed HTTP client for the local Selector WebUI API."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class SelectorApiError(RuntimeError):
    """A safe representation of an upstream WebUI API failure."""


class SelectorApiClient:
    def __init__(self, base_url: str, *, timeout: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
                response = await client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise SelectorApiError("选品服务暂时无法连接，请确认服务已启动。") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise SelectorApiError("选品服务返回了无法解析的响应。") from exc
        if response.is_error:
            detail = payload.get("error") if isinstance(payload, dict) else None
            raise SelectorApiError(str(detail or f"选品服务请求失败（HTTP {response.status_code}）。"))
        if not isinstance(payload, dict):
            raise SelectorApiError("选品服务返回格式错误。")
        return payload

    async def preflight(self) -> dict[str, Any]:
        return await self._request("GET", "/api/preflight")

    async def categories(self) -> dict[str, Any]:
        return await self._request("GET", "/api/categories")

    async def browser_status(self) -> dict[str, Any]:
        return await self._request("GET", "/api/browser-setup/status")

    async def list_jobs(self) -> dict[str, Any]:
        return await self._request("GET", "/api/jobs")

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/jobs/{quote(job_id, safe='')}")

    async def start_job(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/run", json=body)

    async def job_action(self, job_id: str, action: str) -> dict[str, Any]:
        if action not in {"cancel", "retry"}:
            raise ValueError("unsupported job action")
        return await self._request(
            "POST", f"/api/jobs/{quote(job_id, safe='')}/{action}", json={}
        )

    async def nodes(self, run_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/runs/{int(run_id)}/nodes")

    async def resume_node(
        self, job_id: str, node_id: int, *, resume_token: str, reason: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/jobs/{quote(job_id, safe='')}/nodes/{int(node_id)}/resume",
            json={"resume_token": resume_token, "reason": reason},
        )

    async def results(self, export_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/results", params={"run": export_id})

    async def save(self, key: str, saved: bool) -> dict[str, Any]:
        return await self._request("POST", "/api/saved", json={"key": key, "saved": saved})

    async def browser_action(self, site: str, action: str) -> dict[str, Any]:
        if action not in {"open_login", "save_cookies"}:
            raise ValueError("unsupported browser action")
        return await self._request(
            "POST", "/api/browser-setup", json={"site": site, "action": action}
        )

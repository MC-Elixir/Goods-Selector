"""Business-safe tool implementation exposed through MCP.

The model never receives arbitrary HTTP, filesystem, shell, browser automation,
cookie, or execution-resume-token access.  Every mutation also requires an
explicit confirmation flag from the conversation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from selector_mcp.client import SelectorApiClient
from selector_mcp.store import IdempotencyStore

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
_TERMINAL_STATUSES = frozenset(
    {"success", "failed", "human_required", "review_required", "cancelled"}
)
_SECRET_RE = re.compile(
    r"(?i)(?:authorization\s*[:=]\s*)?bearer\s+[^\s,;]+"
    r"|(?:api[_-]?key|access[_-]?token|resume[_-]?token|cookie)\s*[:=]\s*[^\s,;]+"
)


def _need_confirmation(confirm: bool) -> None:
    if confirm is not True:
        raise ValueError("这是写操作。请先向用户说明影响，并在用户确认后传 confirm=true。")


def _short_text(value: Any, limit: int = 500) -> str:
    text = _SECRET_RE.sub("[REDACTED]", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_config(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    keys = (
        "source_mode", "category", "keyword", "marketplace", "limit", "no_mock",
        "llm_verification", "require_market_data", "require_supplier_evidence",
    )
    return {key: source.get(key) for key in keys if key in source}


def _safe_job(value: Any) -> dict[str, Any]:
    job = value if isinstance(value, dict) else {}
    safe: dict[str, Any] = {
        key: job.get(key)
        for key in (
            "id", "status", "created_at", "started_at", "finished_at", "message",
            "run_log_id", "queue_position", "attempt", "retry_of",
        )
        if key in job
    }
    safe["config"] = _safe_config(job.get("config"))
    if job.get("error"):
        safe["error"] = _short_text(job.get("error"))
    if isinstance(job.get("audit"), dict):
        safe["audit"] = {
            key: job["audit"].get(key)
            for key in (
                "candidate_count", "mock_count", "invalid_for_decision_count",
                "suspicious_price_count", "avg_margin", "status",
            )
            if key in job["audit"]
        }
    if isinstance(job.get("result_summary"), dict):
        safe["result_summary"] = {}
        for key in ("status", "summary", "error"):
            if key in job["result_summary"]:
                value = job["result_summary"].get(key)
                safe["result_summary"][key] = _short_text(value) if isinstance(value, str) else value
    safe["has_exports"] = bool(job.get("exports"))
    return safe


def _safe_preflight(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    checks = []
    for check in data.get("checks") or []:
        if not isinstance(check, dict):
            continue
        checks.append({
            key: (_short_text(check.get(key)) if key == "detail" else check.get(key))
            for key in ("key", "label", "level", "status", "detail", "ready")
            if key in check
        })
    return {
        "ready": bool(data.get("ready")),
        "summary": _short_text(data.get("summary")),
        "blocking_count": int(data.get("blocking_count") or 0),
        "warning_count": int(data.get("warning_count") or 0),
        "checks": checks,
    }


def _export_id(job: dict[str, Any]) -> str | None:
    exports = job.get("exports") if isinstance(job.get("exports"), dict) else {}
    raw = exports.get("json")
    if not raw:
        return None
    stem = Path(str(raw)).stem
    return stem.removeprefix("candidates_") or None


_CANDIDATE_KEYS = (
    "key", "export_id", "asin", "title", "brand", "category", "price", "image",
    "amazon_url", "supplier", "offer_url", "buy_cost_cny", "moq", "margin",
    "net_profit", "score", "passed", "rejection_reasons", "mock",
    "invalid_for_decision", "match_quality", "visual_similarity", "spec_match_score",
    "spec_match_matched", "spec_match_missing", "spec_match_conflicts",
    "review_status", "review_summary", "decision_brief", "saved",
)


def _safe_candidate(item: Any) -> dict[str, Any]:
    row = item if isinstance(item, dict) else {}
    return {key: row.get(key) for key in _CANDIDATE_KEYS if key in row}


def _validate_job_id(job_id: str) -> str:
    value = str(job_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", value):
        raise ValueError("job_id 格式不正确。")
    return value


class SelectorService:
    def __init__(
        self,
        client: SelectorApiClient,
        store: IdempotencyStore,
        *,
        public_base_url: str = "http://127.0.0.1:8765",
    ) -> None:
        self.client = client
        self.store = store
        self.public_base_url = public_base_url.rstrip("/")
        self._start_lock = asyncio.Lock()

    async def check_environment(self) -> dict[str, Any]:
        """检查运行条件；开始选品前必须调用。"""
        return _safe_preflight(await self.client.preflight())

    async def list_categories(self) -> dict[str, Any]:
        """列出当前支持的 Amazon US 类目。"""
        payload = await self.client.categories()
        return {"marketplace": "US", "categories": payload.get("categories") or []}

    async def list_jobs(self, limit: int = 10) -> dict[str, Any]:
        """查看最近任务，最多返回 20 个。"""
        bounded = max(1, min(int(limit), 20))
        jobs = (await self.client.list_jobs()).get("jobs") or []
        return {"jobs": [_safe_job(job) for job in jobs[:bounded]]}

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """查看一个任务的安全摘要。"""
        return {"job": _safe_job(await self.client.get_job(_validate_job_id(job_id)))}

    async def wait_for_job(self, job_id: str, wait_seconds: int = 10) -> dict[str, Any]:
        """短暂等待任务状态变化；单次最多等待 30 秒。"""
        value = _validate_job_id(job_id)
        bounded = max(0, min(int(wait_seconds), 30))
        first = await self.client.get_job(value)
        initial_status = first.get("status")
        if initial_status in _TERMINAL_STATUSES or bounded == 0:
            return {"job": _safe_job(first), "changed": False}
        deadline = asyncio.get_running_loop().time() + bounded
        current = first
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(min(2, max(0.1, deadline - asyncio.get_running_loop().time())))
            current = await self.client.get_job(value)
            if current.get("status") != initial_status or current.get("status") in _TERMINAL_STATUSES:
                return {"job": _safe_job(current), "changed": True}
        return {"job": _safe_job(current), "changed": False}

    async def start_sourcing(
        self,
        request_id: str,
        source_mode: str,
        category: str = "",
        keyword: str = "",
        limit: int = 10,
        llm_verification: bool = False,
        require_market_data: bool = False,
        require_supplier_evidence: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """确认后开始一次真实、No-Mock 的 Amazon US 选品任务。"""
        _need_confirmation(confirm)
        request_id = str(request_id or "").strip()
        if not _REQUEST_ID_RE.fullmatch(request_id):
            raise ValueError("request_id 需为 8–64 位字母、数字或 . _ : -。")
        mode = str(source_mode or "").strip().lower()
        if mode not in {"category", "keyword"}:
            raise ValueError("source_mode 只能是 category 或 keyword。")
        bounded_limit = int(limit)
        if not 1 <= bounded_limit <= 50:
            raise ValueError("通过助手发起的单次任务 limit 必须为 1–50。")
        body = {
            "source_mode": mode,
            "category": str(category or "").strip(),
            "keyword": str(keyword or "").strip(),
            "marketplace": "US",
            "limit": bounded_limit,
            "no_mock": True,
            "llm_verification": bool(llm_verification),
            "require_market_data": bool(require_market_data),
            "require_supplier_evidence": bool(require_supplier_evidence),
        }
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        async with self._start_lock:
            cached = self.store.lookup(request_id, fingerprint)
            if cached is not None:
                return {**cached, "idempotent_replay": True}
            preflight = _safe_preflight(await self.client.preflight())
            if not preflight["ready"]:
                return {
                    "started": False,
                    "reason": "环境检查未通过；请先处理阻塞项。",
                    "preflight": preflight,
                }
            payload = await self.client.start_job(body)
            result = {
                "started": True,
                "job": _safe_job(payload.get("job")),
                "idempotent_replay": False,
            }
            self.store.record(request_id, fingerprint, result)
            return result

    async def get_top_candidates(
        self, job_id: str, limit: int = 5, sort_by: str = "score"
    ) -> dict[str, Any]:
        """返回任务的前 1–10 个候选，支持按 score/margin/net_profit 排序。"""
        job, rows = await self._job_results(job_id)
        if sort_by not in {"score", "margin", "net_profit"}:
            raise ValueError("sort_by 只能是 score、margin 或 net_profit。")
        bounded = max(1, min(int(limit), 10))
        rows.sort(
            key=lambda row: row.get(sort_by) if isinstance(row.get(sort_by), (int, float)) else float("-inf"),
            reverse=True,
        )
        return {
            "job": _safe_job(job),
            "candidates": [_safe_candidate(row) for row in rows[:bounded]],
            "count": min(len(rows), bounded),
        }

    async def get_candidate(self, job_id: str, asin: str) -> dict[str, Any]:
        """按 ASIN 查看候选详情。"""
        _, rows = await self._job_results(job_id)
        value = str(asin or "").strip().upper()
        if not _ASIN_RE.fullmatch(value):
            raise ValueError("ASIN 格式不正确。")
        row = next((row for row in rows if str(row.get("asin") or "").upper() == value), None)
        if row is None:
            raise ValueError("该任务结果中没有找到这个 ASIN。")
        return {"candidate": _safe_candidate(row)}

    async def compare_candidates(self, job_id: str, asins: list[str]) -> dict[str, Any]:
        """横向比较 2–5 个候选。"""
        if not isinstance(asins, list) or not 2 <= len(asins) <= 5:
            raise ValueError("请提供 2–5 个 ASIN。")
        _, rows = await self._job_results(job_id)
        wanted = [str(value or "").strip().upper() for value in asins]
        if any(not _ASIN_RE.fullmatch(value) for value in wanted):
            raise ValueError("ASIN 格式不正确。")
        by_asin = {str(row.get("asin") or "").upper(): row for row in rows}
        return {"candidates": [_safe_candidate(by_asin[value]) for value in wanted if value in by_asin]}

    async def explain_rejection(self, job_id: str, asin: str) -> dict[str, Any]:
        """解释某候选未通过或需要复核的原因。"""
        detail = (await self.get_candidate(job_id, asin))["candidate"]
        return {
            "asin": detail.get("asin"),
            "passed": detail.get("passed"),
            "review_status": detail.get("review_status"),
            "rejection_reasons": detail.get("rejection_reasons") or [],
            "spec_conflicts": detail.get("spec_match_conflicts") or [],
            "spec_missing": detail.get("spec_match_missing") or [],
            "decision_brief": detail.get("decision_brief"),
        }

    async def save_candidate(
        self, job_id: str, asin: str, saved: bool = True, confirm: bool = False
    ) -> dict[str, Any]:
        """确认后保存或取消保存一个候选。"""
        _need_confirmation(confirm)
        detail = (await self.get_candidate(job_id, asin))["candidate"]
        key = str(detail.get("key") or "")
        if not key:
            raise ValueError("候选缺少保存标识。")
        result = await self.client.save(key, bool(saved))
        return {"asin": detail.get("asin"), "saved": bool(result.get("saved"))}

    async def get_report(self, job_id: str) -> dict[str, Any]:
        """获取任务报告的本机下载链接。"""
        job = await self.client.get_job(_validate_job_id(job_id))
        exports = job.get("exports") if isinstance(job.get("exports"), dict) else {}
        research = job.get("research") if isinstance(job.get("research"), dict) else {}
        research_exports = research.get("exports") if isinstance(research.get("exports"), dict) else {}
        reports = []
        for kind, raw in [
            *((f"sourcing_{key}", value) for key, value in exports.items()),
            *((f"research_{key}", value) for key, value in research_exports.items()),
        ]:
            name = Path(str(raw)).name
            if not name or Path(name).suffix.lower() not in {".json", ".xlsx", ".csv", ".md", ".html"}:
                continue
            reports.append({
                "type": str(kind),
                "filename": name,
                "url": f"{self.public_base_url}/api/exports/{quote(name)}",
            })
        return {"job": _safe_job(job), "reports": reports}

    async def list_human_actions(self, job_id: str) -> dict[str, Any]:
        """列出任务需要用户完成的登录、验证码或人工复核动作。"""
        job = await self.client.get_job(_validate_job_id(job_id))
        actions: list[dict[str, Any]] = []
        run_id = job.get("run_log_id")
        if run_id:
            nodes = (await self.client.nodes(int(run_id))).get("nodes") or []
            for node in nodes:
                if not isinstance(node, dict) or not node.get("human_action_required"):
                    continue
                actions.append(self._safe_action(node))
        elif job.get("status") == "human_required":
            actions.append({
                "type": "browser_verification",
                "message": _short_text(job.get("error") or job.get("message")),
                "resume_method": "selector_resume_job",
            })
        return {"job": _safe_job(job), "actions": actions}

    async def browser_status(self) -> dict[str, Any]:
        """检查专用 Chrome 和 Amazon/1688 登录资料是否可用，不返回 Cookie。"""
        data = await self.client.browser_status()
        sites = {}
        for name, item in (data.get("sites") or {}).items():
            if isinstance(item, dict):
                sites[name] = {
                    key: item.get(key)
                    for key in ("ready", "status", "label", "message", "cookie_count", "updated_at")
                    if key in item
                }
        return {
            "configured": bool(data.get("configured")),
            "reachable": bool(data.get("reachable")),
            "detail": _short_text(data.get("detail")),
            "requires_dedicated_profile": bool(data.get("requires_dedicated_profile", True)),
            "sites": sites,
            "operator_url": f"{self.public_base_url}/operator",
        }

    async def begin_login(self, site: str, confirm: bool = False) -> dict[str, Any]:
        """确认后在用户专用 Chrome 中打开 Amazon 或 1688 登录页。"""
        _need_confirmation(confirm)
        value = self._site(site)
        result = await self.client.browser_action(value, "open_login")
        return {key: result.get(key) for key in ("ok", "status", "site", "label", "message")}

    async def finish_login(self, site: str, confirm: bool = False) -> dict[str, Any]:
        """用户完成登录/验证码后，确认保存站点登录态；不会返回 Cookie。"""
        _need_confirmation(confirm)
        value = self._site(site)
        result = await self.client.browser_action(value, "save_cookies")
        return {key: result.get(key) for key in ("ok", "status", "site", "label", "message", "cookie_count")}

    async def resume_job(
        self, job_id: str, node_id: int | None = None, confirm: bool = False
    ) -> dict[str, Any]:
        """人工处理完成后，确认恢复阻塞任务；恢复令牌由服务端内部使用。"""
        _need_confirmation(confirm)
        value = _validate_job_id(job_id)
        job = await self.client.get_job(value)
        run_id = job.get("run_log_id")
        if not run_id:
            if job.get("status") != "human_required":
                raise ValueError("该任务当前没有可恢复的人工步骤。")
            payload = await self.client.job_action(value, "retry")
            return {"job": _safe_job(payload.get("job")), "resumed": True}
        nodes = (await self.client.nodes(int(run_id))).get("nodes") or []
        selected = None
        for node in nodes:
            if not isinstance(node, dict) or not node.get("human_action_required"):
                continue
            if node_id is None or int(node.get("id") or 0) == int(node_id):
                selected = node
                break
        if selected is None:
            raise ValueError("该任务当前没有匹配的人工阻塞节点。")
        token = str(selected.get("resume_token") or "")
        if not token:
            raise ValueError("人工节点缺少内部恢复令牌，请在操作页中重试。")
        payload = await self.client.resume_node(
            value, int(selected["id"]), resume_token=token, reason="用户已完成登录或验证码处理"
        )
        return {
            "job": _safe_job(payload.get("job")),
            "action": self._safe_action(payload.get("node") or selected),
            "resumed": True,
        }

    async def cancel_job(self, job_id: str, confirm: bool = False) -> dict[str, Any]:
        """确认后取消排队中或运行中的任务。"""
        _need_confirmation(confirm)
        payload = await self.client.job_action(_validate_job_id(job_id), "cancel")
        return {"job": _safe_job(payload.get("job")), "cancel_requested": True}

    async def retry_job(self, job_id: str, confirm: bool = False) -> dict[str, Any]:
        """确认后重试失败或已取消的任务。"""
        _need_confirmation(confirm)
        payload = await self.client.job_action(_validate_job_id(job_id), "retry")
        return {"job": _safe_job(payload.get("job")), "retried": True}

    async def _job_results(self, job_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        job = await self.client.get_job(_validate_job_id(job_id))
        export_id = _export_id(job)
        if not export_id:
            raise ValueError("该任务还没有可读取的候选结果。")
        payload = await self.client.results(export_id)
        rows = [row for row in (payload.get("items") or []) if isinstance(row, dict)]
        return job, rows

    @staticmethod
    def _site(site: str) -> str:
        value = str(site or "").strip().lower()
        if value not in {"amazon", "1688"}:
            raise ValueError("site 只能是 amazon 或 1688。")
        return value

    @staticmethod
    def _safe_action(node: Any) -> dict[str, Any]:
        data = node if isinstance(node, dict) else {}
        result = {
            key: data.get(key)
            for key in ("id", "status", "stage", "scope_type", "scope_key", "error_code", "human_action_required")
            if key in data
        }
        if data.get("error_detail"):
            result["error_detail"] = _short_text(data.get("error_detail"))
        result["resume_method"] = "selector_resume_job"
        return result

"""Local WebUI server for Amazon Selector Agent."""
from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from agent.browser_agent import run_browser_task
from agent.browser_setup import (
    capture_browser_cookies,
    get_browser_setup_status,
    open_login_page,
)
from agent.categories import canonical_category, list_categories
from agent.chat_tools import answer_chat
from agent.config_status import (
    check_alibaba_pifatuan,
    check_seller_sprite_asin,
    configure_alibaba_supplier_search,
    configure_seller_sprite,
    configure_sellersprite_browser,
    configure_vision_model,
    get_config_status,
)
from agent.history import hide_result, list_accepted_supplier_shortlist, list_export_runs, list_results, set_saved
from agent.manual_queue import list_manual_queue, update_manual_item
from agent.review_decisions import set_supplier_review
from agent.run_events import list_run_events
from agent.runner import AGENT_SYSTEM_PROMPT, AgentRuntime
from agent.seller_research_service import run_competitor_export, run_seller_research_from_file
from agent.seller_sprite_diagnostics import seller_sprite_market_data_guard
from agent.sellersprite_batch import run_reverse_keyword_batch
from agent.sellersprite_models import SellerSpriteResult
from agent.sellersprite_policy import validate_sellersprite_asin
from agent.sellersprite_service import run_reverse_keyword_export
from agent.state import AgentRunConfig
from agent.target_contract_review import (
    list_target_contract_reviews,
    save_target_contract_review,
)
from agent.trial_feedback import (
    list_trial_feedback,
    save_trial_feedback,
    summarize_trial_feedback,
)
from config.settings import settings
from crawlers.amazon_search import keyword_preview, normalize_keyword
from db.seller_research_repository import get_seller_research_run, list_seller_research_runs
from db.sellersprite_repository import list_sellersprite_imports
from db.session import engine as db_engine
from execution.models import LeaseLost
from matchers.imported_suppliers import import_alibaba_supplier_payload, list_imported_suppliers

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "webui"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_PUBLIC_SELLERSPRITE_NUMERIC_FIELDS = frozenset({
    "search_volume", "search_volume_lower_bound",
    "purchase_volume", "purchase_volume_lower_bound",
    "purchase_rate", "purchase_rate_lower_bound",
    "competing_products", "competing_products_lower_bound",
    "spr", "spr_lower_bound", "organic_rank", "organic_rank_lower_bound",
    "ad_rank", "ad_rank_lower_bound", "trend_lower_bound",
    "trend_duration_seconds", "duration_seconds",
})
_PUBLIC_SELLERSPRITE_TEXT_FIELDS = frozenset({"trend", "duration"})


class AgentRequestHandler(SimpleHTTPRequestHandler):
    runtime = AgentRuntime()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/preflight":
            return self._json(self.runtime.preflight())
        if parsed.path == "/api/config/status":
            return self._json(get_config_status())
        if parsed.path == "/api/browser-setup/status":
            return self._json(get_browser_setup_status())
        if parsed.path == "/api/categories":
            return self._json({"marketplace": "US", "categories": list_categories()})
        if parsed.path == "/api/keyword-preview":
            keyword = str((parse_qs(parsed.query).get("keyword") or [""])[0]).strip()
            if not keyword:
                return self._json({"error": "keyword is required"}, HTTPStatus.BAD_REQUEST)
            return self._json(keyword_preview(keyword))
        if parsed.path == "/api/jobs":
            return self._json({"jobs": self.runtime.list_jobs()})
        if parsed.path == "/api/trial/feedback/summary":
            return self._json(summarize_trial_feedback())
        if parsed.path == "/api/trial/feedback":
            qs = parse_qs(parsed.query)
            job_id = str((qs.get("job_id") or [""])[0]).strip() or None
            raw_limit = (qs.get("limit") or [100])[0]
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return self._json({"error": "limit must be an integer"}, HTTPStatus.BAD_REQUEST)
            return self._json({
                "items": list_trial_feedback(job_id=job_id, limit=limit)
            })
        run_nodes_match = re.fullmatch(r"/api/runs/(\d+)/nodes", parsed.path)
        if run_nodes_match:
            return self._json({
                "run_id": int(run_nodes_match.group(1)),
                "nodes": self.runtime.execution_nodes(int(run_nodes_match.group(1))),
            })
        run_attempts_match = re.fullmatch(
            r"/api/runs/(\d+)/nodes/(\d+)/attempts", parsed.path
        )
        if run_attempts_match:
            run_id = int(run_attempts_match.group(1))
            node_id = int(run_attempts_match.group(2))
            status, payload = _handle_execution_attempt_query(self.runtime, run_id, node_id)
            return self._json(payload, status)
        if parsed.path == "/api/run-events":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run_id") or [None])[0]
            job_id = (qs.get("job_id") or [None])[0]
            limit = int((qs.get("limit") or [200])[0] or 200)
            return self._json({"events": list_run_events(run_id=run_id, job_id=job_id, limit=limit)})
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            job = self.runtime.get_job(job_id)
            return self._json(job or {"error": "not found"}, HTTPStatus.OK if job else HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/runs":
            return self._json({"runs": list_export_runs()})
        if parsed.path == "/api/results":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run") or [None])[0]
            return self._json(list_results(run_id=run_id))
        if parsed.path == "/api/reviewed-suppliers":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run") or [None])[0]
            return self._json(list_accepted_supplier_shortlist(run_id=run_id))
        if parsed.path == "/api/reviewed-suppliers.csv":
            qs = parse_qs(parsed.query)
            run_id = (qs.get("run") or [None])[0]
            return self._send_reviewed_suppliers_csv(run_id=run_id)
        if parsed.path == "/api/manual-queue":
            qs = parse_qs(parsed.query)
            status = (qs.get("status") or [None])[0]
            return self._json(list_manual_queue(status=status))
        if parsed.path == "/api/target-contract/reviews":
            return self._json(list_target_contract_reviews())
        if parsed.path == "/api/imported-suppliers":
            qs = parse_qs(parsed.query)
            limit = int((qs.get("limit") or [200])[0] or 200)
            return self._json(list_imported_suppliers(limit=limit))
        if parsed.path == "/api/sellersprite/imports":
            raw_limit = (parse_qs(parsed.query).get("limit") or [20])[0]
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return self._json({"error": "limit must be an integer"}, HTTPStatus.BAD_REQUEST)
            return self._json({"items": list_sellersprite_imports(db_engine, limit=limit)})
        if parsed.path == "/api/seller-research/lists":
            raw_limit = (parse_qs(parsed.query).get("limit") or [20])[0]
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                return self._json({"error": "limit must be an integer"}, HTTPStatus.BAD_REQUEST)
            return self._json({"items": list_seller_research_runs(db_engine, limit=limit)})
        if parsed.path.startswith("/api/seller-research/lists/"):
            run_id = unquote(parsed.path.rsplit("/", 1)[-1])
            run = get_seller_research_run(db_engine, run_id)
            return self._json(run or {"error": "not found"}, HTTPStatus.OK if run else HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/prompt":
            return self._json({"system_prompt": AGENT_SYSTEM_PROMPT})
        if parsed.path.startswith("/api/exports/"):
            return self._send_export(parsed.path.removeprefix("/api/exports/"))
        if parsed.path in {"/operator", "/operator/"}:
            self.path = "/operator.html"
            return super().do_GET()
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
            if parsed.path == "/api/trial/full-research":
                config = _full_research_config_from_body(body)
                job = self.runtime.start_run(config)
                return self._json({"job": job.to_dict()}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/trial/feedback":
                return self._json(
                    {"feedback": _save_trial_feedback_for_job(self.runtime, body)},
                    HTTPStatus.CREATED,
                )
            if parsed.path == "/api/run":
                config = _config_from_body(body)
                market_guard_error = _market_data_guard_error(config)
                if market_guard_error:
                    return self._json({"error": market_guard_error}, HTTPStatus.BAD_REQUEST)
                job = self.runtime.start_run(config)
                return self._json({"job": job.to_dict()}, HTTPStatus.ACCEPTED)
            operator_resume_match = re.fullmatch(
                r"/api/operator/jobs/([A-Za-z0-9_-]{6,64})/resume", parsed.path
            )
            if operator_resume_match:
                payload = _resume_human_job(
                    self.runtime,
                    operator_resume_match.group(1),
                    reason=str(body.get("reason") or "用户已完成人工验证").strip(),
                )
                return self._json(payload, HTTPStatus.ACCEPTED)
            if parsed.path.startswith("/api/jobs/"):
                status, payload = _handle_job_action(parsed.path, self.runtime, body)
                return self._json(payload, status)
            if parsed.path == "/api/chat":
                message = str(body.get("message") or "").strip()
                if not message:
                    return self._json({"error": "message is required"}, HTTPStatus.BAD_REQUEST)
                return self._json(answer_chat(
                    message,
                    run_id=body.get("run_id"),
                    selected_asin=body.get("selected_asin"),
                    use_llm=True,
                ))
            if parsed.path == "/api/browser-agent":
                status, payload = _handle_browser_agent_request(body)
                return self._json(payload, status)
            if parsed.path == "/api/browser-setup":
                action = str(body.get("action") or "").strip()
                site = str(body.get("site") or "").strip().lower()
                if action == "open_login":
                    return self._json(open_login_page(site))
                if action == "save_cookies":
                    return self._json(capture_browser_cookies(site))
                raise ValueError("action must be open_login or save_cookies")
            if parsed.path == "/api/sellersprite/reverse-keywords":
                return self._json(_handle_sellersprite_reverse_keyword_request(body))
            if parsed.path == "/api/sellersprite/reverse-keywords-batch":
                return self._json(_handle_sellersprite_reverse_keyword_batch_request(body))
            if parsed.path == "/api/seller-research/import":
                return self._json(_handle_seller_research_import(body))
            if parsed.path == "/api/seller-research/browser-export":
                return self._json(_handle_seller_research_browser_export(body))
            if parsed.path == "/api/sellersprite/browser-config":
                enabled = body.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be a boolean")
                return self._json(configure_sellersprite_browser(
                    locator_profile_path=str(body.get("locator_profile_path") or ""),
                    download_dir=str(body.get("download_dir") or ""),
                    host_download_dir=str(body.get("host_download_dir") or ""),
                    enabled=enabled,
                ))
            if parsed.path == "/api/config/seller-sprite":
                result = configure_seller_sprite(
                    str(body.get("key") or ""),
                    base_url=body.get("base_url"),
                )
                return self._json(result)
            if parsed.path == "/api/config/vision-model":
                result = configure_vision_model(
                    str(body.get("key") or ""),
                    str(body.get("model") or ""),
                    base_url=body.get("base_url"),
                    provider=body.get("provider"),
                )
                return self._json(result)
            if parsed.path == "/api/config/seller-sprite/asin-check":
                result = check_seller_sprite_asin(
                    str(body.get("asin") or ""),
                    marketplace=str(body.get("marketplace") or "US"),
                )
                return self._json(result)
            if parsed.path == "/api/config/alibaba/search-api":
                result = configure_alibaba_supplier_search(
                    str(body.get("namespace") or ""),
                    str(body.get("method") or ""),
                    keyword_param=body.get("keyword_param"),
                    candidates=body.get("candidates"),
                )
                return self._json(result)
            if parsed.path == "/api/config/alibaba/pifatuan-check":
                result = check_alibaba_pifatuan(
                    str(body.get("keyword") or "水杯"),
                    limit=int(body.get("limit") or 3),
                )
                return self._json(result)
            if parsed.path == "/api/imported-suppliers":
                result = import_alibaba_supplier_payload(
                    body.get("payload"),
                    keyword=str(body.get("keyword") or ""),
                    note=str(body.get("note") or ""),
                )
                return self._json(result)
            if parsed.path == "/api/saved":
                key = str(body.get("key") or "")
                if not key:
                    return self._json({"error": "key is required"}, HTTPStatus.BAD_REQUEST)
                saved = bool(body.get("saved"))
                return self._json(set_saved(key, saved))
            if parsed.path == "/api/results/hide":
                return self._json(hide_result(str(body.get("key") or "")))
            if parsed.path == "/api/manual-queue":
                key = str(body.get("key") or "")
                if not key:
                    return self._json({"error": "key is required"}, HTTPStatus.BAD_REQUEST)
                item = update_manual_item(
                    key,
                    status=body.get("status"),
                    note=body.get("note"),
                )
                return self._json({"item": item})
            if parsed.path == "/api/supplier-review":
                result = set_supplier_review(
                    str(body.get("key") or ""),
                    str(body.get("status") or ""),
                    note=body.get("note"),
                )
                return self._json(result)
            if parsed.path == "/api/target-contract/reviews":
                case = save_target_contract_review(
                    str(body.get("case_id") or ""),
                    str(body.get("action") or ""),
                    offer_id=body.get("offer_id"),
                    note=body.get("note"),
                )
                return self._json({"case": case})
        except KeyError:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except LeaseLost as exc:
            return self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except ValueError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            return self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[agent-web] {self.address_string()} - {fmt % args}")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(
            payload, ensure_ascii=False, indent=2, default=_json_default
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_export(self, filename: str) -> None:
        safe_name = Path(unquote(filename)).name
        path = settings.export_dir / safe_name
        if not path.exists() or not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND, "Export not found")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open("rb") as f:
            self.wfile.write(f.read())

    def _send_reviewed_suppliers_csv(self, run_id: str | None = None) -> None:
        rows = list_accepted_supplier_shortlist(run_id=run_id)["items"]
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=reviewed_supplier_csv_fields(), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        data = output.getvalue().encode("utf-8-sig")
        filename = f"accepted_suppliers_{run_id or 'all'}.csv"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), AgentRequestHandler)
    print(f"Amazon Selector Agent WebUI: http://{host}:{port}")
    httpd.serve_forever()


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def reviewed_supplier_csv_fields() -> list[str]:
    return [
        "export_id", "asin", "product_title", "total_score", "profit_margin",
            "supplier_rank", "supplier", "supplier_title", "offer_url", "price_cny",
            "moq", "monthly_sales", "repeat_buyer_rate", "is_factory", "sourcing_source",
            "match_quality", "visual_similarity", "candidate_score",
        "supplier_quality_score", "supplier_business_score", "spec_match_score",
        "spec_conflicts", "spec_missing", "reviewed_at", "note",
    ]


def _handle_job_action(
    path: str,
    runtime: AgentRuntime,
    body: dict | None = None,
) -> tuple[HTTPStatus, dict]:
    parts = [part for part in path.split("/") if part]
    if parts[:2] != ["api", "jobs"]:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    if len(parts) == 6 and parts[3] == "nodes":
        job_id, raw_node_id, action = parts[2], parts[4], parts[5]
        if action not in {"resume", "retry", "force-rerun"}:
            return HTTPStatus.NOT_FOUND, {"error": "not found"}
        try:
            node_id = int(raw_node_id)
        except ValueError:
            raise ValueError("node_id must be an integer")
        reason = str((body or {}).get("reason") or "").strip()
        if not reason:
            raise ValueError("reason is required")
        resume_token = str((body or {}).get("resume_token") or "").strip()
        if not resume_token:
            raise ValueError("resume_token is required")
        payload = runtime.operate_node(
            job_id, node_id, action, reason=reason, resume_token=resume_token
        )
        return HTTPStatus.ACCEPTED, payload
    if len(parts) != 4:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    job_id, action = parts[2], parts[3]
    if action == "cancel":
        return HTTPStatus.OK, {"job": runtime.cancel_job(job_id)}
    if action == "retry":
        job = runtime.retry_job(job_id)
        return HTTPStatus.ACCEPTED, {"job": job.to_dict()}
    return HTTPStatus.NOT_FOUND, {"error": "not found"}


def _resume_human_job(runtime: AgentRuntime, job_id: str, *, reason: str) -> dict:
    """Resume the first human gate without exposing its token to the browser."""
    job = runtime.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if not reason:
        raise ValueError("reason is required")
    run_id = job.get("run_log_id")
    if not run_id:
        if job.get("status") != "human_required":
            raise ValueError("job has no human action to resume")
        return {"job": runtime.retry_job(job_id).to_dict(), "resumed": True}
    node = next(
        (
            item for item in runtime.execution_nodes(int(run_id))
            if isinstance(item, dict) and item.get("human_action_required")
        ),
        None,
    )
    if not node:
        raise ValueError("job has no human action to resume")
    resume_token = str(node.get("resume_token") or "")
    if not resume_token:
        raise ValueError("human action is missing its internal resume token")
    result = runtime.operate_node(
        job_id,
        int(node["id"]),
        "resume",
        reason=reason,
        resume_token=resume_token,
    )
    result_node = result.get("node") or {}
    safe_node = {
        key: result_node.get(key)
        for key in (
            "id", "status", "stage", "scope_type", "scope_key",
            "error_code", "human_action_required",
        )
        if key in result_node
    }
    return {"job": result.get("job"), "node": safe_node, "resumed": True}


def _save_trial_feedback_for_job(
    runtime: AgentRuntime,
    body: dict,
) -> dict:
    job_id = str(body.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    job = runtime.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    job_status = str(job.get("status") or "")
    if job_status not in {"success", "failed", "cancelled", "review_required"}:
        raise ValueError("feedback is only accepted after the trial job has ended")
    config = job.get("config") or {}
    if config.get("workflow_mode") != "full_research":
        raise ValueError("feedback is only accepted for a full research trial")
    source_mode = str(config.get("source_mode") or "")
    sourcing_exports = job.get("exports") or {}
    # The formal workflow has one user-facing deliverable. JSON is a backend
    # sidecar and the legacy research workbook is no longer produced.
    workbook_path = sourcing_exports.get("xlsx")
    deliverables_ready = bool(workbook_path and str(workbook_path).strip())
    normalized = dict(body)
    normalized["job_id"] = job_id
    normalized["job_status"] = job_status
    normalized["source_mode"] = source_mode
    normalized["workflow_completed"] = job_status in {"success", "review_required"}
    normalized["deliverables_ready"] = bool(deliverables_ready)
    return save_trial_feedback(normalized)


def _handle_execution_attempt_query(
    runtime: AgentRuntime,
    run_id: int,
    node_id: int,
) -> tuple[HTTPStatus, dict]:
    try:
        attempts = runtime.execution_attempts(int(run_id), int(node_id))
    except KeyError:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    return HTTPStatus.OK, {
        "run_id": int(run_id),
        "node_id": int(node_id),
        "attempts": attempts,
    }


def _handle_browser_agent_request(body: dict) -> tuple[HTTPStatus, dict]:
    task_type = str(body.get("task_type") or "").strip()
    if not task_type:
        raise ValueError("task_type is required")
    result = run_browser_task(
        task_type,
        url=str(body.get("url") or ""),
        offer_url=str(body.get("offer_url") or ""),
        asin=str(body.get("asin") or ""),
        keyword=str(body.get("keyword") or ""),
    )
    return HTTPStatus.OK, result


def _handle_sellersprite_reverse_keyword_request(body: dict) -> dict:
    """Run one bounded browser export and expose only its public evidence."""
    # Do not stringify JSON scalars: ``1234567890`` and ``true`` must never
    # become valid-looking ASINs at the API boundary.
    asin = validate_sellersprite_asin(body.get("asin"))
    sourcing_run_id = _optional_sellersprite_sourcing_run_id(body.get("sourcing_run_id"))
    result = run_reverse_keyword_export(asin=asin, sourcing_run_id=sourcing_run_id)
    return _safe_sellersprite_result_payload(result)


def _handle_sellersprite_reverse_keyword_batch_request(body: dict) -> dict:
    raw_asins = body.get("asins")
    if not isinstance(raw_asins, list):
        raise ValueError("asins must be a JSON array")
    sourcing_run_id = _optional_sellersprite_sourcing_run_id(body.get("sourcing_run_id"))
    batch = run_reverse_keyword_batch(raw_asins, sourcing_run_id=sourcing_run_id)
    return {
        "results": [_safe_sellersprite_result_payload(result) for result in batch.results],
        "summary": {
            "requested_count": len(raw_asins),
            "processed_count": len(batch.results),
            "success_count": batch.success_count,
            "human_required_count": batch.human_required_count,
            "stopped": batch.stopped,
            "stop_reason": batch.stop_reason,
        },
    }


def _handle_seller_research_import(body: dict) -> dict:
    """Analyze one already-downloaded SellerSprite competitor export file."""
    filename = str(body.get("file") or body.get("filename") or "").strip()
    if not filename:
        raise ValueError("file is required (place the export under data/imports)")
    path = _resolve_seller_research_import(filename)
    if path is None:
        raise ValueError("import file not found under data/imports or data/imports/sellersprite")
    payload = run_seller_research_from_file(
        path,
        niche_label=str(body.get("niche_label") or "").strip(),
        keyword=str(body.get("keyword") or "").strip(),
        marketplace=str(body.get("marketplace") or "US").strip().upper() or "US",
        category=_optional_target_category(body.get("category")),
        engine=db_engine,
        generate_ai_reasons=_bool_default(body.get("generate_ai_reasons"), True),
        export=True,
    )
    return _seller_research_public_payload(payload)


def _handle_seller_research_browser_export(body: dict) -> dict:
    """Drive the SellerSprite browser competitor export, then build the shortlist."""
    keyword = str(body.get("keyword") or "").strip()
    if not keyword:
        raise ValueError("keyword is required")
    payload = run_competitor_export(
        keyword,
        niche_label=str(body.get("niche_label") or "").strip(),
        marketplace=str(body.get("marketplace") or "US").strip().upper() or "US",
        category=_optional_target_category(body.get("category")),
        sellersprite_url=str(body.get("sellersprite_url") or "").strip(),
        engine=db_engine,
        generate_ai_reasons=_bool_default(body.get("generate_ai_reasons"), True),
        export=True,
    )
    return _seller_research_public_payload(payload)


_TARGET_CATEGORY_IDS = frozenset(
    {"outdoor_storage", "patio_heater", "patio_furniture_sets", "patio_umbrellas_shade"}
)


def _optional_target_category(value: object) -> str | None:
    if value in (None, "", "auto"):
        return None
    if not isinstance(value, str) or value not in _TARGET_CATEGORY_IDS:
        raise ValueError("category must be one of the four target category ids")
    return value


def _resolve_seller_research_import(filename: str) -> Path | None:
    safe_name = Path(unquote(filename)).name
    if not safe_name:
        return None
    import_dir = settings.sellersprite_import_dir
    for base in (import_dir, import_dir.parent):
        candidate = base / safe_name
        if candidate.is_file():
            return candidate
    return None


def _seller_research_public_payload(payload: dict) -> dict:
    """Expose export files as download basenames served by /api/exports/."""
    safe = dict(payload)
    exports = payload.get("exports") or {}
    safe["exports"] = {kind: Path(str(value)).name for kind, value in exports.items()}
    return safe


def _bool_default(value: object, default: bool) -> bool:
    return default if value is None else bool(value)


def _optional_sellersprite_sourcing_run_id(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("sourcing_run_id must be a UUID")
    try:
        return str(uuid.UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ValueError("sourcing_run_id must be a UUID") from exc


def _safe_sellersprite_result_payload(result: SellerSpriteResult) -> dict:
    """Serialize only browser-export fields safe for the local WebUI.

    The importer manifest includes host paths and raw source data; neither is
    an API contract.  Keep this response limited to run metadata and the
    compact keyword evidence returned by the service.
    """
    context = result.context
    safe_data = _safe_sellersprite_result_data(result.data)
    status = result.status
    error_code = result.error_code
    if status == "SUCCESS" and not _has_complete_sellersprite_success_evidence(safe_data):
        # Never claim a successful browser export if an injected/broken service
        # result omitted the immutable evidence required by this contract.
        status = "INTERNAL"
        error_code = "INTERNAL"
        safe_data = {}
    return {
        "status": status,
        "error_code": error_code,
        "context": {
            "asin": context.asin,
            "sourcing_run_id": context.sourcing_run_id,
            "call_id": context.call_id,
            "observed_at": context.observed_at,
        },
        "data": safe_data,
    }


def _safe_sellersprite_result_data(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    safe: dict = {}
    row_count = data.get("row_count")
    if isinstance(row_count, int) and not isinstance(row_count, bool) and row_count >= 0:
        safe["row_count"] = row_count
    file_sha256 = data.get("file_sha256")
    if isinstance(file_sha256, str) and _SHA256_RE.fullmatch(file_sha256):
        safe["file_sha256"] = file_sha256.lower()
    keyword_rows = data.get("keyword_rows")
    if isinstance(keyword_rows, list):
        safe["keyword_rows"] = _safe_sellersprite_keyword_rows(keyword_rows)
    manifest_id = data.get("manifest_id")
    canonical_manifest_id = _canonical_sellersprite_manifest_id(manifest_id)
    if canonical_manifest_id is not None:
        safe["manifest_id"] = canonical_manifest_id
    return safe


def _safe_sellersprite_keyword_rows(rows: list[object]) -> list[dict]:
    safe_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keyword = row.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        safe_row: dict = {"keyword": keyword.strip()}
        for field in _PUBLIC_SELLERSPRITE_NUMERIC_FIELDS:
            value = row.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                # JSON serialization rejects only NaN/Infinity inconsistently;
                # a string comparison keeps this small boundary dependency-free.
                if value == value and value not in (float("inf"), float("-inf")):
                    safe_row[field] = value
        for field in _PUBLIC_SELLERSPRITE_TEXT_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                safe_row[field] = value.strip()
        safe_rows.append(safe_row)
        if len(safe_rows) == 20:
            break
    return safe_rows


def _has_complete_sellersprite_success_evidence(data: dict) -> bool:
    return (
        isinstance(data.get("row_count"), int)
        and not isinstance(data.get("row_count"), bool)
        and data["row_count"] >= 0
        and isinstance(data.get("file_sha256"), str)
        and _SHA256_RE.fullmatch(data["file_sha256"]) is not None
        and isinstance(data.get("keyword_rows"), list)
        and _canonical_sellersprite_manifest_id(data.get("manifest_id")) is not None
    )


def _canonical_sellersprite_manifest_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(uuid.UUID(value))
    except ValueError:
        return None
    return canonical if value == canonical else None


def _config_from_body(body: dict) -> AgentRunConfig:
    marketplace = str(body.get("marketplace") or "US").strip().upper()
    if marketplace != "US":
        raise ValueError("marketplace is fixed to Amazon US")
    source_mode = str(body.get("source_mode") or "category").strip().lower()
    if source_mode not in {"category", "keyword"}:
        raise ValueError("source_mode must be category or keyword")
    keyword = str(body.get("keyword") or "").strip()
    category = str(body.get("category") or "").strip()
    if source_mode == "keyword":
        if not keyword:
            raise ValueError("keyword is required")
        normalized = normalize_keyword(keyword)
        if normalized.requires_english_query:
            raise ValueError(
                "Amazon US keyword sourcing requires an English query. "
                "Replace the Chinese product phrase with the English phrase shown on Amazon US."
            )
        category = ""
    else:
        if not category:
            raise ValueError("category is required")
        category = canonical_category(category)
    limit = int(body.get("limit") or 10)
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    request_no_mock = bool(body.get("no_mock", True))
    no_mock = request_no_mock if _dev_allow_mock_suppliers() else True
    return AgentRunConfig(
        category=category,
        source_mode=source_mode,  # type: ignore[arg-type]
        keyword=keyword,
        marketplace=marketplace,
        limit=limit,
        no_mock=no_mock,
        llm_verification=body.get("llm_verification"),
        require_market_data=bool(body.get("require_market_data", False)),
        require_supplier_evidence=bool(body.get("require_supplier_evidence", False)),
    )


def _full_research_config_from_body(body: dict) -> AgentRunConfig:
    """Validate the bounded one-click workflow exposed to trial users."""
    config = _config_from_body({
        **body,
        "no_mock": True,
        "require_market_data": False,
        "require_supplier_evidence": body.get("require_supplier_evidence", True),
    })
    if config.limit > 20:
        raise ValueError("controlled trial limit must be between 1 and 20")
    research_keyword = str(
        body.get("research_keyword")
        or body.get("keyword")
        or body.get("category")
        or ""
    ).strip()
    if not research_keyword:
        raise ValueError("research_keyword is required")
    config.workflow_mode = "full_research"
    config.research_keyword = research_keyword
    config.research_niche_label = str(
        body.get("niche_label") or research_keyword
    ).strip()
    config.research_category = _optional_target_category(
        body.get("research_category")
    )
    config.generate_ai_reasons = _bool_default(
        body.get("generate_ai_reasons"), False
    )
    return config


def _dev_allow_mock_suppliers() -> bool:
    return str(os.getenv("DEV_ALLOW_MOCK_SUPPLIERS") or "").strip().lower() in {"1", "true", "yes", "on"}


def _market_data_guard_error(config: AgentRunConfig) -> str | None:
    if not config.require_market_data:
        return None
    ready, reason = seller_sprite_market_data_guard()
    return None if ready else reason

"""Local WebUI server for Amazon Selector Agent."""
from __future__ import annotations

import csv
import json
import mimetypes
import os
import re
import uuid
from io import StringIO
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from agent.categories import canonical_category, list_categories
from agent.browser_agent import run_browser_task
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
from agent.runner import AGENT_SYSTEM_PROMPT, AgentRuntime
from agent.run_events import list_run_events
from agent.state import AgentRunConfig
from agent.seller_sprite_diagnostics import seller_sprite_market_data_guard
from agent.sellersprite_models import SellerSpriteResult
from agent.sellersprite_policy import validate_sellersprite_asin
from agent.sellersprite_service import run_reverse_keyword_export
from db.sellersprite_repository import list_sellersprite_imports
from db.session import engine as db_engine
from config.settings import settings
from crawlers.amazon_search import keyword_preview, normalize_keyword
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
        if parsed.path == "/api/categories":
            return self._json({"marketplace": "US", "categories": list_categories()})
        if parsed.path == "/api/keyword-preview":
            keyword = str((parse_qs(parsed.query).get("keyword") or [""])[0]).strip()
            if not keyword:
                return self._json({"error": "keyword is required"}, HTTPStatus.BAD_REQUEST)
            return self._json(keyword_preview(keyword))
        if parsed.path == "/api/jobs":
            return self._json({"jobs": self.runtime.list_jobs()})
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
        if parsed.path == "/api/prompt":
            return self._json({"system_prompt": AGENT_SYSTEM_PROMPT})
        if parsed.path.startswith("/api/exports/"):
            return self._send_export(parsed.path.removeprefix("/api/exports/"))
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
            if parsed.path == "/api/run":
                config = _config_from_body(body)
                market_guard_error = _market_data_guard_error(config)
                if market_guard_error:
                    return self._json({"error": market_guard_error}, HTTPStatus.BAD_REQUEST)
                job = self.runtime.start_run(config)
                return self._json({"job": job.to_dict()}, HTTPStatus.ACCEPTED)
            if parsed.path.startswith("/api/jobs/"):
                status, payload = _handle_job_action(parsed.path, self.runtime)
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
            if parsed.path == "/api/sellersprite/reverse-keywords":
                return self._json(_handle_sellersprite_reverse_keyword_request(body))
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
        except KeyError:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
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
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
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


def reviewed_supplier_csv_fields() -> list[str]:
    return [
        "export_id", "asin", "product_title", "total_score", "profit_margin",
            "supplier_rank", "supplier", "supplier_title", "offer_url", "price_cny",
            "moq", "monthly_sales", "repeat_buyer_rate", "is_factory", "sourcing_source",
            "match_quality", "visual_similarity", "candidate_score",
        "supplier_quality_score", "supplier_business_score", "spec_match_score",
        "spec_conflicts", "spec_missing", "reviewed_at", "note",
    ]


def _handle_job_action(path: str, runtime: AgentRuntime) -> tuple[HTTPStatus, dict]:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 4 or parts[:2] != ["api", "jobs"]:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    job_id, action = parts[2], parts[3]
    if action == "cancel":
        return HTTPStatus.OK, {"job": runtime.cancel_job(job_id)}
    if action == "retry":
        job = runtime.retry_job(job_id)
        return HTTPStatus.ACCEPTED, {"job": job.to_dict()}
    return HTTPStatus.NOT_FOUND, {"error": "not found"}


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


def _dev_allow_mock_suppliers() -> bool:
    return str(os.getenv("DEV_ALLOW_MOCK_SUPPLIERS") or "").strip().lower() in {"1", "true", "yes", "on"}


def _market_data_guard_error(config: AgentRunConfig) -> str | None:
    if not config.require_market_data:
        return None
    ready, reason = seller_sprite_market_data_guard()
    return None if ready else reason

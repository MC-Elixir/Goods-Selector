"""Local WebUI server for Amazon Selector Agent."""
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from agent.history import list_export_runs, list_results, set_saved
from agent.runner import AGENT_SYSTEM_PROMPT, AgentRuntime
from agent.state import AgentRunConfig
from config.settings import settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "webui"


class AgentRequestHandler(SimpleHTTPRequestHandler):
    runtime = AgentRuntime()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/preflight":
            return self._json(self.runtime.preflight())
        if parsed.path == "/api/jobs":
            return self._json({"jobs": self.runtime.list_jobs()})
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
                job = self.runtime.start_run(config)
                return self._json({"job": job.to_dict()}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/saved":
                key = str(body.get("key") or "")
                if not key:
                    return self._json({"error": "key is required"}, HTTPStatus.BAD_REQUEST)
                saved = bool(body.get("saved"))
                return self._json(set_saved(key, saved))
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


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), AgentRequestHandler)
    print(f"Amazon Selector Agent WebUI: http://{host}:{port}")
    httpd.serve_forever()


def _config_from_body(body: dict) -> AgentRunConfig:
    category = str(body.get("category") or "").strip()
    if not category:
        raise ValueError("category is required")
    marketplace = str(body.get("marketplace") or "US").strip().upper()
    if marketplace not in {"US", "UK", "DE", "JP"}:
        raise ValueError("marketplace must be one of US, UK, DE, JP")
    limit = int(body.get("limit") or 10)
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    return AgentRunConfig(
        category=category,
        marketplace=marketplace,
        limit=limit,
        no_mock=bool(body.get("no_mock", True)),
        llm_verification=body.get("llm_verification"),
    )

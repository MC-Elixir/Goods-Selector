from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_webui_form_exposes_keyword_mode_and_hides_mock_switch():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert 'name="no_mock"' not in index
    assert 'name="source_mode"' in index
    assert 'name="keyword"' in index
    assert "source_mode" in app
    assert 'no_mock: true' in app
    assert "Formal mode disables mock suppliers" not in index
    assert "正式模式会禁用 mock 供应商" not in app


def test_webui_is_fixed_to_amazon_us_and_has_chat_panel():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "Amazon US" in index
    assert 'value="UK"' not in index
    assert 'value="DE"' not in index
    assert 'value="JP"' not in index
    assert 'id="chatPanel"' in index
    assert "/api/chat" in app


def test_webui_exposes_job_cancel_and_retry_actions():
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "/api/jobs/${encodeURIComponent(jobId)}/cancel" in app
    assert "/api/jobs/${encodeURIComponent(jobId)}/retry" in app
    assert "job-action" in app


def test_webui_renders_recent_job_events():
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert "jobEventTimeline" in app
    assert "job-events" in app
    assert ".job-events" in styles


def test_webui_exposes_browser_assistant_panel():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'id="browserAgentForm"' in index
    assert 'name="task_type"' in index
    assert "/api/browser-agent" in app
    assert "sendBrowserAgentTask" in app
    assert ".browser-agent-result" in styles

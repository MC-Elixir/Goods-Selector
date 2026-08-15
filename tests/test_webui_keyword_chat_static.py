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


def test_webui_exposes_controlled_one_click_research_workflow():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'data-section="trial"' in index
    assert 'id="trialForm"' in index
    assert 'id="trialStages"' in index
    assert 'id="trialContinueButton"' in index
    assert 'id="trialFeedbackForm"' in index
    assert 'id="trialValidationPanel"' in index
    assert "/api/trial/full-research" in app
    assert "/api/trial/feedback/summary" in app
    assert "startFullResearch" in app
    assert "continueTrialJob" in app
    assert "renderTrialFeedbackSummary" in app
    assert "job.research?.exports?.xlsx" in app
    assert ".trial-workspace" in styles
    assert ".trial-stages" in styles
    assert ".trial-validation-panel" in styles


def test_webui_exposes_recoverable_node_status_and_operations():
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert "/api/runs/${encodeURIComponent(runId)}/nodes" in app
    assert "/nodes/${encodeURIComponent(button.dataset.nodeId)}/${button.dataset.action}" in app
    assert 'data-action="resume"' in app
    assert 'data-action="force-rerun"' in app
    assert "window.prompt" in app
    assert ".execution-nodes" in styles


def test_webui_renders_recent_job_events():
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert "jobEventTimeline" in app
    assert "job-events" in app
    assert ".job-events" in styles


def test_webui_treats_sellersprite_api_as_optional():
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "settings.sellerSpriteOptional" in app
    assert "!status.seller_sprite?.configured" in app
    assert "SellerSprite API (optional)" in app
    assert "卖家精灵 API（可选）" in app
    assert "market analysis uses browser export" in app


def test_webui_exposes_browser_assistant_panel():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'id="browserAgentForm"' in index
    assert 'name="task_type"' in index
    assert "/api/browser-agent" in app
    assert "sendBrowserAgentTask" in app
    assert ".browser-agent-result" in styles


def test_webui_exposes_visual_model_and_result_delete_controls():
    index = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert 'id="visionModelForm"' in index
    assert 'name="model"' in index
    assert "/api/config/vision-model" in app
    assert "hide-result" in app

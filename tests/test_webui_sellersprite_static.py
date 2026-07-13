"""Static contract tests for the bounded SellerSprite export panel."""
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_webui_exposes_a_dedicated_sellersprite_reverse_keyword_card():
    html = (PROJECT_ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'id="sellerSpriteReverseKeywordForm"' in html
    assert 'name="asin"' in html
    assert 'id="sellerSpriteReverseKeywordStatus"' in html
    assert 'id="sellerSpriteReverseKeywordResults"' in html
    assert 'postJson("/api/sellersprite/reverse-keywords"' in js
    assert "renderSellerSpriteKeywordRows" in js
    assert ".sellersprite-keyword-results" in styles


def test_webui_sellersprite_panel_uses_bounded_escaped_structured_rows():
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "rows.slice(0, 20)" in js
    assert "escapeHtml(typeof safeRow.keyword" in js
    assert "escapeHtml(sellerSpriteMetricValue" in js
    assert "escapeHtml(sellerSpriteRateValue" in js
    assert "escapeHtml(typeof safeRow.trend" in js
    assert 'postJson("/api/sellersprite/reverse-keywords"' in js


def test_webui_sellersprite_panel_uses_only_keyword_rows_and_reports_bounded_results():
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "function sellerSpriteKeywordRows(result)" in js
    assert "result.data?.keyword_rows" in js
    assert "result.data?.keywords" not in js
    assert "sellersprite.reverseKeywords.showing" in js
    assert "total > shown" in js
    assert "replace(\"{shown}\", sellerSpriteNumberText(shown))" in js
    assert "replace(\"{total}\", sellerSpriteNumberText(total))" in js
    assert "if (!shown) return t(\"sellersprite.reverseKeywords.noRows\")" in js


def test_webui_sellersprite_panel_has_submission_and_request_failure_guards():
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert 'status.textContent = t("sellersprite.reverseKeywords.running")' in js
    assert "submitButton.disabled = true" in js
    assert 'status.textContent = t("sellersprite.reverseKeywords.requestFailed")' in js
    assert "state.sellerSpriteKeywordRows = []" in js
    assert "finally {\n    submitButton.disabled = false;\n  }" in js


def test_webui_sellersprite_panel_has_translated_human_action_states():
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    for key in (
        "sellersprite.reverseKeywords.title",
        "sellersprite.reverseKeywords.needsHuman",
        "sellersprite.reverseKeywords.captcha",
        "sellersprite.reverseKeywords.authentication",
        "sellersprite.reverseKeywords.permission",
        "sellersprite.reverseKeywords.disabled",
        "sellersprite.reverseKeywords.showing",
    ):
        assert js.count(f'"{key}"') >= 2

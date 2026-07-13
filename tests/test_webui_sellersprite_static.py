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
    assert "sellerSpriteMetricValue" in js
    assert "sellerSpriteStatusText" in js
    assert 'postJson("/api/sellersprite/reverse-keywords"' in js


def test_webui_sellersprite_panel_has_translated_human_action_states():
    js = (PROJECT_ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    for key in (
        "sellersprite.reverseKeywords.title",
        "sellersprite.reverseKeywords.needsHuman",
        "sellersprite.reverseKeywords.captcha",
        "sellersprite.reverseKeywords.authentication",
        "sellersprite.reverseKeywords.permission",
        "sellersprite.reverseKeywords.disabled",
    ):
        assert js.count(f'"{key}"') >= 2

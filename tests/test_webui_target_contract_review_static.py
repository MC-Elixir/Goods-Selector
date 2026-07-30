from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_webui_exposes_pinned_target_contract_review_flow():
    html = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'data-section="contract-review"' in html
    assert 'id="contractReviewSection"' in html
    assert 'id="contractReviewList"' in html
    assert "/api/target-contract/reviews" in js
    assert 'data-contract-action="accept"' in js
    assert 'data-contract-action="reject"' in js
    assert 'data-contract-action="no_match"' in js
    assert "Stored evidence JSON" in js
    assert ".contract-review-case" in styles


def test_review_renderer_escapes_pinned_and_stored_evidence():
    js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "escapeHtml(amazon.title || item.amazon_title" in js
    assert "escapeHtml(candidate.title" in js
    assert "escapeHtml(JSON.stringify(evidence, null, 2))" in js
    assert "escapeAttr(candidate.offer_url)" in js

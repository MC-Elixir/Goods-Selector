from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_webui_exposes_background_human_action_notifications():
    html = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "webui" / "styles.css").read_text(encoding="utf-8")

    assert 'id="notificationButton"' in html
    assert 'id="backgroundAlert"' in html
    assert "Notification.requestPermission()" in js
    assert 'requireInteraction: true' in js
    assert "syncHumanActionAlerts()" in js
    assert ".background-alert" in styles


def test_resume_refreshes_1688_session_before_clearing_a_browser_block():
    js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")

    assert "refresh1688SessionBeforeResume(node)" in js
    assert '["CAPTCHA", "CAPTCHA_COOLDOWN", "AUTH_REQUIRED"]' in js
    assert 'action: "save_cookies"' in js
    assert 'site: "1688"' in js

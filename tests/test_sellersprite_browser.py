from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.sellersprite_models import SellerSpriteLocatorProfile
from agent.tools.sellersprite_browser import (
    PlaywrightSellerSpriteSession,
    SellerSpriteWorkflowError,
)


def valid_profile() -> SellerSpriteLocatorProfile:
    return SellerSpriteLocatorProfile(
        panel_open="css=panel_open",
        ready="css=ready",
        login_required="css=login_required",
        permission_required="css=permission_required",
        captcha="css=captcha",
        reverse_keywords="css=reverse_keywords",
        asin_input="css=asin_input",
        submit="css=submit",
        results_ready="css=results_ready",
        export_menu="css=export_menu",
        export="css=export",
    )


class FakeLocator:
    def __init__(self, page: "FakePage", name: str) -> None:
        self.page = page
        self.name = name

    def is_visible(self) -> bool:
        return self.name in self.page.visible_markers

    def click(self, **_kwargs) -> None:
        self.page.clicked.append(self.name)
        callback = self.page.on_click.get(self.name)
        if callback:
            callback()

    def hover(self, **_kwargs) -> None:
        self.page.hovered.append(self.name)
        callback = self.page.on_hover.get(self.name)
        if callback:
            callback()

    def fill(self, value: str, **_kwargs) -> None:
        self.page.filled[self.name] = value

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(self.page, selector.removeprefix("css="))


class FakePage:
    def __init__(self, *, asin: str, visible_markers: set[str]) -> None:
        self.asin = asin
        self.visible_markers = visible_markers
        self.goto_calls: list[str] = []
        self.clicked: list[str] = []
        self.hovered: list[str] = []
        self.filled: dict[str, str] = {}
        self.on_click: dict[str, object] = {}
        self.on_hover: dict[str, object] = {}
        self.on_goto: object | None = None
        self.timeout_calls: list[int] = []
        self.url = f"https://www.amazon.com/dp/{asin}"

    def goto(self, url: str, **_kwargs) -> None:
        self.goto_calls.append(url)
        if self.on_goto:
            self.on_goto()

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector.removeprefix("css="))

    def frame_locator(self, _selector: str) -> FakeLocator:
        return FakeLocator(self, "frame")

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.timeout_calls.append(_milliseconds)
        return None


class FakeObserver:
    def __init__(self, artifact: object) -> None:
        self.artifact = artifact
        self.snapshots: list[Path] = []
        self.waits: list[tuple[Path, object, int]] = []

    def snapshot(self, path: Path) -> object:
        self.snapshots.append(path)
        return "snapshot"

    def wait(
        self,
        path: Path,
        snapshot: object,
        timeout_seconds: int,
        *,
        cancel_check=None,
    ) -> object:
        self.waits.append((path, snapshot, timeout_seconds))
        if cancel_check:
            cancel_check()
        return self.artifact


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.contexts = [type("Context", (), {"pages": [page]})()]
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def new_browser_cdp_session(self):
        return self.cdp_session


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.chromium = self
        self.connected_to: str | None = None
        self.stopped = False

    def connect_over_cdp(self, url: str) -> FakeBrowser:
        self.connected_to = url
        return self.browser

    def stop(self) -> None:
        self.stopped = True


def test_adapter_opens_only_us_asin_page_and_checks_redirected_asin(tmp_path):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"ready"})
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    session.open_amazon_product("B00Q7OAN50")

    assert page.goto_calls == ["https://www.amazon.com/dp/B00Q7OAN50"]

    page.url = "https://www.amazon.com/dp/B000000000"
    with pytest.raises(SellerSpriteWorkflowError, match="ASIN_MISMATCH"):
        session.open_amazon_product("B00Q7OAN50")


def test_adapter_cancellation_after_navigation_prevents_followup_wait(tmp_path):
    cancelled = False
    page = FakePage(asin="B00Q7OAN50", visible_markers={"ready"})

    def cancel_after_goto() -> None:
        nonlocal cancelled
        cancelled = True

    page.on_goto = cancel_after_goto
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
        is_cancelled=lambda: cancelled,
    )

    with pytest.raises(SellerSpriteWorkflowError, match="CANCELLED"):
        session.open_amazon_product("B00Q7OAN50")

    assert page.goto_calls == ["https://www.amazon.com/dp/B00Q7OAN50"]
    assert page.timeout_calls == []


def test_adapter_attaches_only_through_injected_cdp_resolver(tmp_path):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"ready"})
    browser = FakeBrowser(page)
    playwright = FakePlaywright(browser)
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        playwright_factory=lambda: playwright,
        cdp_resolver=lambda: "ws://host.docker.internal:9222/devtools/browser/1",
    )

    with session as attached:
        assert attached.page is page

    assert playwright.connected_to == "ws://host.docker.internal:9222/devtools/browser/1"
    assert browser.closed is False
    assert playwright.stopped


def test_adapter_stops_for_human_terminal_state_without_clicking(tmp_path):
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "captcha", "reverse_keywords", "asin_input", "submit", "results_ready", "export"},
    )
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    with pytest.raises(SellerSpriteWorkflowError, match="CAPTCHA"):
        session.check_sellersprite_extension()

    assert page.clicked == []


def test_adapter_reclassifies_login_that_appears_after_reverse_click(tmp_path):
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords"},
    )
    page.on_click["reverse_keywords"] = lambda: page.visible_markers.add("login_required")
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    with pytest.raises(SellerSpriteWorkflowError, match="SELLERSPRITE_LOGIN_REQUIRED"):
        session.export_sellersprite_reverse_keywords("B00Q7OAN50")


def test_adapter_opens_collapsed_panel_before_ready_check(tmp_path):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"panel_open"})
    page.on_click["panel_open"] = lambda: page.visible_markers.add("ready")
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    session.check_sellersprite_extension()

    assert page.clicked == ["panel_open"]


def test_adapter_waits_for_extension_panel_to_finish_opening(tmp_path):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"panel_open"})

    def reveal_after_panel_animation(_milliseconds: int) -> None:
        page.visible_markers.add("ready")

    page.wait_for_timeout = reveal_after_panel_animation
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    session.check_sellersprite_extension()

    assert page.clicked == ["panel_open"]


def test_adapter_does_not_toggle_an_already_open_panel(tmp_path):
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"panel_open", "ready"},
    )
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
    )

    session.check_sellersprite_extension()

    assert page.clicked == []


def test_adapter_snapshots_before_single_export_click_and_delegates_download(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords", "asin_input", "submit", "results_ready", "export_menu", "export"},
    )
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
        download_observer=observer,
        export_timeout_seconds=17,
    )

    session.check_sellersprite_extension()
    downloaded = session.export_sellersprite_reverse_keywords("B00Q7OAN50")

    assert downloaded is artifact
    assert page.clicked == ["reverse_keywords", "submit", "export_menu", "export"]
    assert page.filled == {"asin_input": "B00Q7OAN50"}
    assert observer.snapshots == [tmp_path]
    assert observer.waits == [(tmp_path, "snapshot", 17)]


def test_adapter_direct_export_mode_snapshots_before_only_click(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords", "asin_input", "submit", "results_ready", "export"},
    )
    profile = replace(valid_profile(), export_menu="css=export", export="css=export")
    session = PlaywrightSellerSpriteSession(
        profile=profile,
        download_dir=tmp_path,
        page=page,
        download_observer=observer,
    )

    downloaded = session.export_sellersprite_reverse_keywords("B00Q7OAN50")

    assert downloaded is artifact
    assert page.clicked == ["reverse_keywords", "submit", "export"]
    assert observer.snapshots == [tmp_path]


def test_adapter_sets_temporary_cdp_download_policy_before_snapshot_and_export(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords", "asin_input", "submit", "results_ready", "export_menu", "export"},
    )
    browser = FakeBrowser(page)
    browser.cdp_session = type("Cdp", (), {"calls": [], "detached": False})()
    browser.cdp_session.send = lambda method, params: browser.cdp_session.calls.append((method, params))
    browser.cdp_session.detach = lambda: setattr(browser.cdp_session, "detached", True)
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(), download_dir=tmp_path, page=page, download_observer=observer,
    )
    session._browser = browser

    assert session.export_sellersprite_reverse_keywords("B00Q7OAN50") is artifact

    assert browser.cdp_session.calls == [("Browser.setDownloadBehavior", {
        "behavior": "allow", "downloadPath": str(tmp_path), "eventsEnabled": True,
    })]
    assert browser.cdp_session.detached is True
    assert observer.snapshots == [tmp_path]
    assert page.clicked[-1] == "export"


def test_competitor_export_uses_reviewed_overflow_hover_at_compact_viewport(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    profile = replace(
        valid_profile(),
        competitor_results_ready="css=competitor_results_ready",
        competitor_export_menu="css=competitor_export",
        competitor_export="css=competitor_export",
        competitor_export_overflow="css=competitor_export_overflow",
    )
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"competitor_results_ready", "competitor_export_overflow"},
    )
    page.on_hover["competitor_export_overflow"] = lambda: page.visible_markers.add(
        "competitor_export"
    )
    session = PlaywrightSellerSpriteSession(
        profile=profile,
        download_dir=tmp_path,
        page=page,
        download_observer=observer,
    )

    assert session.export_competitor_products("current-amazon-list") is artifact

    assert page.hovered == ["competitor_export_overflow"]
    assert page.clicked == ["competitor_export"]
    assert observer.snapshots == [tmp_path]


def test_competitor_export_expands_compact_sellersprite_panel_before_waiting_for_table(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    profile = replace(
        valid_profile(),
        competitor_results_ready="css=competitor_results_ready",
        competitor_export_menu="css=competitor_export",
        competitor_export="css=competitor_export",
    )
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"panel_open"},
    )

    def expand_panel():
        page.visible_markers.update({
            "ready",
            "competitor_results_ready",
            "competitor_export",
        })

    page.on_click["panel_open"] = expand_panel
    session = PlaywrightSellerSpriteSession(
        profile=profile,
        download_dir=tmp_path,
        page=page,
        download_observer=observer,
    )

    assert session.export_competitor_products("current-amazon-list") is artifact

    assert page.clicked == ["panel_open", "competitor_export"]
    assert page.timeout_calls == [1000]
    assert observer.snapshots == [tmp_path]


def test_adapter_stops_for_configured_quota_state_before_any_export_click(tmp_path):
    profile = valid_profile().__class__(
        **{**valid_profile().__dict__, "quota_required": "css=quota_required"}
    )
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "quota_required", "reverse_keywords", "asin_input", "submit", "results_ready", "export_menu", "export"},
    )
    session = PlaywrightSellerSpriteSession(profile=profile, download_dir=tmp_path, page=page)

    with pytest.raises(SellerSpriteWorkflowError, match="SELLERSPRITE_QUOTA_EXCEEDED"):
        session.export_sellersprite_reverse_keywords("B00Q7OAN50")

    assert page.clicked == []


def test_adapter_cancellation_after_submit_prevents_results_snapshot_and_export(tmp_path):
    cancelled = False
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords", "asin_input", "submit", "results_ready", "export"},
    )

    def cancel_after_submit() -> None:
        nonlocal cancelled
        cancelled = True

    page.on_click["submit"] = cancel_after_submit
    observer = FakeObserver(object())
    session = PlaywrightSellerSpriteSession(
        profile=valid_profile(),
        download_dir=tmp_path,
        page=page,
        download_observer=observer,
        is_cancelled=lambda: cancelled,
    )

    with pytest.raises(SellerSpriteWorkflowError, match="CANCELLED"):
        session.export_sellersprite_reverse_keywords("B00Q7OAN50")

    assert page.clicked == ["reverse_keywords", "submit"]
    assert observer.snapshots == []


def test_adapter_never_uses_an_unvalidated_direct_profile(tmp_path):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"ready"})
    invalid_profile = valid_profile().__class__(
        **{**valid_profile().__dict__, "ready": "742,381"}
    )
    session = PlaywrightSellerSpriteSession(
        profile=invalid_profile,
        download_dir=tmp_path,
        page=page,
    )

    with pytest.raises(SellerSpriteWorkflowError, match="EXTENSION_UNAVAILABLE"):
        session.check_sellersprite_extension()

    assert page.clicked == []


@pytest.mark.parametrize("prefix", ["iframe", "shadow"])
def test_adapter_uses_explicit_profile_boundary_for_frame_or_shadow(tmp_path, prefix):
    page = FakePage(asin="B00Q7OAN50", visible_markers={"ready"})
    profile = valid_profile().__class__(
        **{**valid_profile().__dict__, "ready": f"{prefix}=css=host >> css=ready"}
    )
    session = PlaywrightSellerSpriteSession(
        profile=profile,
        download_dir=tmp_path,
        page=page,
    )

    session.check_sellersprite_extension()

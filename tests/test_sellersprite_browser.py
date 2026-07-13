from __future__ import annotations

from pathlib import Path

import pytest

from agent.sellersprite_models import SellerSpriteLocatorProfile
from agent.tools.sellersprite_browser import (
    PlaywrightSellerSpriteSession,
    SellerSpriteWorkflowError,
)


def valid_profile() -> SellerSpriteLocatorProfile:
    return SellerSpriteLocatorProfile(
        ready="css=ready",
        login_required="css=login_required",
        permission_required="css=permission_required",
        captcha="css=captcha",
        reverse_keywords="css=reverse_keywords",
        asin_input="css=asin_input",
        submit="css=submit",
        results_ready="css=results_ready",
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
        self.filled: dict[str, str] = {}
        self.url = f"https://www.amazon.com/dp/{asin}"

    def goto(self, url: str, **_kwargs) -> None:
        self.goto_calls.append(url)

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector.removeprefix("css="))

    def frame_locator(self, _selector: str) -> FakeLocator:
        return FakeLocator(self, "frame")

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


class FakeObserver:
    def __init__(self, artifact: object) -> None:
        self.artifact = artifact
        self.snapshots: list[Path] = []
        self.waits: list[tuple[Path, object, int]] = []

    def snapshot(self, path: Path) -> object:
        self.snapshots.append(path)
        return "snapshot"

    def wait(self, path: Path, snapshot: object, timeout_seconds: int) -> object:
        self.waits.append((path, snapshot, timeout_seconds))
        return self.artifact


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.contexts = [type("Context", (), {"pages": [page]})()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


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
    assert browser.closed and playwright.stopped


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


def test_adapter_snapshots_before_single_export_click_and_delegates_download(tmp_path):
    artifact = object()
    observer = FakeObserver(artifact)
    page = FakePage(
        asin="B00Q7OAN50",
        visible_markers={"ready", "reverse_keywords", "asin_input", "submit", "results_ready", "export"},
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
    assert page.clicked == ["reverse_keywords", "submit", "export"]
    assert page.filled == {"asin_input": "B00Q7OAN50"}
    assert observer.snapshots == [tmp_path]
    assert observer.waits == [(tmp_path, "snapshot", 17)]


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

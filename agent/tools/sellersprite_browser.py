"""Deterministic, profile-driven SellerSprite browser operations.

This module deliberately does not discover or synthesize selectors.  A
human-validated :class:`SellerSpriteLocatorProfile` is the sole authority for
extension interactions, which keeps the browser workflow safe to attach to a
user's already-running Chrome session through CDP.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from agent.browser_agent import _resolve_cdp_ws
from agent.sellersprite_models import SellerSpriteContext, SellerSpriteLocatorProfile
from agent.sellersprite_policy import normalize_sellersprite_error_code, validate_sellersprite_asin
from agent.tools.browser_downloads import (
    DownloadedArtifact,
    DownloadError,
    DownloadSnapshot,
    snapshot_download_dir,
    wait_for_new_download,
)
from agent.tools.sellersprite_importer import (
    ImportedSellerSpriteExport,
    SellerSpriteImportError,
    import_sellersprite_export,
)

_AMAZON_US_HOSTS = frozenset({"amazon.com", "www.amazon.com"})
_ASIN_PATH_RE = re.compile(r"^/dp/(?P<asin>[A-Z0-9]{10})(?:/|$)", re.IGNORECASE)
_HUMAN_TERMINAL_LOCATORS = (
    ("captcha", "CAPTCHA"),
    ("login_required", "SELLERSPRITE_LOGIN_REQUIRED"),
    ("permission_required", "SELLERSPRITE_PERMISSION_REQUIRED"),
    ("quota_required", "SELLERSPRITE_QUOTA_EXCEEDED"),
)
_PROFILE_LOCATOR_NAMES = (
    "panel_open",
    "ready",
    "login_required",
    "permission_required",
    "captcha",
    "reverse_keywords",
    "asin_input",
    "submit",
    "results_ready",
    "export_menu",
    "export",
)
_LOCATOR_PREFIXES = frozenset(
    {"css", "text", "role", "id", "name", "iframe", "shadow"}
)


class SellerSpriteWorkflowError(RuntimeError):
    """A browser-layer result that is safe to expose to the workflow."""

    def __init__(self, error_code: str) -> None:
        self.error_code = normalize_sellersprite_error_code(error_code)
        super().__init__(self.error_code)


class FilesystemDownloadObserver:
    """Small adapter so filesystem observation is fully replaceable in tests."""

    def snapshot(self, path: Path) -> DownloadSnapshot:
        return snapshot_download_dir(path)

    def wait(
        self,
        path: Path,
        snapshot: DownloadSnapshot,
        timeout_seconds: int,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> DownloadedArtifact:
        return wait_for_new_download(
            path,
            snapshot,
            timeout_seconds,
            cancel_check=cancel_check,
        )


class PlaywrightSellerSpriteSession:
    """Attach to Chrome and perform one profile-defined reverse-keyword export."""

    def __init__(
        self,
        *,
        profile: SellerSpriteLocatorProfile,
        download_dir: Path | str,
        browser_download_dir: Path | str | None = None,
        page_timeout_seconds: int = 45,
        export_timeout_seconds: int = 120,
        download_observer: Any | None = None,
        importer: Callable[[SellerSpriteContext, DownloadedArtifact], ImportedSellerSpriteExport]
        | None = None,
        page: Any | None = None,
        playwright_factory: Callable[[], Any] | None = None,
        cdp_resolver: Callable[[], str] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.profile = profile
        self.download_dir = Path(download_dir)
        self.browser_download_dir = str(browser_download_dir or download_dir)
        self.page_timeout_seconds = page_timeout_seconds
        self.export_timeout_seconds = export_timeout_seconds
        self._download_observer = download_observer or FilesystemDownloadObserver()
        self._importer = importer or import_sellersprite_export
        self._page = page
        self._playwright_factory = playwright_factory
        self._cdp_resolver = cdp_resolver or _resolve_cdp_ws
        self._is_cancelled = is_cancelled or (lambda: False)
        self._playwright: Any | None = None
        self._browser: Any | None = None

    @property
    def page(self) -> Any:
        if self._page is None:
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        return self._page

    def __enter__(self) -> "PlaywrightSellerSpriteSession":
        self._ensure_not_cancelled()
        if self._page is not None:
            return self
        try:
            self._ensure_not_cancelled()
            factory = self._playwright_factory or _default_playwright_factory
            self._playwright = factory()
            self._ensure_not_cancelled()
            cdp_endpoint = self._cdp_resolver()
            self._ensure_not_cancelled()
            self._browser = self._playwright.chromium.connect_over_cdp(
                cdp_endpoint
            )
            self._ensure_not_cancelled()
            self._page = _first_attached_page(self._browser)
            self._ensure_not_cancelled()
        except SellerSpriteWorkflowError:
            self._close()
            raise
        except Exception as exc:
            self._close()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE") from exc
        return self

    def __exit__(self, *_args: object) -> None:
        self._close()

    def open_amazon_product(self, asin: str) -> None:
        asin = validate_sellersprite_asin(asin)
        target = f"https://www.amazon.com/dp/{asin}"
        self._ensure_not_cancelled()
        try:
            self.page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self.page_timeout_seconds * 1000,
            )
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()
        try:
            self.page.wait_for_timeout(5000)
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()
        if not _page_asin_matches(self.page, asin):
            raise SellerSpriteWorkflowError("ASIN_MISMATCH")
        self._ensure_not_cancelled()

    def open_sellersprite_page(self, url: str) -> None:
        """Navigate to a SellerSprite web-app page for the competitor flow."""
        target = (url or "").strip()
        if not target:
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()
        try:
            self.page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self.page_timeout_seconds * 1000,
            )
            self.page.wait_for_timeout(3000)
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()
        self._raise_if_human_terminal()

    def check_sellersprite_extension(self) -> None:
        self._ensure_not_cancelled()
        if not _profile_is_valid(self.profile):
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._raise_if_human_terminal()
        if not self._is_visible("ready"):
            self._click_required("panel_open")
            # The extension expands asynchronously after navigation.  Keep a
            # bounded settling interval before evaluating the explicit ready
            # marker; do not infer readiness from the click itself.
            try:
                self.page.wait_for_timeout(1000)
            except Exception as exc:
                raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE") from exc
            self._ensure_not_cancelled()
            self._raise_if_human_terminal()
        if not self._is_visible("ready"):
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()

    def export_sellersprite_reverse_keywords(self, asin: str) -> DownloadedArtifact:
        """Click exactly one configured Export control after a directory snapshot."""

        asin = validate_sellersprite_asin(asin)
        self._ensure_not_cancelled()
        self._raise_if_human_terminal()
        self._click_required("reverse_keywords")
        self._raise_if_human_terminal()
        self._fill_required("asin_input", asin)
        self._click_required("submit")
        self._raise_if_human_terminal()
        if not self._wait_until_visible("results_ready"):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()
        # SellerSprite renders the result marker before the table actions. In
        # practice the export control can appear 1–2 minutes later, so using
        # ``results_ready`` alone races the export click and is misclassified
        # as extension-unavailable. Wait for the reviewed export locator too.
        overflow_opened = False
        if getattr(self.profile, "export_overflow", "") and self._is_visible("export_overflow"):
            self._click_required("export_overflow")
            overflow_opened = True
        export_visible = self._wait_until_visible(
            "export_menu",
            timeout_seconds=max(
                int(self.page_timeout_seconds),
                int(self.export_timeout_seconds),
            ),
        )
        if not export_visible and not overflow_opened and getattr(self.profile, "export_overflow", ""):
            # The extension uses a compact responsive footer at the current
            # CDP viewport. Open its explicit overflow menu, then re-check the
            # reviewed export locator; no selector discovery is performed.
            self._click_required("export_overflow")
            export_visible = self._wait_until_visible(
                "export_menu",
                timeout_seconds=int(self.page_timeout_seconds),
            )
        if not export_visible:
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

        self._ensure_not_cancelled()
        self._raise_if_human_terminal()
        self._configure_download_behavior()
        self._ensure_not_cancelled()
        direct_export = self.profile.export_menu == self.profile.export
        if not direct_export:
            self._click_required("export_menu")
        self._ensure_not_cancelled()
        try:
            snapshot = self._download_observer.snapshot(self.download_dir)
        except SellerSpriteWorkflowError:
            raise
        except DownloadError as exc:
            raise SellerSpriteWorkflowError(exc.error_code) from exc
        except Exception as exc:
            raise SellerSpriteWorkflowError("INVALID_EXPORT") from exc
        self._ensure_not_cancelled()

        self._raise_if_human_terminal()
        self._click_required("export")
        self._ensure_not_cancelled()
        return self.wait_for_browser_download(snapshot)

    def export_competitor_products(self, keyword: str) -> DownloadedArtifact:
        """Run exactly one profile-defined competitor/market export.

        Uses either a profile-defined keyword search, or the product list
        already visible in the attached Amazon tab. Selectors come only from
        the human-validated competitor_* locators; none are discovered here.
        """
        keyword = (keyword or "").strip()
        if not keyword:
            raise SellerSpriteWorkflowError("INVALID_EXPORT")
        if not self.profile.has_competitor_locators():
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

        self._ensure_not_cancelled()
        self._raise_if_human_terminal()
        if not self._is_visible("competitor_results_ready"):
            # Amazon search pages often start with SellerSprite's compact
            # toolbar only. Expand the reviewed extension panel before waiting
            # for the competitor table; otherwise the UI can look configured
            # while the export waits until timeout for a table that is never
            # rendered.
            self.check_sellersprite_extension()
        if getattr(self.profile, "competitor_lookup", ""):
            self._click_required("competitor_lookup")
            self._raise_if_human_terminal()
        search_input = getattr(self.profile, "competitor_keyword_input", "")
        search_submit = getattr(self.profile, "competitor_submit", "")
        if bool(search_input) != bool(search_submit):
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        if search_input:
            self._fill_required("competitor_keyword_input", keyword)
            self._click_required("competitor_submit")
            self._raise_if_human_terminal()
        results_timeout = max(int(self.page_timeout_seconds), int(self.export_timeout_seconds))
        if not self._wait_until_visible("competitor_results_ready", timeout_seconds=results_timeout):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()

        overflow_locator = getattr(self.profile, "competitor_export_overflow", "")
        export_visible = self._is_visible("competitor_export_menu")
        overflow_opened = False
        if (
            not export_visible
            and overflow_locator
            and self._is_visible("competitor_export_overflow")
        ):
            # At compact Chrome viewports SellerSprite exposes the footer
            # actions in a reviewed hover popover, rather than after a click.
            # Hover first; retain the click fallback below for profiles whose
            # explicit overflow control is click-driven.
            self._hover_required("competitor_export_overflow")
            overflow_opened = True
        if not export_visible:
            export_visible = self._wait_until_visible(
                "competitor_export_menu", timeout_seconds=int(self.page_timeout_seconds)
            )
        if not export_visible and not overflow_opened and overflow_locator:
            self._click_required("competitor_export_overflow")
            export_visible = self._wait_until_visible(
                "competitor_export_menu", timeout_seconds=int(self.page_timeout_seconds)
            )
        if not export_visible:
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

        self._ensure_not_cancelled()
        self._raise_if_human_terminal()
        self._configure_download_behavior()
        self._ensure_not_cancelled()
        direct_export = self.profile.competitor_export_menu == self.profile.competitor_export
        if not direct_export:
            self._click_required("competitor_export_menu")
        self._ensure_not_cancelled()
        try:
            snapshot = self._download_observer.snapshot(self.download_dir)
        except SellerSpriteWorkflowError:
            raise
        except DownloadError as exc:
            raise SellerSpriteWorkflowError(exc.error_code) from exc
        except Exception as exc:
            raise SellerSpriteWorkflowError("INVALID_EXPORT") from exc
        self._ensure_not_cancelled()

        self._raise_if_human_terminal()
        self._click_required("competitor_export")
        self._ensure_not_cancelled()
        return self.wait_for_browser_download(snapshot)

    def wait_for_browser_download(self, snapshot: DownloadSnapshot) -> DownloadedArtifact:
        self._ensure_not_cancelled()
        try:
            artifact = self._download_observer.wait(
                self.download_dir,
                snapshot,
                self.export_timeout_seconds,
                cancel_check=self._is_cancelled,
            )
        except SellerSpriteWorkflowError:
            raise
        except DownloadError as exc:
            raise SellerSpriteWorkflowError(exc.error_code) from exc
        except Exception as exc:
            raise SellerSpriteWorkflowError("DOWNLOAD_TIMEOUT") from exc
        self._ensure_not_cancelled()
        return artifact

    def _configure_download_behavior(self) -> None:
        """Allow downloads only for this attached Chrome CDP browser session."""
        if self._browser is None:
            # Unit-test adapters may inject a page without a real browser. A
            # production session obtains ``_browser`` through CDP in __enter__.
            return
        try:
            cdp_session = self._browser.new_browser_cdp_session()
            try:
                cdp_session.send(
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": self.browser_download_dir,
                        "eventsEnabled": True,
                    },
                )
            finally:
                cdp_session.detach()
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("DOWNLOAD_TIMEOUT") from exc

    def import_sellersprite_export(
        self,
        context: SellerSpriteContext,
        artifact: DownloadedArtifact,
    ) -> ImportedSellerSpriteExport:
        try:
            return self._importer(context, artifact)
        except SellerSpriteImportError as exc:
            raise SellerSpriteWorkflowError(exc.error_code) from exc
        except Exception as exc:
            raise SellerSpriteWorkflowError("INVALID_EXPORT") from exc

    def _click_required(self, locator_name: str) -> None:
        self._ensure_not_cancelled()
        if not self._wait_until_visible(locator_name):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()
        try:
            self._locator(locator_name).click(timeout=self.page_timeout_seconds * 1000)
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()

    def _hover_required(self, locator_name: str) -> None:
        self._ensure_not_cancelled()
        if not self._wait_until_visible(locator_name):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()
        try:
            self._locator(locator_name).hover(timeout=self.page_timeout_seconds * 1000)
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()

    def _fill_required(self, locator_name: str, value: str) -> None:
        self._ensure_not_cancelled()
        if not self._wait_until_visible(locator_name):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._ensure_not_cancelled()
        try:
            self._locator(locator_name).fill(
                value,
                timeout=self.page_timeout_seconds * 1000,
            )
        except SellerSpriteWorkflowError:
            raise
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        self._ensure_not_cancelled()

    def _raise_if_human_terminal(self) -> None:
        for locator_name, error_code in _HUMAN_TERMINAL_LOCATORS:
            if not getattr(self.profile, locator_name, ""):
                continue
            if self._is_visible(locator_name):
                raise SellerSpriteWorkflowError(error_code)

    def _is_visible(self, locator_name: str) -> bool:
        self._ensure_not_cancelled()
        try:
            visible = bool(self._locator(locator_name).is_visible())
        except SellerSpriteWorkflowError:
            raise
        except Exception:
            return False
        self._ensure_not_cancelled()
        return visible

    def _wait_until_visible(
        self,
        locator_name: str,
        *,
        timeout_seconds: int | None = None,
    ) -> bool:
        """Wait for one reviewed locator without discovering alternatives."""
        self._ensure_not_cancelled()
        try:
            locator = self._locator(locator_name)
            wait_for = getattr(locator, "wait_for", None)
            if callable(wait_for):
                wait_for(
                    state="visible",
                    timeout=(
                        int(timeout_seconds or self.page_timeout_seconds) * 1000
                    ),
                )
            visible = bool(locator.is_visible())
        except SellerSpriteWorkflowError:
            raise
        except Exception:
            return False
        self._ensure_not_cancelled()
        return visible

    def _locator(self, locator_name: str) -> Any:
        # The profile validates this locator's syntax at load time.  Passing it
        # verbatim preserves its explicit selector engine and forbids generated
        # selectors or coordinate-based interactions.
        self._ensure_not_cancelled()
        value = getattr(self.profile, locator_name)
        prefix, _separator, payload = value.partition("=")
        if prefix == "iframe":
            frame_selector, target_selector = _split_nested_locator(payload)
            locator = self.page.frame_locator(frame_selector).locator(target_selector)
            self._ensure_not_cancelled()
            return locator
        if prefix == "shadow":
            host_selector, target_selector = _split_nested_locator(payload)
            # Playwright locators pierce an open shadow root.  The explicit
            # host/target profile boundary prevents discovery or selector
            # generation; a closed root simply reports unavailable upstream.
            locator = self.page.locator(host_selector).locator(target_selector)
            self._ensure_not_cancelled()
            return locator
        locator = self.page.locator(value)
        self._ensure_not_cancelled()
        return locator

    def _ensure_not_cancelled(self) -> None:
        if self._is_cancelled():
            raise SellerSpriteWorkflowError("CANCELLED")

    def _close(self) -> None:
        _browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        # This is a CDP attachment to the user's visible Chrome session.
        # ``browser.close()`` would instruct Chrome to close, rather than just
        # disconnecting this client. Stopping Playwright below releases the
        # connection without touching the user's browser, pages, or downloads.
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def _default_playwright_factory() -> Any:
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def _first_attached_page(browser: Any) -> Any:
    """Select an Amazon page, never an arbitrary first Chrome tab.

    Playwright's CDP page order is not the visible tab-strip order. Chrome
    internal pages (notably ``chrome://settings/downloads``) can therefore be
    returned first and make a healthy SellerSprite extension look unavailable.
    The extension workflow is Amazon-only, so fail closed when no Amazon US
    page is open instead of attaching to an unrelated tab.
    """
    for context in getattr(browser, "contexts", []):
        for page in getattr(context, "pages", []):
            try:
                parsed = urlparse(str(page.url))
            except Exception:
                continue
            if (
                parsed.scheme in {"http", "https"}
                and (parsed.hostname or "").lower() in _AMAZON_US_HOSTS
            ):
                return page
    raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")


def _page_asin_matches(page: Any, asin: str) -> bool:
    """Accept only a final Amazon US `/dp/<ASIN>` URL for this export run."""

    try:
        parsed = urlparse(str(page.url))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    match = _ASIN_PATH_RE.match(parsed.path)
    return bool(match and host in _AMAZON_US_HOSTS and match.group("asin").upper() == asin)


def _profile_is_valid(profile: SellerSpriteLocatorProfile) -> bool:
    """Defend against callers bypassing ``SellerSpriteLocatorProfile.from_json``."""

    for name in _PROFILE_LOCATOR_NAMES:
        value = getattr(profile, name, None)
        if not _locator_value_is_valid(value):
            return False
    return True


def _locator_value_is_valid(value: object, *, nested: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, selector = value.partition("=")
    if not separator or prefix not in _LOCATOR_PREFIXES or not selector.strip():
        return False
    if prefix not in {"iframe", "shadow"}:
        return True
    if nested:
        return False
    try:
        outer, inner = _split_nested_locator(selector)
    except SellerSpriteWorkflowError:
        return False
    return _locator_value_is_valid(outer, nested=True) and _locator_value_is_valid(
        inner, nested=True
    )


def _split_nested_locator(value: str) -> tuple[str, str]:
    outer, separator, inner = value.partition(">>")
    if not separator or not outer.strip() or not inner.strip():
        raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
    return outer.strip(), inner.strip()

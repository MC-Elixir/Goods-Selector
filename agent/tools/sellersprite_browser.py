"""Deterministic, profile-driven SellerSprite browser operations.

This module deliberately does not discover or synthesize selectors.  A
human-validated :class:`SellerSpriteLocatorProfile` is the sole authority for
extension interactions, which keeps the browser workflow safe to attach to a
user's already-running Chrome session through CDP.
"""
from __future__ import annotations

import re
from pathlib import Path
from time import monotonic
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
_SOURCING_1688_HOSTS = frozenset({"aibuy.1688.com"})
_OFFER_ID_RE = re.compile(r"/offer/(\d+)", re.IGNORECASE)
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

# JavaScript executed inside each 1688 supplier card element to extract
# structured data.  Uses defensive accessors so missing sub-elements yield
# null rather than throwing.
_CARD_EXTRACT_JS = r"""
(el) => {
    const text = (sel) => {
        const node = el.querySelector(sel);
        return node ? node.textContent.trim() : '';
    };
    const attr = (sel, name) => {
        const node = el.querySelector(sel);
        return node ? (node.getAttribute(name) || '') : '';
    };
    const labeledValue = (label) => {
        for (const row of el.querySelectorAll('[class*="attrItem"], [class*="attribute"]')) {
            const labelNode = row.querySelector('[class*="attrLabel"], [class*="label"]');
            if ((labelNode?.textContent || '').trim() !== label) continue;
            const valueNode = row.querySelector('[class*="attrValue"], [class*="value"]');
            return (valueNode?.textContent || '').trim();
        }
        return '';
    };
    // The 1688 Newton page renders a result without an anchor in the public
    // markup. Its already-rendered React data is a fallback only; Python
    // still validates the returned offer URL before accepting a candidate.
    const reactCardData = () => {
        try {
            const fiberKey = Object.keys(el).find((key) => key.startsWith('__reactFiber$'));
            let fiber = fiberKey ? el[fiberKey] : null;
            for (let level = 0; fiber && level < 6; level += 1, fiber = fiber.return) {
                const data = fiber.memoizedProps?.data;
                if (data && typeof data === 'object' && (data.offerId || data.link || data.title)) {
                    return data;
                }
            }
        } catch (_) {
            // A different renderer simply falls back to the public DOM.
        }
        return {};
    };
    const cardData = reactCardData();
    const link = el.querySelector('a[href*="1688.com/offer/"], a[href*="detail.1688.com"]');
    const img = el.querySelector('img');
    const wrap = el.closest('[class*="productCellWrap"]') || el.parentElement;
    const body = (el.textContent || '').trim();
    const rowBody = ((wrap && wrap !== el ? wrap.textContent : body) || '').trim();
    const labeledFromBody = (label, valuePattern) => {
        const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const pattern = valuePattern || '[^\\n]+';
        const match = body.match(new RegExp(escaped + '\\s*[:：]\\s*(' + pattern + ')'));
        return match ? match[1].trim() : '';
    };
    const looksLikeCompany = (value) => /公司|厂|店|商行|工作室|集团|有限/.test(value || '');
    const looksLikeMetric = (value) => /复购率|月销|起批|起订|揽收|退款|评分/.test(value || '');
    const companyFromDom = [...el.querySelectorAll('.company, .supplier-name, .seller-nick, [class*="company"], [class*="supplier"]')]
        .map((node) => (node.textContent || '').trim())
        .find((value) => value && looksLikeCompany(value) && !looksLikeMetric(value)) || '';
    const factory = Boolean(
        el.querySelector('[class*="factory"], [class*="shili"], .icon-factory')
        || /实力商家|源头工厂|生产厂家/.test(rowBody)
        || /生产厂家|源头工厂|超级工厂/.test(String(cardData.gmType || ''))
        || /超级工厂|源头工厂/.test(String(cardData.merchantIdentity || ''))
    );
    const trader = /贸易公司|经销批发/.test(rowBody)
        || /贸易公司|经销批发|贸易商/.test(String(cardData.gmType || ''));
    return {
        title: text('.title, .offer-title, [class*="title"]')
            || (link ? (link.textContent || '').trim() : '')
            || (cardData.title || '')
            || body.slice(0, 120),
        price: (() => {
            const fromDom = text('.price, .offer-price');
            if (fromDom && /\d/.test(fromDom)) return fromDom;
            if (cardData.price) return String(cardData.price);
            const hashed = text('[class*="productPrice"], [class*="priceInteger"]');
            return hashed && /\d/.test(hashed) ? hashed : '';
        })(),
        moq: text('.moq, .min-order, [class*="moq"], [class*="min-order"]')
            || ((body.match(/(\d+)\s*条起批/) || [])[1] || '')
            || ((body.match(/(\d+)\s*件起订/) || [])[1] || '')
            || (body.includes('一件起订') ? '1' : '')
            || (cardData.quantityBegin ? String(cardData.quantityBegin) : ''),
        monthly_sales: labeledFromBody('月销量', '[\\d,.]+\\s*万?\\+?')
            || (cardData.soldText || '')
            || text('.sales, .monthly-sales, [class*="sales"], [class*="deal"], [class*="sold"]'),
        repeat_buyer_rate: labeledFromBody('复购率', '\\d+(?:\\.\\d+)?\\s*%')
            || labeledFromBody('回头率', '\\d+(?:\\.\\d+)?\\s*%')
            || (cardData.repurchaseRate || '')
            || labeledValue('回头率:'),
        supplier_name: companyFromDom || (cardData.companyName || ''),
        offer_url: link ? link.href : (cardData.link || ''),
        image_url: img ? (img.src || img.getAttribute('data-src') || '') : (cardData.imageUrl || ''),
        gm_type: cardData.gmType || '',
        merchant_identity: cardData.merchantIdentity || '',
        delivery_time: cardData.deliveryTime || '',
        is_factory: factory ? true : (trader ? false : null),
    };
}
"""


def _raw_offer_id(raw: dict[str, Any]) -> str:
    match = _OFFER_ID_RE.search(str(raw.get("offer_url") or ""))
    return match.group(1) if match else ""


def _merge_raw_sourcing_cards(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill empty dialog-card fields from Newton cards with the same offer id."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in primary:
        offer_id = _raw_offer_id(raw) or f"idx:{len(order)}"
        by_id[offer_id] = dict(raw)
        order.append(offer_id)
    for raw in secondary:
        offer_id = _raw_offer_id(raw)
        if not offer_id:
            continue
        if offer_id not in by_id:
            continue
        merged = dict(by_id[offer_id])
        for key, value in raw.items():
            current = merged.get(key)
            if current in (None, "") and value not in (None, ""):
                merged[key] = value
        by_id[offer_id] = merged
    return [by_id[offer_id] for offer_id in order]


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
                cdp_endpoint, timeout=self.page_timeout_seconds * 1000,
            )
            self._ensure_not_cancelled()
            self._page = _first_attached_page(self._browser)
            self._ensure_not_cancelled()
        except SellerSpriteWorkflowError:
            self._close()
            raise
        except TimeoutError:
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
        if _page_asin_matches(self.page, asin):
            self._ensure_not_cancelled()
            return
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

    def read_product_packaging(self, asin: str) -> dict:
        """Read explicit package values without a query or download."""
        from agent.sellersprite_packaging import parse_packaging_panel

        self._ensure_not_cancelled()
        self._raise_if_human_terminal()
        if not _page_asin_matches(self.page, asin):
            raise SellerSpriteWorkflowError("ASIN_MISMATCH")
        if not self.profile.product_packaging:
            return {}
        if not self._wait_until_visible("product_packaging", timeout_seconds=10):
            return {}
        text = self._target_locator("product_packaging").inner_text(
            timeout=self.page_timeout_seconds * 1000
        )
        self._ensure_not_cancelled()
        return parse_packaging_panel(text, asin=asin, source_ref=self.page.url)

    def check_sellersprite_extension(self) -> None:
        self._ensure_not_cancelled()
        if not _profile_is_valid(self.profile):
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        self._raise_if_human_terminal()
        if not self._is_visible("ready"):
            # Some extension builds inject the panel shell first and render a
            # login/permission state several seconds later without exposing
            # the compact panel button.  Wait for the reviewed ready marker,
            # then re-check terminal locators before declaring the extension
            # unavailable.  No selector discovery or sourcing action occurs.
            if not self._is_visible("panel_open"):
                if self._wait_until_visible(
                    "ready",
                    timeout_seconds=min(int(self.page_timeout_seconds), 10),
                ):
                    self._ensure_not_cancelled()
                    return
                self._raise_if_human_terminal()
                raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
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

    def source_1688_suppliers(self, asin: str) -> list[dict[str, Any]]:
        """Open SellerSprite's 1688 sourcing modal and extract supplier cards.

        Current SellerSprite 5.x opens an in-page ``dialog-source`` modal on
        the Amazon product page. Older layouts that open a 1688 Newton tab
        remain a fallback. Returns raw dicts; the caller converts them into
        SupplierDTO objects.
        """
        asin = validate_sellersprite_asin(asin)
        if not self.profile.has_sourcing_1688_locators():
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

        self._ensure_not_cancelled()
        self._raise_if_human_terminal()

        if getattr(self.profile, "sourcing_1688_login", "") and self._is_visible("sourcing_1688_login"):
            raise SellerSpriteWorkflowError("SELLERSPRITE_LOGIN_REQUIRED")

        results_timeout = max(int(self.page_timeout_seconds), int(self.export_timeout_seconds))
        if self._wait_until_attached("sourcing_1688_results", timeout_seconds=min(2, results_timeout)):
            return self._extract_sourcing_1688_cards()

        dialog_open = bool(
            getattr(self.profile, "sourcing_1688_dialog", "")
            and self._is_visible("sourcing_1688_dialog")
        )
        known_pages = self._attached_pages()
        if not dialog_open:
            self._reveal_sourcing_1688_nav()
            known_pages = self._attached_pages()
            self._click_required("sourcing_1688_nav")
            self._raise_if_human_terminal()
            self._ensure_not_cancelled()

        if self._wait_until_attached("sourcing_1688_results", timeout_seconds=results_timeout):
            return self._extract_sourcing_1688_cards()

        self._switch_to_sourcing_1688_page(known_pages)
        self._raise_if_human_terminal()
        self._ensure_not_cancelled()
        if not self._wait_until_attached("sourcing_1688_results", timeout_seconds=results_timeout):
            self._raise_if_human_terminal()
            if getattr(self.profile, "sourcing_1688_login", "") and self._is_visible("sourcing_1688_login"):
                raise SellerSpriteWorkflowError("SELLERSPRITE_LOGIN_REQUIRED")
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")
        return self._extract_sourcing_1688_cards()

    def _extract_sourcing_1688_cards(self) -> list[dict[str, Any]]:
        self._ensure_not_cancelled()
        try:
            self.page.wait_for_timeout(2000)
        except Exception:
            pass
        self._ensure_not_cancelled()
        try:
            cards = self._locator("sourcing_1688_card")
            count = cards.count()
        except Exception as exc:
            raise SellerSpriteWorkflowError("EXPORT_FAILED") from exc
        if count == 0:
            return []
        suppliers: list[dict[str, Any]] = []
        for i in range(min(count, 30)):
            self._ensure_not_cancelled()
            try:
                card = cards.nth(i)
                raw = card.evaluate(_CARD_EXTRACT_JS)
                if isinstance(raw, dict) and raw.get("title"):
                    suppliers.append(raw)
            except Exception:
                raise SellerSpriteWorkflowError("EXPORT_FAILED") from None
        self._ensure_not_cancelled()
        return suppliers

    def _reveal_sourcing_1688_nav(self) -> None:
        """Bring the lazily injected Amazon product quick-view into the DOM."""
        self._ensure_not_cancelled()
        if self._is_visible("sourcing_1688_nav"):
            return
        try:
            self.page.locator("#productTitle").scroll_into_view_if_needed(
                timeout=self.page_timeout_seconds * 1000
            )
        except Exception:
            try:
                self.page.evaluate("window.scrollTo(0, 900)")
            except Exception as exc:
                raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE") from exc
        self._ensure_not_cancelled()
        if not self._wait_until_visible(
            "sourcing_1688_nav",
            timeout_seconds=int(self.page_timeout_seconds),
        ):
            self._raise_if_human_terminal()
            raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

    def _attached_pages(self) -> tuple[Any, ...]:
        if self._browser is None:
            return (self.page,)
        return tuple(
            page
            for context in self._browser.contexts
            for page in context.pages
        )

    def _switch_to_sourcing_1688_page(self, known_pages: tuple[Any, ...]) -> None:
        """Switch to the SellerSprite 1688 Newton tab.

        Prefer a newly opened tab. If the extension reuses an already-open
        Newton page, wait briefly for a new tab then fall back to the newest
        existing one instead of treating that reuse as an extension failure.
        """
        if _is_sourcing_1688_url(getattr(self.page, "url", "")):
            return
        known_newton = any(
            _is_sourcing_1688_url(getattr(page, "url", "")) for page in known_pages
        )
        wait_seconds = min(
            max(int(self.page_timeout_seconds), int(self.export_timeout_seconds)),
            30,
        )
        if known_newton:
            wait_seconds = min(wait_seconds, 3)
        deadline = monotonic() + wait_seconds
        existing: list[Any] = []
        while monotonic() < deadline:
            self._ensure_not_cancelled()
            existing = [
                candidate
                for candidate in self._attached_pages()
                if _is_sourcing_1688_url(getattr(candidate, "url", ""))
            ]
            for candidate in existing:
                if candidate in known_pages:
                    continue
                self._adopt_sourcing_1688_page(candidate)
                return
            try:
                self.page.wait_for_timeout(250)
            except Exception as exc:
                raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE") from exc
        if existing:
            self._adopt_sourcing_1688_page(existing[-1])
            return
        raise SellerSpriteWorkflowError("EXTENSION_UNAVAILABLE")

    def _adopt_sourcing_1688_page(self, candidate: Any) -> None:
        self._page = candidate
        try:
            candidate.wait_for_load_state(
                "domcontentloaded",
                timeout=self.page_timeout_seconds * 1000,
            )
        except Exception:
            # The reviewed results locator below, rather than navigation
            # alone, remains the authority for result readiness.
            pass

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
            self._target_locator(locator_name).click(timeout=self.page_timeout_seconds * 1000)
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
            self._target_locator(locator_name).hover(timeout=self.page_timeout_seconds * 1000)
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
            self._target_locator(locator_name).fill(
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
            visible = bool(self._target_locator(locator_name).is_visible())
        except SellerSpriteWorkflowError:
            raise
        except TimeoutError:
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
            locator = self._target_locator(locator_name)
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

    def _wait_until_attached(
        self,
        locator_name: str,
        *,
        timeout_seconds: int | None = None,
    ) -> bool:
        """Wait for one reviewed locator to be present, even below the fold."""
        self._ensure_not_cancelled()
        try:
            locator = self._locator(locator_name)
            first = getattr(locator, "first", locator)
            wait_for = getattr(locator, "wait_for", None)
            if callable(wait_for):
                getattr(first, "wait_for", wait_for)(
                    state="attached",
                    timeout=(
                        int(timeout_seconds or self.page_timeout_seconds) * 1000
                    ),
                )
            attached = locator.count() > 0
        except SellerSpriteWorkflowError:
            raise
        except Exception:
            return False
        self._ensure_not_cancelled()
        return attached

    def _target_locator(self, locator_name: str) -> Any:
        """Use the first match so duplicate extension nodes do not fail strict mode."""
        locator = self._locator(locator_name)
        return getattr(locator, "first", locator)

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


def _is_sourcing_1688_url(url: object) -> bool:
    if not isinstance(url, str) or not url:
        return False
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return hostname in _SOURCING_1688_HOSTS


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

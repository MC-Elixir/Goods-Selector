"""SellerSprite extension 1688 sourcing integration.

Drives the SellerSprite browser extension's embedded "1688找货" feature on an
Amazon product page, extracts matched 1688 suppliers from the extension panel
DOM, and converts them into SupplierDTO objects for the pipeline match stage.

This module never fabricates supplier data.  An unconfigured integration is
skipped, while a configured integration that needs login, permission, quota,
captcha, or extension repair raises a typed human-action handoff.
"""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from loguru import logger

from agent.sellersprite_policy import validate_sellersprite_asin
from agent.sellersprite_service import SellerSpriteDependencies
from agent.tools.sellersprite_browser import SellerSpriteWorkflowError
from agent.cancellation import CancellationRequested
from execution.models import HumanActionRequired
from matchers.alibaba_pailitao import SupplierDTO


# Human-terminal error codes that should not be retried or logged as warnings.
_HUMAN_CODES = frozenset({
    "EXTENSION_UNAVAILABLE",
    "SELLERSPRITE_LOGIN_REQUIRED",
    "SELLERSPRITE_PERMISSION_REQUIRED",
    "SELLERSPRITE_QUOTA_EXCEEDED",
    "CAPTCHA",
})

_OFFER_ID_RE = re.compile(r"/offer/(\d+)", re.IGNORECASE)

_HUMAN_INSTRUCTIONS = {
    "EXTENSION_UNAVAILABLE": "请在 9222 专用 Chrome 中确认卖家精灵插件已启用、已登录且产品页可见插件面板，然后继续任务。",
    "SELLERSPRITE_LOGIN_REQUIRED": "请在 9222 专用 Chrome 中登录卖家精灵和 1688，然后继续任务。",
    "SELLERSPRITE_PERMISSION_REQUIRED": "请在卖家精灵插件中确认当前账号已开通 1688 找货权限。",
    "SELLERSPRITE_QUOTA_EXCEEDED": "卖家精灵 1688 找货额度不足；请恢复额度后继续任务。",
    "CAPTCHA": "请在 9222 专用 Chrome 中完成验证码或滑块，然后继续任务。",
}


def run_sellersprite_1688_sourcing(
    asin: str,
    *,
    cancel_check: Callable[[], bool] | None = None,
    dependencies: SellerSpriteDependencies | None = None,
) -> list[SupplierDTO]:
    """Use the SellerSprite extension to find 1688 suppliers for an ASIN.

    Returns a list of SupplierDTO objects extracted from the extension's 1688
    sourcing panel. Returns an empty list when the integration is unconfigured
    or yields no results; configured human-terminal states are raised.
    """
    asin = validate_sellersprite_asin(asin)
    deps = dependencies or SellerSpriteDependencies()

    # Guard: browser flow must be enabled and locators configured.
    if not deps.browser_enabled or deps.profile is None or deps.session_factory is None:
        logger.debug(f"[sellersprite-1688] ASIN={asin} skipped: browser flow not configured")
        return []
    if not deps.profile.has_sourcing_1688_locators():
        logger.debug(f"[sellersprite-1688] ASIN={asin} skipped: sourcing_1688 locators not configured")
        return []

    is_cancelled = cancel_check or deps.is_cancelled or (lambda: False)

    try:
        with deps.session_factory() as session:
            session.open_amazon_product(asin)
            if is_cancelled():
                raise CancellationRequested("cancelled during SellerSprite 1688 sourcing")
            session.check_sellersprite_extension()
            if is_cancelled():
                raise CancellationRequested("cancelled during SellerSprite 1688 sourcing")
            raw_suppliers = session.source_1688_suppliers(asin)
    except SellerSpriteWorkflowError as exc:
        if exc.error_code in _HUMAN_CODES:
            raise HumanActionRequired(
                exc.error_code,
                f"SellerSprite 1688 sourcing requires human action for ASIN {asin}",
                instructions=_HUMAN_INSTRUCTIONS[exc.error_code],
            ) from exc
        logger.info(f"[sellersprite-1688] ASIN={asin} workflow error: {exc.error_code}")
        return []
    except CancellationRequested:
        raise
    except HumanActionRequired:
        raise
    except Exception as exc:
        logger.info(f"[sellersprite-1688] ASIN={asin} unexpected error: {exc}")
        return []

    if not raw_suppliers:
        logger.debug(f"[sellersprite-1688] ASIN={asin} no suppliers found in extension panel")
        return []

    suppliers = _convert_to_supplier_dtos(raw_suppliers, asin)
    if suppliers:
        logger.info(
            f"[sellersprite-1688] ASIN={asin} extracted {len(suppliers)} suppliers from extension"
        )
    return suppliers


def _convert_to_supplier_dtos(
    raw_suppliers: list[dict[str, Any]],
    asin: str,
) -> list[SupplierDTO]:
    """Convert raw DOM-extracted dicts into validated SupplierDTO objects."""
    results: list[SupplierDTO] = []
    seen_offer_ids: set[str] = set()

    for raw in raw_suppliers:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue

        offer_url = str(raw.get("offer_url") or "").strip()
        offer_id = _extract_offer_id(offer_url)
        if not offer_id:
            # A stable 1688 offer identity is required for a decision-grade
            # match.  Never invent an offer ID or a clickable detail URL.
            continue

        if offer_id in seen_offer_ids:
            continue
        seen_offer_ids.add(offer_id)

        price = _parse_price(raw.get("price"))
        moq = _parse_int(raw.get("moq"))
        monthly_sales = _parse_int(raw.get("monthly_sales"))
        supplier_name = str(raw.get("supplier_name") or "").strip() or None
        image_url = str(raw.get("image_url") or "").strip() or None
        is_factory_raw = raw.get("is_factory")
        is_factory = is_factory_raw if isinstance(is_factory_raw, bool) else None

        dto = SupplierDTO(
            alibaba_offer_id=offer_id,
            supplier_name=supplier_name,
            offer_url=offer_url,
            offer_image_url=image_url,
            moq=moq,
            base_price_cny=price,
            price_tiers=[{"qty": moq or 1, "price": price}] if price else None,
            monthly_sales=monthly_sales,
            repeat_buyer_rate=None,
            is_factory=is_factory,
            title_cn=title,
            # The extension finding a candidate is discovery evidence, not a
            # semantic match score.  The shared verifier fills this later.
            match_quality_score=None,
            match_verification_method="sellersprite_extension_unverified",
            raw_data={
                "source": "sellersprite_1688",
                "asin": asin,
                "observed_price": raw.get("price"),
                "observed_moq": raw.get("moq"),
                "observed_monthly_sales": raw.get("monthly_sales"),
                "identity_verified": True,
            },
        )
        results.append(dto)

    return results


def _extract_offer_id(url: str) -> str:
    """Extract numeric offer ID from a 1688 URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host != "1688.com" and not host.endswith(".1688.com"):
        return ""
    match = _OFFER_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    query = parse_qs(parsed.query)
    for key in ("offerId", "offer_id", "offerid"):
        value = (query.get(key) or [""])[0]
        if str(value).isdigit():
            return str(value)
    return ""


def _parse_price(value: object) -> float | None:
    """Parse a price string like '¥12.50' or '12.5-25.0' into a float."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Remove currency symbols and whitespace.
    text = re.sub(r"[¥￥$\s]", "", text)
    # Take the first number (lower bound of a range).
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        price = float(match.group(1))
        return price if 0 < price < 1_000_000 else None
    except (ValueError, OverflowError):
        return None


def _parse_int(value: object) -> int | None:
    """Parse an integer from a possibly noisy string like '月销 1200+' or '50件起订'."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d+)", text.replace(",", ""))
    if not match:
        return None
    try:
        result = int(match.group(1))
        return result if result > 0 else None
    except (ValueError, OverflowError):
        return None

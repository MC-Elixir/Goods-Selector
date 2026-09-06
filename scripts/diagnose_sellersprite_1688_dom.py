"""Read-only SellerSprite 1688 locator check against the attached Chrome.

The script opens one Amazon product page and the extension panel, but never
clicks the 1688 sourcing action.  It therefore validates reviewed locators
without spending sourcing quota or triggering a supplier search.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.browser_agent import _resolve_cdp_ws
from agent.sellersprite_browser_config import load_sellersprite_browser_config, project_local_path
from agent.sellersprite_models import SellerSpriteLocatorProfile
from config.settings import PROJECT_ROOT, settings


_DIAGNOSTIC_ASIN = "B00Q7OAN50"


def main() -> None:
    config = load_sellersprite_browser_config(PROJECT_ROOT, settings)
    profile_path = (
        project_local_path(PROJECT_ROOT, config.locator_profile_path)
        if config.locator_profile_path.startswith("/app/data/")
        else config.locator_profile_path
    )
    profile = SellerSpriteLocatorProfile.from_json(Path(profile_path))
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(_resolve_cdp_ws())
        page = next(
            page
            for context in browser.contexts
            for page in context.pages
            if page.url.startswith("http")
        )
        page.goto(
            f"https://www.amazon.com/dp/{_DIAGNOSTIC_ASIN}",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        page.wait_for_timeout(8_000)
        panel = page.locator(profile.panel_open).first
        if panel.is_visible():
            panel.click(timeout=30_000)
            page.wait_for_timeout(2_000)

        def state(name: str) -> dict[str, object]:
            selector = getattr(profile, name, "")
            if not selector:
                return {"configured": False, "count": 0, "visible": False}
            locator = page.locator(selector)
            return {
                "configured": True,
                "count": locator.count(),
                "visible": locator.first.is_visible() if locator.count() else False,
            }

        payload = {
            "page_url": page.url,
            "quota_consuming_action_performed": False,
            "locators": {
                name: state(name)
                for name in (
                    "panel_open",
                    "ready",
                    "login_required",
                    "permission_required",
                    "captcha",
                    "quota_required",
                    "sourcing_1688_nav",
                    "sourcing_1688_results",
                    "sourcing_1688_card",
                    "sourcing_1688_login",
                )
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Print sanitized SellerSprite locator diagnostics from the attached Chrome."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from agent.browser_agent import _resolve_cdp_ws
from agent.sellersprite_browser_config import (
    load_sellersprite_browser_config,
    project_local_path,
)
from agent.sellersprite_models import SellerSpriteLocatorProfile
from config.settings import PROJECT_ROOT, settings


def main() -> None:
    def emit(step: str, value: object) -> None:
        print(json.dumps({"step": step, "value": value}, ensure_ascii=False), flush=True)

    config = load_sellersprite_browser_config(PROJECT_ROOT, settings)
    raw_path = config.locator_profile_path
    profile_path = (
        project_local_path(PROJECT_ROOT, raw_path)
        if raw_path.startswith("/app/data/")
        else raw_path
    )
    profile = SellerSpriteLocatorProfile.from_json(Path(profile_path))
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(_resolve_cdp_ws())
        page = next(
            page
            for context in browser.contexts
            for page in context.pages
            if page.url.startswith("http")
        )
        page.goto(
            "https://www.amazon.com/dp/B00Q7OAN50",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        page.wait_for_timeout(10_000)
        emit("page_ready", page.url)
        panel = page.locator(profile.panel_open).first
        if panel.is_visible():
            emit("panel_open", True)
            panel.click(timeout=45_000)
            page.wait_for_timeout(3_000)
        workflow = {}
        reverse = page.locator(profile.reverse_keywords).first
        workflow["reverse_visible"] = reverse.is_visible()
        emit("reverse_visible", workflow["reverse_visible"])
        if reverse.is_visible():
            reverse.click(timeout=45_000)
            page.wait_for_timeout(2_000)
        asin_input = page.locator(profile.asin_input).first
        submit = page.locator(profile.submit).first
        workflow["asin_input_visible"] = asin_input.is_visible()
        workflow["submit_visible"] = submit.is_visible()
        emit("search_controls", {
            "asin_input": workflow["asin_input_visible"],
            "submit": workflow["submit_visible"],
        })
        if asin_input.is_visible() and submit.is_visible():
            asin_input.fill("B00Q7OAN50", timeout=45_000)
            submit.click(timeout=45_000)
            emit("submitted", True)
            page.wait_for_timeout(10_000)
        workflow["results_ready_visible"] = page.locator(
            profile.results_ready
        ).first.is_visible()
        workflow["export_menu_visible"] = page.locator(
            profile.export_menu
        ).first.is_visible()
        workflow["export_visible"] = page.locator(profile.export).first.is_visible()
        emit("result_controls", workflow)
        known = {
            name: {
                "count": page.locator(getattr(profile, name)).count(),
                "visible": page.locator(getattr(profile, name)).first.is_visible(),
            }
            for name in (
                "panel_open",
                "ready",
                "login_required",
                "captcha",
                "reverse_keywords",
            )
        }
        print(json.dumps(
            {
                "pages": [item.url for context in browser.contexts for item in context.pages],
                "selected_url": page.url,
                "known_locators": known,
                "workflow": workflow,
            },
            ensure_ascii=False,
            indent=2,
        ))
    finally:
        playwright.stop()


if __name__ == "__main__":
    main()

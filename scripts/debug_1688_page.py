"""
1688 搜索页调试：看真实页面结构
================================

3 个测试：
  1. 用现有 cookies + persistent profile 打开搜索页 → 保存 HTML
  2. 不带 cookies 匿名打开搜索页 → 保存 HTML
  3. 检查 1688 真实页面用的产品卡片选择器（与代码假设对比）

跑法：PYTHONIOENCODING=utf-8 py scripts/debug_1688_page.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
PROFILE_DIR = DATA_DIR / "browser_profiles" / "1688"
COOKIES_FILE = DATA_DIR / "1688_cookies.json"

SEARCH_URL = "https://s.1688.com/selloffer/offer_search.htm?keywords={kw}"


def get_proxy() -> str | None:
    return (
        os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    )


def load_cookies_into(ctx):
    if not COOKIES_FILE.exists():
        return 0
    import json
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    pw_cookies = []
    for c in cookies:
        pw_cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate", -1),
        })
    ctx.add_cookies(pw_cookies)
    return len(pw_cookies)


def test_with_profile(pw, label: str, use_cookies: bool):
    print(f"\n{'='*60}\n【{label}】\n{'='*60}")

    proxy = get_proxy()
    common = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": UA,
        "locale": "zh-CN",
    }
    if proxy:
        common["proxy"] = {"server": proxy}

    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        **common,
    )
    page = ctx.new_page() if ctx.pages else None
    if page is None:
        page = ctx.pages[0]
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    if use_cookies:
        n = load_cookies_into(ctx)
        print(f"  加载 {n} 个 cookies")
    else:
        print("  匿名模式（无 cookies）")

    url = SEARCH_URL.format(kw=quote("保温杯", encoding="gbk"))
    print(f"  访问: {url}")
    try:
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  goto 异常: {e}")

    time.sleep(8)

    final_url = page.url
    title = page.title()
    html_len = len(page.content())
    print(f"  最终 URL: {final_url}")
    print(f"  页面 title: {title!r}")
    print(f"  HTML 长度: {html_len}")

    # 保存截图 + HTML
    screenshot_path = DATA_DIR / f"debug_{label}.png"
    html_path = DATA_DIR / f"debug_{label}.html"
    page.screenshot(path=str(screenshot_path), full_page=False)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page.content())
    print(f"  截图: {screenshot_path}")
    print(f"  HTML: {html_path}")

    # 试多个选择器
    candidates = [
        "a.search-offer-item.major-offer",     # 项目里用的
        "a[data-aplus-report]",
        "div[data-aplus-report]",
        "a[href*='detail.1688.com']",
        "a[href*='offerId=']",
        ".sm-offer-item",
        "div.sm-offer-item",
        "[class*='offer']",
        "a[href*='detail.m.1688.com']",
    ]
    print("\n  选择器匹配结果:")
    for sel in candidates:
        n = page.locator(sel).count()
        marker = "  ←✓" if n > 0 else "    "
        print(f"   {marker} {sel!r:<50} → {n} 个")

    # 看看页面是不是风控/登录
    body_text = page.inner_text("body")[:500]
    print(f"\n  页面正文前 500 字:\n  {body_text[:500]!r}")

    ctx.close()


def main():
    print("1688 搜索页调试\n")
    with sync_playwright() as pw:
        test_with_profile(pw, "with_cookies", use_cookies=True)
        # 用新 profile 目录测匿名
        anon_dir = DATA_DIR / "browser_profiles" / "1688_anon"
        anon_dir.mkdir(parents=True, exist_ok=True)
        test_with_profile_anon(pw, anon_dir)

    print("\n结束。检查 data/debug_*.png 和 data/debug_*.html 找问题。")


def test_with_profile_anon(pw, profile_dir):
    print(f"\n{'='*60}\n【anon】\n{'='*60}")
    proxy = get_proxy()
    common = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": UA,
        "locale": "zh-CN",
    }
    if proxy:
        common["proxy"] = {"server": proxy}
    ctx = pw.chromium.launch_persistent_context(user_data_dir=str(profile_dir), **common)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    url = SEARCH_URL.format(kw=quote("保温杯", encoding="gbk"))
    print(f"  访问: {url}")
    try:
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  goto 异常: {e}")

    time.sleep(8)
    final_url = page.url
    title = page.title()
    print(f"  最终 URL: {final_url}")
    print(f"  页面 title: {title!r}")

    page.screenshot(path=str(DATA_DIR / "debug_anon.png"), full_page=False)
    with open(DATA_DIR / "debug_anon.html", "w", encoding="utf-8") as f:
        f.write(page.content())

    for sel in ["a.search-offer-item.major-offer", "a[href*='detail.1688.com']", "[class*='offer']"]:
        n = page.locator(sel).count()
        print(f"   {sel!r:<45} → {n} 个")

    body_text = page.inner_text("body")[:300]
    print(f"\n  正文前 300 字: {body_text!r}")

    ctx.close()


if __name__ == "__main__":
    sys.exit(main() or 0)

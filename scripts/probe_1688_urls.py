"""
1688 多入口探测
================

s.1688.com 搜索被 TMD 拦了。试这些 URL 看哪些能拿到结果：
  1. m.1688.com 移动端
  2. 1688.com 首页
  3. s.1688.com 主页（非搜索）
  4. detail.1688.com 商品详情
  5. pub.1688.com 老接口

跑法：PYTHONIOENCODING=utf-8 py scripts/probe_1688_urls.py
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

PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profiles" / "1688"
DATA_DIR = PROJECT_ROOT / "data"

URLS = [
    ("1688首页", "https://www.1688.com/"),
    ("1688移动首页", "https://m.1688.com/"),
    ("s.1688.com主页", "https://s.1688.com/"),
    ("1688搜索-保温杯", "https://s.1688.com/selloffer/offer_search.htm?keywords=" + quote("保温杯", encoding="gbk")),
    ("1688搜索-水杯", "https://m.1688.com/selloffer/offer_search.htm?keywords=" + quote("水杯", encoding="gbk")),
    ("offer详情-示例", "https://detail.1688.com/offer/573741401425.html"),
]


def main():
    print("1688 多入口探测\n")
    with sync_playwright() as pw:
        common = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": UA,
            "locale": "zh-CN",
        }
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        if proxy:
            common["proxy"] = {"server": proxy}

        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), **common
        )
        # 加载 cookies
        if (DATA_DIR / "1688_cookies.json").exists():
            import json
            with open(DATA_DIR / "1688_cookies.json", "r", encoding="utf-8") as f:
                cookies = json.load(f)
            pw_cookies = [{
                "name": c["name"], "value": c["value"],
                "domain": c["domain"], "path": c.get("path", "/"),
                "expires": c.get("expirationDate", -1),
            } for c in cookies]
            ctx.add_cookies(pw_cookies)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for label, url in URLS:
            print(f"\n{'='*60}\n【{label}】\n   {url}\n{'='*60}")
            try:
                resp = page.goto(url, timeout=30_000, wait_until="domcontentloaded", referer="https://www.1688.com/")
                time.sleep(6)
                final_url = page.url
                title = page.title()
                blocked = "验证码" in title or "punish" in final_url or "x5secdata" in final_url
                # 检查是否拿到了产品数据
                product_count = page.locator("a[href*='detail.1688.com'], a[href*='offerId=']").count()
                print(f"  HTTP: {resp.status if resp else '?'} | final: {final_url[:100]}")
                print(f"  title: {title!r}")
                print(f"  命中产品卡片: {product_count}")
                print(f"  被拦截: {'❌ 是' if blocked else '✅ 否'}")
                if not blocked and product_count > 0:
                    print("  >>> 这个 URL 可用！")
            except Exception as e:
                print(f"  异常: {e}")

        ctx.close()
    print("\n结束。")


if __name__ == "__main__":
    sys.exit(main() or 0)

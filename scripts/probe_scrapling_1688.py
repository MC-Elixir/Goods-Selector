"""
Scrapling 探针 v3：cookies + 反复测
===================================

观察 TMD 行为：
  1. 单请求：能绕过
  2. 多请求：第二次开始被拦
  3. 加 cookies 能不能撑过？
  4. Fetcher（非浏览器）能绕过吗？

跑法：PYTHONIOENCODING=utf-8 py scripts/probe_scrapling_1688.py
"""
from __future__ import annotations

import json
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

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="INFO", format="<g>{time:HH:mm:ss}</g> | {message}")

COOKIES_FILE = PROJECT_ROOT / "data" / "1688_cookies.json"


def load_cookies_for_scrapling():
    """把 Playwright cookies 格式转成 Scrapling 可用（返回 (cookies_str_for_url)）。"""
    if not COOKIES_FILE.exists():
        return None
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def test_stealth_with_cookies():
    print("\n" + "=" * 70)
    print("Test A: StealthyFetcher + cookies 反复请求")
    print("=" * 70)
    from scrapling.fetchers import StealthyFetcher

    cookie_str = load_cookies_for_scrapling()
    if not cookie_str:
        print("⚠️  没有 cookies 文件（用匿名模式）")
    else:
        print(f"  加载 {len(cookie_str)} 字符的 cookie 串")

    for i, kw in enumerate(["保温杯", "水杯", "不锈钢水杯"], 1):
        url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote(kw, encoding='gbk')}"
        print(f"\n  [{i}/{3}] {kw} - {url[:80]}")
        t0 = time.time()
        try:
            extra_headers = {"Cookie": cookie_str} if cookie_str else {}
            page = StealthyFetcher.fetch(
                url,
                headless=True,
                stealth=True,
                network_idle=True,
                timeout=60_000,
                extra_headers=extra_headers if extra_headers else None,
            )
        except Exception as e:
            print(f"      ❌ {e}")
            continue
        elapsed = time.time() - t0
        title = page.css("title::text").get() or ""
        if isinstance(title, bytes):
            title = title.decode("utf-8", errors="replace")
        print(f"      耗时: {elapsed:.1f}s | status: {page.status}")
        print(f"      title: {title[:60]!r}")
        cards = page.css("a[href*='detail.1688.com']")
        n_cards = len(cards) if hasattr(cards, "__len__") else 0
        print(f"      产品链接数: {n_cards}")
        if n_cards > 0:
            print("      ✅ 成功！")
            for c in cards[:2]:
                href = c.attrib.get("href", "")
                print(f"        - {href[:90]}")


def test_plain_fetcher():
    print("\n" + "=" * 70)
    print("Test B: Fetcher（HTTP-only，curl_cffi TLS 指纹伪装）")
    print("=" * 70)
    from scrapling.fetchers import Fetcher

    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={quote('保温杯', encoding='gbk')}"
    print(f"  URL: {url[:80]}")
    t0 = time.time()
    try:
        page = Fetcher.fetch(
            url,
            impersonate="chrome",
            stealthy_headers=True,
            timeout=30_000,
        )
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s | status: {page.status}")
    title = page.css("title::text").get() if page.css("title::text") else ""
    if isinstance(title, bytes):
        title = title.decode("utf-8", errors="replace")
    print(f"  title: {title[:60]!r}")
    cards = page.css("a[href*='detail.1688.com']")
    n = len(cards) if hasattr(cards, "__len__") else 0
    print(f"  产品链接数: {n}")


def main():
    test_stealth_with_cookies()
    test_plain_fetcher()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

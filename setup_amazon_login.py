"""
Amazon 登录配置工具
====================

打开浏览器让你手动登录 Amazon / 解验证码，登录后自动保存 cookies 到
data/amazon_cookies.json。下次跑爬虫时自动复用——能显著降低 captcha 触发概率。

用法：
    python setup_amazon_login.py

流程：
    1. 打开 Amazon 首页
    2. 你手动登录（或者解掉 captcha）
    3. 在另一个终端跑：
           echo 1 > data/.amazon_save_flag
    4. 脚本检测到 flag 后自动保存 cookies

使用 Playwright 持久浏览器上下文打开真实页面，并轮询 flag 文件保存 cookies。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

from crawlers._amazon_cookies import save_cookies

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {message}")


COOKIES_FILE = Path(__file__).parent / "data" / "amazon_cookies.json"
FLAG_FILE = Path(__file__).parent / "data" / ".amazon_save_flag"


def main() -> None:
    logger.info("=" * 60)
    logger.info("Amazon 登录配置工具")
    logger.info("=" * 60)
    logger.info("")
    logger.info("操作步骤：")
    logger.info("  1. 浏览器会自动打开 Amazon 首页")
    logger.info("  2. 如果出现 captcha，请在浏览器里解掉")
    logger.info("  3. （可选）登录你的 Amazon 账号")
    logger.info("  4. 在另一个终端跑：")
    logger.info(f"       echo 1 > {FLAG_FILE}")
    logger.info("     脚本会自动保存 cookies 然后退出")
    logger.info("")

    # 第一时间清掉旧 flag，避免上次中断遗留导致一启动就保存/退出。
    FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    FLAG_FILE.unlink(missing_ok=True)

    from playwright.sync_api import sync_playwright

    profile_dir = Path(__file__).parent / "data" / "amazon_login_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        locale="en-US",
        timezone_id="America/New_York",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--start-maximized",
        ],
    )

    try:
        logger.info("正在打开 Amazon 首页...")
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            "https://www.amazon.com",
            timeout=60_000,
            wait_until="domcontentloaded",
        )
        logger.info(f"已加载：{page.url[:80]}")

        logger.info("")
        logger.info("👉 请在浏览器里登录 / 解 captcha")
        logger.info(f"👉 然后在另一终端跑：echo 1 > {FLAG_FILE}")
        logger.info("")

        max_wait = 600  # 10 分钟
        start = time.time()
        saved = False
        last_heartbeat = start

        while time.time() - start < max_wait:
            if FLAG_FILE.exists():
                logger.info("检测到保存信号，正在导出 cookies...")
                try:
                    cookies = context.cookies()
                    if not cookies:
                        logger.warning("浏览器里没找到任何 cookies —— 你登录过吗？")
                    else:
                        if save_cookies(cookies, COOKIES_FILE):
                            logger.info(f"✅ 已保存 {len(cookies)} 个 cookies 到：{COOKIES_FILE}")
                            saved = True
                except Exception as e:
                    logger.error(f"保存失败: {e}")
                break

            now = time.time()
            if now - last_heartbeat >= 5:
                elapsed = int(now - start)
                remaining = int((max_wait - elapsed) / 60)
                logger.info(f"等待保存信号中...（已 {elapsed}s / 剩 {remaining} 分钟）")
                last_heartbeat = now

            time.sleep(2)

        if not saved:
            logger.warning("⚠️ 超时（10 分钟）—— cookies 未保存")

    finally:
        FLAG_FILE.unlink(missing_ok=True)
        try:
            context.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass

    logger.info("=" * 60)


if __name__ == "__main__":
    main()

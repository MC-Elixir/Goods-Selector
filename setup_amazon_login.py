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

镜像 setup_1688_login.py 的交互方式（headless=False + 轮询 flag 文件），因为
input() 在 headless=False 浏览器弹出后会被挂起。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

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

    from scrapling.fetchers import StealthySession

    session = StealthySession(
        headless=False,
        cookies=[],  # 不预设
        extra_headers={"Accept-Language": "en-US,en;q=0.9"},
        locale="en-US",
        timezone_id="America/New_York",
        useragent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        solve_cloudflare=True,
        hide_canvas=True,
        block_webrtc=True,
    )
    session.start()

    try:
        logger.info("正在打开 Amazon 首页...")
        page = session.fetch(
            "https://www.amazon.com",
            timeout=60_000,
            wait=3,
        )
        logger.info(f"已加载：{page.url[:80]}")

        # 清理旧 flag
        FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        FLAG_FILE.unlink(missing_ok=True)

        logger.info("")
        logger.info("👉 请在浏览器里登录 / 解 captcha")
        logger.info(f"👉 然后在另一终端跑：echo 1 > {FLAG_FILE}")
        logger.info("")

        max_wait = 600  # 10 分钟
        start = time.time()
        saved = False

        while time.time() - start < max_wait:
            if FLAG_FILE.exists():
                logger.info("检测到保存信号，正在导出 cookies...")
                try:
                    ctx = session.context
                    cookies = ctx.cookies() if ctx else []
                    if not cookies:
                        logger.warning("浏览器里没找到任何 cookies —— 你登录过吗？")
                    else:
                        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
                        import json
        #                     atomic write via temp + rename
                        import tempfile, os
                        fd, tmp = tempfile.mkstemp(
                            prefix=f".{COOKIES_FILE.name}.",
                            suffix=".tmp",
                            dir=str(COOKIES_FILE.parent),
                        )
                        try:
                            with os.fdopen(fd, "w", encoding="utf-8") as f:
                                json.dump(cookies, f, ensure_ascii=False, indent=2)
                            os.replace(tmp, COOKIES_FILE)
                            logger.info(f"✅ 已保存 {len(cookies)} 个 cookies 到：{COOKIES_FILE}")
                            saved = True
                        except Exception:
                            try:
                                os.unlink(tmp)
                            except OSError:
                                pass
                            raise
                except Exception as e:
                    logger.error(f"保存失败: {e}")
                break

            time.sleep(2)

            # 检查浏览器是否还活着
            try:
                # session.context 可能不响应，try 一小段
                if not session.context or not session.context.pages:
                    logger.warning("浏览器已关闭")
                    break
            except Exception:
                logger.warning("浏览器已关闭")
                break

        if not saved:
            logger.warning("⚠️ 超时或浏览器已关闭 —— cookies 未保存")

    finally:
        FLAG_FILE.unlink(missing_ok=True)
        try:
            session.close()
        except Exception:
            pass

    logger.info("=" * 60)


if __name__ == "__main__":
    main()

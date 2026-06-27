"""
1688 自动保存 cookies（非交互版）
================================
setup_1688_login.py 的精简版：打开浏览器 → 检测是否已登录 →
检测到登录就立刻保存 cookies 退出，不轮询等待 flag 文件。

适用：你刚才跑 setup_1688_login.py 时浏览器已显示登录态，
但脚本因没收到保存信号超时退出。再跑这个，登录态若还在就自动存上。

如果打开后是未登录状态，请在浏览器里手动登录/扫码/解滑块，
脚本每 3 秒检测一次，检测到 work.1688.com 就自动保存。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {message}")

COOKIES_FILE = Path(__file__).parent / "data" / "1688_cookies.json"


def _has_login_cookie(cookies: list) -> bool:
    """必须有 unb（1688 用户唯一标识）才算真正登录，否则只是访客态。
    这是关键防线：避免在登录页重定向链里误判为已登录、存下不完整 cookies。"""
    names = {c.get("name") for c in cookies}
    return "unb" in names


def save_cookies(session) -> int:
    ctx = session.context
    cookies = ctx.cookies() if ctx else []
    if not cookies:
        logger.warning("浏览器里没找到 cookies —— 登录了吗？")
        return 0
    relevant = [
        c for c in cookies
        if "1688" in c.get("domain", "") or "taobao" in c.get("domain", "")
    ]
    # 关键校验：没 unb 说明没真正登录，拒绝保存以免覆盖好文件
    if not _has_login_cookie(relevant):
        logger.warning(
            f"⚠️ 检测到 {len(relevant)} 个 cookies 但缺 unb（未真正登录），不保存"
        )
        logger.warning("   请在浏览器里完成登录/扫码/解滑块，脚本会继续检测...")
        return 0
    # 备份旧文件，避免再次覆盖
    if COOKIES_FILE.exists():
        bak = COOKIES_FILE.with_suffix(".json.bak")
        try:
            import shutil
            shutil.copy2(COOKIES_FILE, bak)
            logger.info(f"已备份旧 cookies → {bak.name}")
        except Exception:
            pass
    fd, tmp = tempfile.mkstemp(
        prefix=f".{COOKIES_FILE.name}.", suffix=".tmp", dir=str(COOKIES_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(relevant, f, ensure_ascii=False, indent=2)
        os.replace(tmp, COOKIES_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info(f"✅ 已保存 {len(relevant)} 个 1688 cookies（含 unb，登录有效）→ {COOKIES_FILE}")
    return len(relevant)


def main() -> None:
    from scrapling.fetchers import StealthySession

    session = StealthySession(
        headless=False,
        cookies=[],
        extra_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        useragent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        solve_cloudflare=True,
        hide_canvas=True,
        block_webrtc=True,
    )
    session.start()

    try:
        logger.info("打开 1688 登录入口...")
        logger.info("若浏览器显示登录页，请扫码/登录/解滑块；登录成功脚本自动保存。")
        page = session.fetch(
            "https://login.1688.com/member/signin.htm",
            timeout=60_000,
            wait=3,
        )
        logger.info(f"页面: {page.url[:70]}")

        # 判定登录的唯一标准：cookies 里有 unb（用户唯一标识）。
        # 不再用标题判断——登录页重定向链标题可能恰好含"采购批发"导致误判。
        def _try_save() -> int:
            try:
                cookies = session.context.cookies() if session.context else []
            except Exception:
                cookies = []
            relevant = [
                c for c in cookies
                if "1688" in c.get("domain", "") or "taobao" in c.get("domain", "")
            ]
            if _has_login_cookie(relevant):
                logger.info(f"检测到 unb，登录有效（{len(relevant)} 个 cookies），保存...")
                return save_cookies(session)
            return 0

        saved = _try_save()  # 首次：可能本来就已登录

        # 未登录则轮询：每 4 秒探测一次登录态，最长 5 分钟
        if not saved:
            logger.info("尚未登录，开始轮询检测（每 4s 一次，最多 5 分钟）...")
            start = time.time()
            while time.time() - start < 300:
                time.sleep(4)
                try:
                    session.fetch("https://work.1688.com/", timeout=30_000, wait=2)
                except Exception:
                    pass
                saved = _try_save()
                if saved:
                    break
                elapsed = int(time.time() - start)
                if elapsed % 16 < 4:
                    logger.info(f"⏳ 等待登录...（{elapsed}s / 最多 5 分钟）")

        if saved:
            logger.info(f"✅ 完成，已保存 {saved} 个 cookies（含 unb）。可重跑 E2E。")
        else:
            logger.warning("⚠️ 5 分钟内未检测到 unb（未真正登录），cookies 未保存，旧文件未动。")
    finally:
        try:
            session.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

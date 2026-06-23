"""
1688 登录配置工具（v2 — StealthySession 版）
=============================================

打开浏览器让你手动登录 1688，登录后自动保存 cookies 到
data/1688_cookies.json。下次跑爬虫时自动复用——能显著降低 1688 搜索页的
captcha / redirect-to-login 概率。

为什么不用裸 Playwright：
    1688 首页登录用的是 iframe 模态框，Cloudflare/Tengine 反爬对裸
    Playwright 指纹敏感 → 模态框 iframe 被拦截，弹出空白。Amazon 那边
    已经在用 patchright 修补的 chromium（更抗检测），同样策略也适用于 1688。

为什么打开 login.1688.com/member/signin.htm 而不是 login.taobao.com：
    1688 的登录实际走淘宝统一登录系统（login.taobao.com）。但直接打开
    login.taobao.com 会跳到通用的 i.taobao.com（国际版）登录页。
    必须从 1688 的入口 login.1688.com/member/signin.htm 走，302 链会带上
    from=1688web 这个参数，Taobao 才会渲染 1688 登录表单。
    旧版的 `login.1688.com/mini_login.htm` 已经 404 了。

用法：
    python setup_1688_login.py
流程：
    1. 浏览器会自动打开 https://login.1688.com/member/signin.htm
    2. 你手动登录（如果出现滑块请解掉）
    3. 登录成功后会跳到 work.1688.com —— 在另一终端跑：
           echo 1 > data/.1688_save_flag
    4. 脚本检测到 flag 后自动保存 cookies 然后退出
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {message}")


COOKIES_FILE = Path(__file__).parent / "data" / "1688_cookies.json"
FLAG_FILE = Path(__file__).parent / "data" / ".1688_save_flag"


def main() -> None:
    logger.info("=" * 60)
    logger.info("1688 登录配置工具 (v2 — StealthySession)")
    logger.info("=" * 60)
    logger.info("")

    # 第一时间清掉所有旧 flag —— 万一之前留了脏数据，脚本一启动就会误判
    # "已收到保存信号" 然后秒退。常见于上次脚本崩了/中断了没清理的情况。
    FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    FLAG_FILE.unlink(missing_ok=True)

    logger.info("操作步骤：")
    logger.info("  1. 浏览器会自动打开 https://login.1688.com/member/signin.htm")
    logger.info("  2. 用账号密码 / 扫码登录")
    logger.info("  3. 如果出现滑块 captcha，请手动解掉")
    logger.info("  4. 登录成功后会跳到 work.1688.com —— 然后选一种保存方式：")
    logger.info(f"     (a) 在另一终端跑：echo 1 > {FLAG_FILE}")
    logger.info("     (b) 或者直接在这个终端按 Enter 键")
    logger.info("  5. 脚本会自动保存 cookies 然后退出")
    logger.info("")

    # 复用 Amazon 那套 StealthySession 配置（patchright + curl_cffi 抗检测）
    from scrapling.fetchers import StealthySession

    session = StealthySession(
        headless=False,
        cookies=[],  # 不预设
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
        logger.info("正在打开 1688 登录入口 ...")
        # 必须从 login.1688.com/member/signin.htm 入口走 —— 它会 302 链
        # 重定向到 login.taobao.com/?...&from=1688web。
        # from=1688web 这个参数决定 Taobao 渲染 1688 登录表单（不是 i.taobao.com 通用登录）。
        page = session.fetch(
            "https://login.1688.com/member/signin.htm",
            timeout=60_000,
            wait=3,  # 等滑块/二维码 iframe 渲染
        )
        logger.info(f"已加载：{page.url[:80]}")
        # 防御：Adaptor 上 css("title") 可能返回空集合（一些挑战页无 <title>）
        title_nodes = page.css("title")
        title = (title_nodes.first.text or "").strip() if title_nodes else ""
        logger.info(f"页面标题：{title[:60]!r}")
        # 接受两种合法状态：
        #   - 登录页（title 含 "登录" 或 "login"）
        #   - 已登录跳到 work.1688.com / member.1688.com（"买家工作台"）
        page_url = page.url
        is_login_page = "登录" in title or "login" in title.lower()
        is_logged_in = "work.1688.com" in page_url or "member.1688.com" in page_url or "买家工作台" in title
        if not (is_login_page or is_logged_in):
            logger.warning(f"页面 title 不像登录页（{title!r}），可能没加载到正确页面")
            logger.info("请在浏览器里手动访问 https://login.1688.com/member/signin.htm")
        elif is_logged_in:
            logger.info("检测到页面已经是登录后的工作台（work.1688.com），直接保存 cookies")

        # 注意：不要检查 session.context.pages —— StealthySession 用 page-pool
        # 复用页面，fetch() 返回后页面可能已经放回池里，context.pages 列表在
        # 这种设计下不可靠。改用"轮询 flag 文件 + 周期心跳"的纯文件信号，
        # 10 分钟超时兜底。
        #
        # 之前试过在后台线程用 input() 监听 Enter 键，但有 bug：
        # 1) PowerShell 下 daemon thread 里的 input() 行为不稳，0 长度输入也
        #    会被当成 Enter
        # 2) 用户可能并不期望按 Enter 触发保存
        # 所以只保留 flag 文件这一种信号，更可预测。
        max_wait = 600  # 10 分钟
        start = time.time()
        saved = False
        last_heartbeat = start

        while time.time() - start < max_wait:
            if FLAG_FILE.exists():
                logger.info("检测到保存信号，正在导出 cookies...")
                try:
                    ctx = session.context
                    cookies = ctx.cookies() if ctx else []
                    if not cookies:
                        logger.warning("浏览器里没找到 cookies —— 你登录过吗？")
                    else:
                        # 过滤：只保留 1688 域的（防 Cookie 串味）
                        relevant = [
                            c for c in cookies
                            if "1688" in c.get("domain", "")
                            or "taobao" in c.get("domain", "")
                        ]
                        if not relevant:
                            logger.warning("没找到 1688/taobao 域的 cookies")
                        # 原子写
                        fd, tmp = tempfile.mkstemp(
                            prefix=f".{COOKIES_FILE.name}.",
                            suffix=".tmp",
                            dir=str(COOKIES_FILE.parent),
                        )
                        try:
                            with os.fdopen(fd, "w", encoding="utf-8") as f:
                                json.dump(relevant, f, ensure_ascii=False, indent=2)
                            os.replace(tmp, COOKIES_FILE)
                            logger.info(
                                f"✅ 已保存 {len(relevant)} 个 1688 cookies 到：{COOKIES_FILE}"
                            )
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

            # 5 秒一次心跳 —— 让用户清楚脚本还在等，不是卡了
            now = time.time()
            if now - last_heartbeat >= 5:
                elapsed = int(now - start)
                remaining = int((max_wait - elapsed) / 60)
                logger.info(
                    f"⏳ 等待保存信号中...（已 {elapsed}s / 剩 {remaining} 分钟）"
                )
                last_heartbeat = now
            time.sleep(2)

        if not saved:
            logger.warning("⚠️ 超时（10 分钟） —— cookies 未保存")

    finally:
        FLAG_FILE.unlink(missing_ok=True)
        try:
            session.close()
        except Exception:
            pass

    logger.info("=" * 60)


if __name__ == "__main__":
    main()

"""
1688 OAuth 授权码流程工具
=========================

流程：
    1. 在 1688 开放平台后台（https://open.1688.com/ ）配置回调 URL
       （推荐 http://127.0.0.1:8765/callback ）
    2. 启动本脚本：python scripts/get_1688_token.py
    3. 脚本启动一个本地 HTTP server 监听 8765，
       浏览器自动打开授权页（也可手动复制 URL）
    4. 用户在 1688 页面点同意 → 1688 回调到 http://127.0.0.1:8765/callback?code=xxx
    5. 脚本自动用 code 换 access_token + refresh_token
    6. token 写回 .env 末尾

usage:
    python scripts/get_1688_token.py

如果 callback URL 不是 127.0.0.1:8765，通过环境变量覆盖：
    ALIBABA_REDIRECT_URI=http://your.host:port/cb python scripts/get_1688_token.py
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values, set_key  # noqa: E402

ENV_FILE = PROJECT_ROOT / ".env"

# ---------- 1688 OAuth 端点（参考开放平台文档；如变更请同步修改） ----------
AUTH_URL = "https://auth.1688.com/oauth/authorize"
TOKEN_URL = "https://gw.open.1688.com/openapi/param2/1/system.oauth2/token"

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"
DEFAULT_PORT = 8765

# 用于本地存储的临时状态
_auth_code: str | None = None
_auth_error: str | None = None


class CallbackHandler(BaseHTTPRequestHandler):
    """拦截 1688 回调，提取 ?code= 或 ?error="""

    def do_GET(self):  # noqa: N802
        global _auth_code, _auth_error
        q = parse_qs(urlparse(self.path).query)
        if "code" in q:
            _auth_code = q["code"][0]
            body = "<h2>授权成功！</h2><p>可以关闭此页面，回到终端查看 token。</p>"
        elif "error" in q:
            _auth_error = q.get("error_description", q["error"])[0]
            body = f"<h2>授权失败</h2><p>{_auth_error}</p>"
        else:
            body = "<h2>无效回调</h2><p>未收到 code 或 error 参数。</p>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt, *args):  # noqa: A003
        # 静默默认 access log
        pass


def main() -> int:
    cfg = dotenv_values(ENV_FILE)
    app_key = cfg.get("ALIBABA_APP_KEY", "").strip()
    app_secret = cfg.get("ALIBABA_APP_SECRET", "").strip()
    redirect_uri = os.environ.get("ALIBABA_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip()

    if not app_key or not app_secret:
        print("❌ .env 缺少 ALIBABA_APP_KEY 或 ALIBABA_APP_SECRET")
        return 1

    # ---------- 1. 解析 redirect URI 拿 port ----------
    parsed = urlparse(redirect_uri)
    port = parsed.port or DEFAULT_PORT

    # ---------- 2. 启动 HTTP server ----------
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    print(f"🔌 回调监听已启动: {redirect_uri}")

    # ---------- 3. 拼装授权 URL 并打开浏览器 ----------
    auth_url = (
        f"{AUTH_URL}"
        f"?client_id={app_key}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&state=amazon_selector"
        f"&force_auth=true"
    )
    print(f"\n👉 请在浏览器打开以下链接完成授权：\n   {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # ---------- 4. 等待回调 ----------
    print("⏳ 等待 1688 回调（最长 5 分钟）…")
    server.timeout = 300
    while _auth_code is None and _auth_error is None:
        server.handle_request()

    if _auth_error:
        print(f"❌ 授权失败: {_auth_error}")
        return 1
    if not _auth_code:
        print("❌ 超时未收到 code")
        return 1

    print(f"✅ 收到 authorization_code: {_auth_code[:8]}…")

    # ---------- 5. 换 access_token ----------
    print("🔄 正在交换 access_token…")
    token_resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": app_key,
            "client_secret": app_secret,
            "code": _auth_code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    if token_resp.status_code != 200:
        print(f"❌ token 接口 HTTP {token_resp.status_code}: {token_resp.text}")
        return 1

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token:
        print(f"❌ 响应里没有 access_token: {json.dumps(token_data, ensure_ascii=False)[:300]}")
        return 1

    # ---------- 6. 写回 .env ----------
    set_key(str(ENV_FILE), "ALIBABA_ACCESS_TOKEN", access_token)
    if refresh_token:
        set_key(str(ENV_FILE), "ALIBABA_REFRESH_TOKEN", refresh_token)
    print(f"✅ access_token 已写入 .env（expires_in={token_data.get('expires_in', '?')}s）")
    if refresh_token:
        print(f"✅ refresh_token 已写入 .env（refresh_expires_in={token_data.get('refresh_token_expires_in', '?')}s）")

    print("\n🎉 授权完成！可以运行 python main.py run --category \"Home & Kitchen\" --limit 5 试一下。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

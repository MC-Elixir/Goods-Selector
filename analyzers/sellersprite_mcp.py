"""卖家精灵 MCP 传输适配层。

把本仓库既有的 REST 调用（`/v1/...` + params/json）翻译成官方 MCP 工具调用，
使 `MaijiajinglingClient` 的 DTO 解析层无需改动即可切换数据通道。

MCP 网关：https://mcp.sellersprite.com/mcp
认证：`secret-key` 请求头（与 REST 网关一致）
"""
from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable, Optional

from analyzers.maijiajingling import MarketDataError

DEFAULT_MCP_URL = "https://mcp.sellersprite.com/mcp"


@dataclass(frozen=True)
class McpToolCall:
    """一次 MCP 工具调用的名称与入参。"""

    name: str
    arguments: dict[str, Any]


# REST 端点 → 官方 MCP 工具 code（见 https://open.sellersprite.com/mcp 工具表）
_STATIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/v1/sales/prediction/bsr"): "bsr_prediction",
    ("GET", "/v1/product/node"): "product_node",
    ("POST", "/v1/product/competitor-lookup"): "competitor_lookup",
    ("POST", "/v1/keyword-research"): "keyword_research",
    ("POST", "/v1/keyword-research/trends"): "keyword_research_trends",
    ("POST", "/v1/review"): "review",
    ("POST", "/v1/discount/asin"): "asin_coupon_trend",
}


def resolve_tool_call(
    method: str,
    endpoint: str,
    params: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
) -> McpToolCall:
    """把 REST 风格调用解析为 MCP 工具调用，无法映射时抛稳定错误。"""
    verb = method.upper()
    path = "/" + endpoint.split("?", 1)[0].strip("/")
    segments = path.strip("/").split("/")

    if verb == "GET" and len(segments) == 4 and segments[0] == "v1" and segments[1] == "asin":
        return McpToolCall("asin_detail", {"marketplace": segments[2], "asin": segments[3]})

    tool = _STATIC_ROUTES.get((verb, path))
    if tool is None:
        raise MarketDataError(
            "UNSUPPORTED_ENDPOINT",
            f"SellerSprite MCP has no tool for {verb} {path}",
        )

    if json is not None:
        arguments = dict(json)
    elif params is not None:
        arguments = dict(params)
    else:
        arguments = {}
    return McpToolCall(tool, arguments)


# 官方业务码（见 https://open.sellersprite.com/api 「code 码说明」）
_AUTH_CODES = frozenset({
    "ERROR_SECRET_KEY",
    "ERROR_SECRET_KEY_OVERDUE",
    "ERROR_SECRET_KEY_INVALID",
})
_QUOTA_CODES = frozenset({"ERROR_VISIT_MAX"})

# isError 结果只有自由文本可判，这里做保守的关键词归类
_AUTH_TOKENS = ("unauthorized", "forbidden", "invalid key", "invalid secret", "secret-key", "401", "403")
_QUOTA_TOKENS = ("rate limit", "too many requests", "visit_max", "quota", "429")


def _first_text(result: Any) -> str:
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text
    return ""


def _error_from_text(text: str) -> MarketDataError:
    """把上游自由文本归类为稳定错误码——不回显原文，避免密钥或 PII 外泄。"""
    normalized = text.lower()
    if any(token in normalized for token in _AUTH_TOKENS):
        return MarketDataError("AUTH_REQUIRED", "SellerSprite MCP rejected the credentials")
    if any(token in normalized for token in _QUOTA_TOKENS):
        return MarketDataError("RATE_LIMITED", "SellerSprite MCP quota or rate limit reached")
    return MarketDataError("UPSTREAM_ERROR", "SellerSprite MCP tool reported an error")


def _is_envelope(payload: Any) -> bool:
    """判断 payload 是否已经是 REST 风格的 {code, message, data} 信封。"""
    if not isinstance(payload, dict) or "code" not in payload:
        return False
    code = str(payload.get("code") or "")
    if code == "OK" or code.upper().startswith("ERROR"):
        return True
    return "data" in payload


def parse_tool_result(result: Any, tool_name: str = "") -> dict:
    """把 MCP `CallToolResult` 归一化成既有解析层期望的 REST 信封。"""
    text = _first_text(result)

    if getattr(result, "isError", False):
        raise _error_from_text(text)

    payload: Any = None
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        payload = structured.get("result") if set(structured) == {"result"} else structured
    elif text:
        try:
            payload = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise MarketDataError(
                "MISSING_REQUIRED_DATA",
                f"SellerSprite MCP tool {tool_name or '?'} returned non-JSON content",
            ) from exc

    if payload is None:
        raise MarketDataError(
            "MISSING_REQUIRED_DATA",
            f"SellerSprite MCP tool {tool_name or '?'} returned no content",
        )

    if not _is_envelope(payload):
        return {"code": "OK", "data": payload}

    code = str(payload.get("code") or "")
    if code in _AUTH_CODES:
        raise MarketDataError("AUTH_REQUIRED", "SellerSprite MCP rejected the credentials")
    if code in _QUOTA_CODES:
        raise MarketDataError("RATE_LIMITED", "SellerSprite MCP quota or rate limit reached")
    return payload


class _McpResponse:
    """最小 httpx.Response 替身，只暴露既有解析层用到的两个方法。"""

    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class SellerSpriteMcpTransport:
    """与 `httpx.Client` 同形的 MCP 传输层，可直接替换 `MaijiajinglingClient._client`。"""

    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_MCP_URL,
        *,
        tool_caller: Optional[Callable[[str, dict], Any]] = None,
        timeout: float = 60.0,
    ):
        self.url = url or DEFAULT_MCP_URL
        self._caller = tool_caller or _create_streamable_http_caller(api_key, self.url, timeout)

    def request(self, method: str, endpoint: str, **kwargs) -> _McpResponse:
        call = resolve_tool_call(
            method,
            endpoint,
            params=kwargs.get("params"),
            json=kwargs.get("json"),
        )
        result = self._caller(call.name, call.arguments)
        return _McpResponse(parse_tool_result(result, call.name))

    def get(self, endpoint: str, **kwargs) -> _McpResponse:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> _McpResponse:
        return self.request("POST", endpoint, **kwargs)

    def close(self) -> None:
        closer = getattr(self._caller, "close", None)
        if callable(closer):
            closer()


class _EventLoopBridge:
    """在后台线程里跑一个常驻 event loop，让同步流水线能复用异步 MCP 会话。

    会话必须活在同一个 loop 上，所以不能用逐次 `asyncio.run()`——
    那样每次调用都要重新握手，既慢又会多消耗一次配额。
    """

    def __init__(self, name: str):
        self._name = name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro, timeout: float):
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._serve, args=(loop,), name=self._name, daemon=True
                )
                thread.start()
                self._loop, self._thread = loop, thread
            loop = self._loop

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        loop.close()


def _session_error(exc: BaseException) -> MarketDataError:
    if isinstance(exc, MarketDataError):
        return exc
    if isinstance(exc, (FutureTimeoutError, TimeoutError, asyncio.TimeoutError)):
        return MarketDataError("TIMEOUT", "SellerSprite MCP request timed out")
    return _error_from_text(f"{type(exc).__name__}: {exc}")


@asynccontextmanager
async def _default_session_factory(url: str, headers: dict[str, str]):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            yield session


class StreamableHttpToolCaller:
    """通过 streamable HTTP 调用卖家精灵 MCP 工具的同步 caller。

    这里是纯 RPC，不经过任何大模型：工具名和入参由 `resolve_tool_call` 决定。
    """

    def __init__(
        self,
        api_key: str,
        url: str = DEFAULT_MCP_URL,
        timeout: float = 60.0,
        session_factory: Optional[Callable[[str, dict], Any]] = None,
    ):
        self._api_key = api_key
        self._url = url or DEFAULT_MCP_URL
        self._timeout = timeout
        self._session_factory = session_factory or _default_session_factory
        self._bridge: Optional[_EventLoopBridge] = None
        self._session: Any = None
        self._stack: Optional[AsyncExitStack] = None
        self._lock = threading.Lock()

    def __call__(self, name: str, arguments: dict) -> Any:
        session, bridge = self._ensure_session()
        try:
            return bridge.run(session.call_tool(name, arguments), timeout=self._timeout)
        except BaseException as exc:
            raise _session_error(exc) from exc

    def _ensure_session(self) -> tuple[Any, _EventLoopBridge]:
        with self._lock:
            if self._session is not None and self._bridge is not None:
                return self._session, self._bridge

            bridge = _EventLoopBridge("sellersprite-mcp")
            try:
                session, stack = bridge.run(self._open(), timeout=self._timeout)
            except BaseException as exc:
                bridge.close()
                raise _session_error(exc) from exc

            self._bridge, self._session, self._stack = bridge, session, stack
            return session, bridge

    async def _open(self) -> tuple[Any, AsyncExitStack]:
        stack = AsyncExitStack()
        try:
            session = await stack.enter_async_context(
                self._session_factory(self._url, {"secret-key": self._api_key})
            )
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        return session, stack

    def close(self) -> None:
        with self._lock:
            bridge, stack = self._bridge, self._stack
            self._bridge, self._session, self._stack = None, None, None
        if bridge is None:
            return
        if stack is not None:
            try:
                bridge.run(stack.aclose(), timeout=self._timeout)
            except BaseException:  # 关闭阶段的失败不应掩盖业务结果
                pass
        bridge.close()


def _create_streamable_http_caller(api_key: str, url: str, timeout: float) -> StreamableHttpToolCaller:
    return StreamableHttpToolCaller(api_key, url, timeout)

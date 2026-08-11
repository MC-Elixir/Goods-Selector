"""卖家精灵 MCP 传输适配层单测（离线，不连 mcp.sellersprite.com）。"""
from __future__ import annotations

import json

import pytest
from mcp.types import CallToolResult, TextContent

from analyzers.maijiajingling import MaijiajinglingClient, MarketDataError
from analyzers.sellersprite_mcp import (
    SellerSpriteMcpTransport,
    StreamableHttpToolCaller,
    _EventLoopBridge,
    parse_tool_result,
    resolve_tool_call,
)


def _text_result(payload, is_error: bool = False) -> CallToolResult:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=is_error)


class _RecordingToolCaller:
    """替身：记录 MCP 工具调用，避免测试连真实网关。"""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"code": "OK", "data": {}}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def __call__(self, name: str, arguments: dict) -> CallToolResult:
        self.calls.append((name, arguments))
        return _text_result(self.payload)

    def close(self) -> None:
        self.closed = True


def test_asin_detail_endpoint_maps_path_segments_to_tool_arguments():
    call = resolve_tool_call("GET", "/v1/asin/US/B0TEST1234")

    assert call.name == "asin_detail"
    assert call.arguments == {"marketplace": "US", "asin": "B0TEST1234"}


def test_bsr_prediction_endpoint_maps_query_params_to_tool_arguments():
    call = resolve_tool_call(
        "GET",
        "/v1/sales/prediction/bsr",
        params={"marketplace": "US", "bsr": 1006, "categoryId": "1055398"},
    )

    assert call.name == "bsr_prediction"
    assert call.arguments == {"marketplace": "US", "bsr": 1006, "categoryId": "1055398"}


def test_competitor_lookup_endpoint_maps_json_body_to_tool_arguments():
    payload = {"marketplace": "US", "asins": ["B0TEST1234"], "page": 1, "size": 10}

    call = resolve_tool_call("POST", "/v1/product/competitor-lookup", json=payload)

    assert call.name == "competitor_lookup"
    assert call.arguments == payload


def test_keyword_research_trends_maps_to_its_own_tool():
    research = resolve_tool_call("POST", "/v1/keyword-research", json={"keywords": "mat"})
    trends = resolve_tool_call("POST", "/v1/keyword-research/trends", json={"keyword": "mat"})

    assert research.name == "keyword_research"
    assert trends.name == "keyword_research_trends"


def test_product_node_and_review_and_discount_endpoints_are_routed():
    assert resolve_tool_call("GET", "/v1/product/node", params={}).name == "product_node"
    assert resolve_tool_call("POST", "/v1/review", json={}).name == "review"
    assert resolve_tool_call("POST", "/v1/discount/asin", json={}).name == "asin_coupon_trend"


def test_visits_endpoint_is_rejected_because_mcp_has_no_quota_tool():
    with pytest.raises(MarketDataError) as excinfo:
        resolve_tool_call("GET", "/v1/visits")

    assert excinfo.value.error_code == "UNSUPPORTED_ENDPOINT"


def test_unknown_endpoint_raises_stable_error_instead_of_guessing():
    with pytest.raises(MarketDataError) as excinfo:
        resolve_tool_call("POST", "/v1/traffic/keyword", json={})

    assert excinfo.value.error_code == "UNSUPPORTED_ENDPOINT"


def test_method_mismatch_is_rejected():
    with pytest.raises(MarketDataError) as excinfo:
        resolve_tool_call("GET", "/v1/keyword-research", params={})

    assert excinfo.value.error_code == "UNSUPPORTED_ENDPOINT"


def test_rest_envelope_in_text_content_is_passed_through_unchanged():
    body = parse_tool_result(_text_result({"code": "OK", "data": {"asin": "B0TEST1234"}}))

    assert body == {"code": "OK", "data": {"asin": "B0TEST1234"}}


def test_structured_content_is_preferred_over_text_content():
    result = CallToolResult(
        content=[TextContent(type="text", text="human readable summary")],
        structuredContent={"code": "OK", "data": {"bsr": 1006}},
    )

    assert parse_tool_result(result) == {"code": "OK", "data": {"bsr": 1006}}


def test_structured_content_result_wrapper_is_unwrapped():
    result = CallToolResult(
        content=[],
        structuredContent={"result": {"code": "OK", "data": {"bsr": 1006}}},
    )

    assert parse_tool_result(result) == {"code": "OK", "data": {"bsr": 1006}}


def test_bare_object_payload_is_wrapped_into_rest_envelope():
    body = parse_tool_result(_text_result({"asin": "B0TEST1234", "bsr": 1006}))

    assert body == {"code": "OK", "data": {"asin": "B0TEST1234", "bsr": 1006}}


def test_bare_list_payload_is_wrapped_into_rest_envelope():
    body = parse_tool_result(_text_result([{"keyword": "mat", "search": 4200}]))

    assert body == {"code": "OK", "data": [{"keyword": "mat", "search": 4200}]}


def test_secret_key_error_code_maps_to_auth_required():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result({"code": "ERROR_SECRET_KEY_INVALID", "message": "bad key"}))

    assert excinfo.value.error_code == "AUTH_REQUIRED"


def test_expired_secret_key_maps_to_auth_required():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result({"code": "ERROR_SECRET_KEY_OVERDUE", "message": "expired"}))

    assert excinfo.value.error_code == "AUTH_REQUIRED"


def test_visit_max_error_code_maps_to_rate_limited():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result({"code": "ERROR_VISIT_MAX", "message": "quota used up"}))

    assert excinfo.value.error_code == "RATE_LIMITED"


def test_tool_error_flag_raises_upstream_error():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result("upstream exploded", is_error=True))

    assert excinfo.value.error_code == "UPSTREAM_ERROR"


def test_tool_error_flag_with_auth_text_maps_to_auth_required():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result("401 Unauthorized: invalid secret-key", is_error=True))

    assert excinfo.value.error_code == "AUTH_REQUIRED"


def test_non_json_text_is_missing_required_data():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result("I could not find that ASIN."))

    assert excinfo.value.error_code == "MISSING_REQUIRED_DATA"


def test_empty_content_is_missing_required_data():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(CallToolResult(content=[]))

    assert excinfo.value.error_code == "MISSING_REQUIRED_DATA"


def test_error_diagnostics_never_leak_the_secret_key():
    with pytest.raises(MarketDataError) as excinfo:
        parse_tool_result(_text_result("auth failed for secret-key sk-live-abcd1234", is_error=True))

    assert "sk-live-abcd1234" not in excinfo.value.diagnostic


def test_transport_get_calls_the_mapped_tool_and_returns_rest_body():
    caller = _RecordingToolCaller({"code": "OK", "data": {"asin": "B0TEST1234"}})
    transport = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    response = transport.get("/v1/asin/US/B0TEST1234")

    assert caller.calls == [("asin_detail", {"marketplace": "US", "asin": "B0TEST1234"})]
    assert response.json() == {"code": "OK", "data": {"asin": "B0TEST1234"}}


def test_transport_post_forwards_json_body_as_tool_arguments():
    caller = _RecordingToolCaller()
    transport = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    transport.post("/v1/keyword-research", json={"marketplace": "US", "keywords": "mat"})

    assert caller.calls == [("keyword_research", {"marketplace": "US", "keywords": "mat"})]


def test_transport_request_dispatches_on_method():
    caller = _RecordingToolCaller()
    transport = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    transport.request("POST", "/v1/review", json={"asin": "B0TEST1234"})

    assert caller.calls[0][0] == "review"


def test_transport_response_raise_for_status_is_a_noop():
    caller = _RecordingToolCaller()
    transport = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    assert transport.get("/v1/product/node", params={"marketplace": "US"}).raise_for_status() is None


def test_transport_close_releases_the_session():
    caller = _RecordingToolCaller()
    transport = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    transport.close()

    assert caller.closed is True


def test_transport_is_a_drop_in_replacement_for_the_http_client():
    """核心契约：换掉 _client 后，既有 DTO 解析层无需改动。"""
    caller = _RecordingToolCaller({
        "code": "OK",
        "data": {
            "asin": "B0TEST1234",
            "brand": "Generic",
            "bsrRank": 1006,
            "nodeIdPath": "1055398:1063252",
            "bsrLabel": "Home & Kitchen",
            "price": 21.99,
            "title": "Test Product",
        },
    })
    client = MaijiajinglingClient(api_key="test-key")
    client._client = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    detail = client.asin_detail("US", "B0TEST1234")

    assert detail.asin == "B0TEST1234"
    assert detail.bsr == 1006
    assert detail.bsr_category_id == "1055398"
    assert detail.title == "Test Product"
    assert caller.calls == [("asin_detail", {"marketplace": "US", "asin": "B0TEST1234"})]


def test_bsr_prediction_over_mcp_reaches_the_dto_layer():
    caller = _RecordingToolCaller({
        "code": "OK",
        "data": {"estDailySales": 18, "estMonthSales": 540, "categoryLabel": "Kitchen"},
    })
    client = MaijiajinglingClient(api_key="test-key")
    client._client = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    pred = client.bsr_prediction("US", 1006, "1055398")

    assert pred.est_monthly_sales == 540
    assert caller.calls == [
        ("bsr_prediction", {"marketplace": "US", "bsr": 1006, "categoryId": "1055398"})
    ]


# ------------------------------------------------------------------
# 同步 ↔ 异步桥接
# ------------------------------------------------------------------


def test_bridge_runs_a_coroutine_from_sync_code():
    bridge = _EventLoopBridge("test-bridge")
    try:
        async def answer():
            return 42

        assert bridge.run(answer(), timeout=5) == 42
    finally:
        bridge.close()


def test_bridge_keeps_one_loop_so_a_session_can_survive_across_calls():
    bridge = _EventLoopBridge("test-bridge")
    try:
        async def loop_id():
            import asyncio

            return id(asyncio.get_running_loop())

        assert bridge.run(loop_id(), timeout=5) == bridge.run(loop_id(), timeout=5)
    finally:
        bridge.close()


def test_bridge_propagates_the_original_exception():
    bridge = _EventLoopBridge("test-bridge")
    try:
        async def boom():
            raise KeyError("inner failure")

        with pytest.raises(KeyError):
            bridge.run(boom(), timeout=5)
    finally:
        bridge.close()


def test_bridge_close_is_idempotent_and_stops_the_thread():
    bridge = _EventLoopBridge("test-bridge")

    async def noop():
        return None

    bridge.run(noop(), timeout=5)
    thread = bridge._thread
    bridge.close()
    bridge.close()

    assert thread is not None and not thread.is_alive()


# ------------------------------------------------------------------
# StreamableHttpToolCaller
# ------------------------------------------------------------------


class _FakeMcpSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []
        self.initialized = 0

    async def initialize(self):
        self.initialized += 1

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return _text_result(self.payload)


class _FakeSessionFactory:
    """替代 streamablehttp_client + ClientSession 的注入点。"""

    def __init__(self, session=None, error=None):
        self.session = session or _FakeMcpSession({"code": "OK", "data": {}})
        self.error = error
        self.opened = 0
        self.closed = 0
        self.headers: dict | None = None

    def __call__(self, url, headers):
        self.headers = headers
        factory = self

        class _Ctx:
            async def __aenter__(self):
                if factory.error:
                    raise factory.error
                factory.opened += 1
                return factory.session

            async def __aexit__(self, *exc):
                factory.closed += 1
                return False

        return _Ctx()


def test_tool_caller_opens_the_session_once_and_reuses_it():
    factory = _FakeSessionFactory()
    caller = StreamableHttpToolCaller("test-key", session_factory=factory)
    try:
        caller("asin_detail", {"asin": "B0TEST1234"})
        caller("bsr_prediction", {"bsr": 1006})
    finally:
        caller.close()

    assert factory.opened == 1
    assert factory.session.initialized == 1
    assert factory.session.calls == [
        ("asin_detail", {"asin": "B0TEST1234"}),
        ("bsr_prediction", {"bsr": 1006}),
    ]


def test_tool_caller_sends_the_secret_key_header():
    factory = _FakeSessionFactory()
    caller = StreamableHttpToolCaller("sk-live-abcd1234", session_factory=factory)
    try:
        caller("asin_detail", {"asin": "B0TEST1234"})
    finally:
        caller.close()

    assert factory.headers == {"secret-key": "sk-live-abcd1234"}


def test_tool_caller_close_releases_the_session_and_is_idempotent():
    factory = _FakeSessionFactory()
    caller = StreamableHttpToolCaller("test-key", session_factory=factory)
    caller("asin_detail", {"asin": "B0TEST1234"})

    caller.close()
    caller.close()

    assert factory.closed == 1


def test_tool_caller_connection_failure_becomes_a_stable_error():
    factory = _FakeSessionFactory(error=ConnectionRefusedError("gateway down"))
    caller = StreamableHttpToolCaller("test-key", session_factory=factory)

    with pytest.raises(MarketDataError) as excinfo:
        caller("asin_detail", {"asin": "B0TEST1234"})
    caller.close()

    assert excinfo.value.error_code == "UPSTREAM_ERROR"


def test_tool_caller_auth_failure_during_connect_is_auth_required():
    factory = _FakeSessionFactory(error=RuntimeError("401 Unauthorized"))
    caller = StreamableHttpToolCaller("test-key", session_factory=factory)

    with pytest.raises(MarketDataError) as excinfo:
        caller("asin_detail", {"asin": "B0TEST1234"})
    caller.close()

    assert excinfo.value.error_code == "AUTH_REQUIRED"


def test_tool_caller_reconnects_after_close():
    factory = _FakeSessionFactory()
    caller = StreamableHttpToolCaller("test-key", session_factory=factory)
    caller("asin_detail", {"asin": "B0TEST1234"})
    caller.close()

    caller("asin_detail", {"asin": "B0TEST5678"})
    caller.close()

    assert factory.opened == 2


# ------------------------------------------------------------------
# 客户端通道选择
# ------------------------------------------------------------------


def test_client_keeps_rest_transport_by_default():
    import httpx

    client = MaijiajinglingClient(api_key="test-key")
    try:
        assert isinstance(client._client, httpx.Client)
    finally:
        client.close()


def test_client_builds_an_mcp_transport_when_asked():
    client = MaijiajinglingClient(api_key="test-key", transport="mcp")
    try:
        assert isinstance(client._client, SellerSpriteMcpTransport)
        assert client._client.url == "https://mcp.sellersprite.com/mcp"
    finally:
        client.close()


def test_client_reads_the_transport_from_settings(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "mjjl_transport", "mcp", raising=False)
    client = MaijiajinglingClient(api_key="test-key")
    try:
        assert isinstance(client._client, SellerSpriteMcpTransport)
    finally:
        client.close()


def test_client_transport_argument_wins_over_settings(monkeypatch):
    import httpx

    from config.settings import settings

    monkeypatch.setattr(settings, "mjjl_transport", "mcp", raising=False)
    client = MaijiajinglingClient(api_key="test-key", transport="rest")
    try:
        assert isinstance(client._client, httpx.Client)
    finally:
        client.close()


def test_get_visits_over_mcp_degrades_instead_of_raising():
    client = MaijiajinglingClient(api_key="test-key", transport="mcp")
    try:
        body = client.get_visits()
    finally:
        client.close()

    assert body["code"] == "UNSUPPORTED"
    assert "mcp" in body["message"].lower()


def test_analyze_market_runs_end_to_end_over_mcp():
    """MCP 通道下 4 步编排应产出与 REST 相同形状的 MarketAnalysisDTO。"""

    class _ChainCaller:
        def __init__(self):
            self.calls: list[str] = []

        def __call__(self, name, arguments):
            self.calls.append(name)
            payloads = {
                "asin_detail": {
                    "asin": "B0TEST1234",
                    "brand": "Generic",
                    "title": "Silicone Kitchen Mat",
                    "price": 24.99,
                    "bsrRank": 1200,
                    "nodeIdPath": "1055398:1063252",
                    "bsrLabel": "Kitchen Mats",
                    "nodeLabel": "Kitchen Mats",
                },
                "bsr_prediction": {"estDailySales": 18, "estMonthSales": 540},
                "competitor_lookup": {
                    "items": [
                        {"price": 24.99, "reviewCount": 100, "totalRevenue": 1000},
                        {"price": 19.99, "reviewCount": 50, "totalRevenue": 500},
                    ]
                },
                "keyword_research": {
                    "items": [
                        {
                            "keyword": "kitchen mat",
                            "searchVolume": 4200,
                            "purchase": 280,
                            "opportunityScore": 0.12,
                        }
                    ]
                },
            }
            return _text_result({"code": "OK", "data": payloads.get(name, {})})

    caller = _ChainCaller()
    client = MaijiajinglingClient(api_key="test-key")
    client._client = SellerSpriteMcpTransport(api_key="test-key", tool_caller=caller)

    dto = client.analyze_market("B0TEST1234", "US", keyword="kitchen mat")

    assert dto.est_monthly_sales == 540
    assert dto.competing_listings == 2
    assert dto.avg_price_top10 == 22.49
    assert dto.search_volume_monthly == 4200
    assert dto.opportunity_score == 0.12
    assert caller.calls == [
        "asin_detail",
        "bsr_prediction",
        "competitor_lookup",
        "keyword_research",
    ]

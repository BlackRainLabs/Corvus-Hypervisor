"""LLM streaming gateway, router, and dummy provider tests."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from corvus.llm.dummy_server import DEFAULT_SUCCESS_MESSAGE, DummyLlmServer
from corvus.llm.models import LlmRequestPayload
from corvus.llm.providers.openai_compat import OpenAiCompatProviderAdapter
from corvus.llm.providers.stub import StubProviderAdapter
from corvus.llm.registry import LlmProviderRegistry, ProviderConfig
from corvus.llm.service import LlmGatewayService
from corvus.node.config import NodeConfig
from corvus.node.main import CorvusNode
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSecurity,
    MessageSource,
    MessageTags,
    Scope,
    TriggeredBy,
)
from corvus.runtime.ipc_client import NodeIpcClient
from corvus.runtime.llm_client import build_llm_request, collect_llm_stream
from corvus.server.bootstrap import (
    FULL_TEST_MANIFEST_HASH,
    TEST_AGENT_ID,
    TEST_MANIFEST,
    TEST_MANIFEST_HASH,
)
from corvus.server.db import Database
from corvus.server.vsock import TransportGateway

ECHO_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "echo",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _llm_request(
    *,
    stream: bool = False,
    tools_schema: list | None = None,
    agent_id: str = TEST_AGENT_ID,
) -> FrameworkMessage:
    payload: dict = {
        "provider": "stub",
        "model": "stub-v1",
        "messages": [{"role": "user", "content": "stream test"}],
    }
    if stream:
        payload["stream"] = True
    if tools_schema is not None:
        payload["tools_schema"] = tools_schema
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload=payload,
    )


@pytest.mark.asyncio
async def test_stub_provider_stream_yields_terminal_completion():
    adapter = StubProviderAdapter()
    request = LlmRequestPayload(
        model="stub-v1",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    chunks = []
    completion = None
    async for chunk in adapter.stream(
        provider_id="stub",
        api_base_url="stub://local",
        api_key=None,
        request=request,
        timeout_seconds=5.0,
    ):
        if chunk.is_terminal:
            completion = chunk.completion
        else:
            chunks.append(chunk.delta)
    assert chunks
    assert completion is not None
    assert completion.content == "".join(chunks)
    assert "hello" in (completion.content or "")


@pytest.mark.asyncio
async def test_gateway_accepts_stream_with_local_tools(app_ctx, full_manifest_agent):
    message = _llm_request(stream=True, tools_schema=ECHO_TOOL)
    prepared, error = await app_ctx.llm.prepare(message, user_id="test-user")
    assert error is None
    assert prepared is not None
    assert prepared.payload.stream is True
    assert prepared.upstream_payload.tools_schema


@pytest.mark.asyncio
async def test_gateway_accepts_stream_with_hybrid_provider_tools(app_ctx, tmp_path):
    db = Database(tmp_path / "hybrid-stream.db")
    await db.connect()
    manifest = {
        **TEST_MANIFEST,
        "engines": {
            **TEST_MANIFEST["engines"],
            "engine3": {
                **TEST_MANIFEST["engines"]["engine3"],
                "tool_execution_mode": "hybrid",
                "provider_tools": ["stub:hosted_echo"],
            },
        },
    }
    await db.upsert_agent("hybrid-stream-agent", TEST_MANIFEST_HASH, manifest)

    providers = dict(app_ctx.llm_registry.providers)
    providers["stub"] = ProviderConfig(
        provider_id="stub",
        api_base_url="stub://local",
        credential_ref="none",
        supported_models=["stub-v1"],
        hosted_tools_allowed=True,
        allowed_hosted_tools=["hosted_echo"],
    )
    gateway = LlmGatewayService(
        db,
        app_ctx.audit,
        LlmProviderRegistry(providers),
        default_provider="stub",
    )
    message = _llm_request(stream=True, agent_id="hybrid-stream-agent")
    prepared, error = await gateway.prepare(message, user_id="admin-user")
    assert error is None
    assert prepared is not None
    assert prepared.provider_tool_names == ["hosted_echo"]

    completion = None
    async for chunk in gateway.iter_stream(prepared):
        if chunk.is_terminal:
            completion = chunk.completion
    assert completion is not None
    result = await gateway.finalize_stream(
        prepared,
        user_id="admin-user",
        completion=completion,
        duration_ms=1,
    )
    assert result.success is True
    assert result.provider_tools_used == ["hosted_echo"]
    assert result.trust_boundary == "provider"
    await db.close()


@pytest.mark.asyncio
async def test_stub_stream_yields_provider_tools_used():
    adapter = StubProviderAdapter()
    request = LlmRequestPayload(
        model="stub-v1",
        messages=[{"role": "user", "content": "search"}],
        stream=True,
    )
    completion = None
    async for chunk in adapter.stream(
        provider_id="stub",
        api_base_url="stub://local",
        api_key=None,
        request=request,
        timeout_seconds=5.0,
        provider_tool_entries=[{"type": "hosted_echo"}],
    ):
        if chunk.is_terminal:
            completion = chunk.completion
    assert completion is not None
    assert completion.content == "Stub provider-hosted tool result"
    assert completion.provider_tools_used == ["hosted_echo"]
    assert completion.finish_reason == "stop"


@pytest.mark.asyncio
async def test_stub_stream_yields_tool_calls():
    adapter = StubProviderAdapter()
    request = LlmRequestPayload(
        model="stub-v1",
        messages=[{"role": "user", "content": "use a tool"}],
        stream=True,
        tools_schema=ECHO_TOOL,
    )
    completion = None
    async for chunk in adapter.stream(
        provider_id="stub",
        api_base_url="stub://local",
        api_key=None,
        request=request,
        timeout_seconds=5.0,
    ):
        if chunk.is_terminal:
            completion = chunk.completion
    assert completion is not None
    assert completion.finish_reason == "tool_calls"
    assert completion.tool_calls
    assert completion.tool_calls[0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_gateway_stream_surfaces_tool_calls(app_ctx, full_manifest_agent):
    message = _llm_request(stream=True, tools_schema=ECHO_TOOL)
    prepared, error = await app_ctx.llm.prepare(message, user_id="test-user")
    assert error is None
    assert prepared is not None

    completion = None
    async for chunk in app_ctx.llm.iter_stream(prepared):
        if chunk.is_terminal:
            completion = chunk.completion
    assert completion is not None
    result = await app_ctx.llm.finalize_stream(
        prepared,
        user_id="test-user",
        completion=completion,
        duration_ms=1,
    )
    assert result.success is True
    assert result.tool_calls
    assert result.tool_calls[0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_gateway_prepare_accepts_stream_request(app_ctx):
    message = _llm_request(stream=True)
    prepared, error = await app_ctx.llm.prepare(message, user_id="test-user")
    assert error is None
    assert prepared is not None
    assert prepared.payload.stream is True


async def _start_node_stack(
    app_ctx,
    tmp_path,
    *,
    vm_id: str = "vm-stream-test",
    manifest_hash: str = TEST_MANIFEST_HASH,
):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id=vm_id,
        manifest_hash=manifest_hash,
        ipc_socket_path=ipc_path,
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=port,
        vsock_host_cid=2,
        vsock_port=4040,
    )
    server_config = replace(app_ctx.config, tcp_port=port, use_tcp=True)
    gateway = TransportGateway(
        server_config,
        app_ctx.handle_message,
        app_ctx.sessions.unbind_connection,
        transport=app_ctx.transport,
    )
    await gateway.start()
    await asyncio.sleep(0.05)

    node = CorvusNode(config)
    node_task = asyncio.create_task(node.run())
    for _ in range(50):
        if node.session.handshake_complete:
            break
        await asyncio.sleep(0.05)
    assert node.session.handshake_complete
    return gateway, node, node_task, ipc_path, config


async def _register_turn(
    ipc_path, vm_id: str, *, manifest_hash: str = TEST_MANIFEST_HASH
) -> UUID:
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE2,
        manifest_hash=manifest_hash,
    )
    await client.connect()
    assert await client.wait_handshake()
    turn_id = uuid4()
    user_query = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id=vm_id),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER, target="corvus_server"
        ),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=turn_id,
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
        security=MessageSecurity(may_leave_vm=True),
        payload={
            "user_id": "test-user",
            "platform": "api",
            "channel_id": "c1",
            "content": {"text": "register turn for stream"},
        },
    )
    ack = await client.submit_and_wait(user_query)
    assert ack.payload.get("success") is True
    await client.close()
    return turn_id


@pytest.mark.asyncio
async def test_engine3_receives_streaming_llm_response(app_ctx, tmp_path):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(app_ctx, tmp_path)
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE3,
        manifest_hash=TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(ipc_path, config.vm_id)
        llm_req = build_llm_request(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            provider="stub",
            model="stub-v1",
            messages=[{"role": "user", "content": "integration stream"}],
            stream=True,
        )
        result = await collect_llm_stream(client, llm_req, timeout=30.0)
        assert result.ok is True
        assert result.provider == "stub"
        assert "integration stream" in (result.content or "")
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()


class _ScriptedIpc:
    def __init__(self, inbound: list[FrameworkMessage]) -> None:
        self._inbound = list(inbound)

    async def submit(self, message: FrameworkMessage) -> dict:
        del message
        return {"accepted": True}

    async def wait_inbound(self, timeout: float = 0.0) -> FrameworkMessage:
        del timeout
        return self._inbound.pop(0)


def _inbound(msg_type: str, payload: dict, *, message_class: MessageClass) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER, target="engine3"
        ),
        message_class=message_class,
        type=msg_type,
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.LLM_RESULT),
        payload=payload,
    )


@pytest.mark.asyncio
async def test_collect_llm_stream_preserves_tool_calls():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "echo", "arguments": "{}"},
    }
    ipc = _ScriptedIpc(
        [
            _inbound("llm_stream_start", {"success": True}, message_class=MessageClass.RESPONSE),
            _inbound(
                "llm_stream_chunk",
                {"index": 0, "delta": "Thinking "},
                message_class=MessageClass.EVENT,
            ),
            _inbound(
                "llm_response",
                {
                    "success": True,
                    "provider": "stub",
                    "model": "stub-v1",
                    "content": "",
                    "tool_calls": [tool_call],
                    "finish_reason": "tool_calls",
                },
                message_class=MessageClass.RESPONSE,
            ),
        ]
    )
    llm_req = build_llm_request(
        TEST_AGENT_ID,
        "vm",
        uuid4(),
        provider="stub",
        model="stub-v1",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    result = await collect_llm_stream(ipc, llm_req, timeout=5.0)
    assert result.ok is True
    assert result.content == "Thinking "
    assert result.tool_calls == [tool_call]
    assert result.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_engine3_streaming_receives_tool_calls(app_ctx, full_manifest_agent, tmp_path):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx,
        tmp_path,
        vm_id="vm-stream-tools",
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE3,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(
            ipc_path, config.vm_id, manifest_hash=FULL_TEST_MANIFEST_HASH
        )
        llm_req = build_llm_request(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            provider="stub",
            model="stub-v1",
            messages=[{"role": "user", "content": "use echo"}],
            tools_schema=ECHO_TOOL,
            stream=True,
        )
        result = await collect_llm_stream(client, llm_req, timeout=30.0)
        assert result.ok is True
        assert result.tool_calls
        assert result.tool_calls[0]["function"]["name"] == "echo"
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()


@pytest.mark.asyncio
async def test_dummy_http_streaming(app_ctx, dummy_llm_server: DummyLlmServer):
    adapter = OpenAiCompatProviderAdapter()
    request = LlmRequestPayload(
        model="dummy-v1",
        messages=[{"role": "user", "content": "hello dummy stream"}],
        stream=True,
    )
    chunks = []
    completion = None
    async for chunk in adapter.stream(
        provider_id="dummy-http",
        api_base_url=dummy_llm_server.base_url,
        api_key=None,
        request=request,
        timeout_seconds=5.0,
    ):
        if chunk.is_terminal:
            completion = chunk.completion
        elif chunk.delta:
            chunks.append(chunk.delta)
    assert chunks
    assert completion is not None
    full = "".join(chunks)
    assert DEFAULT_SUCCESS_MESSAGE in full
    assert "hello dummy stream" in full


@pytest.mark.asyncio
async def test_dummy_http_streaming_tool_calls(app_ctx, dummy_llm_server: DummyLlmServer):
    adapter = OpenAiCompatProviderAdapter()
    request = LlmRequestPayload(
        model="dummy-v1",
        messages=[{"role": "user", "content": "use a tool"}],
        stream=True,
        tools_schema=ECHO_TOOL,
    )
    completion = None
    async for chunk in adapter.stream(
        provider_id="dummy-http",
        api_base_url=dummy_llm_server.base_url,
        api_key=None,
        request=request,
        timeout_seconds=5.0,
    ):
        if chunk.is_terminal:
            completion = chunk.completion
    assert completion is not None
    assert completion.finish_reason == "tool_calls"
    assert completion.tool_calls
    call = completion.tool_calls[0]
    assert call["id"] == "call_dummy_1"
    assert call["function"]["name"] == "echo"
    assert call["function"]["arguments"] == '{"text": "hi"}'


@pytest.fixture
async def dummy_llm_server():
    async with DummyLlmServer() as server:
        yield server


def _dummy_http_registry(base_url: str) -> LlmProviderRegistry:
    return LlmProviderRegistry(
        {
            "dummy-http": ProviderConfig(
                provider_id="dummy-http",
                api_base_url=base_url,
                credential_ref="none",
                supported_models=["dummy-v1"],
            )
        }
    )


@pytest.mark.asyncio
async def test_gateway_stream_via_dummy_http(
    app_ctx, dummy_llm_server: DummyLlmServer, full_manifest_agent
):
    registry = _dummy_http_registry(dummy_llm_server.base_url)
    gateway = LlmGatewayService(
        app_ctx.db,
        app_ctx.audit,
        registry,
        default_provider="dummy-http",
    )
    message = _llm_request(stream=True)
    message.payload["provider"] = "dummy-http"
    message.payload["model"] = "dummy-v1"
    prepared, error = await gateway.prepare(message, user_id="test-user")
    assert error is None
    assert prepared is not None

    chunks = []
    completion = None
    async for chunk in gateway.iter_stream(prepared):
        if chunk.is_terminal:
            completion = chunk.completion
        elif chunk.delta:
            chunks.append(chunk.delta)
    assert chunks
    assert completion is not None
    result = await gateway.finalize_stream(
        prepared,
        user_id="test-user",
        completion=completion,
        duration_ms=1,
    )
    assert result.success is True
    assert DEFAULT_SUCCESS_MESSAGE in (result.content or "")

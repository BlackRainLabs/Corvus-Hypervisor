"""AgentTransport routing tests: (agent_id, vm_id) keying prevents VM collisions."""

from __future__ import annotations

from uuid import uuid4

import pytest

from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.server.transport import AgentTransport


class FakeWriter:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self._closing = False

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    async def drain(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True


def _message() -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id="corvus-server", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.ENGINE, target=EngineId.ENGINE3.value),
        message_class=MessageClass.RESPONSE,
        type="llm_response",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.LLM_RESULT),
        payload={"success": True},
    )


@pytest.mark.asyncio
async def test_deliver_routes_to_correct_vm_of_same_agent():
    transport = AgentTransport()
    writer_a, writer_b = FakeWriter(), FakeWriter()
    transport.register_writer(1, writer_a)
    transport.register_writer(2, writer_b)
    transport.bind_agent("agent-x", "vm-a", 1)
    transport.bind_agent("agent-x", "vm-b", 2)

    assert await transport.deliver("agent-x", "vm-a", _message()) is True
    assert await transport.deliver("agent-x", "vm-b", _message()) is True

    assert len(writer_a.chunks) == 1
    assert len(writer_b.chunks) == 1


@pytest.mark.asyncio
async def test_deliver_unknown_vm_returns_false():
    transport = AgentTransport()
    transport.register_writer(1, FakeWriter())
    transport.bind_agent("agent-x", "vm-a", 1)

    assert await transport.deliver("agent-x", "vm-missing", _message()) is False


def test_is_agent_connected_is_vm_scoped():
    transport = AgentTransport()
    transport.register_writer(1, FakeWriter())
    transport.bind_agent("agent-x", "vm-a", 1)

    assert transport.is_agent_connected("agent-x", "vm-a") is True
    assert transport.is_agent_connected("agent-x", "vm-b") is False


def test_unbind_one_vm_leaves_other_bound():
    transport = AgentTransport()
    transport.register_writer(1, FakeWriter())
    transport.register_writer(2, FakeWriter())
    transport.bind_agent("agent-x", "vm-a", 1)
    transport.bind_agent("agent-x", "vm-b", 2)

    transport.unbind(2)

    assert transport.is_agent_connected("agent-x", "vm-a") is True
    assert transport.is_agent_connected("agent-x", "vm-b") is False


def test_second_vm_bind_does_not_evict_first():
    transport = AgentTransport()
    transport.register_writer(1, FakeWriter())
    transport.register_writer(2, FakeWriter())
    transport.bind_agent("agent-x", "vm-a", 1)
    transport.bind_agent("agent-x", "vm-b", 2)

    # Both remain independently addressable (the pre-fix bug overwrote by agent_id).
    assert transport.is_agent_connected("agent-x", "vm-a") is True
    assert transport.is_agent_connected("agent-x", "vm-b") is True

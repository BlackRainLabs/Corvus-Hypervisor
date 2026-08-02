"""Runtime memory client helper tests."""

from uuid import uuid4

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
from corvus.runtime.memory_client import (
    build_memory_query_key,
    build_memory_write,
    is_elevation_required,
    parse_memory_response,
)


def test_build_memory_write_sets_turn_correlation():
    turn_id = uuid4()
    msg = build_memory_write(
        "agent-a",
        "vm-1",
        turn_id,
        key="note-1",
        content="hello",
    )
    assert msg.type == "memory:write"
    assert msg.tags.origin_correlation_id == turn_id
    assert msg.payload["target_agent_id"] == "agent-a"
    assert msg.payload["record"]["key"] == "note-1"


def test_parse_memory_write_response():
    req = build_memory_query_key("agent-a", "vm-1", uuid4(), key="k1")
    resp = FrameworkMessage(
        source=MessageSource(agent_id="corvus-server", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.ENGINE, target="engine4"),
        message_class=MessageClass.RESPONSE,
        type="memory:query_response",
        correlation_id=req.correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.MEMORY_RESULT),
        payload={
            "success": True,
            "records": [{"key": "k1", "content": "hello"}],
            "record_id": None,
            "error": None,
        },
    )
    result = parse_memory_response(resp)
    assert result.ok is True
    assert result.records == [{"key": "k1", "content": "hello"}]


def test_parse_elevation_error():
    req = build_memory_write("agent-a", "vm-1", uuid4(), key="k1", content="x")
    err = FrameworkMessage(
        source=MessageSource(agent_id="corvus-server", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.ENGINE, target="engine4"),
        message_class=MessageClass.ERROR,
        type="error",
        correlation_id=req.correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={
            "code": "SERVER_ELEVATION_REQUIRED",
            "message": "Policy requires elevation",
            "details": {"elevation_id": "elev-123"},
        },
    )
    result = parse_memory_response(err)
    assert result.ok is False
    assert is_elevation_required(result)
    assert result.elevation_id == "elev-123"

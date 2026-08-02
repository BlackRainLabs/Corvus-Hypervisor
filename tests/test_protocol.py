"""FrameworkMessage protocol tests."""

from uuid import uuid4

from corvus.protocol import (
    DestinationType,
    EngineId,
    ErrorCode,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
    decode_line,
    encode_message,
    make_error_message,
)


def test_round_trip_serialization():
    message = FrameworkMessage(
        source=MessageSource(agent_id="a1", engine=EngineId.ENGINE2, vm_id="vm1"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT),
        payload={"user_id": "u1", "content": {"text": "hi"}},
    )
    restored = decode_line(encode_message(message))
    assert restored.type == "user_query"
    assert restored.source.agent_id == "a1"
    assert restored.source.engine == EngineId.ENGINE2.value


def test_error_message_factory():
    cid = uuid4()
    err = make_error_message(
        code=ErrorCode.SERVER_RBAC_DENIED,
        layer="policy",
        message="denied",
        recoverable=True,
        agent_id="a1",
        vm_id="vm1",
        correlation_id=cid,
        target_engine=EngineId.ENGINE3,
    )
    assert err.message_class == MessageClass.ERROR
    assert err.payload["code"] == "SERVER_RBAC_DENIED"

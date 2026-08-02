"""Corvus Node unit tests."""

from uuid import uuid4

from corvus.node.routing import resolve_inbound_target
from corvus.node.validator import MessageValidator
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
from corvus.protocol.errors import ErrorCode


def _msg(
    *,
    engine: EngineId,
    msg_type: str,
    dest_type: DestinationType = DestinationType.CORVUS_SERVER,
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id="a1", engine=engine, vm_id="vm1"),
        destination=MessageDestination(type=dest_type, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type=msg_type,
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
    )


def test_validator_denies_wrong_engine_type():
    validator = MessageValidator()
    message = _msg(engine=EngineId.ENGINE3, msg_type="memory:query")
    error = validator.validate(
        message,
        registered_engine=EngineId.ENGINE3,
        handshake_complete=True,
        claimed_engine=EngineId.ENGINE3,
        agent_id="a1",
        vm_id="vm1",
    )
    assert error is not None
    assert error.payload["code"] == ErrorCode.NODE_CAPABILITY_DENIED.value


def test_validator_denies_origin_spoof():
    validator = MessageValidator()
    message = _msg(engine=EngineId.ENGINE2, msg_type="user_query")
    error = validator.validate(
        message,
        registered_engine=EngineId.ENGINE2,
        handshake_complete=True,
        claimed_engine=EngineId.ENGINE3,
        agent_id="a1",
        vm_id="vm1",
    )
    assert error is not None
    assert error.payload["code"] == ErrorCode.NODE_ORIGIN_SPOOF.value


def test_validator_allows_engine2_user_query():
    validator = MessageValidator()
    message = _msg(engine=EngineId.ENGINE2, msg_type="user_query")
    error = validator.validate(
        message,
        registered_engine=EngineId.ENGINE2,
        handshake_complete=True,
        claimed_engine=EngineId.ENGINE2,
        agent_id="a1",
        vm_id="vm1",
    )
    assert error is None


def test_routing_broadcast_memory():
    message = FrameworkMessage(
        source=MessageSource(agent_id="srv", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.BROADCAST, target="*"),
        message_class=MessageClass.EVENT,
        type="memory:query_result",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={},
    )
    assert resolve_inbound_target(message) == EngineId.ENGINE4


def test_routing_rejects_corvus_server_inbound():
    message = FrameworkMessage(
        source=MessageSource(agent_id="srv", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER, target="corvus_server"
        ),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={},
    )
    assert resolve_inbound_target(message) is None

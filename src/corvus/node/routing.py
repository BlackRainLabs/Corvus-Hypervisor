"""Inbound message routing per CORVUS-NODE Section 4."""

from __future__ import annotations

from corvus.protocol.models import DestinationType, EngineId, FrameworkMessage


def resolve_inbound_target(message: FrameworkMessage) -> EngineId | None:
    dest = message.destination

    if dest.type == DestinationType.CORVUS_SERVER:
        return None

    if dest.type == DestinationType.ENGINE:
        try:
            return EngineId(dest.target)
        except ValueError:
            return None

    if dest.type == DestinationType.LOOP:
        return EngineId.LOOP

    if dest.type == DestinationType.BROADCAST:
        return _broadcast_target(message.type)

    return None


def _broadcast_target(message_type: str) -> EngineId:
    if message_type == "agent_response":
        return EngineId.ENGINE2
    if message_type == "tool_call":
        return EngineId.ENGINE1
    if message_type == "llm_response":
        return EngineId.ENGINE3
    if message_type in {"llm_stream_start", "llm_stream_chunk"}:
        return EngineId.ENGINE3
    if message_type.startswith("memory:"):
        return EngineId.ENGINE4
    return EngineId.LOOP

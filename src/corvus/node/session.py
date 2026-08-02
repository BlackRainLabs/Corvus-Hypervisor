"""Node-side session and handshake state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from corvus.node.config import NodeConfig, resolve_manifest_hash
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
    decode_line,
    encode_message,
)
from corvus.protocol.models import DEFAULT_POLICY_SNAPSHOT


class SessionManager:
    def __init__(self, config: NodeConfig) -> None:
        self.config = config
        self.session_token: str | None = None
        self.session_expires_at: datetime | None = None
        self.policy_snapshot: dict[str, Any] = dict(DEFAULT_POLICY_SNAPSHOT)
        self.handshake_complete = False
        self._handshake_correlation_id: UUID | None = None

    def inject_session(self, message: FrameworkMessage) -> FrameworkMessage:
        payload = dict(message.payload)
        if self.session_token:
            payload["_session"] = {"token": self.session_token}
        return message.model_copy(update={"payload": payload})

    def build_handshake_request(self) -> FrameworkMessage:
        self._handshake_correlation_id = uuid4()
        return FrameworkMessage(
            source=MessageSource(
                agent_id=self.config.agent_id,
                engine=EngineId.CORVUS_NODE,
                vm_id=self.config.vm_id,
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.SYSTEM,
            type="handshake",
            correlation_id=self._handshake_correlation_id,
            tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
            payload={
                "manifest_hash": resolve_manifest_hash(self.config),
                "protocol_version": "2.0",
                "vm_instance_id": self.config.vm_id,
                "agent_id": self.config.agent_id,
                "registered_engines": list(self.config.registered_engines),
            },
        )

    def build_handshake_ack(self) -> FrameworkMessage | None:
        if self._handshake_correlation_id is None or self.session_token is None:
            return None
        return FrameworkMessage(
            source=MessageSource(
                agent_id=self.config.agent_id,
                engine=EngineId.CORVUS_NODE,
                vm_id=self.config.vm_id,
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.RESPONSE,
            type="handshake",
            correlation_id=self._handshake_correlation_id,
            tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
            payload={"ack": True, "_session": {"token": self.session_token}},
        )

    async def perform_handshake(self, reader, writer) -> bool:
        request = self.build_handshake_request()
        writer.write((encode_message(request) + "\n").encode("utf-8"))
        await writer.drain()

        for _ in range(self.config.handshake_max_retries):
            line = await reader.readline()
            if not line:
                return False
            response = decode_line(line.decode("utf-8"))
            if response.message_class == MessageClass.ERROR:
                return False
            if response.type != "handshake":
                continue
            if "session_token" not in response.payload:
                continue

            self.session_token = response.payload["session_token"]
            expires_raw = response.payload.get("session_expires_at")
            if expires_raw:
                self.session_expires_at = datetime.fromisoformat(expires_raw)
                if self.session_expires_at.tzinfo is None:
                    self.session_expires_at = self.session_expires_at.replace(tzinfo=UTC)
            self.policy_snapshot = response.payload.get(
                "policy_snapshot", DEFAULT_POLICY_SNAPSHOT
            )

            ack = self.build_handshake_ack()
            if ack is None:
                return False
            writer.write((encode_message(ack) + "\n").encode("utf-8"))
            await writer.drain()
            self.handshake_complete = True
            return True

        return False

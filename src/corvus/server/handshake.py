"""Boot-time handshake handling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from corvus.policy.rules import RuleStore
from corvus.protocol import (
    DEFAULT_POLICY_SNAPSHOT,
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
    make_error_message,
)
from corvus.protocol.errors import ErrorCode, ErrorLayer
from corvus.server.db import Database
from corvus.server.session import SessionManager

if TYPE_CHECKING:
    from corvus.server.pending_replay import PendingReplayQueue


class HandshakeHandler:
    def __init__(
        self,
        db: Database,
        sessions: SessionManager,
        rules: RuleStore | None = None,
        *,
        transport=None,
        pending_replay: PendingReplayQueue | None = None,
    ) -> None:
        self.db = db
        self.sessions = sessions
        self.rules = rules
        self.transport = transport
        self.pending_replay = pending_replay

    async def handle(
        self, message: FrameworkMessage, connection_id: int
    ) -> FrameworkMessage | None:
        payload = message.payload
        agent_id = payload.get("agent_id") or message.source.agent_id
        manifest_hash = payload.get("manifest_hash")
        vm_instance_id = payload.get("vm_instance_id") or message.source.vm_id

        if not manifest_hash or not agent_id:
            return make_error_message(
                code=ErrorCode.NODE_VALIDATION_FAILED,
                layer=ErrorLayer.SERVER,
                message="Handshake missing manifest_hash or agent_id",
                recoverable=True,
                agent_id=agent_id or "unknown",
                vm_id=vm_instance_id or "unknown",
                correlation_id=message.correlation_id,
                original_message_id=message.id,
            )

        agent = await self.db.get_agent(agent_id)
        if agent is None or agent["manifest_hash"] != manifest_hash:
            return make_error_message(
                code=ErrorCode.SERVER_SESSION_INVALID,
                layer=ErrorLayer.SERVER,
                message="Unknown agent or manifest hash mismatch",
                recoverable=False,
                agent_id=agent_id,
                vm_id=vm_instance_id,
                correlation_id=message.correlation_id,
                original_message_id=message.id,
            )

        registered_engines = set(payload.get("registered_engines") or [])
        manifest_engines = set((agent["manifest"].get("engines") or {}).keys())
        unknown_engines = sorted(registered_engines - manifest_engines)
        if unknown_engines:
            return make_error_message(
                code=ErrorCode.NODE_VALIDATION_FAILED,
                layer=ErrorLayer.SERVER,
                message="Handshake registered engines outside launch manifest",
                recoverable=False,
                agent_id=agent_id,
                vm_id=vm_instance_id,
                correlation_id=message.correlation_id,
                details={"unknown_engines": unknown_engines},
                original_message_id=message.id,
            )

        token, expires_at = await self.sessions.create_session(agent_id, vm_instance_id)
        self.sessions.bind_connection(connection_id, token)
        if self.transport is not None:
            self.transport.bind_agent(agent_id, vm_instance_id, connection_id)

        if message.message_class == MessageClass.SYSTEM and message.type == "handshake":
            if message.payload.get("ack"):
                return None
            return FrameworkMessage(
                source=MessageSource(
                    agent_id="corvus-server",
                    engine=EngineId.CORVUS_NODE,
                    vm_id="server",
                ),
                destination=MessageDestination(
                    type=DestinationType.ENGINE, target=EngineId.CORVUS_NODE.value
                ),
                message_class=MessageClass.SYSTEM,
                type="handshake",
                correlation_id=message.correlation_id,
                tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
                payload={
                    "session_token": token,
                    "session_expires_at": expires_at.isoformat(),
                    "policy_snapshot": self._policy_snapshot(agent["manifest"]),
                    "server_time": datetime.now(UTC).isoformat(),
                },
            )

        return make_error_message(
            code=ErrorCode.NODE_VALIDATION_FAILED,
            layer=ErrorLayer.SERVER,
            message="Invalid handshake message",
            recoverable=True,
            agent_id=agent_id,
            vm_id=vm_instance_id,
            correlation_id=message.correlation_id,
            original_message_id=message.id,
        )

    async def send_ack(self, original: FrameworkMessage, token: str) -> FrameworkMessage:
        return FrameworkMessage(
            source=MessageSource(
                agent_id=original.source.agent_id,
                engine=EngineId.CORVUS_NODE,
                vm_id=original.source.vm_id,
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.RESPONSE,
            type="handshake",
            correlation_id=original.correlation_id,
            tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
            payload={"ack": True, "_session": {"token": token}},
        )

    def _policy_snapshot(self, manifest: dict) -> dict:
        engines = manifest.get("engines", {})
        snapshot = dict(DEFAULT_POLICY_SNAPSHOT)
        snapshot.update({
            "ruleset_hash": self.rules.ruleset_hash if self.rules else "",
            "manifest_engines": sorted(engines.keys()),
            "engine1_tools": engines.get("engine1", {}).get("tools", []),
            "engine3_providers": engines.get("engine3", {}).get("allowed_providers", []),
            "engine3_models": engines.get("engine3", {}).get("allowed_models", []),
            "engine4_namespaces": engines.get("engine4", {}).get("namespaces", []),
        })
        return snapshot

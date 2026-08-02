"""Replay approved memory elevations and notify connected agents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from corvus.audit.store import AuditStore
from corvus.memory.service import MemoryService
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
from corvus.server.db import Database
from corvus.server.transport import AgentTransport

if TYPE_CHECKING:
    from corvus.server.pending_replay import PendingReplayQueue

logger = logging.getLogger(__name__)

MEMORY_REPLAY_TYPES = frozenset({"memory:query", "memory:write", "memory:delete"})


def resolve_replay_message(elevation: dict[str, Any]) -> dict[str, Any] | None:
    message = elevation.get("message") or {}
    msg_type = message.get("type")
    if msg_type in MEMORY_REPLAY_TYPES:
        return message
    if msg_type == "memory:grant_request":
        pending = (elevation.get("context") or {}).get("pending_replay")
        if isinstance(pending, dict):
            return pending
    return None


def build_memory_response(message: FrameworkMessage, payload: dict[str, Any]) -> FrameworkMessage:
    payload = {**payload, "original_type": message.type}
    return FrameworkMessage(
        source=MessageSource(
            agent_id="corvus-server",
            engine=EngineId.CORVUS_NODE,
            vm_id="server",
        ),
        destination=MessageDestination(
            type=DestinationType.ENGINE,
            target=str(message.source.engine),
        ),
        message_class=MessageClass.RESPONSE,
        type=f"{message.type}_response",
        correlation_id=message.correlation_id,
        tags=MessageTags(
            triggered_by=TriggeredBy.MEMORY_RESULT,
            origin_correlation_id=message.tags.origin_correlation_id or message.correlation_id,
        ),
        payload=payload,
    )


def build_grant_created_notification(
    *,
    agent_id: str,
    vm_id: str,
    turn_id: UUID | None,
    elevation_id: str,
    grant_id: str,
    target_agent_id: str,
    namespace: str,
    replay_delivered: bool,
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(
            agent_id="corvus-server",
            engine=EngineId.CORVUS_NODE,
            vm_id="server",
        ),
        destination=MessageDestination(type=DestinationType.ENGINE, target=EngineId.ENGINE4.value),
        message_class=MessageClass.SYSTEM,
        type="memory:grant_created",
        correlation_id=turn_id or uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.SYSTEM,
            origin_correlation_id=turn_id,
        ),
        payload={
            "elevation_id": elevation_id,
            "grant_id": grant_id,
            "target_agent_id": target_agent_id,
            "namespace": namespace,
            "replay_delivered": replay_delivered,
        },
    )


class ElevationReplayService:
    def __init__(
        self,
        db: Database,
        memory: MemoryService,
        transport: AgentTransport,
        audit: AuditStore,
        pending_replay: PendingReplayQueue | None = None,
    ) -> None:
        self.db = db
        self.memory = memory
        self.transport = transport
        self.audit = audit
        self.pending_replay = pending_replay

    async def replay_after_approval(
        self,
        elevation_id: str,
        *,
        grant_id: str | None,
        approver_user_id: str,
    ) -> dict[str, Any]:
        elevation = await self.db.get_elevation(elevation_id)
        if elevation is None:
            return {"replayed": False, "reason": "elevation_not_found"}

        if grant_id is None:
            grant_id = await self._grant_id_from_grant_request(elevation, approver_user_id)
        if grant_id is None:
            return {"replayed": False, "reason": "no_grant_for_replay"}

        pending_replay_queued = False

        replay_raw = resolve_replay_message(elevation)
        if replay_raw is None:
            grant_delivered = await self._notify_grant_created(
                elevation,
                grant_id=grant_id,
                replay_delivered=False,
            )
            if grant_delivered is False:
                pending_replay_queued = True
            return {
                "replayed": False,
                "reason": "no_replay_target",
                "grant_id": grant_id,
                "pending_replay_queued": pending_replay_queued,
            }

        replay_payload = dict(replay_raw.get("payload") or {})
        replay_payload["grant_id"] = grant_id
        replay_raw = {**replay_raw, "payload": replay_payload}
        replay_message = FrameworkMessage.model_validate(replay_raw)

        result = await self.memory.handle(replay_message, grant_id=grant_id)
        response = build_memory_response(replay_message, result.model_dump(mode="json"))
        agent_id = replay_message.source.agent_id
        vm_id = replay_message.source.vm_id
        replay_delivered = await self.transport.deliver(agent_id, vm_id, response)
        if not replay_delivered:
            await self._queue_message(
                agent_id=agent_id,
                vm_id=vm_id,
                elevation_id=elevation_id,
                grant_id=grant_id,
                message=response,
            )
            pending_replay_queued = True

        target_agent_id = str(
            replay_payload.get("target_agent_id", replay_message.source.agent_id)
        )
        namespace = str(replay_payload.get("namespace", "private"))
        grant_delivered = await self._notify_grant_created(
            elevation,
            grant_id=grant_id,
            replay_delivered=replay_delivered,
            target_agent_id=target_agent_id,
            namespace=namespace,
            turn_id=replay_message.tags.origin_correlation_id,
        )
        if grant_delivered is False:
            pending_replay_queued = True

        await self.audit.log_security_event(
            event_type="elevation_replay",
            correlation_id=str(replay_message.correlation_id),
            agent_id=agent_id,
            details={
                "elevation_id": elevation_id,
                "grant_id": grant_id,
                "approver_user_id": approver_user_id,
                "replay_type": replay_message.type,
                "replay_delivered": replay_delivered,
                "pending_replay_queued": pending_replay_queued,
                "success": result.success,
            },
        )
        return {
            "replayed": True,
            "grant_id": grant_id,
            "replay_delivered": replay_delivered,
            "pending_replay_queued": pending_replay_queued,
            "success": result.success,
        }

    async def _queue_message(
        self,
        *,
        agent_id: str,
        vm_id: str,
        elevation_id: str,
        grant_id: str,
        message: FrameworkMessage,
    ) -> None:
        if self.pending_replay is None:
            return
        await self.pending_replay.enqueue(agent_id, vm_id, elevation_id, grant_id, message)

    async def _grant_id_from_grant_request(
        self, elevation: dict[str, Any], approver_user_id: str
    ) -> str | None:
        message = elevation.get("message") or {}
        if message.get("type") != "memory:grant_request":
            return None
        payload = message.get("payload") or {}
        duration = int(payload.get("requested_duration_seconds") or 3600)
        expires_at = (datetime.now(UTC) + timedelta(seconds=duration)).isoformat()
        return await self.db.create_grant(
            subject_agent=str(message.get("source", {}).get("agent_id")),
            target_agent=str(payload.get("target_agent_id")),
            namespace=str(payload.get("namespace")),
            permissions=list(payload.get("permissions") or ["read"]),
            expires_at=expires_at,
            created_by=approver_user_id,
        )

    async def _notify_grant_created(
        self,
        elevation: dict[str, Any],
        *,
        grant_id: str,
        replay_delivered: bool,
        target_agent_id: str | None = None,
        namespace: str | None = None,
        turn_id: UUID | None = None,
    ) -> bool | None:
        message = elevation.get("message") or {}
        source = message.get("source") or {}
        payload = message.get("payload") or {}
        agent_id = str(source.get("agent_id") or "")
        if not agent_id:
            return None
        parsed_turn: UUID | None = None
        if turn_id is not None:
            parsed_turn = turn_id if isinstance(turn_id, UUID) else UUID(str(turn_id))
        else:
            tags = message.get("tags") or {}
            origin = tags.get("origin_correlation_id")
            if origin:
                parsed_turn = UUID(str(origin))
        vm_id = str(source.get("vm_id") or "unknown")
        notification = build_grant_created_notification(
            agent_id=agent_id,
            vm_id=vm_id,
            turn_id=parsed_turn,
            elevation_id=str(elevation.get("id")),
            grant_id=grant_id,
            target_agent_id=target_agent_id or str(payload.get("target_agent_id") or agent_id),
            namespace=namespace or str(payload.get("namespace") or "private"),
            replay_delivered=replay_delivered,
        )
        delivered = await self.transport.deliver(agent_id, vm_id, notification)
        if not delivered:
            await self._queue_message(
                agent_id=agent_id,
                vm_id=vm_id,
                elevation_id=str(elevation.get("id")),
                grant_id=grant_id,
                message=notification,
            )
        return delivered

"""Offline pending replay queue for elevation delivery after reconnect."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from corvus.audit.store import AuditStore
from corvus.protocol import FrameworkMessage
from corvus.server.db import Database
from corvus.server.transport import AgentTransport

logger = logging.getLogger(__name__)


class PendingReplayQueue:
    def __init__(self, db: Database, transport: AgentTransport, audit: AuditStore) -> None:
        self.db = db
        self.transport = transport
        self.audit = audit

    async def enqueue(
        self,
        agent_id: str,
        vm_id: str,
        elevation_id: str,
        grant_id: str,
        message: FrameworkMessage,
    ) -> str:
        replay_id = await self.db.enqueue_pending_replay(
            agent_id=agent_id,
            vm_id=vm_id,
            elevation_id=elevation_id,
            grant_id=grant_id,
            message=message.model_dump(mode="json"),
        )
        logger.info(
            "queued pending replay id=%s agent=%s vm=%s elevation=%s type=%s",
            replay_id,
            agent_id,
            vm_id,
            elevation_id,
            message.type,
        )
        return replay_id

    async def flush_for_vm(self, agent_id: str, vm_id: str) -> int:
        pending = await self.db.list_pending_replays(agent_id, vm_id)
        if not pending:
            return 0

        delivered_count = 0
        now = datetime.now(UTC).isoformat()
        for row in pending:
            message = FrameworkMessage.model_validate(row["message"])
            if not await self.transport.deliver(agent_id, vm_id, message):
                logger.warning(
                    "pending replay flush stopped for agent=%s vm=%s at id=%s",
                    agent_id,
                    vm_id,
                    row["id"],
                )
                break
            await self.db.mark_pending_replay_delivered(row["id"], now)
            await self.audit.log_security_event(
                event_type="pending_replay_delivered",
                correlation_id=str(message.correlation_id),
                agent_id=agent_id,
                details={
                    "vm_id": vm_id,
                    "elevation_id": row["elevation_id"],
                    "grant_id": row["grant_id"],
                    "message_type": message.type,
                    "pending_replay_id": row["id"],
                },
            )
            delivered_count += 1

        if delivered_count:
            logger.info(
                "flushed %s pending replay message(s) for agent=%s vm=%s",
                delivered_count,
                agent_id,
                vm_id,
            )
        return delivered_count

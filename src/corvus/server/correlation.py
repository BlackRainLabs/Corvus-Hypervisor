"""Turn correlation state store backed by SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from corvus.protocol import FrameworkMessage, MessageClass, TriggeredBy
from corvus.server.config import ServerConfig
from corvus.server.db import Database


class CorrelationStore:
    def __init__(self, db: Database, config: ServerConfig) -> None:
        self.db = db
        self.config = config

    async def startup(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.turn_timeout_seconds)
        await self.db.purge_expired_turn_states(cutoff_iso=cutoff.isoformat())

    async def _purge_expired(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.turn_timeout_seconds)
        await self.db.purge_expired_turn_states(cutoff_iso=cutoff.isoformat())

    async def register_user_query(self, message: FrameworkMessage) -> None:
        await self._purge_expired()
        user_id = message.payload.get("user_id")
        now = datetime.now(UTC).isoformat()
        await self.db.upsert_turn_state(
            root_correlation_id=str(message.correlation_id),
            agent_id=message.source.agent_id,
            user_id=str(user_id) if user_id else None,
            started_at=now,
            last_activity=now,
            depth=0,
        )

    async def validate(self, message: FrameworkMessage) -> tuple[bool, str | None]:
        if message.type == "user_query" and message.tags.triggered_by == TriggeredBy.USER_INPUT:
            return True, None

        if message.message_class == MessageClass.SYSTEM:
            return True, None

        if message.type == "handshake":
            return True, None

        origin_id = message.tags.origin_correlation_id or message.correlation_id
        turn = await self.db.get_turn_state(str(origin_id))
        if turn is None:
            if message.type == "user_query":
                return True, None
            return False, "SERVER_CORRELATION_INVALID"

        cutoff = datetime.now(UTC) - timedelta(seconds=self.config.turn_timeout_seconds)
        last_activity = datetime.fromisoformat(str(turn["last_activity"]))
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=UTC)
        if last_activity < cutoff:
            await self.db.delete_turn_state(str(origin_id))
            return False, "SERVER_CORRELATION_EXPIRED"

        if turn["agent_id"] != message.source.agent_id:
            return False, "SERVER_CORRELATION_INVALID"

        depth = int(turn["depth"]) + 1
        if depth > self.config.max_chain_depth:
            return False, "SERVER_CORRELATION_INVALID"

        now = datetime.now(UTC).isoformat()
        await self.db.update_turn_state_activity(
            root_correlation_id=str(origin_id),
            last_activity=now,
            depth=depth,
        )
        await self._purge_expired()
        return True, None

    async def get_user_id_for_turn(self, correlation_id: UUID) -> str | None:
        turn = await self.db.get_turn_state(str(correlation_id))
        if turn and turn.get("user_id"):
            return str(turn["user_id"])
        return None

    async def get_user_id_for_message(self, message: FrameworkMessage) -> str | None:
        origin_id = message.tags.origin_correlation_id or message.correlation_id
        user_id = await self.get_user_id_for_turn(origin_id)
        if user_id:
            return user_id
        if message.type == "user_query":
            uid = message.payload.get("user_id")
            return str(uid) if uid else None
        return None

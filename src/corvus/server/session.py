"""Session token management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from corvus.server.config import ServerConfig
from corvus.server.db import Database


class SessionManager:
    def __init__(self, db: Database, config: ServerConfig) -> None:
        self.db = db
        self.config = config
        self._connection_tokens: dict[int, str] = {}

    def bind_connection(self, connection_id: int, token: str) -> None:
        self._connection_tokens[connection_id] = token

    def unbind_connection(self, connection_id: int) -> None:
        self._connection_tokens.pop(connection_id, None)

    def get_connection_token(self, connection_id: int) -> str | None:
        return self._connection_tokens.get(connection_id)

    @property
    def active_connection_count(self) -> int:
        return len(self._connection_tokens)

    def status_snapshot(self) -> dict[str, int]:
        return {"active_connections": self.active_connection_count}

    async def create_session(self, agent_id: str, vm_id: str) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(hours=self.config.session_ttl_hours)
        token = await self.db.create_session(agent_id, vm_id, expires_at)
        return token, expires_at

    async def validate_token(self, token: str | None) -> dict[str, str] | None:
        if not token:
            return None
        session = await self.db.get_session(token)
        if session is None:
            return None
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires_at:
            return None
        return session

    async def validate_connection(self, connection_id: int) -> dict[str, str] | None:
        token = self.get_connection_token(connection_id)
        return await self.validate_token(token)

    def extract_session_token(self, payload: dict) -> str | None:
        session = payload.get("_session")
        if isinstance(session, dict):
            token = session.get("token")
            return str(token) if token else None
        token = payload.get("session_token")
        return str(token) if token else None

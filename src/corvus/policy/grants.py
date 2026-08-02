"""DB-backed grant evaluation for RBAC memory gates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from corvus.server.db import Database


class GrantEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def evaluate(
        self,
        *,
        subject_agent: str,
        target_agent: str,
        namespace: str,
        permission: str,
        grant_id: str | None = None,
    ) -> dict[str, Any]:
        if target_agent == subject_agent:
            return {"valid": True, "grant_id": None, "reason": "owner_access"}

        grant = await self.db.find_valid_grant(
            subject_agent=subject_agent,
            target_agent=target_agent,
            namespace=namespace,
            permission=permission,
            grant_id=grant_id,
            now=datetime.now(UTC),
        )
        if grant is None:
            return {"valid": False, "grant_id": grant_id, "reason": "no_valid_grant"}
        return {"valid": True, "grant_id": grant["id"], "reason": "grant_valid"}


def permission_for_message_type(message_type: str) -> str:
    if message_type.endswith(":write"):
        return "write"
    if message_type.endswith(":delete"):
        return "delete"
    return "read"

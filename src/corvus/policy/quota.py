"""Quota counter metering for RBAC decisions and memory operations."""

from __future__ import annotations

from typing import Any

from corvus.server.db import Database


class QuotaService:
    def __init__(
        self,
        db: Database,
        *,
        memory_writes_daily_limit: int = 10_000,
    ) -> None:
        self.db = db
        self.memory_writes_daily_limit = memory_writes_daily_limit

    @staticmethod
    def memory_write_key(agent_id: str) -> str:
        return f"agent:{agent_id}:memory_writes:daily"

    async def evaluate(
        self,
        *,
        key: str,
        limit: int | None,
        requested: int = 0,
        window_type: str = "daily",
    ) -> dict[str, Any]:
        if limit is None:
            return {
                "checked": False,
                "quota_key": key,
                "remaining_after": None,
                "would_exceed": False,
                "would_consume_tokens": requested,
            }
        counter = await self.db.get_or_create_quota_counter(
            key=key,
            limit=limit,
            window_type=window_type,
        )
        remaining_after = int(counter["limit"]) - int(counter["used"]) - requested
        return {
            "checked": True,
            "quota_key": key,
            "remaining_after": remaining_after,
            "would_exceed": remaining_after < 0,
            "would_consume_tokens": requested,
        }

    async def increment_memory_write(self, agent_id: str) -> dict[str, Any]:
        key = self.memory_write_key(agent_id)
        await self.db.get_or_create_quota_counter(
            key=key,
            limit=self.memory_writes_daily_limit,
            window_type="daily",
        )
        counter = await self.db.increment_quota_counter(key, delta=1)
        if counter is None:
            raise RuntimeError(f"quota counter missing after create: {key}")
        return counter

    @staticmethod
    def llm_tokens_key(user_id: str | None) -> str:
        return f"user:{user_id or 'anonymous'}:llm_tokens:daily"

    async def increment_llm_tokens(
        self,
        user_id: str | None,
        tokens: int,
        *,
        daily_limit: int | None = None,
    ) -> dict[str, Any]:
        if tokens <= 0:
            key = self.llm_tokens_key(user_id)
            existing = await self.db.get_quota_counter(key)
            if existing is not None:
                return existing
            limit = daily_limit if daily_limit is not None else 100_000
            await self.db.get_or_create_quota_counter(
                key=key,
                limit=limit,
                window_type="daily",
            )
            counter = await self.db.get_quota_counter(key)
            if counter is None:
                raise RuntimeError(f"quota counter missing after create: {key}")
            return counter
        key = self.llm_tokens_key(user_id)
        limit = daily_limit if daily_limit is not None else 100_000
        await self.db.get_or_create_quota_counter(
            key=key,
            limit=limit,
            window_type="daily",
        )
        counter = await self.db.increment_quota_counter(key, delta=tokens)
        if counter is None:
            raise RuntimeError(f"quota counter missing after create: {key}")
        return counter

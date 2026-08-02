"""Background retention sweeper for memory records."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from corvus.memory.vec_store import delete_record_embedding
from corvus.server.db import Database

logger = logging.getLogger(__name__)


class MemoryRetentionSweeper:
    def __init__(
        self,
        db: Database,
        *,
        interval_seconds: float = 900.0,
        soft_delete_retention_hours: int = 24,
    ) -> None:
        self.db = db
        self.interval_seconds = interval_seconds
        self.soft_delete_retention = timedelta(hours=soft_delete_retention_hours)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def sweep_once(self) -> tuple[int, int]:
        now = datetime.now(UTC)
        expired = await self._purge_expired(now)
        tombstones = await self._purge_soft_deleted(now)
        if expired or tombstones:
            logger.info(
                "memory retention sweep: expired=%s soft_deleted=%s",
                expired,
                tombstones,
            )
        return expired, tombstones

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("memory retention sweep failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    async def _purge_expired(self, now: datetime) -> int:
        cursor = await self.db.conn.execute(
            """
            SELECT id FROM memory_records
            WHERE deleted_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at <= ?
            """,
            (now.isoformat(),),
        )
        record_ids = [str(row[0]) for row in await cursor.fetchall()]
        for record_id in record_ids:
            await self._hard_delete_record(record_id)
        return len(record_ids)

    async def _purge_soft_deleted(self, now: datetime) -> int:
        cutoff = (now - self.soft_delete_retention).isoformat()
        cursor = await self.db.conn.execute(
            """
            SELECT id FROM memory_records
            WHERE deleted_at IS NOT NULL
              AND deleted_at <= ?
            """,
            (cutoff,),
        )
        record_ids = [str(row[0]) for row in await cursor.fetchall()]
        for record_id in record_ids:
            await self._hard_delete_record(record_id)
        return len(record_ids)

    async def _hard_delete_record(self, record_id: str) -> None:
        await delete_record_embedding(self.db.conn, record_id=record_id)
        await self.db.conn.execute("DELETE FROM memory_records WHERE id = ?", (record_id,))
        await self.db.conn.commit()

"""Background sweeper for expired pending elevations."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from corvus.server.db import Database

logger = logging.getLogger(__name__)


class ElevationSweeper:
    def __init__(self, db: Database, *, interval_seconds: float = 300.0) -> None:
        self.db = db
        self.interval_seconds = interval_seconds
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

    async def sweep_once(self) -> int:
        now = datetime.now(UTC)
        expired = await self.db.expire_pending_elevations(now)
        if expired:
            logger.info("elevation sweep: expired=%s", expired)
        return expired

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("elevation sweep failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

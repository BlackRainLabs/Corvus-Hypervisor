"""Base engine with IPC lifecycle."""

from __future__ import annotations

import asyncio
import logging

from corvus.protocol.models import EngineId
from corvus.runtime.config import RunMode, RuntimeConfig, load_config, resolve_manifest_hash
from corvus.runtime.coordinator import Coordinator
from corvus.runtime.ipc_client import NodeIpcClient

logger = logging.getLogger(__name__)

IDLE_ENGINES = frozenset()


class BaseEngine:
    engine_id: EngineId

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or load_config()
        self.run_mode = self.config.run_mode
        self.ipc = NodeIpcClient(
            str(self.config.ipc_socket_path),
            self.engine_id,
            manifest_hash=resolve_manifest_hash(self.config),
            connect_timeout=self.config.ipc_connect_timeout,
        )
        self.coordinator = Coordinator(self.config.coordinator_path)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        await self.ipc.connect()
        if not await self.ipc.wait_handshake():
            logger.critical("%s: handshake timeout", self.engine_id.value)
            return

        self.coordinator.mark_ready(self.engine_id.value)
        logger.info("%s ready", self.engine_id.value)

        try:
            if self.run_mode == RunMode.ONCE and self.engine_id in IDLE_ENGINES:
                logger.info("%s idle (once mode)", self.engine_id.value)
                return
            await self.serve()
            if self.run_mode == RunMode.DAEMON and not self._stop.is_set():
                await self._stop.wait()
        finally:
            await self.ipc.close()

    async def serve(self) -> None:
        await self._stop.wait()

    def request_stop(self) -> None:
        self._stop.set()

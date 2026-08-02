"""IPC client for Agent Loop and engines."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from corvus.node.models import IpcOperation
from corvus.protocol import FrameworkMessage, decode_line
from corvus.protocol.models import EngineId

InboundHandler = Callable[[FrameworkMessage], Awaitable[None]]

logger = logging.getLogger(__name__)


async def wait_for_socket(path: str | Path, timeout: float = 60.0) -> None:
    """Wait until a Unix socket exists and accepts connections."""
    sock_path = Path(path)
    deadline = asyncio.get_running_loop().time() + timeout
    last_log = 0.0
    while asyncio.get_running_loop().time() < deadline:
        if sock_path.exists():
            try:
                reader, writer = await asyncio.open_unix_connection(str(sock_path))
                writer.close()
                await writer.wait_closed()
                return
            except (ConnectionRefusedError, FileNotFoundError):
                pass
        now = asyncio.get_running_loop().time()
        if now - last_log >= 5.0:
            logger.info("waiting for Node IPC at %s", sock_path)
            last_log = now
        await asyncio.sleep(0.05)
    raise RuntimeError(f"Node IPC socket not available at {sock_path} after {timeout}s")


class NodeIpcClient:
    def __init__(
        self,
        socket_path: str,
        engine: EngineId,
        *,
        manifest_hash: str = "",
        connect_timeout: float = 60.0,
    ) -> None:
        self.socket_path = socket_path
        self.engine = engine
        self.manifest_hash = manifest_hash
        self.connect_timeout = connect_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._inbound_queue: asyncio.Queue[FrameworkMessage] = asyncio.Queue()
        self._pending: asyncio.Queue[asyncio.Future[dict[str, Any]]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._on_inbound: InboundHandler | None = None

    async def connect(self) -> None:
        await wait_for_socket(self.socket_path, timeout=self.connect_timeout)
        deadline = asyncio.get_running_loop().time() + self.connect_timeout
        last_log = 0.0
        while asyncio.get_running_loop().time() < deadline:
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(
                    self.socket_path
                )
                break
            except (FileNotFoundError, ConnectionRefusedError):
                now = asyncio.get_running_loop().time()
                if now - last_log >= 5.0:
                    logger.info("waiting for Node IPC at %s", self.socket_path)
                    last_log = now
                await asyncio.sleep(0.05)
        else:
            raise RuntimeError(f"Cannot connect to Node IPC at {self.socket_path}")

        self._reader_task = asyncio.create_task(self._read_loop())

        sub = {
            "operation": IpcOperation.SUBSCRIBE_ENGINE.value,
            "engine": self.engine.value,
            "payload": {"manifest_engine_hash": self.manifest_hash} if self.manifest_hash else {},
        }
        resp = await self._request(sub)
        if not resp.get("accepted"):
            raise RuntimeError(f"subscribe_engine failed: {resp}")

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    def set_inbound_handler(self, handler: InboundHandler) -> None:
        self._on_inbound = handler

    async def health_check(self) -> dict[str, Any]:
        return await self._request(
            {"operation": IpcOperation.HEALTH_CHECK.value, "engine": self.engine.value}
        )

    async def wait_handshake(self, timeout: float = 30.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            health = await self.health_check()
            if health.get("handshake_complete"):
                return True
            await asyncio.sleep(0.1)
        return False

    async def submit(self, message: FrameworkMessage) -> dict[str, Any]:
        envelope = {
            "operation": IpcOperation.SUBMIT_OUTBOUND.value,
            "engine": self.engine.value,
            "message": message.model_dump(mode="json", by_alias=True),
        }
        return await self._request(envelope)

    async def submit_and_wait(
        self, message: FrameworkMessage, timeout: float = 10.0
    ) -> FrameworkMessage:
        resp = await self.submit(message)
        if not resp.get("accepted"):
            err = resp.get("error")
            raise RuntimeError(f"submit rejected: {err}")
        return await self.wait_inbound(timeout=timeout)

    async def wait_inbound(self, timeout: float = 10.0) -> FrameworkMessage:
        return await asyncio.wait_for(self._inbound_queue.get(), timeout=timeout)

    async def _request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if self._writer is None:
            raise RuntimeError("Not connected")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        await self._pending.put(fut)
        self._writer.write((json.dumps(envelope) + "\n").encode("utf-8"))
        await self._writer.drain()
        return await fut

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            line = await self._reader.readline()
            if not line:
                break
            data = json.loads(line.decode("utf-8"))
            if data.get("operation") == IpcOperation.RECEIVE_INBOUND.value:
                message = decode_line(json.dumps(data["message"]))
                await self._inbound_queue.put(message)
                if self._on_inbound is not None:
                    await self._on_inbound(message)
                continue
            try:
                fut = self._pending.get_nowait()
            except asyncio.QueueEmpty:
                continue
            if not fut.done():
                fut.set_result(data)

    @staticmethod
    def parse_message_id(resp: dict[str, Any]) -> UUID | None:
        mid = resp.get("message_id")
        return UUID(mid) if mid else None

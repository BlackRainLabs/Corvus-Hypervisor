"""AF_VSOCK / TCP bus client to Corvus Server."""

from __future__ import annotations

import asyncio
import json
import socket
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from corvus.node.config import NodeConfig
from corvus.protocol import FrameworkMessage, encode_message
from corvus.protocol.codec import decode_line

InboundHandler = Callable[[FrameworkMessage], Awaitable[None]]
ReconnectHandler = Callable[
    [asyncio.StreamReader, asyncio.StreamWriter], Awaitable[bool]
]


async def open_server_connection(
    config: NodeConfig,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if config.use_tcp:
        return await asyncio.open_connection(config.tcp_host, config.tcp_port)
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.setblocking(False)
    await asyncio.get_running_loop().sock_connect(
        sock, (config.vsock_host_cid, config.vsock_port)
    )
    return await asyncio.open_connection(sock=sock)


class BusClient:
    def __init__(
        self,
        config: NodeConfig,
        on_inbound: InboundHandler,
        on_reconnect: ReconnectHandler | None = None,
    ) -> None:
        self.config = config
        self.on_inbound = on_inbound
        self.on_reconnect = on_reconnect
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._outbound: deque[FrameworkMessage] = deque(maxlen=config.outbound_queue_max)
        self._stop = asyncio.Event()
        self._reader_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._handshake_complete = False

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await open_server_connection(self.config)
        self._reader = reader
        self._writer = writer
        return reader, writer

    async def start(self, *, after_handshake: bool = False) -> None:
        self._handshake_complete = after_handshake
        self._stop.clear()
        if self._reader is None or self._writer is None:
            await self.connect()
        self._ensure_io_tasks()

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._reader_task, self._writer_task, self._reconnect_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await self._close_transport()

    def mark_handshake_complete(self) -> None:
        self._handshake_complete = True

    async def send(self, message: FrameworkMessage) -> bool:
        if len(self._outbound) >= self.config.outbound_queue_max:
            return False
        self._outbound.append(message)
        return True

    def _ensure_io_tasks(self) -> None:
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._read_loop())
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._write_loop())

    def _ensure_reconnect(self) -> None:
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _read_loop(self) -> None:
        while not self._stop.is_set():
            if self._reader is None:
                await asyncio.sleep(0.05)
                continue
            line = await self._reader.readline()
            if not line:
                if not self._stop.is_set():
                    self._ensure_reconnect()
                break
            try:
                message = decode_line(line.decode("utf-8"))
            except Exception:
                continue
            if (
                message.type == "handshake"
                and message.message_class.value == "system"
                and "session_token" in message.payload
            ):
                continue
            await self.on_inbound(message)

    async def _write_loop(self) -> None:
        while not self._stop.is_set():
            if not self._outbound:
                await asyncio.sleep(0.01)
                continue
            if self._writer is None:
                await asyncio.sleep(0.05)
                continue
            message = self._outbound.popleft()
            try:
                self._writer.write((encode_message(message) + "\n").encode("utf-8"))
                await self._writer.drain()
            except Exception:
                self._outbound.appendleft(message)
                await self._close_transport()
                self._ensure_reconnect()
                await asyncio.sleep(0.05)

    async def _reconnect_loop(self) -> None:
        delay = self.config.reconnect_base_seconds
        await self._close_transport()
        while not self._stop.is_set() and self._handshake_complete:
            try:
                reader, writer = await self.connect()
                if self.on_reconnect is not None:
                    if not await self.on_reconnect(reader, writer):
                        await self._close_transport()
                        raise RuntimeError("reconnect handshake failed")
                self._ensure_io_tasks()
                return
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.config.reconnect_max_seconds)

    async def _close_transport(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None


def encode_ipc_response(response: dict[str, Any]) -> str:
    return json.dumps(response, separators=(",", ":"), default=str)

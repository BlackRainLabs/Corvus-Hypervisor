"""AF_VSOCK and TCP transport gateway."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path

from corvus.protocol.codec import decode_line, encode_message
from corvus.protocol.models import FrameworkMessage
from corvus.server.config import ServerConfig
from corvus.server.transport import AgentTransport

logger = logging.getLogger(__name__)

MessageHandler = Callable[[FrameworkMessage, int], Awaitable[FrameworkMessage | None]]
DisconnectHandler = Callable[[int], None]


class TransportGateway:
    def __init__(
        self,
        config: ServerConfig,
        handler: MessageHandler,
        on_disconnect: DisconnectHandler | None = None,
        transport: AgentTransport | None = None,
    ) -> None:
        self.config = config
        self.handler = handler
        self.on_disconnect = on_disconnect
        self.transport = transport
        self._server: asyncio.Server | None = None
        self._uds_servers: list[asyncio.Server] = []
        self._uds_watch_task: asyncio.Task | None = None
        self._uds_seen: set[Path] = set()
        self._next_connection_id = 1

    async def start(self) -> None:
        if self.config.use_tcp:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.config.tcp_host,
                self.config.tcp_port,
            )
            return

        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        try:
            sock.setblocking(False)
            sock.bind((self.config.vsock_cid, self.config.vsock_port))
            sock.listen()
            self._server = await asyncio.start_server(self._handle_client, sock=sock)
        except Exception:
            sock.close()
            raise

        self._uds_watch_task = asyncio.create_task(self._watch_firecracker_uds())

    async def stop(self) -> None:
        if self._uds_watch_task is not None:
            self._uds_watch_task.cancel()
            try:
                await self._uds_watch_task
            except asyncio.CancelledError:
                pass
            self._uds_watch_task = None
        for server in self._uds_servers:
            server.close()
            await server.wait_closed()
        self._uds_servers.clear()
        self._uds_seen.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def listen_target(self) -> str:
        if self.config.use_tcp:
            return f"tcp://{self.config.tcp_host}:{self.config.tcp_port}"
        port = self.config.vsock_port
        return (
            f"vsock://{self.config.vsock_cid}:{port} "
            f"+ firecracker-uds:{self.config.vm_state_dir}/vsock-*.sock_{port}"
        )

    @staticmethod
    def firecracker_guest_listen_path(base_uds: Path, port: int) -> Path:
        """Host listen path for guest-initiated vsock connections (Firecracker uds_path_PORT)."""
        return Path(f"{base_uds}_{port}")

    async def _watch_firecracker_uds(self) -> None:
        state_dir = self.config.vm_state_dir
        port = self.config.vsock_port
        while True:
            if state_dir.exists():
                for base_sock in sorted(state_dir.glob("vsock-*.sock")):
                    listen_path = self.firecracker_guest_listen_path(base_sock, port)
                    if listen_path in self._uds_seen:
                        continue
                    try:
                        if listen_path.exists():
                            listen_path.unlink()
                        server = await asyncio.start_unix_server(
                            self._handle_client,
                            path=str(listen_path),
                        )
                    except OSError as exc:
                        logger.debug("uds listen skipped for %s: %s", listen_path, exc)
                        continue
                    self._uds_seen.add(listen_path)
                    self._uds_servers.append(server)
                    logger.info("Firecracker guest transport listening on %s", listen_path)
            await asyncio.sleep(0.25)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection_id = self._next_connection_id
        self._next_connection_id += 1
        if self.transport is not None:
            self.transport.register_writer(connection_id, writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = decode_line(line.decode("utf-8"))
                except Exception:
                    continue
                response = await self.handler(message, connection_id)
                if response is not None:
                    writer.write((encode_message(response) + "\n").encode("utf-8"))
                    await writer.drain()
        finally:
            if self.on_disconnect is not None:
                self.on_disconnect(connection_id)
            if self.transport is not None:
                self.transport.unbind(connection_id)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

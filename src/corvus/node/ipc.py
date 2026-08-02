"""Unix domain socket IPC interface for engines and Agent Loop."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from corvus.node.bus import encode_ipc_response
from corvus.node.models import IpcEnvelope, IpcOperation, IpcResponse
from corvus.protocol.models import EngineId, FrameworkMessage


@dataclass
class IpcClient:
    engine: EngineId
    writer: asyncio.StreamWriter
    manifest_engine_hash: str | None = None


@dataclass
class IPCInterface:
    socket_path: str
    clients: dict[EngineId, IpcClient] = field(default_factory=dict)
    _pending_inbound: dict[EngineId, list[FrameworkMessage]] = field(default_factory=dict)
    _server: asyncio.Server | None = field(default=None, repr=False)

    async def start(self) -> None:
        path = self.socket_path
        try:
            import os

            if os.path.exists(path):
                os.unlink(path)
        except OSError:
            pass
        self._server = await asyncio.start_unix_server(self._handle_client, path=path)

    async def stop(self) -> None:
        for client in list(self.clients.values()):
            client.writer.close()
            try:
                await asyncio.wait_for(client.writer.wait_closed(), timeout=1.0)
            except (Exception, TimeoutError):
                pass
        self.clients.clear()
        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=1.0)
            except (Exception, TimeoutError):
                pass
            self._server = None

    def get_client(self, engine: EngineId) -> IpcClient | None:
        return self.clients.get(engine)

    async def push_inbound(self, engine: EngineId, message: FrameworkMessage) -> bool:
        client = self.clients.get(engine)
        if client is None:
            self._pending_inbound.setdefault(engine, []).append(message)
            return False
        envelope = IpcResponse(
            operation=IpcOperation.RECEIVE_INBOUND,
            message=message,
        )
        return await self._write_response(client.writer, envelope)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        registered: EngineId | None = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    data: dict[str, Any] = json.loads(line.decode("utf-8"))
                    envelope = IpcEnvelope.model_validate(data)
                except (json.JSONDecodeError, ValidationError):
                    await self._write_raw(
                        writer,
                        {"accepted": False, "error": "Invalid IPC envelope"},
                    )
                    continue

                if envelope.operation == IpcOperation.HEALTH_CHECK:
                    response = await self._on_health_check()
                    await self._write_response(writer, response)
                    continue

                if envelope.operation == IpcOperation.SUBSCRIBE_ENGINE:
                    registered = await self._subscribe(envelope, writer)
                    continue

                if registered is None:
                    await self._write_raw(
                        writer,
                        {"accepted": False, "error": "subscribe_engine required first"},
                    )
                    continue

                if envelope.operation == IpcOperation.SUBMIT_OUTBOUND:
                    if envelope.message is None:
                        await self._write_raw(
                            writer,
                            {"accepted": False, "error": "message required"},
                        )
                        continue
                    response = await self._on_submit_outbound(
                        registered,
                        envelope.message,
                        EngineId(envelope.message.source.engine),
                    )
                    await self._write_response(writer, response)
                    continue
        finally:
            if registered is not None:
                self.clients.pop(registered, None)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (Exception, asyncio.CancelledError):
                pass

    async def _subscribe(
        self, envelope: IpcEnvelope, writer: asyncio.StreamWriter
    ) -> EngineId | None:
        engine = EngineId(envelope.engine)
        if engine == EngineId.CORVUS_NODE:
            await self._write_raw(writer, {"accepted": False, "error": "Invalid engine"})
            return None
        if engine in self.clients:
            await self._write_raw(
                writer, {"accepted": False, "error": f"{engine.value} already registered"}
            )
            return None

        manifest_hash = None
        if envelope.payload:
            manifest_hash = envelope.payload.get("manifest_engine_hash")

        self.clients[engine] = IpcClient(
            engine=engine,
            writer=writer,
            manifest_engine_hash=manifest_hash,
        )
        response = await self._on_subscribe(engine)
        await self._write_response(writer, response)
        await self._flush_pending_inbound(engine)
        return engine

    async def _flush_pending_inbound(self, engine: EngineId) -> None:
        pending = self._pending_inbound.pop(engine, [])
        client = self.clients.get(engine)
        if client is None:
            if pending:
                self._pending_inbound[engine] = pending
            return
        for message in pending:
            envelope = IpcResponse(
                operation=IpcOperation.RECEIVE_INBOUND,
                message=message,
            )
            await self._write_response(client.writer, envelope)

    async def _write_response(
        self, writer: asyncio.StreamWriter, response: IpcResponse
    ) -> bool:
        data = response.model_dump(mode="json", exclude_none=True)
        if response.error is not None:
            data["error"] = response.error.model_dump(mode="json", by_alias=True)
        if response.message is not None:
            data["message"] = response.message.model_dump(mode="json", by_alias=True)
        return await self._write_raw(writer, data)

    async def _write_raw(self, writer: asyncio.StreamWriter, data: dict[str, Any]) -> bool:
        try:
            writer.write((encode_ipc_response(data) + "\n").encode("utf-8"))
            await writer.drain()
            return True
        except Exception:
            return False

    async def _on_subscribe(self, engine: EngineId) -> IpcResponse:
        raise NotImplementedError

    async def _on_health_check(self) -> IpcResponse:
        raise NotImplementedError

    async def _on_submit_outbound(
        self,
        registered: EngineId,
        message: FrameworkMessage,
        claimed_engine: EngineId,
    ) -> IpcResponse:
        raise NotImplementedError

"""Active agent transport connections for server-initiated delivery."""

from __future__ import annotations

import asyncio
import logging

from corvus.protocol import FrameworkMessage, encode_message

logger = logging.getLogger(__name__)


class AgentTransport:
    def __init__(self) -> None:
        self._writers: dict[int, asyncio.StreamWriter] = {}
        # Keyed on (agent_id, vm_id) so multiple VMs of the same agent do not
        # collide: each VM's handshake binds its own connection.
        self._agent_connections: dict[tuple[str, str], int] = {}

    def register_writer(self, connection_id: int, writer: asyncio.StreamWriter) -> None:
        self._writers[connection_id] = writer

    def bind_agent(self, agent_id: str, vm_id: str, connection_id: int) -> None:
        self._agent_connections[(agent_id, vm_id)] = connection_id

    def unbind(self, connection_id: int) -> None:
        self._writers.pop(connection_id, None)
        for key, bound_id in list(self._agent_connections.items()):
            if bound_id == connection_id:
                del self._agent_connections[key]

    def is_agent_connected(self, agent_id: str, vm_id: str) -> bool:
        connection_id = self._agent_connections.get((agent_id, vm_id))
        if connection_id is None:
            return False
        writer = self._writers.get(connection_id)
        return writer is not None and not writer.is_closing()

    async def deliver(self, agent_id: str, vm_id: str, message: FrameworkMessage) -> bool:
        connection_id = self._agent_connections.get((agent_id, vm_id))
        if connection_id is None:
            return False
        writer = self._writers.get(connection_id)
        if writer is None or writer.is_closing():
            return False
        try:
            writer.write((encode_message(message) + "\n").encode("utf-8"))
            await writer.drain()
            return True
        except Exception:
            logger.exception("failed to deliver message to agent %s vm %s", agent_id, vm_id)
            return False

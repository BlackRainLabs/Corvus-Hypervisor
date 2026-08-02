"""Corvus Node daemon orchestrator."""

from __future__ import annotations

import asyncio
import logging

from corvus.node.bus import BusClient
from corvus.node.config import NodeConfig, load_config
from corvus.node.ipc import IPCInterface
from corvus.node.models import IpcResponse
from corvus.node.routing import resolve_inbound_target
from corvus.node.session import SessionManager
from corvus.node.validator import MessageValidator
from corvus.protocol import ErrorCode, ErrorLayer, FrameworkMessage, make_error_message
from corvus.protocol.models import DestinationType, EngineId, MessageSource

logger = logging.getLogger(__name__)


class CorvusNode:
    def __init__(self, config: NodeConfig | None = None) -> None:
        self.config = config or load_config()
        self.session = SessionManager(self.config)
        self.validator = MessageValidator()
        self.bus = BusClient(self.config, self.deliver_inbound, self._reconnect_session)
        self.ipc = _NodeIPC(self)
        self._stop = asyncio.Event()

    async def run(self) -> None:
        reader, writer = await self.bus.connect()
        if not await self.session.perform_handshake(reader, writer):
            logger.critical("Handshake failed after retries")
            await self.bus.stop()
            return

        self.validator.update_policy(self.session.policy_snapshot)
        self.bus.mark_handshake_complete()
        await self.bus.start(after_handshake=True)
        await self.ipc.start()
        logger.info(
            "Corvus Node active — agent=%s vm=%s ipc=%s",
            self.config.agent_id,
            self.config.vm_id,
            self.config.ipc_socket_path,
        )

        try:
            await self._stop.wait()
        finally:
            await self.shutdown()

    def request_stop(self) -> None:
        self._stop.set()

    async def shutdown(self) -> None:
        await self.ipc.stop()
        await self.bus.stop()

    async def _reconnect_session(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> bool:
        if not await self.session.perform_handshake(reader, writer):
            logger.error("Corvus Node reconnect handshake failed")
            return False
        self.validator.update_policy(self.session.policy_snapshot)
        self.bus.mark_handshake_complete()
        logger.info("Corvus Node reconnected and refreshed session")
        return True

    async def handle_submit_outbound(
        self,
        registered: EngineId,
        message: FrameworkMessage,
        claimed_engine: EngineId,
    ) -> IpcResponse:
        forced = message.model_copy(
            update={
                "source": MessageSource(
                    agent_id=self.config.agent_id,
                    engine=registered,
                    vm_id=self.config.vm_id,
                )
            }
        )

        error = self.validator.validate(
            forced,
            registered_engine=registered,
            handshake_complete=self.session.handshake_complete,
            claimed_engine=claimed_engine,
            agent_id=self.config.agent_id,
            vm_id=self.config.vm_id,
        )
        if error is not None:
            return IpcResponse(accepted=False, error=error)

        if registered == EngineId.LOOP:
            return IpcResponse(accepted=True, message_id=forced.id)

        outbound = self.session.inject_session(forced)
        if not await self.bus.send(outbound):
            err = make_error_message(
                code=ErrorCode.NODE_VALIDATION_FAILED,
                layer=ErrorLayer.NODE,
                message="Outbound queue full",
                recoverable=True,
                agent_id=self.config.agent_id,
                vm_id=self.config.vm_id,
                correlation_id=forced.correlation_id,
                target_engine=registered,
                original_message_id=forced.id,
            )
            return IpcResponse(accepted=False, error=err)

        return IpcResponse(accepted=True, message_id=forced.id)

    async def deliver_inbound(self, message: FrameworkMessage) -> None:
        target = resolve_inbound_target(message)
        if target is None:
            if message.destination.type == DestinationType.CORVUS_SERVER:
                logger.warning("Invalid inbound corvus_server destination")
            return

        await self.ipc.push_inbound(target, message)


class _NodeIPC(IPCInterface):
    def __init__(self, node: CorvusNode) -> None:
        super().__init__(socket_path=str(node.config.ipc_socket_path))
        self._node = node

    async def _on_subscribe(self, engine: EngineId) -> IpcResponse:
        return IpcResponse(
            accepted=True,
            policy_snapshot=self._node.validator.engine_policy_subset(engine),
        )

    async def _on_health_check(self) -> IpcResponse:
        expires = None
        if self._node.session.session_expires_at:
            expires = self._node.session.session_expires_at.isoformat()
        return IpcResponse(
            status="ok",
            handshake_complete=self._node.session.handshake_complete,
            session_expires_at=expires,
        )

    async def _on_submit_outbound(
        self,
        registered: EngineId,
        message: FrameworkMessage,
        claimed_engine: EngineId,
    ) -> IpcResponse:
        return await self._node.handle_submit_outbound(registered, message, claimed_engine)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Corvus Node daemon")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))

    node = CorvusNode()
    try:
        asyncio.run(node.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

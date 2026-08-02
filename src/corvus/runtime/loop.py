"""Agent Loop state machine."""

from __future__ import annotations

import asyncio
import logging
import signal
from uuid import uuid4

from corvus.protocol.models import EngineId
from corvus.runtime.config import RunMode, RuntimeConfig, load_config, resolve_manifest_hash
from corvus.runtime.coordinator import TERMINAL_PHASES, Coordinator, TurnPhase
from corvus.runtime.ipc_client import NodeIpcClient

logger = logging.getLogger(__name__)

REQUIRED_ENGINES = frozenset({"engine2", "engine3"})


class AgentLoop:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or load_config()
        self.run_mode = self.config.run_mode
        self.ipc = NodeIpcClient(
            str(self.config.ipc_socket_path),
            EngineId.LOOP,
            manifest_hash=resolve_manifest_hash(self.config),
            connect_timeout=self.config.ipc_connect_timeout,
        )
        self.coordinator = Coordinator(self.config.coordinator_path)
        self._stop = asyncio.Event()

    async def run(self) -> bool:
        """Run one turn. Returns True if turn completed successfully."""
        await self.ipc.connect()
        self.coordinator.set_phase(TurnPhase.INIT)

        if not await self.ipc.wait_handshake():
            logger.critical("Agent Loop: handshake timeout")
            return False

        logger.info("Agent Loop: INIT -> RECEIVE")
        self.coordinator.set_phase(TurnPhase.RECEIVE)

        ok, missing = await self.coordinator.await_engines_ready(REQUIRED_ENGINES, timeout=30.0)
        if not ok:
            logger.error("Agent Loop: engines not ready, missing: %s", sorted(missing))
            return False

        turn_id = uuid4()
        logger.info("Agent Loop: RECEIVE -> DISPATCH (turn=%s)", turn_id)
        self.coordinator.set_phase(TurnPhase.DISPATCH, correlation_id=str(turn_id))

        terminal = await self.coordinator.await_phase_in(
            TERMINAL_PHASES, timeout=self.config.turn_timeout_seconds
        )
        if terminal is None:
            logger.error("Agent Loop: turn timeout; aborting")
            self.coordinator.abort("loop_turn_timeout", correlation_id=str(turn_id))
            return False
        if terminal == TurnPhase.ABORTED:
            logger.error(
                "Agent Loop: turn aborted (%s)",
                self.coordinator.read().get("abort_reason"),
            )
            return False

        logger.info("Agent Loop: turn DONE")
        if self.run_mode == RunMode.DAEMON:
            try:
                await self._stop.wait()
            finally:
                await self.ipc.close()
        else:
            await self.ipc.close()
        return True

    def request_stop(self) -> None:
        self._stop.set()


def _install_signal_handlers(loop: AgentLoop) -> None:
    def _handler(*_args: object) -> None:
        loop.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.request_stop())


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Corvus Agent Loop")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_const", const=RunMode.ONCE, dest="run_mode")
    mode.add_argument("--daemon", action="store_const", const=RunMode.DAEMON, dest="run_mode")
    parser.set_defaults(run_mode=RunMode.ONCE)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))

    agent_loop = AgentLoop(load_config(run_mode=args.run_mode))

    async def _run() -> bool:
        _install_signal_handlers(agent_loop)
        return await agent_loop.run()

    try:
        success = asyncio.run(_run())
        raise SystemExit(0 if success else 1)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

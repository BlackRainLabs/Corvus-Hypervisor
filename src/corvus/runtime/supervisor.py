"""In-process runtime supervisor for development."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from corvus.runtime.config import RunMode, RuntimeConfig, load_config
from corvus.runtime.engines.engine1 import ToolsEngine
from corvus.runtime.engines.engine2 import GatewayEngine
from corvus.runtime.engines.engine3 import LlmEngine
from corvus.runtime.engines.engine4 import MemoryEngine
from corvus.runtime.ipc_client import wait_for_socket
from corvus.runtime.loop import AgentLoop
from corvus.server.bootstrap import TEST_MANIFEST_HASH

logger = logging.getLogger(__name__)


def apply_dev_defaults() -> None:
    """Set shared temp paths when env is unset (dev convenience)."""
    if "CORVUS_NODE_SOCK" not in os.environ:
        os.environ["CORVUS_NODE_SOCK"] = "/tmp/corvus-node.sock"
    if "CORVUS_COORDINATOR_PATH" not in os.environ:
        os.environ["CORVUS_COORDINATOR_PATH"] = "/tmp/corvus-coordinator.json"
    if "CORVUS_MANIFEST_HASH" not in os.environ:
        os.environ["CORVUS_MANIFEST_HASH"] = TEST_MANIFEST_HASH


def build_config(run_mode: RunMode) -> RuntimeConfig:
    apply_dev_defaults()
    return load_config(run_mode=run_mode)


async def run_supervisor(*, run_mode: RunMode, all_engines: bool) -> bool:
    apply_dev_defaults()
    config = build_config(run_mode)
    try:
        await wait_for_socket(config.ipc_socket_path, timeout=config.ipc_connect_timeout)
    except RuntimeError:
        logger.error("Node IPC socket not available at %s", config.ipc_socket_path)
        return False

    loop = AgentLoop(config)
    engines: list = [GatewayEngine(config), LlmEngine(config)]
    if all_engines:
        engines = [
            ToolsEngine(config),
            GatewayEngine(config),
            LlmEngine(config),
            MemoryEngine(config),
        ]

    stop = asyncio.Event()

    def _stop_all(*_args: object) -> None:
        stop.set()
        loop.request_stop()
        for e in engines:
            e.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, _stop_all)
        except (NotImplementedError, RuntimeError):
            pass

    if run_mode == RunMode.ONCE:
        # The loop is authoritative: it resolves the turn to DONE or ABORTED (or
        # times out). Once it returns we stop the engines and, after a short grace
        # window for in-flight IPC, cancel any stragglers so a stalled engine can
        # never hang the --once runtime (critical for concurrent multi-agent runs).
        loop_task = asyncio.create_task(loop.run())
        engine_tasks = [asyncio.create_task(e.run()) for e in engines]
        try:
            loop_result: object = await loop_task
        except Exception as exc:  # noqa: BLE001 - surfaced as failed run below
            loop_result = exc

        for e in engines:
            e.request_stop()
        if engine_tasks:
            _, pending = await asyncio.wait(engine_tasks, timeout=5.0)
            for t in pending:
                t.cancel()
            await asyncio.gather(*engine_tasks, return_exceptions=True)

        if isinstance(loop_result, Exception):
            logger.error("loop failed: %s", loop_result)
            return False
        return bool(loop_result)

    tasks = [
        asyncio.create_task(loop.run()),
        *[asyncio.create_task(e.run()) for e in engines],
    ]
    await stop.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Corvus runtime supervisor")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_const", const=RunMode.ONCE, dest="run_mode")
    mode.add_argument("--daemon", action="store_const", const=RunMode.DAEMON, dest="run_mode")
    parser.set_defaults(run_mode=RunMode.ONCE)
    parser.add_argument(
        "--all-engines",
        action="store_true",
        help="Include engine1 and engine4 (engine4 required for memory turn validation)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))

    try:
        success = asyncio.run(
            run_supervisor(run_mode=args.run_mode, all_engines=args.all_engines)
        )
        raise SystemExit(0 if success else 1)
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

"""Engine CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from corvus.protocol.models import EngineId
from corvus.runtime.config import RunMode, load_config
from corvus.runtime.engines.engine1 import ToolsEngine
from corvus.runtime.engines.engine2 import GatewayEngine
from corvus.runtime.engines.engine3 import LlmEngine
from corvus.runtime.engines.engine4 import MemoryEngine

ENGINES = {
    EngineId.ENGINE1: ToolsEngine,
    EngineId.ENGINE2: GatewayEngine,
    EngineId.ENGINE3: LlmEngine,
    EngineId.ENGINE4: MemoryEngine,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Corvus engine process")
    parser.add_argument(
        "--engine",
        required=True,
        choices=["engine1", "engine2", "engine3", "engine4"],
    )
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

    cls = ENGINES[EngineId(args.engine)]
    engine = cls(load_config(run_mode=args.run_mode))

    async def _run() -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, engine.request_stop)
            except (NotImplementedError, RuntimeError):
                pass
        await engine.run()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

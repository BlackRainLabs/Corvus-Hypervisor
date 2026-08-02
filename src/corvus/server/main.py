"""Corvus Server entry point."""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from corvus.management.api import create_app
from corvus.server.bootstrap import AppContext
from corvus.server.config import load_config
from corvus.server.logging_config import configure_logging
from corvus.server.vsock import TransportGateway

configure_logging()
logger = logging.getLogger("corvus.server")


async def run_server() -> None:
    config = load_config()
    ctx = AppContext(config)
    await ctx.startup()

    gateway = TransportGateway(
        config,
        ctx.handle_message,
        ctx.sessions.unbind_connection,
        transport=ctx.transport,
    )
    await gateway.start()
    logger.info("Transport listening on %s", gateway.listen_target)
    logger.info("Management API on http://%s:%s", config.mgmt_host, config.mgmt_port)
    if config.ui_enabled:
        ui_prefix = config.ui_path_prefix.rstrip("/") or "/ui"
        logger.info(
            "Operator Console on http://%s:%s%s",
            config.mgmt_host,
            config.mgmt_port,
            ui_prefix,
        )

    mgmt_app = create_app(ctx)
    mgmt_server = uvicorn.Server(
        uvicorn.Config(mgmt_app, host=config.mgmt_host, port=config.mgmt_port, log_level="info")
    )

    async def serve_transport() -> None:
        assert gateway._server is not None
        async with gateway._server:
            await gateway._server.serve_forever()

    async def serve_management() -> None:
        await mgmt_server.serve()

    try:
        await asyncio.gather(serve_transport(), serve_management())
    finally:
        await gateway.stop()
        await ctx.shutdown()


def main() -> None:
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

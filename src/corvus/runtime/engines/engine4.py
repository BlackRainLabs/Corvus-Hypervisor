"""Engine 4 — Memory client."""

from __future__ import annotations

import logging
import os
from uuid import UUID, uuid4

from corvus.protocol.models import EngineId
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.base import BaseEngine
from corvus.runtime.memory_client import (
    MemoryOpResult,
    build_memory_delete,
    build_memory_grant_request,
    build_memory_query_key,
    build_memory_write,
    is_elevation_required,
    parse_memory_response,
)

logger = logging.getLogger(__name__)


class MemoryEngine(BaseEngine):
    engine_id = EngineId.ENGINE4

    async def serve(self) -> None:
        coord = Coordinator(self.config.coordinator_path)
        self.ipc.set_inbound_handler(self._on_inbound)
        try:
            if not await coord.await_phase(TurnPhase.COLLECT, timeout=60.0):
                logger.warning("engine4: collect phase timeout")
                return

            turn_id = UUID(coord.read().get("correlation_id", str(uuid4())))
            key = f"turn-{turn_id}"
            content = f"Engine4 memory snapshot for {turn_id}"
            logger.info("engine4 memory for turn %s", turn_id)

            write_msg = build_memory_write(
                self.config.agent_id,
                self.config.vm_id,
                turn_id,
                key=key,
                content=content,
            )
            write_in = await self.ipc.submit_and_wait(write_msg)
            write_result = parse_memory_response(write_in)
            if not write_result.ok:
                await self._handle_memory_failure(
                    coord,
                    turn_id,
                    write_result,
                    target_agent_id=self.config.agent_id,
                )
                return

            query_msg = build_memory_query_key(
                self.config.agent_id,
                self.config.vm_id,
                turn_id,
                key=key,
            )
            query_in = await self.ipc.submit_and_wait(query_msg)
            query_result = parse_memory_response(query_in)
            if not query_result.ok:
                await self._handle_memory_failure(
                    coord,
                    turn_id,
                    query_result,
                    target_agent_id=self.config.agent_id,
                    pending_message=query_msg,
                )
                return

            query_content = None
            if query_result.records:
                query_content = query_result.records[0].get("content")

            coord.merge_fields(
                memory_write_record_id=write_result.record_id,
                memory_query_hit=bool(query_result.records),
                memory_query_content=query_content,
                memory_error=None,
            )

            if os.environ.get("CORVUS_ENGINE4_DELETE") == "1" and write_result.record_id:
                delete_msg = build_memory_delete(
                    self.config.agent_id,
                    self.config.vm_id,
                    turn_id,
                    record_id=write_result.record_id,
                )
                delete_in = await self.ipc.submit_and_wait(delete_msg)
                delete_result = parse_memory_response(delete_in)
                if not delete_result.ok:
                    logger.warning("engine4 delete failed: %s", delete_result.error)

            logger.info("engine4 memory complete for turn %s", turn_id)
        finally:
            self.ipc.set_inbound_handler(None)

    async def _on_inbound(self, message) -> None:
        from corvus.protocol.models import FrameworkMessage

        if not isinstance(message, FrameworkMessage):
            return
        coord = Coordinator(self.config.coordinator_path)
        if message.type == "memory:grant_created":
            coord.merge_fields(
                memory_grant_id=message.payload.get("grant_id"),
                memory_elevation_id=message.payload.get("elevation_id"),
                memory_replay_delivered=message.payload.get("replay_delivered"),
            )
            logger.info(
                "engine4 grant created elevation=%s grant=%s replay=%s",
                message.payload.get("elevation_id"),
                message.payload.get("grant_id"),
                message.payload.get("replay_delivered"),
            )
            return
        if message.type.endswith("_response") and message.payload.get("success"):
            result = parse_memory_response(message)
            if result.ok and result.records:
                coord.merge_fields(
                    memory_replay_hit=True,
                    memory_replay_content=result.records[0].get("content"),
                    memory_error=None,
                )

    async def _handle_memory_failure(
        self,
        coord: Coordinator,
        turn_id: UUID,
        result: MemoryOpResult,
        *,
        target_agent_id: str,
        namespace: str = "private",
        pending_message=None,
    ) -> None:
        logger.error("engine4 memory failed: %s (%s)", result.error, result.error_code)
        extra: dict[str, str | None] = {
            "memory_error": result.error or result.error_code,
        }
        if is_elevation_required(result):
            extra["memory_elevation_id"] = result.elevation_id
            extra["memory_error"] = "elevation_required"
            if target_agent_id != self.config.agent_id:
                await self._emit_grant_request(
                    turn_id,
                    target_agent_id,
                    namespace,
                    pending_replay=pending_message,
                )
        coord.merge_fields(**extra)

    async def _emit_grant_request(
        self,
        turn_id: UUID,
        target_agent_id: str,
        namespace: str,
        *,
        pending_replay=None,
    ) -> None:
        grant_req = build_memory_grant_request(
            self.config.agent_id,
            self.config.vm_id,
            turn_id,
            target_agent_id=target_agent_id,
            namespace=namespace,
            permissions=["read"],
            reason="Engine 4 cross-agent memory access",
            pending_replay=pending_replay,
        )
        await self.ipc.submit_and_wait(grant_req)
        logger.info(
            "engine4 emitted memory:grant_request for %s/%s",
            target_agent_id,
            namespace,
        )

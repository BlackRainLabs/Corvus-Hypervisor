"""Engine 1 — Tools & Skills (server-approved, VM-local execution)."""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID, uuid4

from corvus.protocol.models import EngineId
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.base import BaseEngine
from corvus.runtime.tool_client import (
    build_tool_call,
    build_tool_result,
    parse_tool_call_response,
    parse_tool_result_ack,
)
from corvus.tools.runner import ToolExecutionError, run_tool

logger = logging.getLogger(__name__)


class ToolsEngine(BaseEngine):
    engine_id = EngineId.ENGINE1

    async def serve(self) -> None:
        coord = Coordinator(self.config.coordinator_path)
        if not await coord.await_phase(TurnPhase.COLLECT, timeout=60.0):
            logger.warning("engine1: collect phase timeout")
            return

        turn_id = UUID(coord.read().get("correlation_id", str(uuid4())))
        logger.info("engine1 tool for turn %s", turn_id)

        # Bound the COLLECT loop: exit as soon as the turn leaves COLLECT (RESPOND /
        # DONE / ABORTED), on stop request, or when the turn deadline lapses. This
        # prevents a stalled turn from spinning Engine 1 forever (and hanging --once).
        deadline = asyncio.get_running_loop().time() + self.config.turn_timeout_seconds
        while (
            coord.get_phase() == TurnPhase.COLLECT
            and not self._stop.is_set()
            and asyncio.get_running_loop().time() < deadline
        ):
            batch = await coord.await_tool_batch_pending(timeout=1.0)
            if batch is None:
                continue

            batch_id = batch["batch_id"]
            results: list[dict] = []
            merge_fields: dict = {}
            for call in batch["calls"]:
                output = await self._run_tool(
                    turn_id,
                    tool_name=str(call.get("name", "")),
                    arguments=dict(call.get("arguments") or {}),
                )
                results.append(
                    {
                        "id": call.get("id"),
                        "name": call.get("name"),
                        "success": output is not None,
                        "result": output,
                    }
                )
                if output is not None and call.get("name") == "echo":
                    merge_fields["tool_echo_text"] = output.get("text")
                if output is not None and call.get("name") == "terminal":
                    merge_fields["tool_terminal_stdout"] = output.get("stdout")
                    merge_fields["tool_terminal_exit_code"] = output.get("exit_code")

            if merge_fields:
                coord.merge_fields(**merge_fields)
            if not coord.complete_tool_batch(batch_id, results):
                logger.error("engine1: failed to complete tool batch %s", batch_id)

        if coord.get_phase() == TurnPhase.COLLECT and not self._stop.is_set():
            logger.warning("engine1: COLLECT deadline reached without turn resolution")
        logger.info("engine1 tool complete")

    async def _run_tool(
        self,
        turn_id: UUID,
        *,
        tool_name: str,
        arguments: dict,
    ) -> dict | None:
        tool_call = build_tool_call(
            self.config.agent_id,
            self.config.vm_id,
            turn_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        approval_msg = await self.ipc.submit_and_wait(tool_call, timeout=30.0)
        approval = parse_tool_call_response(approval_msg)
        if not approval.ok or not approval.approved:
            logger.error(
                "tool_call not approved (%s): %s (%s)",
                tool_name,
                approval.error,
                approval.error_code,
            )
            return None

        started = time.monotonic()
        try:
            output = run_tool(tool_name, arguments)
            duration_ms = int((time.monotonic() - started) * 1000)
        except ToolExecutionError as exc:
            logger.error("tool execution failed (%s): %s", tool_name, exc)
            return None

        tool_result = build_tool_result(
            self.config.agent_id,
            self.config.vm_id,
            turn_id,
            tool_name=tool_name,
            request_correlation_id=tool_call.correlation_id,
            success=True,
            result=output,
            duration_ms=duration_ms,
        )
        result_ack = await self.ipc.submit_and_wait(tool_result, timeout=30.0)
        if not parse_tool_result_ack(result_ack).ok:
            logger.error("tool_result rejected (%s): %s", tool_name, result_ack.payload)
            return None
        return output

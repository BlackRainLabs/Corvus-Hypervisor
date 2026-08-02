"""Engine 3 — LLM / Inference with local tool loop."""

from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

from corvus.llm.tool_policy import parse_tool_call_arguments
from corvus.protocol.models import EngineId
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.base import BaseEngine
from corvus.runtime.llm_client import build_llm_request, collect_llm_stream, parse_llm_response
from corvus.runtime.tool_schemas import build_tools_schema

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


class LlmEngine(BaseEngine):
    engine_id = EngineId.ENGINE3

    async def serve(self) -> None:
        coord = Coordinator(self.config.coordinator_path)
        if not await coord.await_phase(TurnPhase.COLLECT, timeout=60.0):
            logger.warning("engine3: collect phase timeout")
            coord.abort("engine3_collect_timeout")
            return

        turn_id = UUID(coord.read().get("correlation_id", str(uuid4())))
        logger.info("engine3 llm for turn %s", turn_id)

        user_text = coord.read().get("user_text", "Hello from gateway")
        local_tools = list(self.config.llm_local_tools)
        tools_schema = build_tools_schema(local_tools) if local_tools else None
        messages: list[dict] = [{"role": "user", "content": str(user_text)}]
        response_text = ""

        for iteration in range(MAX_TOOL_ITERATIONS):
            use_stream = self.config.llm_stream
            llm_req = build_llm_request(
                self.config.agent_id,
                self.config.vm_id,
                turn_id,
                provider="stub",
                model="stub-v1",
                messages=messages,
                tools_schema=tools_schema,
                stream=use_stream,
            )
            if use_stream:
                result = await collect_llm_stream(self.ipc, llm_req, timeout=120.0)
            else:
                llm_resp = await self.ipc.submit_and_wait(llm_req, timeout=120.0)
                result = parse_llm_response(llm_resp)
            if not result.ok:
                logger.error("llm_request failed: %s (%s)", result.error, result.error_code)
                coord.abort("engine3_llm_failed", correlation_id=str(turn_id))
                return

            tool_calls = result.tool_calls or []
            if not tool_calls:
                response_text = result.content or ""
                break

            pending = []
            for call in tool_calls:
                fn = call.get("function") or {}
                pending.append(
                    {
                        "id": str(call.get("id", uuid4())),
                        "name": str(fn.get("name", "")),
                        "arguments": parse_tool_call_arguments(fn.get("arguments")),
                    }
                )

            batch_id = str(uuid4())
            coord.publish_tool_batch(batch_id, pending)
            tool_results = await coord.await_tool_batch_complete(batch_id, timeout=60.0)
            if tool_results is None:
                logger.error("engine3: tool batch timeout (%s)", batch_id)
                coord.abort("engine3_tool_batch_timeout", correlation_id=str(turn_id))
                return

            messages.append(
                {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": tool_calls,
                }
            )
            for entry in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry.get("id"),
                        "content": json.dumps(entry.get("result")),
                    }
                )
            logger.info("engine3 completed tool iteration %s", iteration + 1)
        else:
            logger.error("engine3: max tool iterations exceeded")
            coord.abort("engine3_max_tool_iterations", correlation_id=str(turn_id))
            return

        coord.set_phase(
            TurnPhase.RESPOND,
            correlation_id=str(turn_id),
            response_text=response_text,
        )
        logger.info("engine3 llm complete")

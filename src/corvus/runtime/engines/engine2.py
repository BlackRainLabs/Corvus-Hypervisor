"""Engine 2 — Gateway / Channels."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from corvus.protocol import (
    DestinationType,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSecurity,
    MessageSource,
    MessageTags,
    Scope,
    TriggeredBy,
)
from corvus.protocol.models import EngineId
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.base import BaseEngine

logger = logging.getLogger(__name__)


class GatewayEngine(BaseEngine):
    engine_id = EngineId.ENGINE2

    async def serve(self) -> None:
        coord = Coordinator(self.config.coordinator_path)
        if not await coord.await_phase(TurnPhase.DISPATCH, timeout=60.0):
            logger.warning("engine2: dispatch phase timeout")
            coord.abort("engine2_dispatch_timeout")
            return

        turn_id = UUID(coord.read().get("correlation_id", str(uuid4())))
        logger.info("engine2 starting turn %s", turn_id)

        uq = FrameworkMessage(
            source=MessageSource(
                agent_id=self.config.agent_id,
                engine=EngineId.ENGINE2,
                vm_id=self.config.vm_id,
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="user_query",
            correlation_id=turn_id,
            tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
            security=MessageSecurity(may_leave_vm=True),
            payload={
                "user_id": "test-user",
                "platform": "api",
                "channel_id": "default",
                "content": {"text": "Hello from gateway"},
            },
        )
        uq_ack = await self.ipc.submit_and_wait(uq)
        if not uq_ack.payload.get("success"):
            logger.error("user_query failed: %s", uq_ack.payload)
            coord.abort("engine2_user_query_failed", correlation_id=str(turn_id))
            return

        coord.set_phase(
            TurnPhase.COLLECT,
            correlation_id=str(turn_id),
            user_text="Hello from gateway",
        )
        reached = await coord.await_phase_in({TurnPhase.RESPOND, TurnPhase.ABORTED}, timeout=30.0)
        if reached != TurnPhase.RESPOND:
            if reached == TurnPhase.ABORTED:
                logger.error("engine2: turn aborted before respond (%s)",
                             coord.read().get("abort_reason"))
            else:
                logger.error("engine2: respond phase timeout")
                coord.abort("engine2_respond_timeout", correlation_id=str(turn_id))
            return

        response = FrameworkMessage(
            source=MessageSource(
                agent_id=self.config.agent_id,
                engine=EngineId.ENGINE2,
                vm_id=self.config.vm_id,
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="agent_response",
            correlation_id=uuid4(),
            tags=MessageTags(
                triggered_by=TriggeredBy.AGENT_INITIATED,
                origin_correlation_id=turn_id,
                scope=Scope.EXTERNAL,
            ),
            security=MessageSecurity(may_leave_vm=True),
            payload={
                "platform": "api",
                "channel_id": "default",
                "content": {"text": coord.read().get("response_text", "Acknowledged.")},
            },
        )
        ar_ack = await self.ipc.submit_and_wait(response)
        if ar_ack.payload.get("success"):
            coord.set_phase(TurnPhase.DONE, correlation_id=str(turn_id))
            logger.info("engine2 turn complete")
        else:
            logger.error("agent_response failed: %s", ar_ack.payload)
            coord.abort("engine2_agent_response_failed", correlation_id=str(turn_id))

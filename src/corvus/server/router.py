"""Star-topology message router."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from corvus.audit.store import AuditStore
from corvus.llm.service import LlmGatewayService
from corvus.memory.service import MemoryService
from corvus.policy.behavioral import BehavioralMonitor
from corvus.policy.engine import PolicyEngine
from corvus.policy.quota import QuotaService
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
    make_error_message,
)
from corvus.protocol.errors import ErrorCode, ErrorLayer
from corvus.server.correlation import CorrelationStore
from corvus.server.elevation_notify import notify_elevation_pending
from corvus.server.handshake import HandshakeHandler
from corvus.server.session import SessionManager
from corvus.server.transport import AgentTransport
from corvus.tools.service import ToolGatewayService

logger = logging.getLogger(__name__)


class MessageRouter:
    def __init__(
        self,
        sessions: SessionManager,
        handshake: HandshakeHandler,
        correlation: CorrelationStore,
        policy: PolicyEngine,
        audit: AuditStore,
        memory: MemoryService | None = None,
        llm: LlmGatewayService | None = None,
        tools: ToolGatewayService | None = None,
        behavioral: BehavioralMonitor | None = None,
        quotas: QuotaService | None = None,
        llm_tokens_daily_limit: int = 100_000,
        elevation_ttl_hours: int = 1,
        elevation_webhook_url: str | None = None,
        elevation_webhook_secret: str | None = None,
        transport: AgentTransport | None = None,
    ) -> None:
        self.sessions = sessions
        self.handshake = handshake
        self.correlation = correlation
        self.policy = policy
        self.audit = audit
        self.memory = memory
        self.llm = llm
        self.tools = tools
        self.behavioral = behavioral
        self.quotas = quotas
        self.llm_tokens_daily_limit = llm_tokens_daily_limit
        self.elevation_ttl_hours = elevation_ttl_hours
        self.elevation_webhook_url = elevation_webhook_url
        self.elevation_webhook_secret = elevation_webhook_secret
        self.transport = transport

    async def handle(
        self, message: FrameworkMessage, connection_id: int
    ) -> FrameworkMessage | None:
        await self.audit.log_message_hop(message, connection_id=connection_id)

        if message.type == "handshake" and message.message_class == MessageClass.SYSTEM:
            return await self.handshake.handle(message, connection_id)

        if message.type == "handshake" and message.message_class == MessageClass.RESPONSE:
            if message.payload.get("ack") and self.handshake.pending_replay is not None:
                await self.handshake.pending_replay.flush_for_vm(
                    message.source.agent_id, message.source.vm_id
                )
            return None

        session = await self.sessions.validate_connection(connection_id)
        if session is None:
            token = self.sessions.extract_session_token(message.payload)
            session = await self.sessions.validate_token(token)
        if session is None:
            return make_error_message(
                code=ErrorCode.SERVER_SESSION_INVALID,
                layer=ErrorLayer.SERVER,
                message="Missing or expired session token",
                recoverable=False,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                original_message_id=message.id,
            )

        if message.source.agent_id != session["agent_id"]:
            return make_error_message(
                code=ErrorCode.SERVER_SESSION_INVALID,
                layer=ErrorLayer.SERVER,
                message="Agent ID does not match session",
                recoverable=False,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                original_message_id=message.id,
            )

        if message.source.vm_id != session["vm_id"]:
            return make_error_message(
                code=ErrorCode.SERVER_SESSION_INVALID,
                layer=ErrorLayer.SERVER,
                message="VM ID does not match session",
                recoverable=False,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                original_message_id=message.id,
            )

        valid, error_code = await self.correlation.validate(message)
        if not valid:
            code = ErrorCode.SERVER_CORRELATION_INVALID
            if error_code == "SERVER_CORRELATION_EXPIRED":
                code = ErrorCode.SERVER_CORRELATION_EXPIRED
            return make_error_message(
                code=code,
                layer=ErrorLayer.SERVER,
                message=f"Correlation validation failed: {error_code}",
                recoverable=True,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                original_message_id=message.id,
            )

        if message.type == "user_query" and message.tags.triggered_by == TriggeredBy.USER_INPUT:
            await self.correlation.register_user_query(message)

        if self.behavioral is not None:
            await self.behavioral.record_message_hop(message)

        decision = await self.policy.evaluate(message, correlation_valid=valid)
        await self.audit.log_policy_decision(message, decision)

        if self.behavioral is not None and decision.policy_facts is not None:
            await self.behavioral.record_policy_outcome(
                message, decision, decision.policy_facts
            )

        if decision.decision == "deny":
            code = ErrorCode.SERVER_RBAC_DENIED
            if decision.effective_error_code == "SERVER_QUOTA_EXCEEDED":
                code = ErrorCode.SERVER_QUOTA_EXCEEDED
            return make_error_message(
                code=code,
                layer=ErrorLayer.POLICY,
                message="Policy denied request",
                recoverable=True,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                details={"matched_rules": [m.rule_id for m in decision.matched_rules]},
                original_message_id=message.id,
            )

        if decision.decision == "elevate":
            context = {
                "matched_rules": [m.rule_id for m in decision.matched_rules],
                "metadata": decision.metadata,
            }
            pending_replay = message.payload.get("pending_replay")
            if pending_replay:
                context["pending_replay"] = pending_replay
            expires_at = (
                datetime.now(UTC) + timedelta(hours=self.elevation_ttl_hours)
            ).isoformat()
            elevation_id = await self.audit.db.create_elevation(
                message=message.model_dump(mode="json"),
                context=context,
                expires_at=expires_at,
            )
            decision.metadata["elevation_id"] = elevation_id
            rule_ids = [m.rule_id for m in decision.matched_rules]
            await self.audit.log_security_event(
                event_type="elevation_pending",
                correlation_id=str(message.correlation_id),
                agent_id=message.source.agent_id,
                message_id=str(message.id),
                decision="elevate",
                matched_rules=rule_ids,
                details={
                    "elevation_id": elevation_id,
                    "user_id": decision.metadata.get("user_id"),
                    "rule_ids": rule_ids,
                    "expires_at": expires_at,
                },
            )
            notify_elevation_pending(
                self.elevation_webhook_url,
                elevation_id=elevation_id,
                agent_id=message.source.agent_id,
                expires_at=expires_at,
                rule_ids=rule_ids,
                user_id=decision.metadata.get("user_id"),
                webhook_secret=self.elevation_webhook_secret,
            )
            return make_error_message(
                code=ErrorCode.SERVER_ELEVATION_REQUIRED,
                layer=ErrorLayer.POLICY,
                message="Policy requires elevation",
                recoverable=True,
                agent_id=message.source.agent_id,
                vm_id=message.source.vm_id,
                correlation_id=message.correlation_id,
                target_engine=EngineId(message.source.engine),
                details={"elevation_id": elevation_id},
                original_message_id=message.id,
            )

        if message.type.startswith("memory:") and self.memory is not None:
            result = await self.memory.handle(
                message,
                grant_id=decision.metadata.get("grant_id"),
            )
            if (
                result.success
                and message.type == "memory:write"
                and self.quotas is not None
            ):
                await self.quotas.increment_memory_write(message.source.agent_id)
            return self._memory_response(message, result.model_dump(mode="json"))

        if message.type == "llm_request" and self.llm is not None:
            user_id = decision.metadata.get("user_id")
            if message.payload.get("stream"):
                return await self._handle_llm_stream(message, user_id=user_id)
            result = await self.llm.handle(message, user_id=user_id)
            if result.success and self.quotas is not None:
                await self.quotas.increment_llm_tokens(
                    user_id,
                    result.total_tokens,
                    daily_limit=self.llm_tokens_daily_limit,
                )
            return self._llm_response(message, result.to_payload())

        if message.type == "tool_call" and self.tools is not None:
            rule_ids = [m.rule_id for m in decision.matched_rules]
            result = await self.tools.handle_call(
                message,
                user_id=decision.metadata.get("user_id"),
                matched_rules=rule_ids,
            )
            if result.approved and self.behavioral is not None:
                await self.behavioral.record_approved_tool_call(message)
            return self._tool_call_response(message, result.to_payload())

        if message.type == "tool_result" and self.tools is not None:
            rule_ids = [m.rule_id for m in decision.matched_rules]
            result = await self.tools.handle_result(
                message,
                user_id=decision.metadata.get("user_id"),
                matched_rules=rule_ids,
            )
            return self._tool_result_response(message, result.to_payload())

        return self._success_response(message)

    async def _handle_llm_stream(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
    ) -> FrameworkMessage:
        prepared, error = await self.llm.prepare(message, user_id=user_id)
        if error is not None:
            return self._llm_stream_start(message, error.to_payload())

        assert prepared is not None
        if self.transport is None:
            failure = {
                "success": False,
                "provider": prepared.provider_id,
                "model": prepared.payload.model,
                "error": "streaming requires active agent transport",
                "error_code": "LLM_STREAM_UNAVAILABLE",
            }
            return self._llm_stream_start(message, failure)

        asyncio.create_task(
            self._run_llm_stream(message, user_id=user_id, prepared=prepared),
            name=f"llm-stream-{message.correlation_id}",
        )
        return self._llm_stream_start(
            message,
            {
                "success": True,
                "provider": prepared.provider_id,
                "model": prepared.payload.model,
            },
        )

    async def _run_llm_stream(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
        prepared,
    ) -> None:
        agent_id = message.source.agent_id
        vm_id = message.source.vm_id
        started = time.monotonic()
        completion = None
        try:
            async for chunk in self.llm.iter_stream(prepared):
                if chunk.is_terminal:
                    completion = chunk.completion
                    continue
                if not chunk.delta:
                    continue
                chunk_msg = self._llm_stream_chunk(
                    message,
                    {"index": chunk.index, "delta": chunk.delta},
                )
                if not await self.transport.deliver(agent_id, vm_id, chunk_msg):
                    logger.warning(
                        "llm stream chunk delivery failed for agent %s vm %s", agent_id, vm_id
                    )
                    return
        except Exception:
            logger.exception("llm stream failed for agent %s vm %s", agent_id, vm_id)
            failure = {
                "success": False,
                "provider": prepared.provider_id,
                "model": prepared.payload.model,
                "error": "stream provider error",
                "error_code": "LLM_PROVIDER_ERROR",
            }
            await self.transport.deliver(agent_id, vm_id, self._llm_response(message, failure))
            return

        if completion is None:
            failure = {
                "success": False,
                "provider": prepared.provider_id,
                "model": prepared.payload.model,
                "error": "stream ended without completion",
                "error_code": "LLM_PROVIDER_ERROR",
            }
            await self.transport.deliver(agent_id, vm_id, self._llm_response(message, failure))
            return

        duration_ms = int((time.monotonic() - started) * 1000)
        result = await self.llm.finalize_stream(
            prepared,
            user_id=user_id,
            completion=completion,
            duration_ms=duration_ms,
        )
        if result.success and self.quotas is not None:
            await self.quotas.increment_llm_tokens(
                user_id,
                result.total_tokens,
                daily_limit=self.llm_tokens_daily_limit,
            )
        await self.transport.deliver(
            agent_id, vm_id, self._llm_response(message, result.to_payload())
        )

    def _llm_stream_start(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type="llm_stream_start",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.LLM_RESULT,
                origin_correlation_id=message.tags.origin_correlation_id
                or message.correlation_id,
            ),
            payload=payload,
        )

    def _llm_stream_chunk(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.EVENT,
            type="llm_stream_chunk",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.LLM_RESULT,
                origin_correlation_id=message.tags.origin_correlation_id
                or message.correlation_id,
            ),
            payload=payload,
        )

    def _memory_response(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type=f"{message.type}_response",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.MEMORY_RESULT,
                origin_correlation_id=message.correlation_id,
            ),
            payload=payload,
        )

    def _llm_response(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type="llm_response",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.LLM_RESULT,
                origin_correlation_id=message.tags.origin_correlation_id
                or message.correlation_id,
            ),
            payload=payload,
        )

    def _tool_call_response(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type="tool_call_response",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.TOOL_APPROVAL,
                origin_correlation_id=message.tags.origin_correlation_id
                or message.correlation_id,
            ),
            payload=payload,
        )

    def _tool_result_response(self, message: FrameworkMessage, payload: dict) -> FrameworkMessage:
        payload["original_type"] = message.type
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type="tool_result_ack",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.TOOL_RESULT,
                origin_correlation_id=message.tags.origin_correlation_id
                or message.correlation_id,
            ),
            payload=payload,
        )

    def _success_response(self, message: FrameworkMessage) -> FrameworkMessage:
        return FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server",
                engine=EngineId.CORVUS_NODE,
                vm_id="server",
            ),
            destination=MessageDestination(
                type=DestinationType.ENGINE,
                target=str(message.source.engine),
            ),
            message_class=MessageClass.RESPONSE,
            type=f"{message.type}_ack",
            correlation_id=message.correlation_id,
            tags=MessageTags(
                triggered_by=TriggeredBy.SYSTEM,
                origin_correlation_id=message.correlation_id,
            ),
            payload={
                "success": True,
                "received_at": datetime.now(UTC).isoformat(),
                "original_type": message.type,
            },
        )

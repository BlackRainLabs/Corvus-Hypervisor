"""Server-side tool approval gateway — execution stays in the agent VM."""

from __future__ import annotations

from pydantic import ValidationError

from corvus.audit.store import AuditStore
from corvus.protocol import FrameworkMessage
from corvus.server.db import Database
from corvus.tools.models import (
    ToolApprovalResult,
    ToolCallPayload,
    ToolResultAck,
    ToolResultPayload,
)


class ToolGatewayService:
    """Approve or deny tool_call requests; audit tool_result. Never executes tools."""

    def __init__(self, db: Database, audit: AuditStore) -> None:
        self.db = db
        self.audit = audit

    async def handle_call(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
        matched_rules: list[str],
    ) -> ToolApprovalResult:
        try:
            payload = ToolCallPayload.model_validate(message.payload)
        except ValidationError as exc:
            return await self._deny_call(
                message,
                tool_name=str(message.payload.get("tool_name", "unknown")),
                user_id=user_id,
                code="TOOL_PAYLOAD_INVALID",
                reason=str(exc),
            )

        agent = await self.db.get_agent(message.source.agent_id)
        if agent is None:
            return await self._deny_call(
                message,
                tool_name=payload.tool_name,
                user_id=user_id,
                code="TOOL_AGENT_NOT_FOUND",
                reason="agent not found",
            )

        allowed_tools = set(
            agent["manifest"].get("engines", {}).get("engine1", {}).get("tools", [])
        )
        if payload.tool_name not in allowed_tools:
            return await self._deny_call(
                message,
                tool_name=payload.tool_name,
                user_id=user_id,
                code="TOOL_NOT_ALLOWED",
                reason="tool not allowed by agent manifest",
            )

        await self.audit.log_tool_operation(
            message,
            phase="call_approved",
            tool_name=payload.tool_name,
            user_id=user_id,
            result="allow",
            reason="manifest and policy allow",
            matched_rules=matched_rules,
            duration_ms=0,
            success=None,
        )
        return ToolApprovalResult(
            success=True,
            approved=True,
            tool_name=payload.tool_name,
        )

    async def handle_result(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
        matched_rules: list[str],
    ) -> ToolResultAck:
        try:
            payload = ToolResultPayload.model_validate(message.payload)
        except ValidationError as exc:
            return await self._deny_result(
                message,
                tool_name=str(message.payload.get("tool_name", "unknown")),
                user_id=user_id,
                code="TOOL_RESULT_INVALID",
                reason=str(exc),
            )

        agent = await self.db.get_agent(message.source.agent_id)
        if agent is None:
            return ToolResultAck(
                success=False,
                tool_name=payload.tool_name,
                error="agent not found",
                error_code="TOOL_AGENT_NOT_FOUND",
            )

        allowed_tools = set(
            agent["manifest"].get("engines", {}).get("engine1", {}).get("tools", [])
        )
        if payload.tool_name not in allowed_tools:
            return ToolResultAck(
                success=False,
                tool_name=payload.tool_name,
                error="tool not allowed by agent manifest",
                error_code="TOOL_NOT_ALLOWED",
            )

        await self.audit.log_tool_operation(
            message,
            phase="result",
            tool_name=payload.tool_name,
            user_id=user_id,
            result="allow" if payload.success else "deny",
            reason=payload.error or "tool completed",
            matched_rules=matched_rules,
            duration_ms=payload.duration_ms,
            success=payload.success,
        )
        return ToolResultAck(success=True, tool_name=payload.tool_name)

    async def _deny_call(
        self,
        message: FrameworkMessage,
        *,
        tool_name: str,
        user_id: str | None,
        code: str,
        reason: str,
    ) -> ToolApprovalResult:
        await self.audit.log_tool_operation(
            message,
            phase="call_denied",
            tool_name=tool_name,
            user_id=user_id,
            result="deny",
            reason=reason,
            matched_rules=[],
            duration_ms=0,
            success=False,
        )
        return ToolApprovalResult(
            success=False,
            approved=False,
            tool_name=tool_name,
            error=reason,
            error_code=code,
        )

    async def _deny_result(
        self,
        message: FrameworkMessage,
        *,
        tool_name: str,
        user_id: str | None,
        code: str,
        reason: str,
    ) -> ToolResultAck:
        await self.audit.log_tool_operation(
            message,
            phase="result_rejected",
            tool_name=tool_name,
            user_id=user_id,
            result="deny",
            reason=reason,
            matched_rules=[],
            duration_ms=0,
            success=False,
        )
        return ToolResultAck(
            success=False,
            tool_name=tool_name,
            error=reason,
            error_code=code,
        )

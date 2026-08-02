"""Policy fact gathering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from corvus.policy.grants import GrantEngine, permission_for_message_type
from corvus.policy.identity import IdentityResolver
from corvus.policy.quota import QuotaService
from corvus.protocol import FrameworkMessage
from corvus.server.correlation import CorrelationStore
from corvus.server.db import Database

if TYPE_CHECKING:
    from corvus.policy.behavioral import BehavioralMonitor


@dataclass
class PolicyFacts:
    user_id: str | None = None
    role: str = "researcher"
    agent_id: str = ""
    engine: str = ""
    message_type: str = ""
    correlation_chain_valid: bool = True
    triggered_by: str = ""
    scope: str = "local"
    has_valid_grant: bool = False
    grant_id: str | None = None
    grant_reason: str | None = None
    provider: str | None = None
    model: str | None = None
    groups: list[str] = field(default_factory=list)
    privileges: list[str] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=list)
    target_agent_id: str | None = None
    identity_channel: str = "unknown"
    identity_alias: str | None = None
    identity_verified: bool = False
    auth_method: str = "none"
    identity_reason: str = "unresolved"
    quota_key: str | None = None
    quota_remaining_after: int | None = None
    quota_would_exceed: bool = False
    quota_would_consume_tokens: int | None = None
    tool_name: str | None = None
    command: str | None = None
    tool_risk_level: str = "low"
    dangerous_action: bool = False
    behavioral_signals: dict[str, Any] = field(default_factory=dict)
    tool_execution_mode: str = "local"
    provider_tools_requested: bool = False


class FactGatherer:
    def __init__(
        self,
        db: Database,
        correlation: CorrelationStore,
        identity: IdentityResolver | None = None,
        grants: GrantEngine | None = None,
        quotas: QuotaService | None = None,
        behavioral: BehavioralMonitor | None = None,
    ) -> None:
        self.db = db
        self.correlation = correlation
        self.identity = identity or IdentityResolver(db)
        self.grants = grants or GrantEngine(db)
        self.quotas = quotas or QuotaService(db)
        self.behavioral = behavioral

    async def gather(
        self,
        message: FrameworkMessage,
        *,
        correlation_valid: bool,
        override_context: dict[str, Any] | None = None,
    ) -> PolicyFacts:
        identity = await self.identity.resolve(message.payload, override_context)
        user_id = await self.correlation.get_user_id_for_message(message) or identity.user_id
        role = identity.role if identity.user_id else "anonymous"
        groups = list(identity.groups)
        privileges = list(identity.privileges)
        allowed_agents = list(identity.allowed_agents)

        if user_id:
            user = await self.db.get_user(user_id)
            if user:
                role = user.get("role", role)
                groups = list(user.get("groups", groups))
                privileges = list(user.get("privileges", privileges))
                allowed_agents = list(user.get("allowed_agents", allowed_agents))
            elif override_context and override_context.get("user_id"):
                role = str(override_context.get("role", role))

        if override_context:
            if "user_id" in override_context:
                user_id = str(override_context["user_id"])
            if "role" in override_context:
                role = str(override_context["role"])
            if "groups" in override_context:
                groups = [str(group) for group in override_context["groups"]]
            if "privileges" in override_context:
                privileges = [str(privilege) for privilege in override_context["privileges"]]
            if "allowed_agents" in override_context:
                allowed_agents = [str(agent) for agent in override_context["allowed_agents"]]
            if "correlation_chain_valid" in override_context:
                correlation_valid = bool(override_context["correlation_chain_valid"])
            if (
                "has_valid_grant" in override_context
                and override_context["has_valid_grant"] is not None
            ):
                grant_valid = bool(override_context["has_valid_grant"])
            else:
                grant_result = await self._evaluate_grant(message)
                grant_valid = bool(grant_result["valid"])
        else:
            grant_result = await self._evaluate_grant(message)
            grant_valid = bool(grant_result["valid"])
        if override_context and "has_valid_grant" in override_context:
            grant_result = {
                "valid": grant_valid,
                "grant_id": override_context.get("grant_id"),
                "reason": "override",
            }

        provider = message.payload.get("provider")
        model = message.payload.get("model")
        target_agent_id = (
            message.payload.get("target_agent_id")
            or message.payload.get("target_agent")
            or message.payload.get("agent_id")
        )
        quota = await self._evaluate_quota(message, user_id, override_context)
        action = self._classify_action(message)
        tool_execution_mode, provider_tools_requested = await self._tool_execution_context(
            message,
            override_context,
        )
        if override_context and "behavioral_signals" in override_context:
            behavioral_signals = dict(override_context["behavioral_signals"])
        elif self.behavioral is not None:
            behavioral_signals = await self.behavioral.signals_for(message.source.agent_id)
        else:
            behavioral_signals = {}

        return PolicyFacts(
            user_id=user_id,
            role=role,
            agent_id=message.source.agent_id,
            engine=str(message.source.engine),
            message_type=message.type,
            correlation_chain_valid=correlation_valid,
            triggered_by=str(message.tags.triggered_by),
            scope=str(message.tags.scope),
            has_valid_grant=grant_valid,
            grant_id=grant_result.get("grant_id"),
            grant_reason=grant_result.get("reason"),
            provider=str(provider) if provider else None,
            model=str(model) if model else None,
            groups=groups,
            privileges=privileges,
            allowed_agents=allowed_agents,
            target_agent_id=str(target_agent_id) if target_agent_id else None,
            identity_channel=identity.identity_channel,
            identity_alias=identity.identity_alias,
            identity_verified=identity.identity_verified,
            auth_method=identity.auth_method,
            identity_reason=identity.reason,
            quota_key=quota.get("quota_key"),
            quota_remaining_after=quota.get("remaining_after"),
            quota_would_exceed=bool(quota.get("would_exceed", False)),
            quota_would_consume_tokens=quota.get("would_consume_tokens"),
            tool_name=action["tool_name"],
            command=action["command"],
            tool_risk_level=action["tool_risk_level"],
            dangerous_action=action["dangerous_action"],
            behavioral_signals=behavioral_signals,
            tool_execution_mode=tool_execution_mode,
            provider_tools_requested=provider_tools_requested,
        )

    async def _tool_execution_context(
        self,
        message: FrameworkMessage,
        override_context: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        if override_context and "tool_execution_mode" in override_context:
            mode = str(override_context["tool_execution_mode"])
            provider_tools_requested = bool(
                override_context.get("provider_tools_requested")
                or message.payload.get("provider_tools_requested")
            )
            return mode, provider_tools_requested
        if message.type != "llm_request":
            return "local", False
        agent = await self.db.get_agent(message.source.agent_id)
        if agent is None:
            return "local", False
        engine3 = agent["manifest"].get("engines", {}).get("engine3", {})
        mode = str(engine3.get("tool_execution_mode", "local"))
        provider_tools_requested = bool(message.payload.get("provider_tools_requested"))
        return mode, provider_tools_requested

    async def _evaluate_grant(self, message: FrameworkMessage) -> dict[str, Any]:
        if not message.type.startswith("memory:"):
            return {"valid": False, "grant_id": None, "reason": "not_memory_action"}
        namespace = str(message.payload.get("namespace", "private"))
        target_agent_id = str(
            message.payload.get("target_agent_id")
            or message.payload.get("target_agent")
            or message.source.agent_id
        )
        return await self.grants.evaluate(
            subject_agent=message.source.agent_id,
            target_agent=target_agent_id,
            namespace=namespace,
            permission=permission_for_message_type(message.type),
            grant_id=message.payload.get("grant_id"),
        )

    async def _evaluate_quota(
        self,
        message: FrameworkMessage,
        user_id: str | None,
        override_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = override_context or {}
        daily_limit = context.get("daily_token_limit")
        requested = int(
            context.get("tokens")
            or message.payload.get("tokens")
            or message.payload.get("estimated_tokens")
            or 0
        )
        key = f"user:{user_id or 'anonymous'}:llm_tokens:daily"
        return await self.quotas.evaluate(key=key, limit=daily_limit, requested=requested)

    def _classify_action(self, message: FrameworkMessage) -> dict[str, Any]:
        tool_name = message.payload.get("tool_name") or message.payload.get("tool")
        command = (
            message.payload.get("command")
            or message.payload.get("cmd")
            or message.payload.get("args", {}).get("command")
        )
        risk_level = str(message.payload.get("risk_level", "low"))
        requires_elevation = bool(message.payload.get("requires_elevation", False))
        dangerous = requires_elevation or risk_level in {"high", "critical"}
        if command:
            dangerous = dangerous or self._looks_dangerous(str(command))
        if tool_name:
            lowered = str(tool_name).lower()
            dangerous = dangerous or lowered in {"shell", "sudo", "filesystem_write"}
        return {
            "tool_name": str(tool_name) if tool_name else None,
            "command": str(command) if command else None,
            "tool_risk_level": risk_level,
            "dangerous_action": dangerous,
        }

    @staticmethod
    def _looks_dangerous(command: str) -> bool:
        lowered = command.lower()
        patterns = (
            "rm -rf",
            "sudo ",
            "mkfs",
            "dd if=",
            "chmod 777",
            "chown ",
            "curl ",
            "wget ",
            "| sh",
            "| bash",
            "shutdown",
            "reboot",
            "systemctl",
            "iptables",
            "mount ",
            "umount ",
            "kill -9",
        )
        return any(pattern in lowered for pattern in patterns)

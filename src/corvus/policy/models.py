"""Typed RBAC rule and identity contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Pattern = str | list[str]


class RuleSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Pattern | None = None
    agent_id: Pattern | None = None
    user_id: Pattern | None = None
    groups: Pattern | None = None
    identity_channel: Pattern | None = None
    auth_method: Pattern | None = None


class RuleObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: Pattern | None = None
    engine: Pattern | None = None
    target_agent: Pattern | None = None


class RuleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Pattern | None = None


class SignalComparator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gt: float | None = None
    gte: float | None = None
    lt: float | None = None
    lte: float | None = None
    eq: float | int | bool | None = None


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_chain_valid: bool | None = None
    triggered_by: str | None = None
    scope: Pattern | None = None
    has_valid_grant: bool | None = None
    provider: Pattern | None = None
    model: Pattern | None = None
    identity_verified: bool | None = None
    dangerous_action: bool | None = None
    tool_name: Pattern | None = None
    tool_risk_level: Pattern | None = None
    tool_execution_mode: Pattern | None = None
    provider_tools_requested: bool | None = None
    daily_token_limit: int | None = Field(default=None, ge=0)
    rate_limit_rpm: int | None = Field(default=None, ge=0)
    message_rate_anomaly: float | SignalComparator | None = None
    repeated_grant_denials: int | SignalComparator | None = None
    cross_agent_scope_spike: int | SignalComparator | None = None
    tool_pattern_deviation: bool | None = None


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    priority: int = 0
    subject: RuleSubject = Field(default_factory=RuleSubject)
    object: RuleObject = Field(default_factory=RuleObject)
    action: RuleAction = Field(default_factory=RuleAction)
    condition: RuleCondition = Field(default_factory=RuleCondition)
    effect: Literal["allow", "deny", "elevate"] = "deny"
    else_: Literal["elevate"] | None = Field(default=None, alias="else")

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rule id must not be empty")
        return value


class IdentityAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    value: str
    verified: bool = False
    auth_method: str = "alias"
    last_verified_at: datetime | None = None
    display_name: str | None = None


class IdentityResolution(BaseModel):
    user_id: str | None = None
    role: str = "anonymous"
    groups: list[str] = Field(default_factory=list)
    privileges: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    identity_channel: str = "unknown"
    identity_alias: str | None = None
    identity_verified: bool = False
    auth_method: str = "none"
    reason: str = "unresolved"


def normalize_rule(rule: PolicyRule | dict[str, Any]) -> dict[str, Any]:
    model = rule if isinstance(rule, PolicyRule) else PolicyRule.model_validate(rule)
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)

"""Declarative rule loading and matching."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from corvus.policy.facts import PolicyFacts
from corvus.policy.models import normalize_rule
from corvus.server.db import Database


@dataclass
class RuleMatch:
    rule_id: str
    priority: int
    effect: str
    else_effect: str | None
    conditions_passed: bool
    reason: str
    metadata: dict[str, Any] | None = None


class RuleStore:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._rules: list[dict[str, Any]] = []

    async def load_from_file(self, path: Path) -> None:
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text()) or {}
        for rule in data.get("rules", []):
            normalized = self.validate_rule(rule)
            await self.db.upsert_rule(
                normalized["id"],
                int(normalized.get("priority", 0)),
                normalized,
            )
        await self.reload()

    async def reload(self) -> None:
        self._rules = await self.db.list_rules()

    def list_rules(self) -> list[dict[str, Any]]:
        return list(self._rules)

    async def add_rule(self, rule: dict[str, Any]) -> None:
        normalized = self.validate_rule(rule)
        await self.db.upsert_rule(normalized["id"], int(normalized.get("priority", 0)), normalized)
        await self.reload()

    async def delete_rule(self, rule_id: str) -> bool:
        deleted = await self.db.delete_rule(rule_id)
        await self.reload()
        return deleted

    def validate_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        try:
            return normalize_rule(rule)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    @property
    def ruleset_hash(self) -> str:
        import hashlib
        import json

        canonical = json.dumps(self._rules, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _match_pattern(self, pattern: Any, value: str) -> bool:
        if pattern is None:
            return True
        if isinstance(pattern, list):
            return any(self._match_pattern(item, value) for item in pattern)
        if pattern == "*":
            return True
        if isinstance(pattern, str) and ("*" in pattern or "?" in pattern):
            return fnmatch.fnmatch(value, pattern)
        return str(pattern) == value

    def _subject_matches(self, subject: dict[str, Any], facts: PolicyFacts) -> bool:
        role_patterns = subject.get("role")
        if role_patterns is not None and not self._match_pattern(role_patterns, facts.role):
            return False
        agent_patterns = subject.get("agent_id")
        if agent_patterns is not None and not self._match_pattern(agent_patterns, facts.agent_id):
            return False
        user_patterns = subject.get("user_id")
        if user_patterns is not None and not self._match_pattern(
            user_patterns, facts.user_id or ""
        ):
            return False
        group_patterns = subject.get("groups")
        if group_patterns is not None and not self._match_any(group_patterns, facts.groups):
            return False
        channel_patterns = subject.get("identity_channel")
        if channel_patterns is not None and not self._match_pattern(
            channel_patterns, facts.identity_channel
        ):
            return False
        auth_patterns = subject.get("auth_method")
        if auth_patterns is not None and not self._match_pattern(auth_patterns, facts.auth_method):
            return False
        return True

    def _object_matches(self, obj: dict[str, Any], facts: PolicyFacts) -> bool:
        agent_patterns = obj.get("agent_id")
        if agent_patterns is not None and not self._match_pattern(agent_patterns, facts.agent_id):
            return False
        engine_patterns = obj.get("engine")
        if engine_patterns is not None and not self._match_pattern(engine_patterns, facts.engine):
            return False
        target_patterns = obj.get("target_agent")
        if target_patterns is not None and not self._match_pattern(
            target_patterns, facts.target_agent_id or ""
        ):
            return False
        return True

    def _action_matches(self, action: dict[str, Any], facts: PolicyFacts) -> bool:
        types = action.get("type")
        if types is None:
            return True
        if isinstance(types, str):
            types = [types]
        for pattern in types:
            if fnmatch.fnmatch(facts.message_type, pattern):
                return True
        return False

    def _conditions_match(self, condition: dict[str, Any], facts: PolicyFacts) -> tuple[bool, str]:
        if not condition:
            return True, "No conditions"

        if "correlation_chain_valid" in condition:
            expected = bool(condition["correlation_chain_valid"])
            if facts.correlation_chain_valid != expected:
                return False, "correlation_chain_valid mismatch"

        if condition.get("triggered_by") and facts.triggered_by != condition["triggered_by"]:
            return False, "triggered_by mismatch"

        scopes = condition.get("scope")
        if scopes and not self._match_pattern(scopes, facts.scope):
            return False, "scope mismatch"

        if condition.get("has_valid_grant") is True and not facts.has_valid_grant:
            return False, "grant required but not valid"

        if condition.get("identity_verified") is not None:
            if facts.identity_verified != bool(condition["identity_verified"]):
                return False, "identity verification mismatch"

        if condition.get("dangerous_action") is not None:
            if facts.dangerous_action != bool(condition["dangerous_action"]):
                return False, "dangerous_action mismatch"

        tool_names = condition.get("tool_name")
        if tool_names and not self._match_pattern(tool_names, facts.tool_name or ""):
            return False, "tool_name mismatch"

        risk_levels = condition.get("tool_risk_level")
        if risk_levels and not self._match_pattern(risk_levels, facts.tool_risk_level):
            return False, "tool_risk_level mismatch"

        if condition.get("daily_token_limit") is not None and facts.quota_would_exceed:
            return False, "quota would exceed"

        if condition.get("rate_limit_rpm") is not None and facts.quota_would_exceed:
            return False, "quota would exceed"

        providers = condition.get("provider")
        if providers and not self._match_pattern(providers, facts.provider or ""):
            return False, "provider not allowed"

        models = condition.get("model")
        if models and not self._match_pattern(models, facts.model or ""):
            return False, "model not allowed"

        tool_modes = condition.get("tool_execution_mode")
        if tool_modes and not self._match_pattern(tool_modes, facts.tool_execution_mode):
            return False, "tool_execution_mode mismatch"

        if condition.get("provider_tools_requested") is not None:
            expected = bool(condition["provider_tools_requested"])
            if facts.provider_tools_requested != expected:
                return False, "provider_tools_requested mismatch"

        for signal_key in (
            "message_rate_anomaly",
            "repeated_grant_denials",
            "cross_agent_scope_spike",
            "tool_pattern_deviation",
        ):
            if signal_key not in condition:
                continue
            actual = facts.behavioral_signals.get(signal_key)
            if not self._compare_signal(actual, condition[signal_key]):
                return False, f"{signal_key} mismatch"

        return True, "All conditions passed"

    def _compare_signal(self, actual: Any, expected: Any) -> bool:
        if isinstance(expected, dict):
            comparator = expected
        elif hasattr(expected, "model_dump"):
            comparator = expected.model_dump(exclude_none=True)
        else:
            return actual == expected

        if "eq" in comparator and actual != comparator["eq"]:
            return False
        if actual is None:
            return False
        numeric = float(actual)
        if "gt" in comparator and not numeric > float(comparator["gt"]):
            return False
        if "gte" in comparator and not numeric >= float(comparator["gte"]):
            return False
        if "lt" in comparator and not numeric < float(comparator["lt"]):
            return False
        if "lte" in comparator and not numeric <= float(comparator["lte"]):
            return False
        return True

    def evaluate(self, facts: PolicyFacts) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        sorted_rules = sorted(self._rules, key=lambda r: int(r.get("priority", 0)), reverse=True)

        for rule in sorted_rules:
            subject = rule.get("subject", {})
            obj = rule.get("object", {})
            action = rule.get("action", {})

            if not self._subject_matches(subject, facts):
                continue
            if not self._object_matches(obj, facts):
                continue
            if not self._action_matches(action, facts):
                continue

            passed, reason = self._conditions_match(rule.get("condition", {}), facts)
            matches.append(
                RuleMatch(
                    rule_id=rule["id"],
                    priority=int(rule.get("priority", 0)),
                    effect=str(rule.get("effect", "deny")),
                    else_effect=rule.get("else"),
                    conditions_passed=passed,
                    reason=reason,
                    metadata={
                        "grant_id": facts.grant_id,
                        "target_agent_id": facts.target_agent_id,
                        "quota_key": facts.quota_key,
                        "identity_channel": facts.identity_channel,
                        "auth_method": facts.auth_method,
                        "dangerous_action": facts.dangerous_action,
                        "tool_name": facts.tool_name,
                        "tool_risk_level": facts.tool_risk_level,
                    },
                )
            )
        return matches

    def _match_any(self, pattern: Any, values: list[str]) -> bool:
        return any(self._match_pattern(pattern, value) for value in values)

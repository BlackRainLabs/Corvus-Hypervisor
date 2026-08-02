"""Policy decision combiner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from corvus.policy.rules import RuleMatch

if TYPE_CHECKING:
    from corvus.policy.facts import PolicyFacts


@dataclass
class PolicyDecision:
    decision: str
    matched_rules: list[RuleMatch] = field(default_factory=list)
    explanation_trace: list[dict[str, str]] = field(default_factory=list)
    effective_error_code: str | None = None
    metadata: dict[str, str | bool | None] = field(default_factory=dict)
    policy_facts: PolicyFacts | None = None


class DecisionCombiner:
    def combine(self, matches: list[RuleMatch]) -> PolicyDecision:
        trace: list[dict[str, str]] = []
        if not matches:
            trace.append({"step": "default_deny", "detail": "No matching rules"})
            return PolicyDecision(
                decision="deny",
                matched_rules=[],
                explanation_trace=trace,
                effective_error_code="SERVER_RBAC_DENIED",
            )

        by_priority: dict[int, list[RuleMatch]] = {}
        for match in matches:
            by_priority.setdefault(match.priority, []).append(match)

        for priority in sorted(by_priority.keys(), reverse=True):
            group = by_priority[priority]
            trace.append({"step": "evaluate_priority", "detail": f"priority={priority}"})

            denies = [m for m in group if m.effect == "deny" and m.conditions_passed]
            if denies:
                trace.append({"step": "deny_wins", "detail": denies[0].rule_id})
                if any(m.effect == "allow" and m.conditions_passed for m in group):
                    trace.append({"step": "rule_conflict", "detail": f"priority={priority}"})
                return PolicyDecision(
                    decision="deny",
                    matched_rules=group,
                    explanation_trace=trace,
                    effective_error_code="SERVER_RBAC_DENIED",
                    metadata=self._metadata(group),
                )

            allows = [m for m in group if m.effect == "allow" and m.conditions_passed]
            if allows:
                trace.append({"step": "allow", "detail": allows[0].rule_id})
                return PolicyDecision(
                    decision="allow",
                    matched_rules=group,
                    explanation_trace=trace,
                    metadata=self._metadata(group),
                )

            elevates = [m for m in group if m.else_effect == "elevate" and not m.conditions_passed]
            if elevates:
                trace.append({"step": "elevate", "detail": elevates[0].rule_id})
                return PolicyDecision(
                    decision="elevate",
                    matched_rules=group,
                    explanation_trace=trace,
                    effective_error_code="SERVER_ELEVATION_REQUIRED",
                    metadata=self._metadata(group),
                )

            hard_elevates = [m for m in group if m.effect == "elevate" and m.conditions_passed]
            if hard_elevates:
                trace.append({"step": "elevate", "detail": hard_elevates[0].rule_id})
                return PolicyDecision(
                    decision="elevate",
                    matched_rules=group,
                    explanation_trace=trace,
                    effective_error_code="SERVER_ELEVATION_REQUIRED",
                    metadata=self._metadata(group),
                )

        trace.append({"step": "default_deny", "detail": "No decisive rule"})
        return PolicyDecision(
            decision="deny",
            matched_rules=matches,
            explanation_trace=trace,
            effective_error_code="SERVER_RBAC_DENIED",
            metadata=self._metadata(matches),
        )

    def _metadata(self, matches: list[RuleMatch]) -> dict[str, str | bool | None]:
        metadata: dict[str, str | bool | None] = {}
        for match in matches:
            for key, value in (match.metadata or {}).items():
                if value is not None and key not in metadata:
                    metadata[key] = value
        if any("quota" in match.reason for match in matches):
            metadata["quota_failed"] = True
        return metadata

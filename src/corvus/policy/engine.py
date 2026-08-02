"""Policy Decision Point engine."""

from __future__ import annotations

from typing import Any

from corvus.policy.combiner import DecisionCombiner, PolicyDecision
from corvus.policy.facts import FactGatherer
from corvus.policy.rules import RuleMatch, RuleStore
from corvus.protocol import FrameworkMessage


class PolicyEngine:
    def __init__(self, facts: FactGatherer, rules: RuleStore, combiner: DecisionCombiner) -> None:
        self.facts = facts
        self.rules = rules
        self.combiner = combiner

    async def evaluate(
        self,
        message: FrameworkMessage,
        *,
        correlation_valid: bool,
        override_context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        policy_facts = await self.facts.gather(
            message,
            correlation_valid=correlation_valid,
            override_context=override_context,
        )
        if (
            policy_facts.allowed_agents
            and "*" not in policy_facts.allowed_agents
            and policy_facts.agent_id not in policy_facts.allowed_agents
        ):
            return PolicyDecision(
                decision="deny",
                matched_rules=[
                    RuleMatch(
                        rule_id="allowed-agents-precheck",
                        priority=1000,
                        effect="deny",
                        else_effect=None,
                        conditions_passed=True,
                        reason="agent not allowed for user",
                    )
                ],
                explanation_trace=[
                    {
                        "step": "allowed_agents_precheck",
                        "detail": f"{policy_facts.agent_id} not in user allowed_agents",
                    }
                ],
                effective_error_code="SERVER_RBAC_DENIED",
            )
        matches = self.rules.evaluate(policy_facts)
        decision = self.combiner.combine(matches)
        decision.policy_facts = policy_facts
        decision.metadata.update(
            {
                "user_id": policy_facts.user_id,
                "grant_id": policy_facts.grant_id,
                "grant_reason": policy_facts.grant_reason,
                "target_agent_id": policy_facts.target_agent_id,
                "quota_key": policy_facts.quota_key,
                "quota_remaining_after": policy_facts.quota_remaining_after,
                "quota_would_consume_tokens": policy_facts.quota_would_consume_tokens,
                "identity_channel": policy_facts.identity_channel,
                "identity_alias": policy_facts.identity_alias,
                "identity_verified": policy_facts.identity_verified,
                "auth_method": policy_facts.auth_method,
            }
        )
        if decision.metadata.get("quota_failed"):
            decision.effective_error_code = "SERVER_QUOTA_EXCEEDED"
        return decision

    async def simulate(
        self,
        message: FrameworkMessage,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        correlation_valid = True
        if context and "correlation_chain_valid" in context:
            correlation_valid = bool(context["correlation_chain_valid"])
        return await self.evaluate(
            message,
            correlation_valid=correlation_valid,
            override_context=context,
        )

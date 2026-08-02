"""RBAC policy engine tests."""

from uuid import uuid4

import pytest

from corvus.policy.combiner import DecisionCombiner
from corvus.policy.facts import FactGatherer
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)


@pytest.mark.asyncio
async def test_deny_engine3_memory(app_ctx):
    rules = app_ctx.rules
    combiner = DecisionCombiner()
    facts = FactGatherer(app_ctx.db, app_ctx.correlation)

    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={},
    )

    policy_facts = await facts.gather(message, correlation_valid=True)
    matches = rules.evaluate(policy_facts)
    decision = combiner.combine(matches)
    assert decision.decision == "deny"
    assert decision.effective_error_code == "SERVER_RBAC_DENIED"


@pytest.mark.asyncio
async def test_allow_user_query(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE2, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT),
        payload={"user_id": "test-user"},
    )
    decision = await app_ctx.policy.evaluate(message, correlation_valid=True)
    assert decision.decision == "allow"


@pytest.mark.asyncio
async def test_engine4_memory_requires_live_grant(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"target_agent_id": "other-agent", "namespace": "private"},
    )

    decision = await app_ctx.policy.evaluate(message, correlation_valid=True)
    assert decision.decision == "elevate"

    await app_ctx.db.create_grant(
        subject_agent="test-agent-01",
        target_agent="other-agent",
        namespace="private",
        permissions=["read"],
        created_by="test",
    )

    decision = await app_ctx.policy.evaluate(message, correlation_valid=True)
    assert decision.decision == "allow"
    assert decision.metadata["grant_id"]
    assert decision.metadata["target_agent_id"] == "other-agent"


@pytest.mark.asyncio
async def test_cli_pin_required_for_direct_user(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE2, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT),
        payload={"user_id": "test-user", "identity_channel": "cli"},
    )
    facts = await app_ctx.facts.gather(message, correlation_valid=True)
    assert facts.identity_verified is False
    assert facts.auth_method == "unverified"

    facts = await app_ctx.facts.gather(
        message.model_copy(update={"payload": {**message.payload, "pin": "1234"}}),
        correlation_valid=True,
    )
    assert facts.identity_verified is True


@pytest.mark.asyncio
async def test_whatsapp_alias_resolves_user(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE2, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT),
        payload={"platform": "whatsapp", "from": "+15550101001"},
    )
    facts = await app_ctx.facts.gather(message, correlation_valid=True)
    assert facts.user_id == "test-user"
    assert facts.identity_verified is True
    assert facts.identity_channel == "whatsapp"


@pytest.mark.asyncio
async def test_allowed_agents_precheck_denies_unassigned_agent(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="other-agent", engine=EngineId.ENGINE2, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT),
        payload={"user_id": "test-user"},
    )
    decision = await app_ctx.policy.evaluate(message, correlation_valid=True)
    assert decision.decision == "deny"
    assert decision.matched_rules[0].rule_id == "allowed-agents-precheck"


@pytest.mark.asyncio
async def test_dangerous_tool_call_requires_elevation(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE1, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="tool_call",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"tool_name": "shell", "command": "rm -rf /tmp/corvus-danger"},
    )
    decision = await app_ctx.policy.evaluate(message, correlation_valid=True)
    assert decision.decision == "elevate"
    assert decision.matched_rules[0].rule_id == "elevate-dangerous-tool-call"


@pytest.mark.asyncio
async def test_behavioral_deny_rule_matches_on_override(app_ctx):
    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"target_agent_id": "other-agent", "namespace": "private"},
    )
    decision = await app_ctx.policy.evaluate(
        message,
        correlation_valid=True,
        override_context={
            "behavioral_signals": {"repeated_grant_denials": 4},
        },
    )
    assert decision.decision == "deny"
    assert any(
        match.rule_id == "deny-repeated-grant-denials" and match.conditions_passed
        for match in decision.matched_rules
    )

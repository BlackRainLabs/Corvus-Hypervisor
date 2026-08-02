"""Behavioral monitor unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from corvus.policy.combiner import PolicyDecision
from corvus.policy.facts import PolicyFacts
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
from corvus.server.bootstrap import TEST_AGENT_ID


def _memory_query(*, target_agent_id: str = "other-agent") -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "target_agent_id": target_agent_id,
            "namespace": "private",
            "query_type": "key",
            "query": {"key": "secret"},
        },
    )


@pytest.mark.asyncio
async def test_grant_denial_counter_increments_for_cross_agent(app_ctx):
    monitor = app_ctx.behavioral
    message = _memory_query()
    facts = PolicyFacts(
        agent_id=TEST_AGENT_ID,
        target_agent_id="other-agent",
        grant_reason="no_valid_grant",
    )
    await monitor.record_policy_outcome(message, PolicyDecision(decision="elevate"), facts)
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["repeated_grant_denials"] == 1


@pytest.mark.asyncio
async def test_grant_denial_counter_skips_own_namespace(app_ctx):
    monitor = app_ctx.behavioral
    message = _memory_query(target_agent_id=TEST_AGENT_ID)
    facts = PolicyFacts(
        agent_id=TEST_AGENT_ID,
        target_agent_id=TEST_AGENT_ID,
        grant_reason="no_valid_grant",
    )
    await monitor.record_policy_outcome(message, PolicyDecision(decision="elevate"), facts)
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["repeated_grant_denials"] == 0


@pytest.mark.asyncio
async def test_signals_for_reads_prior_grant_denials_before_current_record(app_ctx):
    monitor = app_ctx.behavioral
    message = _memory_query()
    facts = PolicyFacts(
        agent_id=TEST_AGENT_ID,
        target_agent_id="other-agent",
        grant_reason="no_valid_grant",
    )
    for _ in range(4):
        await monitor.record_policy_outcome(
            message, PolicyDecision(decision="elevate"), facts
        )
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["repeated_grant_denials"] == 4


@pytest.mark.asyncio
async def test_cross_agent_scope_spike_counter(app_ctx):
    monitor = app_ctx.behavioral
    await monitor.record_message_hop(_memory_query())
    await monitor.record_message_hop(_memory_query())
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["cross_agent_scope_spike"] == 2


@pytest.mark.asyncio
async def test_grant_denial_window_excludes_old_buckets(app_ctx):
    monitor = app_ctx.behavioral
    old_bucket = (datetime.now(UTC) - timedelta(minutes=11)).replace(second=0, microsecond=0)
    await app_ctx.db.increment_behavioral_counter(
        agent_id=TEST_AGENT_ID,
        signal="grant_denial",
        window_start=old_bucket.isoformat(),
    )
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["repeated_grant_denials"] == 0


def _tool_call_message() -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE1, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="tool_call",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"tool_name": "echo", "arguments": {"text": "hi"}},
    )


@pytest.mark.asyncio
async def test_record_approved_tool_call_increments_counter(app_ctx):
    monitor = app_ctx.behavioral
    await monitor.record_approved_tool_call(_tool_call_message())
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    total = await app_ctx.db.sum_behavioral_counter(
        agent_id=TEST_AGENT_ID,
        signal="tool_call",
        since_iso=now.isoformat(),
    )
    assert total == 1
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["tool_pattern_deviation"] is False


@pytest.mark.asyncio
async def test_tool_pattern_deviation_when_zscore_exceeds_threshold(app_ctx):
    monitor = app_ctx.behavioral
    now = datetime.now(UTC)
    for minutes_ago in (4, 3, 2):
        bucket = (now - timedelta(minutes=minutes_ago)).replace(second=0, microsecond=0)
        await app_ctx.db.increment_behavioral_counter(
            agent_id=TEST_AGENT_ID,
            signal="tool_call",
            window_start=bucket.isoformat(),
            delta=1,
        )
    current = now.replace(second=0, microsecond=0)
    await app_ctx.db.increment_behavioral_counter(
        agent_id=TEST_AGENT_ID,
        signal="tool_call",
        window_start=current.isoformat(),
        delta=20,
    )
    signals = await monitor.signals_for(TEST_AGENT_ID)
    assert signals["tool_pattern_deviation"] is True

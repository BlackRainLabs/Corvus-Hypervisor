"""Behavioral signal collection for RBAC anomaly rules."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from corvus.protocol import FrameworkMessage
from corvus.server.db import Database

if TYPE_CHECKING:
    from corvus.policy.combiner import PolicyDecision
    from corvus.policy.facts import PolicyFacts
    from corvus.server.config import ServerConfig

logger = logging.getLogger(__name__)

SIGNAL_MESSAGE_HOP = "message_hop"
SIGNAL_GRANT_DENIAL = "grant_denial"
SIGNAL_CROSS_AGENT_MEMORY = "cross_agent_memory"
SIGNAL_TOOL_CALL = "tool_call"


def _minute_bucket(now: datetime) -> str:
    floored = now.replace(second=0, microsecond=0)
    return floored.isoformat()


class BehavioralMonitor:
    def __init__(self, db: Database, config: ServerConfig) -> None:
        self.db = db
        self.config = config

    async def startup(self) -> None:
        cutoff = (
            datetime.now(UTC)
            - timedelta(hours=self.config.behavioral_counter_retention_hours)
        ).isoformat()
        purged = await self.db.purge_behavioral_counters(cutoff)
        if purged:
            logger.info("behavioral counter purge: removed=%s", purged)

    async def record_message_hop(self, message: FrameworkMessage) -> None:
        if message.type == "handshake":
            return
        now = datetime.now(UTC)
        bucket = _minute_bucket(now)
        agent_id = message.source.agent_id
        await self.db.increment_behavioral_counter(
            agent_id=agent_id,
            signal=SIGNAL_MESSAGE_HOP,
            window_start=bucket,
        )
        if message.type.startswith("memory:"):
            target_agent_id = (
                message.payload.get("target_agent_id")
                or message.payload.get("target_agent")
                or agent_id
            )
            if str(target_agent_id) != agent_id:
                await self.db.increment_behavioral_counter(
                    agent_id=agent_id,
                    signal=SIGNAL_CROSS_AGENT_MEMORY,
                    window_start=bucket,
                )

    async def record_policy_outcome(
        self,
        message: FrameworkMessage,
        decision: PolicyDecision,
        facts: PolicyFacts,
    ) -> None:
        if not message.type.startswith("memory:"):
            return
        if facts.grant_reason != "no_valid_grant":
            return
        target_agent_id = facts.target_agent_id or message.source.agent_id
        if target_agent_id == message.source.agent_id:
            return
        now = datetime.now(UTC)
        bucket = _minute_bucket(now)
        await self.db.increment_behavioral_counter(
            agent_id=message.source.agent_id,
            signal=SIGNAL_GRANT_DENIAL,
            window_start=bucket,
        )

    async def record_approved_tool_call(self, message: FrameworkMessage) -> None:
        if message.type != "tool_call":
            return
        now = datetime.now(UTC)
        bucket = _minute_bucket(now)
        await self.db.increment_behavioral_counter(
            agent_id=message.source.agent_id,
            signal=SIGNAL_TOOL_CALL,
            window_start=bucket,
        )

    async def signals_for(self, agent_id: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        current_bucket = _minute_bucket(now)
        grant_since = (
            now - timedelta(minutes=self.config.behavioral_grant_denial_window_minutes)
        ).isoformat()
        cross_agent_since = (
            now - timedelta(minutes=self.config.behavioral_cross_agent_window_minutes)
        ).isoformat()

        repeated_grant_denials = await self.db.sum_behavioral_counter(
            agent_id=agent_id,
            signal=SIGNAL_GRANT_DENIAL,
            since_iso=grant_since,
        )
        cross_agent_scope_spike = await self.db.sum_behavioral_counter(
            agent_id=agent_id,
            signal=SIGNAL_CROSS_AGENT_MEMORY,
            since_iso=cross_agent_since,
        )
        message_rate_anomaly = await self._rate_zscore(
            agent_id,
            signal=SIGNAL_MESSAGE_HOP,
            now=now,
            current_bucket=current_bucket,
        )
        tool_rate_zscore = await self._rate_zscore(
            agent_id,
            signal=SIGNAL_TOOL_CALL,
            now=now,
            current_bucket=current_bucket,
        )
        tool_pattern_deviation = (
            tool_rate_zscore > self.config.behavioral_tool_zscore_threshold
        )
        return {
            "message_rate_anomaly": message_rate_anomaly,
            "repeated_grant_denials": repeated_grant_denials,
            "cross_agent_scope_spike": cross_agent_scope_spike,
            "tool_pattern_deviation": tool_pattern_deviation,
        }

    async def _rate_zscore(
        self,
        agent_id: str,
        *,
        signal: str,
        now: datetime,
        current_bucket: str,
    ) -> float:
        baseline_since = (
            now - timedelta(minutes=self.config.behavioral_rate_baseline_minutes)
        ).isoformat()
        baseline_buckets = await self.db.list_behavioral_buckets(
            agent_id=agent_id,
            signal=signal,
            since_iso=baseline_since,
            before_iso=current_bucket,
        )
        if len(baseline_buckets) < 3:
            return 0.0

        counts = [int(bucket["count"]) for bucket in baseline_buckets]
        mean = sum(counts) / len(counts)
        variance = sum((value - mean) ** 2 for value in counts) / len(counts)
        stddev = max(math.sqrt(variance), 1.0)

        current = await self.db.sum_behavioral_counter(
            agent_id=agent_id,
            signal=signal,
            since_iso=current_bucket,
        )
        return (current - mean) / stddev

"""Outbound message validation pipeline."""

from __future__ import annotations

from typing import Any

from corvus.node.rate_limit import TokenBucket
from corvus.protocol import ErrorCode, ErrorLayer, FrameworkMessage, make_error_message
from corvus.protocol.models import DEFAULT_POLICY_SNAPSHOT, DestinationType, EngineId


def _engine_key(engine: EngineId | str) -> str:
    return engine.value if isinstance(engine, EngineId) else engine


class MessageValidator:
    def __init__(self, policy_snapshot: dict[str, Any] | None = None) -> None:
        self._policy = policy_snapshot or DEFAULT_POLICY_SNAPSHOT
        self._buckets: dict[str, TokenBucket] = {}
        self._init_buckets()

    def update_policy(self, policy_snapshot: dict[str, Any]) -> None:
        self._policy = policy_snapshot
        self._init_buckets()

    def _init_buckets(self) -> None:
        limits = self._policy.get("rate_limits", {})
        self._buckets = {}
        for engine, cfg in limits.items():
            self._buckets[engine] = TokenBucket(
                rate=float(cfg.get("messages_per_sec", 10)),
                burst=int(cfg.get("burst", 20)),
            )

    def allowed_types(self, engine: EngineId | str) -> list[str]:
        allowed = self._policy.get("allowed_message_types", {})
        return list(allowed.get(_engine_key(engine), []))

    def engine_policy_subset(self, engine: EngineId | str) -> dict[str, Any]:
        key = _engine_key(engine)
        return {
            "version": self._policy.get("version", "1.0"),
            "rate_limits": {
                key: self._policy.get("rate_limits", {}).get(
                    key, {"messages_per_sec": 10, "burst": 20}
                )
            },
            "allowed_message_types": {
                key: self.allowed_types(engine),
            },
        }

    def validate(
        self,
        message: FrameworkMessage,
        *,
        registered_engine: EngineId,
        handshake_complete: bool,
        claimed_engine: EngineId | None,
        agent_id: str,
        vm_id: str,
    ) -> FrameworkMessage | None:
        if (
            claimed_engine is not None
            and EngineId(claimed_engine) != registered_engine
        ):
            return self._error(
                ErrorCode.NODE_ORIGIN_SPOOF,
                "Engine mismatch on IPC socket",
                recoverable=False,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        if not handshake_complete and not (
            message.type == "handshake" and registered_engine == EngineId.CORVUS_NODE
        ):
            return self._error(
                ErrorCode.NODE_HANDSHAKE_INCOMPLETE,
                "Session not active; handshake required",
                recoverable=True,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        if registered_engine == EngineId.LOOP:
            if message.destination.type == DestinationType.CORVUS_SERVER:
                return self._error(
                    ErrorCode.NODE_CAPABILITY_DENIED,
                    "Agent loop cannot forward directly to Corvus Server",
                    recoverable=True,
                    agent_id=agent_id,
                    vm_id=vm_id,
                    correlation_id=message.correlation_id,
                    target_engine=registered_engine,
                    original_message_id=message.id,
                )
            return None

        if message.destination.type != DestinationType.CORVUS_SERVER:
            return self._error(
                ErrorCode.NODE_VALIDATION_FAILED,
                "Outbound messages must target corvus_server",
                recoverable=True,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        allowed = self.allowed_types(registered_engine)
        if message.type not in allowed:
            return self._error(
                ErrorCode.NODE_CAPABILITY_DENIED,
                f"Message type '{message.type}' not allowed for {registered_engine.value}",
                recoverable=True,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        if message.type.startswith("memory:") and registered_engine != EngineId.ENGINE4:
            return self._error(
                ErrorCode.NODE_CAPABILITY_DENIED,
                "Only engine4 may send memory:* messages",
                recoverable=True,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        bucket = self._buckets.get(registered_engine.value)
        if bucket is not None and not bucket.consume():
            return self._error(
                ErrorCode.NODE_RATE_LIMITED,
                "Rate limit exceeded",
                recoverable=True,
                agent_id=agent_id,
                vm_id=vm_id,
                correlation_id=message.correlation_id,
                target_engine=registered_engine,
                original_message_id=message.id,
            )

        return None

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        *,
        recoverable: bool,
        agent_id: str,
        vm_id: str,
        correlation_id,
        target_engine: EngineId,
        original_message_id,
    ) -> FrameworkMessage:
        return make_error_message(
            code=code,
            layer=ErrorLayer.NODE,
            message=message,
            recoverable=recoverable,
            agent_id=agent_id,
            vm_id=vm_id,
            correlation_id=correlation_id,
            target_engine=target_engine,
            original_message_id=original_message_id,
        )

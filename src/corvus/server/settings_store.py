"""Runtime settings seed, redaction, and in-process apply for Phase 9.4."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, TYPE_CHECKING

from corvus.server.config import ServerConfig
from corvus.server.db import Database

if TYPE_CHECKING:
    from corvus.server.bootstrap import AppContext

# key -> (config attr, secret?, restart_required?, group, env var name or None)
SETTINGS_SPEC: dict[str, tuple[str, bool, bool, str, str | None]] = {
    "mgmt_host": ("mgmt_host", False, True, "system", "CORVUS_MGMT_HOST"),
    "mgmt_port": ("mgmt_port", False, True, "system", "CORVUS_MGMT_PORT"),
    "use_tcp": ("use_tcp", False, True, "system", "CORVUS_USE_TCP"),
    "api_rate_limit_per_minute": (
        "api_rate_limit_per_minute",
        False,
        False,
        "system",
        "CORVUS_API_RATE_LIMIT_PER_MINUTE",
    ),
    "ui_enabled": ("ui_enabled", False, False, "system", "CORVUS_UI_ENABLED"),
    "ui_path_prefix": ("ui_path_prefix", False, False, "system", "CORVUS_UI_PATH_PREFIX"),
    "ui_session_secret": (
        "ui_session_secret",
        True,
        False,
        "system",
        "CORVUS_UI_SESSION_SECRET",
    ),
    "api_key": ("api_key", True, False, "system", "CORVUS_API_KEY"),
    "llm_default_provider": (
        "llm_default_provider",
        False,
        False,
        "inference",
        "CORVUS_LLM_DEFAULT_PROVIDER",
    ),
    "llm_request_timeout_seconds": (
        "llm_request_timeout_seconds",
        False,
        False,
        "inference",
        "CORVUS_LLM_REQUEST_TIMEOUT_SECONDS",
    ),
    "llm_tokens_daily_limit": (
        "llm_tokens_daily_limit",
        False,
        False,
        "inference",
        "CORVUS_LLM_TOKENS_DAILY_LIMIT",
    ),
    "memory_encryption_enabled": (
        "memory_encryption_enabled",
        False,
        False,
        "memory",
        "CORVUS_MEMORY_ENCRYPTION",
    ),
    "memory_master_key": ("memory_master_key", True, False, "memory", "CORVUS_MASTER_KEY"),
    "memory_sweep_interval_seconds": (
        "memory_sweep_interval_seconds",
        False,
        False,
        "memory",
        "CORVUS_MEMORY_SWEEP_INTERVAL_SECONDS",
    ),
    "memory_soft_delete_retention_hours": (
        "memory_soft_delete_retention_hours",
        False,
        False,
        "memory",
        "CORVUS_MEMORY_SOFT_DELETE_RETENTION_HOURS",
    ),
    "memory_writes_daily_limit": (
        "memory_writes_daily_limit",
        False,
        False,
        "memory",
        "CORVUS_MEMORY_WRITES_DAILY_LIMIT",
    ),
    "elevation_webhook_url": (
        "elevation_webhook_url",
        False,
        False,
        "security",
        "CORVUS_ELEVATION_WEBHOOK_URL",
    ),
    "elevation_webhook_secret": (
        "elevation_webhook_secret",
        True,
        False,
        "security",
        "CORVUS_ELEVATION_WEBHOOK_SECRET",
    ),
    "behavioral_grant_denial_window_minutes": (
        "behavioral_grant_denial_window_minutes",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_GRANT_DENIAL_WINDOW_MINUTES",
    ),
    "behavioral_grant_denial_threshold": (
        "behavioral_grant_denial_threshold",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_GRANT_DENIAL_THRESHOLD",
    ),
    "behavioral_cross_agent_window_minutes": (
        "behavioral_cross_agent_window_minutes",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_CROSS_AGENT_WINDOW_MINUTES",
    ),
    "behavioral_cross_agent_threshold": (
        "behavioral_cross_agent_threshold",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_CROSS_AGENT_THRESHOLD",
    ),
    "behavioral_rate_baseline_minutes": (
        "behavioral_rate_baseline_minutes",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_RATE_BASELINE_MINUTES",
    ),
    "behavioral_rate_zscore_threshold": (
        "behavioral_rate_zscore_threshold",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_RATE_ZSCORE_THRESHOLD",
    ),
    "behavioral_tool_zscore_threshold": (
        "behavioral_tool_zscore_threshold",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_TOOL_ZSCORE_THRESHOLD",
    ),
    "behavioral_counter_retention_hours": (
        "behavioral_counter_retention_hours",
        False,
        False,
        "security",
        "CORVUS_BEHAVIORAL_COUNTER_RETENTION_HOURS",
    ),
}


def _env_is_set(env_name: str | None) -> bool:
    return bool(env_name and env_name in os.environ)


async def ensure_settings_seeded(db: Database, config: ServerConfig) -> None:
    existing = {row["key"] for row in await db.list_settings()}
    for key, (attr, secret, restart, _group, _env) in SETTINGS_SPEC.items():
        if key in existing:
            continue
        value = getattr(config, attr, None)
        await db.upsert_setting(key, value, secret=secret, restart_required=restart)


async def load_settings_into_config(db: Database, config: ServerConfig) -> ServerConfig:
    """Apply DB settings where env break-glass is not set."""
    rows = await db.list_settings()
    updates: dict[str, Any] = {}
    for row in rows:
        meta = SETTINGS_SPEC.get(row["key"])
        if meta is None:
            continue
        attr, _secret, _restart, _group, env_name = meta
        if _env_is_set(env_name):
            continue
        value = row["value"]
        if attr == "use_tcp" and isinstance(value, str):
            value = value in {"1", "true", "True"}
        if attr == "memory_encryption_enabled" and isinstance(value, (int, str)):
            value = value in {1, "1", True, "true", "True"}
        if attr == "ui_enabled" and isinstance(value, (int, str)):
            value = value in {1, "1", True, "true", "True"}
        updates[attr] = value
    if not updates:
        return config
    return replace(config, **updates)


def apply_settings_to_context(ctx: AppContext, config: ServerConfig) -> None:
    """Push config into live service fields (non-restart knobs)."""
    ctx.config = config
    ctx.behavioral.config = config
    ctx.llm.default_provider = config.llm_default_provider
    ctx.llm.request_timeout_seconds = config.llm_request_timeout_seconds
    ctx.memory.encryption_enabled = config.memory_encryption_enabled
    ctx.memory.master_key = config.memory_master_key
    ctx.quotas.memory_writes_daily_limit = config.memory_writes_daily_limit
    if hasattr(ctx, "router") and ctx.router is not None:
        ctx.router.llm_tokens_daily_limit = config.llm_tokens_daily_limit
        ctx.router.elevation_webhook_url = config.elevation_webhook_url
        ctx.router.elevation_webhook_secret = config.elevation_webhook_secret
    if hasattr(ctx, "memory_sweeper") and ctx.memory_sweeper is not None:
        from datetime import timedelta

        ctx.memory_sweeper.interval_seconds = config.memory_sweep_interval_seconds
        ctx.memory_sweeper.soft_delete_retention = timedelta(
            hours=config.memory_soft_delete_retention_hours
        )


def settings_public_view(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        meta = SETTINGS_SPEC.get(row["key"])
        group = meta[3] if meta else "other"
        value = "********" if row["secret"] else row["value"]
        grouped.setdefault(group, []).append(
            {
                "key": row["key"],
                "value": value,
                "secret": row["secret"],
                "restart_required": row["restart_required"],
                "updated_at": row["updated_at"],
            }
        )
    return grouped

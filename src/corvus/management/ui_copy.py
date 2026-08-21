"""Operator-facing labels, help text, and small view helpers for the console."""

from __future__ import annotations

from typing import Any

BOOLEAN_SETTING_KEYS = frozenset(
    {"use_tcp", "ui_enabled", "memory_encryption_enabled"}
)

SETTING_LABELS: dict[str, str] = {
    "mgmt_host": "Management bind host",
    "mgmt_port": "Management bind port",
    "use_tcp": "Use TCP instead of vsock",
    "api_rate_limit_per_minute": "API rate limit (per minute)",
    "ui_enabled": "Operator console enabled",
    "ui_path_prefix": "Console path prefix",
    "ui_session_secret": "Console session secret",
    "api_key": "Management API key",
    "llm_default_provider": "Default LLM provider",
    "llm_request_timeout_seconds": "LLM request timeout (seconds)",
    "llm_tokens_daily_limit": "Daily LLM token limit",
    "memory_encryption_enabled": "Encrypt memory at rest",
    "memory_master_key": "Memory master key",
    "memory_sweep_interval_seconds": "Sweeper interval (seconds)",
    "memory_soft_delete_retention_hours": "Soft-delete retention (hours)",
    "memory_writes_daily_limit": "Daily memory write limit",
    "elevation_webhook_url": "Elevation webhook URL",
    "elevation_webhook_secret": "Elevation webhook secret",
    "behavioral_grant_denial_window_minutes": "Grant-denial window (minutes)",
    "behavioral_grant_denial_threshold": "Grant-denial threshold",
    "behavioral_cross_agent_window_minutes": "Cross-agent window (minutes)",
    "behavioral_cross_agent_threshold": "Cross-agent threshold",
    "behavioral_rate_baseline_minutes": "Rate baseline (minutes)",
    "behavioral_rate_zscore_threshold": "Message-rate z-score threshold",
    "behavioral_tool_zscore_threshold": "Tool-call z-score threshold",
    "behavioral_counter_retention_hours": "Behavioral counter retention (hours)",
}

SETTING_HELP: dict[str, str] = {
    "mgmt_host": "Requires restart of corvus-server. The console does not restart the process.",
    "mgmt_port": "Requires restart of corvus-server. The console does not restart the process.",
    "use_tcp": "Requires restart. Use TCP for agent transports instead of vsock.",
    "api_rate_limit_per_minute": (
        "Per API key. Set 0 to disable. Console in-process calls are exempt."
    ),
    "ui_enabled": (
        "Applied at process start. Turning this off does not unmount a running console."
    ),
    "ui_path_prefix": (
        "Applied at process start. Changing this requires a server restart to remount."
    ),
    "ui_session_secret": "Write-only. Changing this signs out all console sessions.",
    "api_key": "Write-only. Changing this invalidates external Management API clients.",
    "llm_default_provider": "Used when an agent manifest does not pin a provider.",
    "llm_request_timeout_seconds": "Server-side LLM gateway timeout per request.",
    "llm_tokens_daily_limit": (
        "Default daily token budget; per-agent counters are under Inference/Security."
    ),
    "memory_encryption_enabled": "Encrypts Engine 4 records at rest using the master key.",
    "memory_master_key": "Write-only. Leave blank to keep the current key.",
    "memory_sweep_interval_seconds": "How often the TTL sweeper runs.",
    "memory_soft_delete_retention_hours": "How long soft-deleted memory records are kept.",
    "memory_writes_daily_limit": "Default daily write budget for memory namespaces.",
    "elevation_webhook_url": "Optional HTTPS endpoint notified on elevation decisions.",
    "elevation_webhook_secret": "Write-only HMAC secret for X-Corvus-Signature.",
    "behavioral_grant_denial_window_minutes": "Sliding window for grant-denial anomaly detection.",
    "behavioral_grant_denial_threshold": (
        "Denials inside the window that raise a behavioral signal."
    ),
    "behavioral_cross_agent_window_minutes": (
        "Sliding window for cross-agent memory access signals."
    ),
    "behavioral_cross_agent_threshold": (
        "Cross-agent attempts inside the window that raise a signal."
    ),
    "behavioral_rate_baseline_minutes": "Baseline window for message-rate z-score.",
    "behavioral_rate_zscore_threshold": "Z-score above which message rate is flagged.",
    "behavioral_tool_zscore_threshold": "Z-score above which tool-call rate is flagged.",
    "behavioral_counter_retention_hours": "How long behavioral counters are retained.",
}

PAGE_LEADS: dict[str, str] = {
    "summary": "Live hypervisor health, pending elevations, and recent audit events.",
    "chat": (
        "Talk to an agent's allowed LLM through the server gateway. "
        "The built-in stub provider echoes your message; dummy-http needs the local dummy API."
    ),
    "agents": (
        "Register, launch, and stop agent microVMs. "
        "Capabilities are selected at create time from server catalogs."
    ),
    "agent_detail": "Lifecycle, per-namespace quotas, and the launch manifest for this agent.",
    "tools": (
        "Server-owned tools, skills, and workspace catalogs baked into agent rootfs at launch."
    ),
    "skills_browse": (
        "Search an allowlisted public Agent Skills registry. "
        "Install still requires pin, sha256, and CORVUS_SKILL_SOURCE_ALLOWLIST."
    ),
    "inference": (
        "LLM providers, credentials, hosted-tool flags, and token budgets "
        "for the server-side gateway."
    ),
    "memory": "Central memory namespace templates, TTL sweeper, and encryption at rest.",
    "users": "Console and agent identities, roles, groups, and elevation privileges.",
    "user_detail": "Edit this user's role, groups, privileges, aliases, and credentials.",
    "security": "RBAC rules, memory grants, elevation review, quotas, and behavioral thresholds.",
    "audit": "Filterable audit log. Every hop through the Corvus Server is recorded here.",
    "system": (
        "Server health, Prometheus scrape dump, and runtime settings. "
        "Bind changes need a restart."
    ),
}

MESSAGE_TYPES: tuple[str, ...] = (
    "tool_call",
    "tool_result",
    "user_query",
    "agent_response",
    "llm_request",
    "llm_response",
    "memory:query",
    "memory:write",
    "memory:delete",
    "memory:grant_request",
)

AUDIT_EVENT_TYPES: tuple[str, ...] = (
    "message_hop",
    "policy_decision",
    "api_mutation",
    "llm_completion",
    "tool_operation",
    "memory_query",
    "memory_write",
    "memory_delete",
    "elevation_approved",
    "elevation_denied",
    "elevation_replay",
    "grant_created",
    "grant_revoked",
    "rule_created",
    "rule_updated",
    "rule_deleted",
    "quota_updated",
    "user_upserted",
    "user_patched",
    "user_deactivated",
    "group_upserted",
    "group_deleted",
    "namespace_quota_updated",
    "pending_replay_delivered",
)

RETENTION_POLICIES: tuple[str, ...] = (
    "agent-private",
    "explicit-grant",
    "ephemeral",
    "shared",
)

WORKSPACE_RETENTION: tuple[str, ...] = ("ephemeral", "persistent")

PRIVILEGES: tuple[str, ...] = (
    "approve_elevation",
    "can_approve_elevation",
    "manage_rules",
)

QUOTA_CLASSES: tuple[str, ...] = ("dev", "prod", "staging")

KNOWN_PLATFORMS: tuple[str, ...] = ("api", "cli", "whatsapp", "telegram", "slack")

_USER_SECRET_KEYS = frozenset({"credential_hash", "pin_hash", "password_hash"})


def humanize_key(key: str) -> str:
    """Title-case a snake_case or colon-delimited key for display."""
    text = str(key or "").replace(":", " ").replace("_", " ").strip()
    if not text:
        return ""
    small = {"of", "at", "in", "for", "and", "or", "per"}
    acronyms = {"llm", "api", "ui", "tcp", "vm", "rbac", "ttl", "hmac"}
    words: list[str] = []
    for index, part in enumerate(text.split()):
        lower = part.lower()
        if lower in acronyms:
            words.append(lower.upper())
        elif index > 0 and lower in small:
            words.append(lower)
        else:
            words.append(part.capitalize())
    return " ".join(words)


def setting_label(key: str) -> str:
    return SETTING_LABELS.get(key, humanize_key(key))


def setting_help(key: str) -> str:
    return SETTING_HELP.get(key, "")


def is_boolean_setting(key: str) -> bool:
    return key in BOOLEAN_SETTING_KEYS


def is_truthy(value: Any) -> bool:
    return value in {True, 1, "1", "true", "True", "yes", "on"}


def annotate_setting(row: dict[str, Any]) -> dict[str, Any]:
    key = str(row.get("key", ""))
    annotated = dict(row)
    annotated["label"] = setting_label(key)
    annotated["help"] = setting_help(key)
    annotated["boolean"] = is_boolean_setting(key)
    annotated["truthy"] = is_truthy(row.get("value")) if annotated["boolean"] else False
    return annotated


def annotate_settings(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [annotate_setting(row) for row in (rows or [])]


def annotate_settings_groups(
    groups: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, list[dict[str, Any]]]:
    return {name: annotate_settings(rows) for name, rows in (groups or {}).items()}


def quota_label(key: str) -> str:
    raw = str(key or "")
    parts = raw.split(":")
    if len(parts) >= 3:
        kind = parts[-1]
        scope = parts[1]
        if kind == "llm_tokens":
            return f"LLM tokens · {scope}"
        if kind in {"memory_writes", "memory_write"}:
            return f"Memory writes · {scope}"
    return humanize_key(raw)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def join_display(value: Any, sep: str = ", ") -> str:
    items = [str(item) for item in as_list(value) if str(item).strip()]
    return sep.join(items) if items else "-"


def redact_user_profile(user: dict[str, Any] | None) -> dict[str, Any]:
    redacted = dict(user or {})
    for key in _USER_SECRET_KEYS:
        if redacted.get(key):
            redacted[key] = "********"
    return redacted


def engine_summary(manifest: dict[str, Any] | None) -> dict[str, Any]:
    data = manifest or {}
    engines = data.get("engines") or {}
    engine1 = engines.get("engine1") or {}
    engine2 = engines.get("engine2") or {}
    engine3 = engines.get("engine3") or {}
    engine4 = engines.get("engine4") or {}
    workspaces = []
    for entry in data.get("workspaces") or []:
        if isinstance(entry, dict):
            workspaces.append(entry.get("workspace_id") or entry.get("id") or "")
        else:
            workspaces.append(str(entry))
    return {
        "tools": as_list(engine1.get("tools")),
        "platforms": as_list(engine2.get("platforms")),
        "providers": as_list(engine3.get("allowed_providers")),
        "models": as_list(engine3.get("allowed_models")),
        "tool_execution_mode": engine3.get("tool_execution_mode") or "local",
        "provider_tools": as_list(engine3.get("provider_tools")),
        "namespaces": as_list(engine4.get("namespaces")),
        "skills": as_list(data.get("skills")),
        "workspaces": [item for item in workspaces if item],
        "rootfs_image": data.get("rootfs_image") or "",
        "memory_mb": (data.get("resource_limits") or {}).get("memory_mb"),
        "vcpu_count": (data.get("resource_limits") or {}).get("vcpu_count"),
    }


def _list_field(container: Any, *keys: str) -> list[str]:
    if not isinstance(container, dict):
        return []
    for key in keys:
        value = container.get(key)
        if value is None:
            continue
        return [str(item) for item in as_list(value)]
    return []


def rule_summary(rule: dict[str, Any] | None) -> dict[str, str]:
    data = rule or {}
    subject = data.get("subject") if isinstance(data.get("subject"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else {}
    action = data.get("action") if isinstance(data.get("action"), dict) else {}
    return {
        "roles": join_display(_list_field(subject, "role", "roles", "group", "groups")),
        "agents": join_display(_list_field(subject, "agent_id", "agent_ids")),
        "engines": join_display(_list_field(obj, "engine", "engines")),
        "action": join_display(_list_field(action, "type", "types")),
        "else": str(data.get("else") or "-"),
    }


def iso_to_datetime_local(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().replace("Z", "").replace(" ", "T")
    if len(text) >= 16:
        return text[:16]
    return text


def datetime_local_to_iso(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().replace(" ", "T")
    if len(text) == 16:
        return f"{text}:00"
    return text


def chat_agent_options(agents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Compact agent rows for the operator chat page (id, status, Engine 3 allowlists)."""
    options: list[dict[str, Any]] = []
    for agent in agents or []:
        summary = engine_summary(agent.get("manifest") if isinstance(agent, dict) else None)
        agent_id = str(agent.get("id") or "")
        if not agent_id:
            continue
        options.append(
            {
                "id": agent_id,
                "status": str(agent.get("status") or "stopped"),
                "providers": summary["providers"] or ["stub"],
                "models": summary["models"] or ["stub-v1"],
            }
        )
    return options


def fleet_counts(agents: list[dict[str, Any]] | None) -> dict[str, int]:
    rows = agents or []
    running = sum(1 for row in rows if row.get("status") == "running")
    failed = sum(1 for row in rows if row.get("status") in {"failed", "degraded"})
    stopped = sum(1 for row in rows if row.get("status") in {"stopped", None, ""})
    other = max(0, len(rows) - running - failed - stopped)
    return {
        "total": len(rows),
        "running": running,
        "stopped": stopped,
        "failed": failed,
        "other": other,
    }


def ids_of(rows: list[dict[str, Any]] | None, *keys: str) -> list[str]:
    found: list[str] = []
    for row in rows or []:
        for key in keys:
            value = row.get(key)
            if value:
                found.append(str(value))
                break
    return found

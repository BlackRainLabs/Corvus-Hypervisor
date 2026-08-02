"""Tool execution mode enforcement for the LLM gateway."""

from __future__ import annotations

import json
from typing import Any, Literal

from corvus.llm.registry import ProviderConfig
from corvus.server.catalog import DEFAULT_CATALOG, CapabilityCatalog

ToolExecutionMode = Literal["local", "hybrid"]

# OpenAI and similar provider-native tool types (not Corvus-local function tools).
PROVIDER_NATIVE_TOOL_TYPES = frozenset(
    {
        "web_search",
        "web_search_preview",
        "code_interpreter",
        "file_search",
        "computer_use_preview",
        "mcp",
    }
)

# finish_reason values that may indicate opaque provider-side tool execution.
OPAQUE_PROVIDER_FINISH_REASONS = frozenset({"tool_calls", "function_call"})


def parse_tool_execution_mode(engine3: dict[str, Any]) -> ToolExecutionMode:
    mode = str(engine3.get("tool_execution_mode", "local"))
    if mode not in ("local", "hybrid"):
        return "local"
    return mode  # type: ignore[return-value]


def normalize_tools_schema(tools_schema: Any) -> list[dict[str, Any]]:
    if tools_schema is None:
        return []
    if isinstance(tools_schema, list):
        return [item for item in tools_schema if isinstance(item, dict)]
    if isinstance(tools_schema, dict):
        tools = tools_schema.get("tools")
        if isinstance(tools, list):
            return [item for item in tools if isinstance(item, dict)]
        return [tools_schema]
    return []


def function_tool_names(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for entry in tools:
        tool_type = str(entry.get("type", "function"))
        if tool_type in PROVIDER_NATIVE_TOOL_TYPES:
            continue
        if tool_type == "function":
            fn = entry.get("function") or {}
            name = fn.get("name")
            if name:
                names.append(str(name))
    return names


def filter_local_tools_schema(
    tools_schema: Any,
    *,
    allowed_tools: set[str],
    catalog: CapabilityCatalog = DEFAULT_CATALOG,
) -> list[dict[str, Any]]:
    """Keep only function tools allowed by manifest and catalog; drop provider-native types."""
    filtered: list[dict[str, Any]] = []
    for entry in normalize_tools_schema(tools_schema):
        tool_type = str(entry.get("type", "function"))
        if tool_type in PROVIDER_NATIVE_TOOL_TYPES:
            continue
        if tool_type != "function":
            continue
        fn = entry.get("function") or {}
        name = str(fn.get("name", ""))
        if name not in allowed_tools or name not in catalog.tools:
            continue
        filtered.append(entry)
    return filtered


def validate_provider_tools(
    provider_tools: list[str],
    *,
    provider_id: str,
    provider: ProviderConfig,
) -> tuple[list[str], str | None]:
    if not provider_tools:
        return [], None
    if not provider.hosted_tools_allowed:
        return [], "provider does not allow hosted tools"
    allowed: list[str] = []
    for entry in provider_tools:
        if ":" not in entry:
            return [], f"invalid provider_tools entry: {entry}"
        entry_provider, tool_name = entry.split(":", 1)
        if entry_provider != provider_id:
            return [], f"provider_tools entry {entry} does not match provider {provider_id}"
        if tool_name not in provider.allowed_hosted_tools:
            return [], f"hosted tool not allowed: {tool_name}"
        allowed.append(tool_name)
    return allowed, None


def build_provider_tool_entries(tool_names: list[str]) -> list[dict[str, Any]]:
    return [{"type": name} for name in tool_names]


def provider_tools_from_manifest(
    engine3: dict[str, Any],
    *,
    provider_id: str,
) -> list[str]:
    if parse_tool_execution_mode(engine3) != "hybrid":
        return []
    raw = engine3.get("provider_tools") or []
    selected: list[str] = []
    for entry in raw:
        text = str(entry)
        if text.startswith(f"{provider_id}:"):
            selected.append(text.split(":", 1)[1])
    return selected


def detect_opaque_provider_execution(
    *,
    finish_reason: str | None,
    tool_calls: list[dict[str, Any]],
    content: str | None,
) -> bool:
    if tool_calls:
        return False
    if finish_reason in OPAQUE_PROVIDER_FINISH_REASONS:
        return True
    if finish_reason == "stop" and content:
        return False
    return False


def parse_tool_call_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {"text": raw}
    return {}

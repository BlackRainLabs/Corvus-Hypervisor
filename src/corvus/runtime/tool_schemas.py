"""Build OpenAI-style tool schemas from the server tool catalog."""

from __future__ import annotations

from typing import Any

from corvus.server.catalog import DEFAULT_CATALOG, CapabilityCatalog

_TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    "echo": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo back"},
        },
        "required": ["text"],
    },
    "terminal": {
        "type": "object",
        "properties": {
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Command argv (allowlisted commands only)",
            },
        },
        "required": ["argv"],
    },
    "file_read": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path relative to CORVUS_TOOL_WORKSPACE_ROOT",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Max bytes to return (capped at 65536)",
            },
        },
        "required": ["path"],
    },
}


def build_tools_schema(
    tool_names: list[str],
    catalog: CapabilityCatalog = DEFAULT_CATALOG,
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name in tool_names:
        if name not in catalog.tools:
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Execute the {name} tool",
                    "parameters": _TOOL_PARAMETERS.get(
                        name,
                        {"type": "object", "properties": {}},
                    ),
                },
            }
        )
    return tools

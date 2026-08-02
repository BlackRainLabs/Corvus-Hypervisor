"""Execute manifest-allowed tools inside Engine 1."""

from __future__ import annotations

from typing import Any

from corvus.tools.registry import get_tool_runner


class ToolExecutionError(Exception):
    pass


def run_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    runner = get_tool_runner(tool_name)
    if runner is None:
        raise ToolExecutionError(f"unknown tool: {tool_name}")
    result = runner(arguments)
    if not isinstance(result, dict):
        raise ToolExecutionError(f"tool returned non-object: {tool_name}")
    return result

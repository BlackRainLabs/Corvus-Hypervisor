"""Registry of Engine 1 local tool implementations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from corvus.skills import runner as skill_runner
from corvus.tools import echo as echo_tool
from corvus.tools import file_read as file_read_tool
from corvus.tools import terminal as terminal_tool

ToolRunner = Callable[[dict[str, Any]], dict[str, Any]]


def _skill_read(arguments: dict[str, Any]) -> dict[str, Any]:
    return skill_runner.run_skill_read(arguments)


def _skill_run(arguments: dict[str, Any]) -> dict[str, Any]:
    return skill_runner.run_skill_run(arguments)


TOOL_REGISTRY: dict[str, ToolRunner] = {
    "echo": echo_tool.run,
    "terminal": terminal_tool.run,
    "file_read": file_read_tool.run,
    "skill_read": _skill_read,
    "skill_run": _skill_run,
}


def get_tool_runner(tool_name: str) -> ToolRunner | None:
    return TOOL_REGISTRY.get(tool_name)

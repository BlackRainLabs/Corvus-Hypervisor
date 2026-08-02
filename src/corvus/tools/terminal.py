"""In-VM terminal tool — runs only after server tool_call approval."""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

ALLOWED_COMMANDS = frozenset({"echo", "pwd", "ls", "whoami", "date", "uname"})


class TerminalToolError(Exception):
    pass


def _argv_from_arguments(arguments: dict[str, Any]) -> list[str]:
    argv_raw = arguments.get("argv")
    if isinstance(argv_raw, list) and argv_raw:
        return [str(part) for part in argv_raw]
    command = arguments.get("command")
    if isinstance(command, str) and command.strip():
        return shlex.split(command)
    raise TerminalToolError("terminal requires argv or command")


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    argv = _argv_from_arguments(arguments)
    if not argv:
        raise TerminalToolError("empty command")

    executable = argv[0]
    if executable not in ALLOWED_COMMANDS:
        raise TerminalToolError(f"command not allowed in agent VM: {executable}")

    timeout = float(arguments.get("timeout_seconds", 10))
    timeout = min(max(timeout, 1.0), 30.0)

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": argv,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exit_code": completed.returncode,
    }

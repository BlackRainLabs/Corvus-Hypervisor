"""Terminal tool unit tests."""

from __future__ import annotations

import pytest

from corvus.tools.terminal import TerminalToolError, run


def test_terminal_runs_allowed_echo():
    result = run({"argv": ["echo", "hello vm"]})
    assert result["exit_code"] == 0
    assert "hello vm" in result["stdout"]


def test_terminal_rejects_disallowed_command():
    with pytest.raises(TerminalToolError, match="not allowed"):
        run({"argv": ["bash", "-c", "echo nope"]})

"""file_read tool and registry tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from corvus.tools.file_read import run as file_read_run
from corvus.tools.registry import TOOL_REGISTRY, get_tool_runner
from corvus.tools.runner import ToolExecutionError, run_tool


def test_registry_includes_builtins():
    assert set(TOOL_REGISTRY) >= {"echo", "terminal", "file_read"}
    assert get_tool_runner("echo") is not None
    assert get_tool_runner("missing") is None


def test_run_tool_echo_via_registry():
    assert run_tool("echo", {"text": "hi"}) == {"text": "hi"}


def test_run_tool_unknown_raises():
    with pytest.raises(ToolExecutionError, match="unknown tool"):
        run_tool("nope", {})


def test_file_read_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORVUS_TOOL_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "notes.txt").write_text("hello workspace", encoding="utf-8")
    result = file_read_run({"path": "notes.txt"})
    assert result["content"] == "hello workspace"
    assert result["path"] == "notes.txt"
    assert result["truncated"] is False


def test_file_read_blocks_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORVUS_TOOL_WORKSPACE_ROOT", str(tmp_path))
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    result = file_read_run({"path": "../secret.txt"})
    assert result["error_code"] == "FILE_READ_PATH_DENIED"


def test_file_read_truncates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORVUS_TOOL_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "big.txt").write_text("abcdef", encoding="utf-8")
    result = file_read_run({"path": "big.txt", "max_bytes": 3})
    assert result["content"] == "abc"
    assert result["truncated"] is True

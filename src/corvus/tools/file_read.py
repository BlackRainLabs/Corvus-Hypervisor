"""Builtin file_read tool — read files under a workspace root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 64 * 1024


def workspace_root() -> Path:
    return Path(os.environ.get("CORVUS_TOOL_WORKSPACE_ROOT", "/workspace")).resolve()


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(arguments.get("path", "")).strip()
    if not raw_path:
        return {"error": "path is required", "error_code": "FILE_READ_PATH_REQUIRED"}

    root = workspace_root()
    candidate = (
        (root / raw_path).resolve()
        if not Path(raw_path).is_absolute()
        else Path(raw_path).resolve()
    )
    try:
        candidate.relative_to(root)
    except ValueError:
        return {"error": "path escapes workspace root", "error_code": "FILE_READ_PATH_DENIED"}

    if not candidate.is_file():
        return {"error": "file not found", "error_code": "FILE_READ_NOT_FOUND"}

    max_bytes = int(arguments.get("max_bytes", DEFAULT_MAX_BYTES))
    max_bytes = max(1, min(max_bytes, DEFAULT_MAX_BYTES))
    data = candidate.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "error": "file is not valid UTF-8",
            "error_code": "FILE_READ_NOT_TEXT",
            "path": str(candidate.relative_to(root)),
        }
    return {
        "path": str(candidate.relative_to(root)),
        "content": content,
        "truncated": truncated,
        "bytes": len(data),
    }

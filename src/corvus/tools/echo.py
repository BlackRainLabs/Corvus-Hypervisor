"""Builtin echo tool for Engine 1 smoke tests."""

from __future__ import annotations

from typing import Any


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    text = arguments.get("text", arguments.get("message", ""))
    return {"text": str(text)}

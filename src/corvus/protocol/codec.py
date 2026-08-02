"""NDJSON codec for FrameworkMessage."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from corvus.protocol.models import FrameworkMessage


class CodecError(ValueError):
    """Raised when a message cannot be encoded or decoded."""


def encode_message(message: FrameworkMessage) -> str:
    data = message.model_dump(mode="json", by_alias=True)
    return json.dumps(data, separators=(",", ":"))


def decode_line(line: str) -> FrameworkMessage:
    line = line.strip()
    if not line:
        raise CodecError("Empty line")
    try:
        data: dict[str, Any] = json.loads(line)
        return FrameworkMessage.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CodecError(str(exc)) from exc

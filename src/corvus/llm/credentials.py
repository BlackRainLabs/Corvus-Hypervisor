"""Resolve provider credentials from opaque refs (never log values)."""

from __future__ import annotations

import os
from pathlib import Path


class CredentialResolutionError(Exception):
    pass


def resolve_credential(credential_ref: str) -> str | None:
    ref = credential_ref.strip()
    if not ref or ref.lower() == "none":
        return None
    if ref.startswith("env:"):
        value = os.environ.get(ref[4:])
        if not value:
            raise CredentialResolutionError(f"environment variable not set: {ref[4:]}")
        return value
    if ref.startswith("file:"):
        path = Path(ref[5:])
        if not path.is_file():
            raise CredentialResolutionError(f"credential file not found: {path}")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise CredentialResolutionError(f"credential file empty: {path}")
        return value
    raise CredentialResolutionError(f"unsupported credential_ref scheme: {ref}")

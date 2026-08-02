"""LLM credential resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from corvus.llm.credentials import CredentialResolutionError, resolve_credential


def test_resolve_none():
    assert resolve_credential("none") is None
    assert resolve_credential("") is None


def test_resolve_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CORVUS_TEST_LLM_KEY", "secret-value")
    assert resolve_credential("env:CORVUS_TEST_LLM_KEY") == "secret-value"


def test_resolve_env_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CORVUS_MISSING_LLM_KEY", raising=False)
    with pytest.raises(CredentialResolutionError, match="not set"):
        resolve_credential("env:CORVUS_MISSING_LLM_KEY")


def test_resolve_file(tmp_path: Path):
    key_file = tmp_path / "api_key"
    key_file.write_text("file-secret\n", encoding="utf-8")
    assert resolve_credential(f"file:{key_file}") == "file-secret"


def test_resolve_file_missing(tmp_path: Path):
    with pytest.raises(CredentialResolutionError, match="not found"):
        resolve_credential(f"file:{tmp_path / 'missing'}")


def test_resolve_unsupported_scheme():
    with pytest.raises(CredentialResolutionError, match="unsupported"):
        resolve_credential("vault:secret/key")

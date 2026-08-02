"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from corvus.server.bootstrap import (
    FULL_TEST_MANIFEST,
    FULL_TEST_MANIFEST_HASH,
    TEST_AGENT_ID,
    AppContext,
)
from corvus.server.config import ServerConfig


@pytest_asyncio.fixture
async def app_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = ServerConfig(
        db_path=tmp_path / "test.db",
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=0,
        vsock_host_cid=2,
        vsock_port=4040,
        mgmt_host="127.0.0.1",
        mgmt_port=0,
        api_key="test-key",
        rules_path=Path(__file__).resolve().parents[1] / "config" / "default_rules.yaml",
        turn_timeout_seconds=300,
        max_chain_depth=16,
        session_ttl_hours=24,
        vm_state_dir=tmp_path / "vms",
        memory_sweep_interval_seconds=86400.0,
        memory_soft_delete_retention_hours=24,
        elevation_sweep_interval_seconds=86400.0,
        elevation_ttl_hours=1,
        elevation_webhook_url=None,
        behavioral_grant_denial_window_minutes=10,
        behavioral_grant_denial_threshold=3,
        behavioral_cross_agent_window_minutes=1,
        behavioral_cross_agent_threshold=10,
        behavioral_rate_baseline_minutes=60,
        behavioral_rate_zscore_threshold=3.0,
        behavioral_tool_zscore_threshold=3.0,
        behavioral_counter_retention_hours=24,
        memory_encryption_enabled=False,
        memory_master_key=None,
        memory_writes_daily_limit=10_000,
        llm_providers_path=Path(__file__).resolve().parents[1] / "config" / "llm_providers.yaml",
        llm_default_provider="stub",
        llm_request_timeout_seconds=60.0,
        llm_tokens_daily_limit=100_000,
    )
    monkeypatch.setenv("CORVUS_USE_TCP", "1")
    monkeypatch.setenv("CORVUS_VM_STATE_DIR", str(tmp_path / "vms"))
    monkeypatch.setenv("CORVUS_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CORVUS_KERNEL_PATH", str(tmp_path / "artifacts" / "vmlinux"))
    monkeypatch.setenv("CORVUS_ROOTFS_PATH", str(tmp_path / "artifacts" / "rootfs.ext4"))
    ctx = AppContext(config)
    await ctx.startup()
    yield ctx
    await ctx.shutdown()


@pytest_asyncio.fixture
async def full_manifest_agent(app_ctx):
    """Register test-agent-01 with tools, memory, and skills for integration tests."""
    await app_ctx.db.upsert_agent(TEST_AGENT_ID, FULL_TEST_MANIFEST_HASH, FULL_TEST_MANIFEST)
    yield
    from corvus.server.bootstrap import TEST_MANIFEST, TEST_MANIFEST_HASH

    await app_ctx.db.upsert_agent(TEST_AGENT_ID, TEST_MANIFEST_HASH, TEST_MANIFEST)

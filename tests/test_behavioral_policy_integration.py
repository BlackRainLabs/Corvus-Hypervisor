"""Behavioral policy integration tests."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from test_engine4_memory_integration import (
    _engine4_client,
    _register_turn,
    _start_node_stack,
)

from corvus.management.api import create_app
from corvus.protocol.errors import ErrorCode
from corvus.runtime.memory_client import (
    build_memory_query_key,
    is_elevation_required,
    parse_memory_response,
)
from corvus.server.bootstrap import TEST_AGENT_ID
from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest


@pytest.mark.asyncio
async def test_repeated_grant_denials_denies_fifth_cross_agent_query(
    app_ctx, tmp_path, full_manifest_agent
):
    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)
    await app_ctx.db.create_memory_record(
        agent_id="other-agent",
        namespace="private",
        key="shared-note",
        content="cross-agent secret",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-behavioral-deny"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            namespace="private",
            key="shared-note",
            target_agent_id="other-agent",
        )

        for _ in range(4):
            denied = parse_memory_response(await client.submit_and_wait(query_msg))
            assert is_elevation_required(denied)

        fifth = parse_memory_response(await client.submit_and_wait(query_msg))
        assert fifth.error_code == ErrorCode.SERVER_RBAC_DENIED.value
        assert not is_elevation_required(fifth)

        logs = await app_ctx.audit.query_logs(agent_id=TEST_AGENT_ID, limit=20)
        deny_logs = [
            log
            for log in logs
            if log["event_type"] == "policy_decision" and log["decision"] == "deny"
        ]
        assert deny_logs
        assert "deny-repeated-grant-denials" in deny_logs[0]["matched_rules"]
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_simulate_behavioral_override_denies(app_ctx):

    app = create_app(app_ctx)
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": app_ctx.config.api_key}
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            "/v1/rules/simulate",
            headers=headers,
            json={
                "message": {
                    "source": {
                        "agent_id": TEST_AGENT_ID,
                        "engine": "engine4",
                        "vm_id": "vm",
                    },
                    "type": "memory:query",
                    "payload": {
                        "target_agent_id": "other-agent",
                        "namespace": "private",
                    },
                },
                "context": {
                    "correlation_chain_valid": True,
                    "behavioral_signals": {"repeated_grant_denials": 4},
                },
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "deny"
    matched = [rule["id"] for rule in body["matched_rules"] if rule["conditions_passed"]]
    assert "deny-repeated-grant-denials" in matched

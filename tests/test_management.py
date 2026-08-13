"""Management API tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.llm.dummy_server import DEFAULT_SUCCESS_MESSAGE, DummyLlmServer
from corvus.llm.registry import ProviderConfig
from corvus.management.api import create_app
from corvus.server.bootstrap import TEST_AGENT_ID


@pytest.mark.asyncio
async def test_register_agent_and_simulate(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/agents",
            headers=headers,
            json={
                "id": "sim-agent",
                "manifest": {"manifest_version": "1.0", "engines": {}},
            },
        )
        assert resp.status_code == 200
        assert "manifest_hash" in resp.json()

        manifest = await client.get("/v1/agents/sim-agent/manifest", headers=headers)
        assert manifest.status_code == 200
        assert manifest.json()["manifest"]["skills"] == []
        assert manifest.json()["manifest"]["engines"]["engine3"]["allowed_providers"] == ["stub"]

        sim = await client.post(
            "/v1/rules/simulate",
            headers=headers,
            json={
                "message": {
                    "source": {"agent_id": "test-agent-01", "engine": "engine3"},
                    "type": "memory:query",
                    "tags": {"triggered_by": "agent_initiated"},
                    "payload": {},
                },
                "context": {"user_id": "test-user", "correlation_chain_valid": True},
            },
        )
        assert sim.status_code == 200
        body = sim.json()
        assert body["decision"] == "deny"
        assert body["effective_error_code"] == "SERVER_RBAC_DENIED"


@pytest.mark.asyncio
async def test_register_agent_rejects_unknown_catalog_selection(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/agents",
            headers=headers,
            json={
                "id": "bad-agent",
                "manifest": {
                    "manifest_version": "1.0",
                    "engines": {"engine1": {"tools": ["unknown-tool"]}},
                },
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "MANIFEST_CATALOG_INVALID"


@pytest.mark.asyncio
async def test_catalog_and_health_endpoints(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tools = await client.get("/v1/catalog/tools", headers=headers)
        assert tools.status_code == 200
        assert tools.json()["tools"][0]["name"] == "echo"

        providers = await client.get("/v1/catalog/llm-providers", headers=headers)
        assert providers.status_code == 200
        provider_ids = {entry["provider_id"] for entry in providers.json()["llm_providers"]}
        assert "openai" in provider_ids
        assert "stub" in provider_ids
        for entry in providers.json()["llm_providers"]:
            assert "credential_ref" not in entry

        workspaces = await client.get("/v1/catalog/workspaces", headers=headers)
        assert workspaces.status_code == 200
        namespace_names = {
            namespace["name"] for namespace in workspaces.json()["memory_namespaces"]
        }
        assert namespace_names == {"private", "shared-knowledge"}
        shared = next(
            namespace
            for namespace in workspaces.json()["memory_namespaces"]
            if namespace["name"] == "shared-knowledge"
        )
        assert set(shared["quota"]) == {
            "max_records",
            "max_record_bytes",
            "default_ttl_seconds",
        }

        health = await client.get("/v1/health", headers=headers)
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["server"]["active_sessions"] == 0
        assert health.json()["server"]["memory_sweeper_running"] is True
        assert health.json()["server"]["elevation_sweeper_running"] is True
        assert "pending_replay_depth" in health.json()["server"]


@pytest.mark.asyncio
async def test_audit_logs_after_simulation(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/rules",
            headers=headers,
            json={
                "id": "temp-rule",
                "priority": 10,
                "subject": {"role": ["researcher"]},
                "object": {"engine": ["engine2"]},
                "action": {"type": ["ping"]},
                "effect": "allow",
            },
        )
        logs = await client.get("/v1/audit/logs", headers=headers)
        assert logs.status_code == 200
        assert len(logs.json()["logs"]) >= 1


@pytest.mark.asyncio
async def test_agents_list_includes_vm_status(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/agents", headers=headers)
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert len(agents) >= 1
        assert agents[0]["status"] == "stopped"
        assert agents[0]["vm_instance_id"] is None


@pytest.mark.asyncio
async def test_launch_agent_without_artifacts(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/agents/test-agent-01/launch", headers=headers)
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "VM_ARTIFACT_MISSING"


@pytest.mark.asyncio
async def test_rule_crud_and_validation(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post(
            "/v1/rules",
            headers=headers,
            json={
                "id": "invalid-rule",
                "condition": {"unknown_condition": True},
            },
        )
        assert invalid.status_code == 422

        created = await client.post(
            "/v1/rules",
            headers=headers,
            json={
                "id": "api-rule",
                "priority": 1,
                "subject": {"role": ["researcher"]},
                "object": {"engine": ["engine2"]},
                "action": {"type": ["ping"]},
                "effect": "allow",
            },
        )
        assert created.status_code == 200

        updated = await client.put(
            "/v1/rules/api-rule",
            headers=headers,
            json={
                "id": "ignored",
                "priority": 2,
                "subject": {"groups": ["research"]},
                "object": {"engine": ["engine2"]},
                "action": {"type": ["ping"]},
                "effect": "allow",
            },
        )
        assert updated.status_code == 200

        deleted = await client.delete("/v1/rules/api-rule", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_users_grants_quotas_elevations_and_audit_filters(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post(
            "/v1/users",
            headers=headers,
            json={
                "id": "cli-user",
                "role": "operator",
                "groups": ["ops"],
                "allowed_agents": ["test-agent-01"],
                "pin": "9999",
                "aliases": [
                    {
                        "platform": "whatsapp",
                        "value": "+15550109999",
                        "verified": True,
                        "auth_method": "phone_number",
                    }
                ],
            },
        )
        assert user.status_code == 200

        grant = await client.post(
            "/v1/grants",
            headers=headers,
            json={
                "subject_agent": "test-agent-01",
                "target_agent": "other-agent",
                "namespace": "private",
                "permissions": ["read"],
                "created_by": "test",
            },
        )
        assert grant.status_code == 200
        grant_id = grant.json()["id"]

        grants = await client.get(f"/v1/grants?grant_id={grant_id}", headers=headers)
        assert grants.status_code == 200

        sim = await client.post(
            "/v1/rules/simulate",
            headers=headers,
            json={
                "message": {
                    "source": {"agent_id": "test-agent-01", "engine": "engine4"},
                    "type": "memory:query",
                    "tags": {"triggered_by": "agent_initiated"},
                    "payload": {
                        "target_agent_id": "other-agent",
                        "namespace": "private",
                    },
                },
                "context": {"correlation_chain_valid": True},
            },
        )
        assert sim.status_code == 200
        assert sim.json()["decision"] == "allow"
        assert sim.json()["grant_evaluation"]["grant_id"] == grant_id

        quota = await client.patch(
            "/v1/quotas/user:test-user:llm_tokens:daily",
            headers=headers,
            json={"limit": 10, "used": 2, "window_type": "daily"},
        )
        assert quota.status_code == 200

        elevations = await client.get("/v1/elevations", headers=headers)
        assert elevations.status_code == 200

        logs = await client.get("/v1/audit/logs?event_type=grant_created", headers=headers)
        assert logs.status_code == 200
        assert logs.json()["logs"][0]["details"]["grant_id"] == grant_id


@pytest.mark.asyncio
async def test_agent_namespace_quota_control_plane_api(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/agents",
            headers=headers,
            json={
                "id": "memory-agent",
                "manifest": {
                    "manifest_version": "1.0",
                    "engines": {
                        "engine4": {"namespaces": ["private", "shared-knowledge"]}
                    },
                },
            },
        )
        assert created.status_code == 200

        namespaces = await client.get("/v1/agents/memory-agent/namespaces", headers=headers)
        assert namespaces.status_code == 200
        body = namespaces.json()
        assert [item["namespace"] for item in body["namespaces"]] == [
            "private",
            "shared-knowledge",
        ]
        assert body["namespaces"][0]["source"] == "catalog_default"
        assert body["namespaces"][0]["quota"]["max_records"] == 1000

        patched = await client.patch(
            "/v1/agents/memory-agent/namespaces/shared-knowledge",
            headers=headers,
            json={
                "max_records": 25,
                "max_record_bytes": 4096,
                "default_ttl_seconds": 3600,
            },
        )
        assert patched.status_code == 200
        patched_body = patched.json()
        assert patched_body["source"] == "agent_override"
        assert patched_body["quota"] == {
            "max_records": 25,
            "max_record_bytes": 4096,
            "default_ttl_seconds": 3600,
        }

        logs = await client.get(
            "/v1/audit/logs?event_type=namespace_quota_updated",
            headers=headers,
        )
        assert logs.status_code == 200
        assert logs.json()["logs"][0]["details"]["agent_id"] == "memory-agent"
        assert logs.json()["logs"][0]["details"]["namespace"] == "shared-knowledge"

        invalid = await client.patch(
            "/v1/agents/memory-agent/namespaces/shared",
            headers=headers,
            json={
                "max_records": 25,
                "max_record_bytes": 4096,
                "default_ttl_seconds": None,
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "NAMESPACE_TEMPLATE_INVALID"


@pytest.mark.asyncio
async def test_elevation_approval_requires_admin_or_privilege(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)
    elevation_id = await app_ctx.db.create_elevation(
        message={"type": "tool_call"},
        context={"reason": "dangerous"},
        expires_at="2999-01-01T00:00:00+00:00",
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post(
            f"/v1/elevations/{elevation_id}/approve",
            headers=headers,
            json={"approver_user_id": "test-user", "pin": "1234"},
        )
        assert denied.status_code == 403

        bad_pin = await client.post(
            f"/v1/elevations/{elevation_id}/approve",
            headers=headers,
            json={"approver_user_id": "admin-user", "pin": "bad"},
        )
        assert bad_pin.status_code == 403

        approved = await client.post(
            f"/v1/elevations/{elevation_id}/approve",
            headers=headers,
            json={"approver_user_id": "admin-user", "pin": "0000"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_agent_chat_stub_echoes_user_text(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/v1/agents/{TEST_AGENT_ID}/chat",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hello stub"}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["provider"] == "stub"
        assert body["model"] == "stub-v1"
        assert "hello stub" in body["reply"]
        assert body["correlation_id"]

        missing = await client.post(
            "/v1/agents/does-not-exist/chat",
            headers=headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "AGENT_NOT_FOUND"

        denied = await client.post(
            f"/v1/agents/{TEST_AGENT_ID}/chat",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "provider": "openai",
                "model": "gpt-4",
            },
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "LLM_PROVIDER_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_agent_chat_dummy_http(app_ctx, full_manifest_agent):
    dummy = app_ctx.llm.registry.get("dummy-http")
    assert dummy is not None
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with DummyLlmServer() as dummy_llm, AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        app_ctx.llm.registry.providers["dummy-http"] = ProviderConfig(
            provider_id="dummy-http",
            api_base_url=dummy_llm.base_url,
            credential_ref="none",
            supported_models=["dummy-v1"],
        )
        resp = await client.post(
            f"/v1/agents/{TEST_AGENT_ID}/chat",
            headers=headers,
            json={
                "messages": [{"role": "user", "content": "ping dummy"}],
                "provider": "dummy-http",
                "model": "dummy-v1",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["provider"] == "dummy-http"
        assert DEFAULT_SUCCESS_MESSAGE in body["reply"]
        assert "ping dummy" in body["reply"]

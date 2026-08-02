"""Phase 9 Management API: agents/users/groups, catalog CRUD, settings."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app


@pytest.mark.asyncio
async def test_patch_agent_and_reject_unknown_catalog(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/agents",
            headers=headers,
            json={
                "id": "patch-agent",
                "manifest": {"manifest_version": "1.0", "engines": {}},
            },
        )
        assert created.status_code == 200

        patched = await client.patch(
            "/v1/agents/patch-agent",
            headers=headers,
            json={
                "manifest": {
                    "manifest_version": "1.0",
                    "engines": {
                        "engine1": {"tools": ["echo"]},
                        "engine3": {"allowed_providers": ["stub"]},
                    },
                }
            },
        )
        assert patched.status_code == 200
        assert patched.json()["manifest"]["engines"]["engine1"]["tools"] == ["echo"]

        bad = await client.patch(
            "/v1/agents/patch-agent",
            headers=headers,
            json={
                "manifest": {
                    "manifest_version": "1.0",
                    "engines": {"engine1": {"tools": ["no-such-tool"]}},
                }
            },
        )
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "MANIFEST_CATALOG_INVALID"


@pytest.mark.asyncio
async def test_user_patch_and_deactivate(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/v1/users",
            headers=headers,
            json={"id": "phase9-user", "role": "viewer", "pin": "1111"},
        )
        patched = await client.patch(
            "/v1/users/phase9-user",
            headers=headers,
            json={"role": "operator", "groups": ["ops"], "active": True},
        )
        assert patched.status_code == 200
        assert patched.json()["user"]["role"] == "operator"
        assert patched.json()["user"]["groups"] == ["ops"]

        deleted = await client.delete("/v1/users/phase9-user", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["active"] is False
        got = await client.get("/v1/users/phase9-user", headers=headers)
        assert got.json()["user"]["active"] is False


@pytest.mark.asyncio
async def test_groups_crud(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/groups",
            headers=headers,
            json={"id": "ops", "members": ["admin-user"], "rule_ids": []},
        )
        assert created.status_code == 200
        assert created.json()["group"]["id"] == "ops"

        patched = await client.patch(
            "/v1/groups/ops",
            headers=headers,
            json={"members": ["admin-user", "test-user"]},
        )
        assert patched.status_code == 200
        assert "test-user" in patched.json()["group"]["members"]

        member = await client.post(
            "/v1/groups/ops/members",
            headers=headers,
            json={"user_id": "phase9-extra"},
        )
        assert member.status_code == 200
        assert "phase9-extra" in member.json()["group"]["members"]

        listed = await client.get("/v1/groups", headers=headers)
        assert any(g["id"] == "ops" for g in listed.json()["groups"])

        deleted = await client.delete("/v1/groups/ops", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True


@pytest.mark.asyncio
async def test_catalog_crud_tools_and_memory_namespaces(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/catalog/tools",
            headers=headers,
            json={
                "name": "phase9-tool",
                "version": "1.0",
                "entrypoint": "corvus.tools.echo",
                "package_source": "builtin",
                "permissions": [],
                "risk_level": "low",
            },
        )
        assert created.status_code == 200

        tools = await client.get("/v1/catalog/tools", headers=headers)
        assert any(t["name"] == "phase9-tool" for t in tools.json()["tools"])

        ns = await client.post(
            "/v1/catalog/memory-namespaces",
            headers=headers,
            json={
                "name": "phase9-ns",
                "retention_policy": "agent-private",
                "quota": {
                    "max_records": 10,
                    "max_record_bytes": 1024,
                    "default_ttl_seconds": None,
                },
            },
        )
        assert ns.status_code == 200
        assert "phase9-ns" in app_ctx.catalog_store.catalog.memory_namespaces
        assert "phase9-ns" in app_ctx.memory.catalog.memory_namespaces

        deleted = await client.delete(
            "/v1/catalog/tools/phase9-tool", headers=headers
        )
        assert deleted.status_code == 200
        tools_after = await client.get("/v1/catalog/tools", headers=headers)
        assert all(t["name"] != "phase9-tool" for t in tools_after.json()["tools"])


@pytest.mark.asyncio
async def test_settings_get_patch_and_secret_redaction(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        got = await client.get("/v1/settings", headers=headers)
        assert got.status_code == 200
        groups = got.json()["settings"]
        assert "inference" in groups
        assert "system" in groups
        secrets = [s for rows in groups.values() for s in rows if s["secret"]]
        assert secrets
        assert all(s["value"] == "********" for s in secrets)

        patched = await client.patch(
            "/v1/settings",
            headers=headers,
            json={"settings": {"llm_default_provider": "stub", "mgmt_port": 18080}},
        )
        assert patched.status_code == 200
        assert app_ctx.config.llm_default_provider == "stub"
        assert "mgmt_port" in patched.json()["restart_required"]


@pytest.mark.asyncio
async def test_llm_provider_crud_reloads_registry(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.put(
            "/v1/catalog/llm_providers/phase9-llm",
            headers=headers,
            json={
                "provider_id": "phase9-llm",
                "api_base_url": "http://127.0.0.1:9999/v1",
                "credential_ref": "env:PHASE9_KEY",
                "supported_models": ["phase9-v1"],
                "hosted_tools_allowed": False,
                "allowed_hosted_tools": [],
            },
        )
        assert created.status_code == 200
        assert app_ctx.llm_registry.get("phase9-llm") is not None
        assert app_ctx.llm_registry.get("phase9-llm").api_base_url.endswith("/v1")

        public = await client.get("/v1/catalog/llm-providers", headers=headers)
        entry = next(
            p for p in public.json()["llm_providers"] if p["provider_id"] == "phase9-llm"
        )
        assert "credential_ref" not in entry
        assert "api_base_url" in entry
        assert entry["api_base_url"].endswith("/v1")

        deleted = await client.delete(
            "/v1/catalog/llm_providers/phase9-llm", headers=headers
        )
        assert deleted.status_code == 200
        assert app_ctx.llm_registry.get("phase9-llm") is None

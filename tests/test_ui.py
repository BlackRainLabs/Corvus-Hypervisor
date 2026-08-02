"""Operator Console (UI) tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app
from corvus.management.ui_client import (
    COOKIE_NAME,
    session_user_id,
    sign_session_for_user,
    verify_session,
)

# Seeded by AppContext.startup(): admin-user has role "admin" and PIN "0000".
ADMIN_USER = "admin-user"
ADMIN_PIN = "0000"


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://ui-test",
        follow_redirects=False,
    )


async def _login(
    client: AsyncClient, username: str = ADMIN_USER, password: str = ADMIN_PIN
) -> None:
    resp = await client.post(
        "/ui/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/ui/")
    assert COOKIE_NAME in resp.cookies or COOKIE_NAME in {
        c.split("=")[0] for c in resp.headers.get_list("set-cookie")
    }


def test_session_cookie_roundtrip():
    token = sign_session_for_user("secret", "admin-user")
    assert verify_session("secret", token)
    assert session_user_id(token) == "admin-user"
    assert not verify_session("secret", token + "x")
    assert not verify_session("other", token)
    assert not verify_session("secret", None)
    assert not verify_session("secret", "garbage")


@pytest.mark.asyncio
async def test_login_required_redirect(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        resp = await client.get("/ui/")
        assert resp.status_code == 307
        assert resp.headers["location"].endswith("/ui/login")


@pytest.mark.asyncio
async def test_login_rejects_bad_password(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        resp = await client.post(
            "/ui/login", data={"username": ADMIN_USER, "password": "wrong"}
        )
        assert resp.status_code == 303
        assert "err=" in resp.headers["location"]
        assert COOKIE_NAME not in resp.cookies


@pytest.mark.asyncio
async def test_login_rejects_non_console_role(app_ctx):
    # test-user is seeded with role "researcher" (PIN 1234) — not an operator/admin.
    app = create_app(app_ctx)
    async with _client(app) as client:
        resp = await client.post(
            "/ui/login", data={"username": "test-user", "password": "1234"}
        )
        assert resp.status_code == 303
        assert "err=" in resp.headers["location"]
        assert COOKIE_NAME not in resp.cookies


@pytest.mark.asyncio
async def test_login_page_renders(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        resp = await client.get("/ui/login")
        assert resp.status_code == 200
        assert "Operator Console" in resp.text


@pytest.mark.asyncio
async def test_all_nav_routes_render(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        for path, marker in [
            ("/ui/", "Overview"),
            ("/ui/agents", "All Agents"),
            ("/ui/tools", "Tools &amp; Skills"),
            ("/ui/inference", "LLM Providers"),
            ("/ui/memory", "Namespace Catalog"),
            ("/ui/users", "Users &amp; Access"),
            ("/ui/security", "RBAC Rules"),
            ("/ui/audit", "Audit Log"),
            ("/ui/system", "Server Configuration"),
        ]:
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert marker in resp.text, path


@pytest.mark.asyncio
async def test_summary_shows_health(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.get("/ui/")
        assert "Active Sessions" in resp.text
        # HTMX partial endpoint
        partial = await client.get("/ui/partials/health")
        assert partial.status_code == 200
        assert "VMs" in partial.text


@pytest.mark.asyncio
async def test_agents_page_lists_seeded_agent(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.get("/ui/agents")
        assert "test-agent-01" in resp.text


@pytest.mark.asyncio
async def test_agent_create_and_detail(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.post(
            "/ui/agents/create",
            data={"agent_id": "ui-agent", "memory_mb": 512, "vcpu_count": 1},
        )
        assert resp.status_code == 303
        assert "msg=" in resp.headers["location"]
        detail = await client.get("/ui/agents/ui-agent")
        assert detail.status_code == 200
        assert "ui-agent" in detail.text
        assert "Resolved Manifest" in detail.text


@pytest.mark.asyncio
async def test_agent_launch_missing_artifacts_reports_error(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.post("/ui/agents/test-agent-01/launch")
        assert resp.status_code == 303
        # No kernel/rootfs in test env -> surfaced as err flash, not a 500
        assert "err=" in resp.headers["location"] or "msg=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_rule_create_and_delete(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        rule_json = (
            '{"id": "ui-test-rule", "priority": 500, '
            '"subject": {"role": ["researcher"]}, "object": {"engine": ["engine4"]}, '
            '"action": {"type": "memory:query"}, "condition": {}, "effect": "allow"}'
        )
        created = await client.post(
            "/ui/security/rules/create", data={"rule_json": rule_json}
        )
        assert created.status_code == 303
        assert "msg=" in created.headers["location"]
        page = await client.get("/ui/security")
        assert "ui-test-rule" in page.text
        deleted = await client.post("/ui/security/rules/ui-test-rule/delete")
        assert deleted.status_code == 303
        assert "msg=" in deleted.headers["location"]


@pytest.mark.asyncio
async def test_rule_create_invalid_json_reports_error(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.post("/ui/security/rules/create", data={"rule_json": "{not json"})
        assert resp.status_code == 303
        assert "err=" in resp.headers["location"]


@pytest.mark.asyncio
async def test_simulate_returns_decision_fragment(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.post(
            "/ui/security/simulate",
            data={
                "agent_id": "test-agent-01",
                "engine": "engine3",
                "msg_type": "memory:query",
                "triggered_by": "agent_initiated",
                "scope": "local",
                "context_json": '{"user_id": "test-user", "correlation_chain_valid": true}',
                "payload_json": "{}",
            },
        )
        assert resp.status_code == 200
        assert "Decision:" in resp.text


@pytest.mark.asyncio
async def test_grant_create_and_revoke(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        created = await client.post(
            "/ui/security/grants/create",
            data={
                "subject_agent": "agent-a",
                "target_agent": "agent-b",
                "namespace": "shared-knowledge",
                "permissions": ["read"],
            },
        )
        assert created.status_code == 303
        assert "msg=" in created.headers["location"]
        grants = await app_ctx.db.list_grants()
        assert grants
        gid = grants[0]["id"]
        revoked = await client.post(f"/ui/security/grants/{gid}/revoke")
        assert revoked.status_code == 303
        assert "msg=" in revoked.headers["location"]


@pytest.mark.asyncio
async def test_user_create_and_detail(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        created = await client.post(
            "/ui/users/create",
            data={
                "user_id": "ui-user",
                "role": "operator",
                "groups": "research, ops",
                "pin": "4321",
            },
        )
        assert created.status_code == 303
        assert "msg=" in created.headers["location"]
        detail = await client.get("/ui/users/ui-user")
        assert detail.status_code == 200
        assert "ui-user" in detail.text
        assert "operator" in detail.text


@pytest.mark.asyncio
async def test_audit_query_renders(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        # Generate an audit event via a mutation, then browse it.
        await client.post(
            "/ui/users/create", data={"user_id": "audit-user", "role": "viewer"}
        )
        resp = await client.get("/ui/audit", params={"event_type": "user_upserted"})
        assert resp.status_code == 200
        assert "user_upserted" in resp.text


@pytest.mark.asyncio
async def test_system_page_redacts_secrets(app_ctx):
    app = create_app(app_ctx)
    async with _client(app) as client:
        await _login(client)
        resp = await client.get("/ui/system")
        assert resp.status_code == 200
        assert app_ctx.config.api_key not in resp.text
        assert "api_key" in resp.text  # the field name is shown
        assert "********" in resp.text


@pytest.mark.asyncio
async def test_ui_disabled_config(app_ctx):
    object.__setattr__(app_ctx.config, "ui_enabled", False)
    app = create_app(app_ctx)
    async with _client(app) as client:
        resp = await client.get("/ui/login")
        assert resp.status_code == 404

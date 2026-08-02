"""Elevation expiry sweeper tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app
from corvus.server.bootstrap import TEST_AGENT_ID
from corvus.server.elevation_sweeper import ElevationSweeper


@pytest.mark.asyncio
async def test_sweeper_expires_pending_elevations(app_ctx):
    expired_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    elevation_id = await app_ctx.db.create_elevation(
        message={
            "type": "memory:query",
            "source": {"agent_id": TEST_AGENT_ID},
        },
        context={},
        expires_at=expired_at,
        status="pending",
    )

    sweeper = ElevationSweeper(app_ctx.db, interval_seconds=3600)
    expired_count = await sweeper.sweep_once()
    assert expired_count == 1

    elevation = await app_ctx.db.get_elevation(elevation_id)
    assert elevation is not None
    assert elevation["status"] == "expired"


@pytest.mark.asyncio
async def test_approve_expired_elevation_returns_409(app_ctx):
    expired_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    elevation_id = await app_ctx.db.create_elevation(
        message={
            "type": "memory:query",
            "source": {"agent_id": TEST_AGENT_ID},
        },
        context={},
        expires_at=expired_at,
        status="pending",
    )

    app = create_app(app_ctx)
    transport = ASGITransport(app=app)
    headers = {"X-API-Key": app_ctx.config.api_key}
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            f"/v1/elevations/{elevation_id}/approve",
            headers=headers,
            json={"approver_user_id": "admin-user", "pin": "0000"},
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ELEVATION_EXPIRED"

    elevation = await app_ctx.db.get_elevation(elevation_id)
    assert elevation is not None
    assert elevation["status"] == "expired"

"""Management API rate-limit tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app
from corvus.management.rate_limit import SlidingWindowRateLimiter
from corvus.management.ui_client import ApiClient


def test_sliding_window_blocks_after_limit():
    limiter = SlidingWindowRateLimiter(limit=3, window_seconds=60.0)
    assert limiter.allow("k")
    assert limiter.allow("k")
    assert limiter.allow("k")
    assert limiter.allow("k") is False
    assert limiter.retry_after_seconds("k") >= 1


def test_sliding_window_disabled_when_limit_zero():
    limiter = SlidingWindowRateLimiter(limit=0)
    for _ in range(50):
        assert limiter.allow("k")


@pytest.mark.asyncio
async def test_api_returns_429_after_burst(app_ctx):
    app_ctx.config = replace(app_ctx.config, api_rate_limit_per_minute=5)
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        statuses = []
        for _ in range(6):
            resp = await client.get("/v1/health", headers=headers)
            statuses.append(resp.status_code)
        assert statuses[:5] == [200, 200, 200, 200, 200]
        assert statuses[5] == 429
        assert "Retry-After" in resp.headers


@pytest.mark.asyncio
async def test_ui_internal_client_bypasses_rate_limit(app_ctx):
    app_ctx.config = replace(app_ctx.config, api_rate_limit_per_minute=2)
    app = create_app(app_ctx)
    api = ApiClient(app, app_ctx.config.api_key)
    for _ in range(5):
        ok, data, status = await api.call("GET", "/v1/health")
        assert ok is True
        assert status == 200
        assert "status" in data or data.get("ok") is not None or isinstance(data, dict)

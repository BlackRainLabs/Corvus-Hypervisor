"""Prometheus metrics exposition tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app
from corvus.server.metrics import collect_metric_values, render_prometheus_metrics


@pytest.mark.asyncio
async def test_metrics_endpoint_prometheus_format(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/metrics", headers=headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        assert "corvus_active_sessions 0" in body
        assert "corvus_memory_sweeper_running 1" in body
        assert "corvus_elevation_sweeper_running 1" in body
        assert "# TYPE corvus_pending_replay_depth gauge" in body


@pytest.mark.asyncio
async def test_render_prometheus_metrics_from_snapshot(app_ctx):
    from corvus.vm.launcher import VMLauncher

    values = await collect_metric_values(app_ctx, VMLauncher())
    rendered = render_prometheus_metrics(values)
    assert rendered.endswith("\n")
    assert "corvus_vm_registry_total" in rendered

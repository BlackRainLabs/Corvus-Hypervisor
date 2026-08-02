"""Catalog API security tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app


@pytest.mark.asyncio
async def test_llm_providers_strip_credential_ref(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/catalog/llm-providers", headers=headers)
        assert resp.status_code == 200
        providers = resp.json()["llm_providers"]
        assert providers
        for entry in providers:
            assert "provider_id" in entry
            assert "supported_models" in entry
            assert "credential_ref" not in entry
            assert "api_base_url" not in entry

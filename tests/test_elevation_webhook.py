"""Elevation webhook dispatch tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from corvus.server.elevation_notify import (
    _post_webhook,
    _sign_body,
    notify_elevation_pending,
)


def test_sign_body_is_stable():
    body = b'{"a":1}'
    assert _sign_body("secret", body) == _sign_body("secret", body)
    assert _sign_body("secret", body).startswith("sha256=")


@pytest.mark.asyncio
async def test_post_webhook_sends_signature_when_secret_set():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, request=request)

    payload = {"event": "elevation_pending", "elevation_id": "e1"}
    with patch("corvus.server.elevation_notify.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        async def post(url, content=None, headers=None):
            request = httpx.Request("POST", url, content=content, headers=headers)
            return await handler(request)

        client.post = post
        client_cls.return_value = client
        await _post_webhook(
            "http://example.test/hook",
            payload,
            secret="whsec",
        )

    assert "x-corvus-signature" in captured["headers"]
    expected = "sha256=" + hmac.new(
        b"whsec", captured["body"], hashlib.sha256
    ).hexdigest()
    assert captured["headers"]["x-corvus-signature"] == expected
    assert json.loads(captured["body"])["elevation_id"] == "e1"


@pytest.mark.asyncio
async def test_post_webhook_failure_does_not_raise():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    with patch("corvus.server.elevation_notify.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None

        async def post(url, content=None, headers=None):
            request = httpx.Request("POST", url, content=content, headers=headers)
            response = await handler(request)
            response.raise_for_status()
            return response

        client.post = post
        client_cls.return_value = client
        await _post_webhook("http://example.test/hook", {"event": "x"})


def test_notify_noop_without_url():
    notify_elevation_pending(
        None,
        elevation_id="e1",
        agent_id="a1",
        expires_at="soon",
        rule_ids=["r1"],
    )

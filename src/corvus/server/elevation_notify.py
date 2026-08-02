"""Optional webhook dispatch for pending elevation notifications."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _sign_body(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _post_webhook(
    url: str,
    payload: dict[str, Any],
    *,
    secret: str | None = None,
) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Corvus-Signature"] = _sign_body(secret, body)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except Exception:
        logger.exception("elevation webhook dispatch failed url=%s", url)


def notify_elevation_pending(
    webhook_url: str | None,
    *,
    elevation_id: str,
    agent_id: str,
    expires_at: str,
    rule_ids: list[str],
    user_id: str | None = None,
    webhook_secret: str | None = None,
) -> None:
    if not webhook_url:
        return
    payload = {
        "event": "elevation_pending",
        "elevation_id": elevation_id,
        "agent_id": agent_id,
        "expires_at": expires_at,
        "rule_ids": rule_ids,
        "user_id": user_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    asyncio.create_task(
        _post_webhook(webhook_url, payload, secret=webhook_secret)
    )

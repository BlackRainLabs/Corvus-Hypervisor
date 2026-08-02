"""Operator console helpers: in-process API client, session cookies, and sidebar nav.

The console never re-implements validation or audit. UI handlers call the app's
own ``/v1`` JSON endpoints in-process through an httpx ``ASGITransport`` client,
injecting the server-held API key so the browser never has to resend it.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

COOKIE_NAME = "corvus_ui"
SESSION_MAX_AGE_SECONDS = 12 * 3600


class ApiClient:
    """Thin wrapper that calls the app's own ``/v1`` endpoints in-process."""

    def __init__(self, app: Any, api_key: str) -> None:
        self._app = app
        self._api_key = api_key

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> tuple[bool, Any, int]:
        """Return ``(ok, data, status_code)``.

        ``data`` is the parsed JSON body on success, or the endpoint's error
        ``detail`` payload (``{code, message, details}``) on failure.
        """
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://corvus-ui"
        ) as client:
            resp = await client.request(
                method,
                path,
                params=_clean_params(params),
                json=json,
                headers={
                    "X-API-Key": self._api_key,
                    "X-Corvus-Internal": "ui",
                },
            )
        ok = 200 <= resp.status_code < 300
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        if not ok and isinstance(body, dict) and "detail" in body:
            body = body["detail"]
        return ok, body, resp.status_code

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET returning the parsed body (or ``{}`` on failure) for read views."""
        ok, data, _ = await self.call("GET", path, params=params)
        return data if ok else {}


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v not in (None, "")}


def sign_session(secret: str, *, now: float | None = None) -> str:
    return sign_session_for_user(secret, user_id="operator", now=now)


def sign_session_for_user(secret: str, user_id: str, *, now: float | None = None) -> str:
    """Signed session token carrying a user id.

    Format: ``<issued>.<user_id>.<mac>`` where mac signs ``issued|user_id``.
    """
    issued = str(int(now if now is not None else time.time()))
    payload = f"{issued}|{user_id}"
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{user_id}.{mac}"


def verify_session(secret: str, token: str | None, *, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    parts = token.split(".")
    if len(parts) == 2:
        # Backward-compatible: <issued>.<mac>
        issued_str, mac = parts
        expected = hmac.new(secret.encode(), issued_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return False
    elif len(parts) == 3:
        issued_str, user_id, mac = parts
        payload = f"{issued_str}|{user_id}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return False
    else:
        return False
    try:
        issued = int(issued_str)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    return 0 <= current - issued <= SESSION_MAX_AGE_SECONDS


def session_user_id(token: str | None) -> str | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) == 3:
        return parts[1]
    return None


@dataclass(frozen=True)
class NavSub:
    label: str
    anchor: str
    badge: str = ""  # "edit" | "read-only" | ""


@dataclass(frozen=True)
class NavItem:
    id: str
    label: str
    path: str  # appended to the UI path prefix, e.g. "/agents"
    subs: tuple[NavSub, ...] = field(default_factory=tuple)


NAV: tuple[NavItem, ...] = (
    NavItem("summary", "Overview", "/"),
    NavItem(
        "agents",
        "Agents",
        "/agents",
        subs=(
            NavSub("All Agents", "#all-agents", "edit"),
            NavSub("Create Agent", "#create-agent", "edit"),
        ),
    ),
    NavItem(
        "tools",
        "Tools & Skills",
        "/tools",
        subs=(
            NavSub("Tools", "#tools", "edit"),
            NavSub("Skills", "#skills", "edit"),
            NavSub("Workspaces", "#workspaces", "edit"),
            NavSub("Execution Policy", "#exec-policy", "informational"),
        ),
    ),
    NavItem(
        "inference",
        "Inference",
        "/inference",
        subs=(
            NavSub("Providers", "#providers", "edit"),
            NavSub("Token Quotas", "#token-quotas", "edit"),
            NavSub("Runtime Settings", "#runtime-settings", "edit"),
        ),
    ),
    NavItem(
        "memory",
        "Memory",
        "/memory",
        subs=(
            NavSub("Namespaces", "#namespaces", "edit"),
            NavSub("Retention Sweeper", "#sweeper", "edit"),
            NavSub("Encryption", "#encryption", "edit"),
        ),
    ),
    NavItem(
        "users",
        "Users & Access",
        "/users",
        subs=(
            NavSub("Users", "#users", "edit"),
            NavSub("Create User", "#create-user", "edit"),
            NavSub("Roles & Privileges", "#roles", "informational"),
            NavSub("Groups", "#groups", "edit"),
        ),
    ),
    NavItem(
        "security",
        "Security",
        "/security",
        subs=(
            NavSub("RBAC Rules", "#rules", "edit"),
            NavSub("Rule Simulator", "#simulator", "edit"),
            NavSub("Grants", "#grants", "edit"),
            NavSub("Elevations", "#elevations", "edit"),
            NavSub("Quotas & Limits", "#quotas", "edit"),
            NavSub("Behavioral Monitoring", "#behavioral", "edit"),
        ),
    ),
    NavItem("audit", "Audit", "/audit"),
    NavItem(
        "system",
        "System",
        "/system",
        subs=(
            NavSub("Health", "#health", "informational"),
            NavSub("Metrics", "#metrics", "informational"),
            NavSub("Configuration", "#config", "edit"),
        ),
    ),
)

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


@dataclass(frozen=True)
class NavItem:
    id: str
    label: str
    path: str  # appended to the UI path prefix, e.g. "/agents"
    mark: str = ""
    subs: tuple[NavSub, ...] = field(default_factory=tuple)


NAV: tuple[NavItem, ...] = (
    NavItem("summary", "Overview", "/", mark="OV"),
    NavItem(
        "agents",
        "Agents",
        "/agents",
        mark="AG",
        subs=(
            NavSub("All Agents", "#all-agents"),
            NavSub("Create Agent", "#create-agent"),
        ),
    ),
    NavItem(
        "tools",
        "Tools & Skills",
        "/tools",
        mark="TS",
        subs=(
            NavSub("Tools", "#tools"),
            NavSub("Skills", "#skills"),
            NavSub("Workspaces", "#workspaces"),
            NavSub("Execution Policy", "#exec-policy"),
        ),
    ),
    NavItem(
        "inference",
        "Inference",
        "/inference",
        mark="IN",
        subs=(
            NavSub("Providers", "#providers"),
            NavSub("Token Quotas", "#token-quotas"),
            NavSub("Runtime Settings", "#runtime-settings"),
        ),
    ),
    NavItem(
        "memory",
        "Memory",
        "/memory",
        mark="ME",
        subs=(
            NavSub("Namespaces", "#namespaces"),
            NavSub("Retention Sweeper", "#sweeper"),
            NavSub("Encryption", "#encryption"),
        ),
    ),
    NavItem(
        "users",
        "Users & Access",
        "/users",
        mark="US",
        subs=(
            NavSub("Users", "#users"),
            NavSub("Create User", "#create-user"),
            NavSub("Roles & Privileges", "#roles"),
            NavSub("Groups", "#groups"),
        ),
    ),
    NavItem(
        "security",
        "Security",
        "/security",
        mark="SE",
        subs=(
            NavSub("RBAC Rules", "#rules"),
            NavSub("Rule Simulator", "#simulator"),
            NavSub("Grants", "#grants"),
            NavSub("Elevations", "#elevations"),
            NavSub("Quotas & Limits", "#quotas"),
            NavSub("Behavioral Monitoring", "#behavioral"),
        ),
    ),
    NavItem("audit", "Audit", "/audit", mark="AU"),
    NavItem(
        "system",
        "System",
        "/system",
        mark="SY",
        subs=(
            NavSub("Health", "#health"),
            NavSub("Metrics", "#metrics"),
            NavSub("Configuration", "#config"),
        ),
    ),
)

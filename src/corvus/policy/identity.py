"""Channel identity and alias resolution for RBAC facts."""

from __future__ import annotations

from typing import Any

from corvus.policy.models import IdentityResolution
from corvus.server.db import Database


class IdentityResolver:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def resolve(
        self,
        payload: dict[str, Any],
        override_context: dict[str, Any] | None = None,
    ) -> IdentityResolution:
        context = override_context or {}
        channel = str(
            context.get("identity_channel")
            or payload.get("identity_channel")
            or payload.get("platform")
            or "unknown"
        )
        auth_method = str(
            context.get("auth_method")
            or payload.get("auth_method")
            or payload.get("auth", {}).get("method", "none")
        )

        user_id = context.get("user_id") or payload.get("user_id")
        if user_id:
            user = await self.db.get_user(str(user_id))
            if user is None:
                return IdentityResolution(
                    user_id=str(user_id),
                    identity_channel=channel,
                    auth_method=auth_method,
                    reason="unknown_user",
                )
            verified = await self._verify_direct_user(user, payload, context, channel)
            return self._from_user(
                user,
                identity_channel=channel,
                identity_alias=context.get("identity_alias") or payload.get("identity_alias"),
                identity_verified=verified,
                auth_method=auth_method if verified else "unverified",
                reason="direct_user" if verified else "credential_required",
            )

        alias_platform = context.get("alias_platform") or payload.get("alias_platform") or channel
        alias_value = context.get("alias_value") or payload.get("alias_value")
        if not alias_value and isinstance(payload.get("sender"), dict):
            sender = payload["sender"]
            alias_platform = sender.get("platform", alias_platform)
            alias_value = sender.get("id") or sender.get("phone") or sender.get("username")
        if not alias_value:
            alias_value = payload.get("from") or payload.get("phone") or payload.get("username")

        if alias_value:
            user = await self.db.find_user_by_alias(str(alias_platform), str(alias_value))
            if user is None:
                return IdentityResolution(
                    identity_channel=str(alias_platform),
                    identity_alias=str(alias_value),
                    auth_method="alias",
                    reason="unknown_alias",
                )
            aliases = user.get("aliases", [])
            alias = next(
                (
                    item
                    for item in aliases
                    if item.get("platform") == alias_platform and item.get("value") == alias_value
                ),
                {},
            )
            verified = bool(alias.get("verified"))
            return self._from_user(
                user,
                identity_channel=str(alias_platform),
                identity_alias=str(alias_value),
                identity_verified=verified,
                auth_method=str(alias.get("auth_method", "alias")),
                reason="verified_alias" if verified else "unverified_alias",
            )

        return IdentityResolution(identity_channel=channel, auth_method=auth_method)

    async def _verify_direct_user(
        self,
        user: dict[str, Any],
        payload: dict[str, Any],
        context: dict[str, Any],
        channel: str,
    ) -> bool:
        if context.get("identity_verified") is not None:
            return bool(context["identity_verified"])
        if channel not in {"cli", "api"}:
            return True
        secret = (
            context.get("pin")
            or context.get("password")
            or payload.get("pin")
            or payload.get("password")
            or payload.get("auth", {}).get("secret")
        )
        if not secret:
            return False
        return await self.db.verify_user_secret(user["id"], str(secret))

    @staticmethod
    def _from_user(
        user: dict[str, Any],
        *,
        identity_channel: str,
        identity_alias: str | None,
        identity_verified: bool,
        auth_method: str,
        reason: str,
    ) -> IdentityResolution:
        return IdentityResolution(
            user_id=user["id"],
            role=user.get("role", "anonymous"),
            groups=list(user.get("groups", [])),
            privileges=list(user.get("privileges", [])),
            allowed_agents=list(user.get("allowed_agents", [])),
            identity_channel=identity_channel,
            identity_alias=identity_alias,
            identity_verified=identity_verified,
            auth_method=auth_method,
            reason=reason,
        )

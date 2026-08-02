"""Management REST API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from corvus.management.rate_limit import SlidingWindowRateLimiter
from corvus.policy.models import IdentityAlias, PolicyRule
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.server.bootstrap import AppContext
from corvus.server.catalog import DEFAULT_CATALOG
from corvus.server.db import hash_secret
from corvus.server.manifest import (
    AgentManifest,
    canonical_manifest,
    manifest_hash,
    resolve_manifest,
)
from corvus.server.metrics import render_prometheus_metrics_for_context
from corvus.vm.launcher import VMLauncher
from corvus.vm.registry import VMRecord


class AgentCreate(BaseModel):
    id: str
    manifest: AgentManifest


RuleCreate = PolicyRule


class UserCreate(BaseModel):
    id: str
    role: str = "researcher"
    groups: list[str] = Field(default_factory=list)
    privileges: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    aliases: list[IdentityAlias] = Field(default_factory=list)
    pin: str | None = None
    password: str | None = None


class GrantCreate(BaseModel):
    subject_agent: str
    target_agent: str
    namespace: str
    permissions: list[str]
    expires_at: str | None = None
    created_by: str = "api"


class QuotaPatch(BaseModel):
    limit: int
    used: int = 0
    window_type: str = "daily"


class NamespaceQuotaPatch(BaseModel):
    max_records: int = Field(ge=1)
    max_record_bytes: int = Field(ge=1)
    default_ttl_seconds: int | None = Field(default=None, ge=1)


class ElevationDecision(BaseModel):
    approver_user_id: str
    pin: str | None = None
    password: str | None = None
    create_grant: dict[str, Any] | None = None


class SimulateMessage(BaseModel):
    source: dict[str, Any]
    type: str
    tags: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class SimulateRequest(BaseModel):
    message: SimulateMessage
    context: dict[str, Any] = Field(default_factory=dict)


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="Corvus Management API", version="1")
    vm_launcher = VMLauncher()
    rate_limiter = SlidingWindowRateLimiter(
        limit=ctx.config.api_rate_limit_per_minute,
        window_seconds=60.0,
    )

    class ApiRateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if not path.startswith("/v1"):
                return await call_next(request)
            if request.headers.get("x-corvus-internal") == "ui":
                return await call_next(request)
            api_key = request.headers.get("x-api-key") or ""
            client = request.client.host if request.client else "unknown"
            key = f"key:{api_key}" if api_key else f"ip:{client}"
            if not rate_limiter.allow(key):
                retry_after = rate_limiter.retry_after_seconds(key)
                body = (
                    '{"detail":{"code":"API_RATE_LIMITED",'
                    '"message":"rate limit exceeded","details":{}}}'
                )
                return Response(
                    content=body,
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(retry_after)},
                )
            return await call_next(request)

    app.add_middleware(ApiRateLimitMiddleware)

    def require_api_key(x_api_key: str = Header(default="")) -> None:
        if x_api_key != ctx.config.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

    def _error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"code": code, "message": message, "details": details or {}}

    def _vm_payload(vm: VMRecord) -> dict[str, Any]:
        return {
            "vm_instance_id": vm.vm_instance_id,
            "agent_id": vm.agent_id,
            "guest_cid": vm.guest_cid,
            "status": vm.status,
            "manifest_hash": vm.manifest_hash,
            "api_socket": vm.api_socket,
            "vsock_uds": vm.vsock_uds,
            "pid": vm.pid,
            "pid_alive": vm_launcher.registry.pid_is_alive(vm.pid),
            "launch_package_dir": vm.launch_package_dir,
            "stdout_log": vm.stdout_log,
            "stderr_log": vm.stderr_log,
            "created_at": vm.created_at,
            "updated_at": vm.updated_at,
            "last_heartbeat_at": vm.last_heartbeat_at,
            "last_error": vm.last_error,
            "stop_reason": vm.stop_reason,
            "graceful_stop": vm.graceful_stop,
        }

    def _agent_with_vm_status(agent: dict[str, Any]) -> dict[str, Any]:
        vm = vm_launcher.registry.latest_by_agent(agent["id"])
        return {
            **agent,
            "status": vm.status if vm else "stopped",
            "vm_instance_id": vm.vm_instance_id if vm else None,
            "guest_cid": vm.guest_cid if vm else None,
            "last_error": vm.last_error if vm else None,
        }

    def _manifest_namespaces(agent: dict[str, Any]) -> list[str]:
        engine4 = agent["manifest"].get("engines", {}).get("engine4", {})
        return list(engine4.get("namespaces", ["private"]))

    async def _require_agent_namespace(agent_id: str, namespace: str) -> dict[str, Any]:
        agent = await ctx.db.get_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_error("AGENT_NOT_FOUND", "Agent not found"),
            )
        if namespace not in DEFAULT_CATALOG.memory_namespaces:
            raise HTTPException(
                status_code=422,
                detail=_error(
                    "NAMESPACE_TEMPLATE_INVALID",
                    "Namespace is not in the server-owned memory namespace catalog",
                    {"namespace": namespace},
                ),
            )
        if namespace not in _manifest_namespaces(agent):
            raise HTTPException(
                status_code=404,
                detail=_error(
                    "NAMESPACE_NOT_ASSIGNED",
                    "Namespace is not assigned to this agent manifest",
                    {"agent_id": agent_id, "namespace": namespace},
                ),
            )
        return agent

    def _namespace_payload(
        *,
        agent_id: str,
        namespace: str,
        override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        template = DEFAULT_CATALOG.memory_namespaces[namespace]
        quota = template.quota.model_dump(mode="json")
        if override:
            quota.update(
                {
                    "max_records": override["max_records"],
                    "max_record_bytes": override["max_record_bytes"],
                    "default_ttl_seconds": override["default_ttl_seconds"],
                }
            )
        return {
            "agent_id": agent_id,
            "namespace": namespace,
            "retention_policy": template.retention_policy,
            "quota": quota,
            "source": "agent_override" if override else "catalog_default",
        }

    async def _require_elevation_approver(body: ElevationDecision) -> dict[str, Any]:
        user = await ctx.db.get_user(body.approver_user_id)
        if user is None:
            raise HTTPException(
                status_code=403,
                detail=_error("ELEVATION_APPROVER_DENIED", "Unknown approver"),
            )
        secret = body.pin or body.password
        if user.get("credential_hash") and (
            not secret or not await ctx.db.verify_user_secret(user["id"], secret)
        ):
            raise HTTPException(
                status_code=403,
                detail=_error("ELEVATION_APPROVER_DENIED", "Approver credential invalid"),
            )
        privileges = set(user.get("privileges", []))
        groups = set(user.get("groups", []))
        allowed = (
            user.get("role") == "admin"
            or "approve_elevation" in privileges
            or "can_approve_elevation" in privileges
            or "admins" in groups
            or "elevation-approvers" in groups
        )
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=_error("ELEVATION_APPROVER_DENIED", "Approver lacks elevation privilege"),
            )
        return user

    @app.get("/v1/catalog/tools")
    async def catalog_tools(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"tools": DEFAULT_CATALOG.api_payload()["tools"]}

    @app.get("/v1/catalog/skills")
    async def catalog_skills(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"skills": DEFAULT_CATALOG.api_payload()["skills"]}

    @app.get("/v1/catalog/llm-providers")
    async def catalog_llm_providers(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"llm_providers": ctx.llm_registry.public_providers()}

    @app.get("/v1/catalog/workspaces")
    async def catalog_workspaces(_: None = Depends(require_api_key)) -> dict[str, Any]:
        payload = DEFAULT_CATALOG.api_payload()
        return {
            "workspaces": payload["workspaces"],
            "memory_namespaces": payload["memory_namespaces"],
        }

    @app.get("/v1/health")
    async def health(_: None = Depends(require_api_key)) -> dict[str, Any]:
        vms = [_vm_payload(vm) for vm in vm_launcher.status()]
        degraded = [vm for vm in vms if vm["status"] in {"degraded", "failed"}]
        behavioral_activity = await ctx.db.get_latest_behavioral_counter_activity()
        return {
            "status": "degraded" if degraded else "ok",
            "server": {
                "database": "connected",
                "active_sessions": ctx.sessions.active_connection_count,
                "memory_sweeper_running": ctx.memory_sweeper.is_running,
                "elevation_sweeper_running": ctx.elevation_sweeper.is_running,
                "pending_replay_depth": await ctx.db.count_pending_replays(),
                "behavioral_counters_latest_at": behavioral_activity,
            },
            "vm_registry": {
                "total": len(vms),
                "active": len(
                    [
                        vm
                        for vm in vms
                        if vm["status"]
                        in {"launching", "booting", "handshaking", "running", "degraded"}
                    ]
                ),
                "failed": len(degraded),
            },
            "vms": vms,
        }

    @app.get("/v1/metrics")
    async def metrics(_: None = Depends(require_api_key)) -> PlainTextResponse:
        body = await render_prometheus_metrics_for_context(ctx, vm_launcher)
        return PlainTextResponse(
            body,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/v1/agents")
    async def list_agents(_: None = Depends(require_api_key)) -> dict[str, Any]:
        agents = await ctx.db.list_agents()
        return {"agents": [_agent_with_vm_status(a) for a in agents]}

    @app.post("/v1/agents")
    async def create_agent(body: AgentCreate, _: None = Depends(require_api_key)) -> dict[str, Any]:
        try:
            manifest = canonical_manifest(resolve_manifest(body.manifest))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=_error("MANIFEST_CATALOG_INVALID", str(exc)),
            ) from exc
        mh = manifest_hash(manifest)
        await ctx.db.upsert_agent(body.id, mh, manifest)
        for grant in manifest.get("launch_grants", []):
            await ctx.db.create_grant(
                subject_agent=body.id,
                target_agent=grant["target_agent"],
                namespace=grant["namespace"],
                permissions=grant["permissions"],
                expires_at=grant.get("expires_at"),
                created_by="launch_manifest",
            )
        await ctx.audit.log_api_mutation(
            endpoint="POST /v1/agents",
            details={"agent_id": body.id, "manifest_hash": mh},
        )
        return {"id": body.id, "manifest_hash": mh}

    @app.get("/v1/agents/{agent_id}/manifest")
    async def get_agent_manifest(
        agent_id: str, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        agent = await ctx.db.get_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_error("AGENT_NOT_FOUND", "Agent not found"),
            )
        return {
            "agent_id": agent_id,
            "manifest_hash": agent["manifest_hash"],
            "manifest": agent["manifest"],
        }

    @app.get("/v1/agents/{agent_id}/namespaces")
    async def get_agent_namespaces(
        agent_id: str, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        agent = await ctx.db.get_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_error("AGENT_NOT_FOUND", "Agent not found"),
            )
        overrides = {
            quota["namespace"]: quota for quota in await ctx.db.list_namespace_quotas(agent_id)
        }
        namespaces = []
        for namespace in _manifest_namespaces(agent):
            if namespace not in DEFAULT_CATALOG.memory_namespaces:
                continue
            namespaces.append(
                _namespace_payload(
                    agent_id=agent_id,
                    namespace=namespace,
                    override=overrides.get(namespace),
                )
            )
        return {"agent_id": agent_id, "namespaces": namespaces}

    @app.patch("/v1/agents/{agent_id}/namespaces/{namespace}")
    async def patch_agent_namespace(
        agent_id: str,
        namespace: str,
        body: NamespaceQuotaPatch,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        await _require_agent_namespace(agent_id, namespace)
        quota = await ctx.db.upsert_namespace_quota(
            agent_id=agent_id,
            namespace=namespace,
            max_records=body.max_records,
            max_record_bytes=body.max_record_bytes,
            default_ttl_seconds=body.default_ttl_seconds,
        )
        await ctx.audit.log_security_event(
            event_type="namespace_quota_updated",
            details={
                "agent_id": agent_id,
                "namespace": namespace,
                "max_records": body.max_records,
                "max_record_bytes": body.max_record_bytes,
                "default_ttl_seconds": body.default_ttl_seconds,
            },
        )
        return _namespace_payload(agent_id=agent_id, namespace=namespace, override=quota)

    @app.get("/v1/agents/{agent_id}/vms")
    async def get_agent_vms(agent_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        agent = await ctx.db.get_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_error("AGENT_NOT_FOUND", "Agent not found"),
            )
        return {
            "agent_id": agent_id,
            "vms": [
                _vm_payload(vm) for vm in vm_launcher.registry.list_by_agent(agent_id)
            ],
        }

    @app.post("/v1/agents/{agent_id}/launch")
    async def launch_agent(agent_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        agent = await ctx.db.get_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=_error("AGENT_NOT_FOUND", "Agent not found"),
            )
        try:
            record = await vm_launcher.launch(
                agent_id,
                agent["manifest"],
                manifest_hash_value=agent["manifest_hash"],
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=_error("VM_ARTIFACT_MISSING", str(exc), {"agent_id": agent_id}),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error("VM_LAUNCH_FAILED", str(exc), {"agent_id": agent_id}),
            ) from exc
        await ctx.audit.log_api_mutation(
            endpoint=f"POST /v1/agents/{agent_id}/launch",
            details={
                "agent_id": agent_id,
                "vm_instance_id": record.vm_instance_id,
                "guest_cid": record.guest_cid,
            },
        )
        return _vm_payload(record)

    @app.post("/v1/agents/{agent_id}/stop")
    async def stop_agent(agent_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        record = vm_launcher.registry.get_by_agent(agent_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=_error("VM_NOT_RUNNING", "No active VM for agent"),
            )
        await vm_launcher.stop(record.vm_instance_id)
        stopped = vm_launcher.registry.get(record.vm_instance_id) or record
        await ctx.audit.log_api_mutation(
            endpoint=f"POST /v1/agents/{agent_id}/stop",
            details={"agent_id": agent_id, "vm_instance_id": record.vm_instance_id},
        )
        return _vm_payload(stopped)

    @app.get("/v1/rules")
    async def list_rules(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"rules": ctx.rules.list_rules()}

    @app.post("/v1/rules")
    async def create_rule(body: RuleCreate, _: None = Depends(require_api_key)) -> dict[str, Any]:
        try:
            rule = ctx.rules.validate_rule(body.model_dump(by_alias=True, exclude_none=True))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=_error("RULE_INVALID", str(exc)),
            ) from exc
        await ctx.rules.add_rule(rule)
        await ctx.audit.log_security_event(
            event_type="rule_created",
            details={"rule_id": body.id, "rule_hash": ctx.rules.ruleset_hash},
        )
        return {"id": body.id}

    @app.put("/v1/rules/{rule_id}")
    async def update_rule(
        rule_id: str, body: RuleCreate, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        data = body.model_dump(by_alias=True, exclude_none=True)
        data["id"] = rule_id
        try:
            rule = ctx.rules.validate_rule(data)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=_error("RULE_INVALID", str(exc)),
            ) from exc
        await ctx.rules.add_rule(rule)
        await ctx.audit.log_security_event(
            event_type="rule_updated",
            details={"rule_id": rule_id, "rule_hash": ctx.rules.ruleset_hash},
        )
        return {"id": rule_id}

    @app.delete("/v1/rules/{rule_id}")
    async def delete_rule(rule_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        deleted = await ctx.rules.delete_rule(rule_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=_error("RULE_NOT_FOUND", "Rule not found"),
            )
        await ctx.audit.log_security_event(
            event_type="rule_deleted",
            details={"rule_id": rule_id, "rule_hash": ctx.rules.ruleset_hash},
        )
        return {"id": rule_id, "deleted": True}

    @app.post("/v1/rules/simulate")
    async def simulate_rules(
        body: SimulateRequest, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        msg_data = body.message
        source = msg_data.source
        message = FrameworkMessage(
            source=MessageSource(
                agent_id=source.get("agent_id", "unknown"),
                engine=EngineId(source.get("engine", "engine1")),
                vm_id=source.get("vm_id", "test"),
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER,
                target="corvus_server",
            ),
            message_class=MessageClass.REQUEST,
            type=msg_data.type,
            tags=MessageTags(
                triggered_by=TriggeredBy(msg_data.tags.get("triggered_by", "agent_initiated")),
                scope=msg_data.tags.get("scope", "local"),
            ),
            payload=msg_data.payload,
        )
        decision = await ctx.policy.simulate(message, body.context)
        grant_checked = (
            "has_valid_grant" in (body.context or {})
            or bool(decision.metadata.get("grant_reason"))
        )
        return {
            "decision": decision.decision,
            "matched_rules": [
                {
                    "id": m.rule_id,
                    "priority": m.priority,
                    "effect": m.effect,
                    "conditions_passed": m.conditions_passed,
                    "reason": m.reason,
                }
                for m in decision.matched_rules
            ],
            "grant_evaluation": {
                "checked": grant_checked,
                "valid": body.context.get("has_valid_grant")
                if "has_valid_grant" in body.context
                else bool(decision.metadata.get("grant_id")),
                "grant_id": body.context.get("grant_id") or decision.metadata.get("grant_id"),
            },
            "quota_impact": {
                "would_consume_tokens": decision.metadata.get("quota_would_consume_tokens"),
                "remaining_after": decision.metadata.get("quota_remaining_after"),
                "would_exceed": bool(decision.metadata.get("quota_failed")),
            },
            "explanation_trace": decision.explanation_trace,
            "effective_error_code": decision.effective_error_code,
        }

    @app.get("/v1/audit/logs")
    async def audit_logs(
        correlation_id: str | None = None,
        origin_correlation_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        rule_id: str | None = None,
        grant_id: str | None = None,
        elevation_id: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        limit: int = 100,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        logs = await ctx.audit.query_logs(
            correlation_id=correlation_id,
            origin_correlation_id=origin_correlation_id,
            agent_id=agent_id,
            user_id=user_id,
            event_type=event_type,
            rule_id=rule_id,
            grant_id=grant_id,
            elevation_id=elevation_id,
            from_ts=from_,
            to_ts=to,
            limit=limit,
        )
        return {"logs": logs}

    @app.get("/v1/users")
    async def list_users(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"users": await ctx.db.list_users()}

    @app.post("/v1/users")
    async def create_user(body: UserCreate, _: None = Depends(require_api_key)) -> dict[str, Any]:
        secret = body.pin or body.password
        profile = {
            "groups": body.groups,
            "privileges": body.privileges,
            "allowed_agents": body.allowed_agents,
            "aliases": [alias.model_dump(mode="json", exclude_none=True) for alias in body.aliases],
        }
        if secret:
            profile["credential_hash"] = hash_secret(secret)
        await ctx.db.upsert_user(body.id, body.role, profile)
        await ctx.audit.log_security_event(
            event_type="user_upserted",
            details={"user_id": body.id, "alias_count": len(body.aliases)},
        )
        return {"id": body.id}

    @app.get("/v1/users/{user_id}")
    async def get_user(user_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        user = await ctx.db.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=_error("USER_NOT_FOUND", "User not found"))
        return {"user": user}

    @app.get("/v1/grants")
    async def list_grants(
        agent_id: str | None = None,
        namespace: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        return {"grants": await ctx.db.list_grants(agent_id=agent_id, namespace=namespace)}

    @app.post("/v1/grants")
    async def create_grant(body: GrantCreate, _: None = Depends(require_api_key)) -> dict[str, Any]:
        grant_id = await ctx.db.create_grant(**body.model_dump())
        await ctx.audit.log_security_event(
            event_type="grant_created",
            details={
                "grant_id": grant_id,
                "subject_agent": body.subject_agent,
                "target_agent": body.target_agent,
                "namespace": body.namespace,
            },
        )
        return {"id": grant_id}

    @app.delete("/v1/grants/{grant_id}")
    async def revoke_grant(grant_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
        revoked = await ctx.db.revoke_grant(grant_id)
        if not revoked:
            raise HTTPException(
                status_code=404,
                detail=_error("GRANT_NOT_FOUND", "Grant not found"),
            )
        await ctx.audit.log_security_event(
            event_type="grant_revoked",
            details={"grant_id": grant_id},
        )
        return {"id": grant_id, "revoked": True}

    @app.get("/v1/quotas")
    async def list_quotas(_: None = Depends(require_api_key)) -> dict[str, Any]:
        return {"quotas": await ctx.db.list_quota_counters()}

    @app.patch("/v1/quotas/{key:path}")
    async def patch_quota(
        key: str, body: QuotaPatch, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        await ctx.db.upsert_quota_counter(
            key=key,
            limit=body.limit,
            used=body.used,
            window_type=body.window_type,
        )
        await ctx.audit.log_security_event(
            event_type="quota_updated",
            details={"quota_key": key, "limit": body.limit},
        )
        return {"key": key}

    @app.get("/v1/elevations")
    async def list_elevations(
        status: str | None = None,
        agent_id: str | None = None,
        _: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        return {
            "elevations": await ctx.db.list_elevations(status=status, agent_id=agent_id)
        }

    @app.post("/v1/elevations/{elevation_id}/approve")
    async def approve_elevation(
        elevation_id: str, body: ElevationDecision, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        approver = await _require_elevation_approver(body)
        elevation = await ctx.db.get_elevation(elevation_id)
        if elevation is None:
            raise HTTPException(
                status_code=404,
                detail=_error("ELEVATION_NOT_FOUND", "Elevation not found"),
            )
        now = datetime.now(UTC)
        expires_at = datetime.fromisoformat(elevation["expires_at"])
        if elevation["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=_error(
                    "ELEVATION_NOT_PENDING",
                    f"Elevation status is {elevation['status']}, not pending",
                ),
            )
        if expires_at <= now:
            await ctx.db.update_elevation_status(elevation_id, "expired")
            raise HTTPException(
                status_code=409,
                detail=_error("ELEVATION_EXPIRED", "Elevation has expired"),
            )
        updated = await ctx.db.update_elevation_status(elevation_id, "approved")
        if not updated:
            raise HTTPException(
                status_code=404,
                detail=_error("ELEVATION_NOT_FOUND", "Elevation not found"),
            )
        if body.create_grant:
            grant = body.create_grant
            grant_id = await ctx.db.create_grant(
                subject_agent=grant["subject_agent"],
                target_agent=grant["target_agent"],
                namespace=grant["namespace"],
                permissions=grant["permissions"],
                expires_at=grant.get("expires_at"),
                created_by=approver["id"],
            )
        else:
            grant_id = None
        replay = await ctx.elevation_replay.replay_after_approval(
            elevation_id,
            grant_id=grant_id,
            approver_user_id=approver["id"],
        )
        if replay.get("grant_id") and grant_id is None:
            grant_id = replay["grant_id"]
        await ctx.audit.log_security_event(
            event_type="elevation_approved",
            details={
                "elevation_id": elevation_id,
                "grant_id": grant_id,
                "approver_user_id": approver["id"],
                "replay": replay,
            },
        )
        return {
            "id": elevation_id,
            "status": "approved",
            "grant_id": grant_id,
            "pending_replay_queued": replay.get("pending_replay_queued", False),
            "replay": replay,
        }

    @app.post("/v1/elevations/{elevation_id}/deny")
    async def deny_elevation(
        elevation_id: str, body: ElevationDecision, _: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        approver = await _require_elevation_approver(body)
        updated = await ctx.db.update_elevation_status(elevation_id, "denied")
        if not updated:
            raise HTTPException(
                status_code=404,
                detail=_error("ELEVATION_NOT_FOUND", "Elevation not found"),
            )
        await ctx.audit.log_security_event(
            event_type="elevation_denied",
            details={"elevation_id": elevation_id, "approver_user_id": approver["id"]},
        )
        return {"id": elevation_id, "status": "denied"}

    if ctx.config.ui_enabled:
        from corvus.management.ui import mount_ui

        mount_ui(app, ctx)

    return app
